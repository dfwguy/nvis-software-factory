#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
#
# verify-deploy.sh — check a running deployment for the things a browser will not tell you.
# Author: Rafael M. Koike & Cursor Agent ("Ada")
#
# A deployment can look fine and be wrong in ways nobody notices for weeks: data on the container's
# writable layer, an endpoint answering without a session, snapshots that have never run. This
# checks those, and reports everything it finds in one pass rather than stopping at the first
# problem -- an operator fixing a deployment wants the whole list.
#
#   ./bin/verify-deploy.sh https://factory.your-site.nvidia.com
#
# Most of the API needs a session, and this script has no way to complete an OIDC flow. So it runs
# ANONYMOUSLY, and turns that into the point: an endpoint that answers without a session is the
# most serious thing this script can find. For the per-dependency checks behind the session, set
# NVSF_SESSION_COOKIE to the nvsf_session cookie from a signed-in browser:
#
#   NVSF_SESSION_COOKIE='nvsf_session=eyJ...' ./bin/verify-deploy.sh https://...
#
# Run it FROM THE VM where possible. The storage checks need Docker access, and those are the ones
# that catch the failure this project exists because of.
#
# Exit codes: 0 all checks passed, 1 at least one FAIL, 2 usage error.
# WARN does not fail the run: it marks something worth a look that may be correct for your site.

set -uo pipefail

readonly CONTAINER="${NVSF_CONTAINER:-nvsf}"
readonly CURL_TIMEOUT="${NVSF_CURL_TIMEOUT:-15}"
readonly SESSION_COOKIE="${NVSF_SESSION_COOKIE:-}"

BASE_URL="${1:-}"
FAILURES=0
WARNINGS=0
CHECKS=0

if [[ -z "${BASE_URL}" || "${BASE_URL}" == "-h" || "${BASE_URL}" == "--help" ]]; then
    # The header comment is the help text; keeping one copy means they cannot disagree.
    sed -n '/^# verify-deploy\.sh/,/^set -uo/p' "$0" | sed '$d; s/^# \{0,1\}//'
    exit 2
fi
BASE_URL="${BASE_URL%/}"

if [[ -t 1 ]]; then
    readonly GREEN=$'\033[0;32m' RED=$'\033[0;31m' YELLOW=$'\033[0;33m'
    readonly DIM=$'\033[2m' RESET=$'\033[0m'
else
    readonly GREEN='' RED='' YELLOW='' DIM='' RESET=''
fi

pass() { CHECKS=$((CHECKS + 1)); printf '  %sPASS%s  %s\n' "${GREEN}" "${RESET}" "$1"; }
skip() { printf '  %sSKIP%s  %s\n' "${DIM}" "${RESET}" "$1"; }
head2() { printf '\n%s\n' "$1"; }

fail() {
    CHECKS=$((CHECKS + 1)); FAILURES=$((FAILURES + 1))
    printf '  %sFAIL%s  %s\n' "${RED}" "${RESET}" "$1"
    # The remedy on the same line as the problem. An operator reading this at 2am should not have
    # to go and find the runbook.
    [[ $# -gt 1 ]] && printf '        %s→ %s%s\n' "${DIM}" "$2" "${RESET}"
    return 0
}

warn() {
    CHECKS=$((CHECKS + 1)); WARNINGS=$((WARNINGS + 1))
    printf '  %sWARN%s  %s\n' "${YELLOW}" "${RESET}" "$1"
    [[ $# -gt 1 ]] && printf '        %s→ %s%s\n' "${DIM}" "$2" "${RESET}"
    return 0
}

# HTTP status for a path, or 000 when the request did not complete at all.
#
# No `|| echo 000` fallback: on a connection failure curl already prints 000 and *also* exits
# non-zero, so the fallback concatenates and yields "000000" -- which matches no case below and
# turns "host is unreachable" into a page of unrelated failures.
status_of() {
    local code
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time "${CURL_TIMEOUT}" \
            "${BASE_URL}$1" 2>/dev/null)"
    printf '%s' "${code:-000}"
}

body_of() {
    curl -sS --max-time "${CURL_TIMEOUT}" "${BASE_URL}$1" 2>/dev/null || echo ""
}

# As above, but carrying the session cookie. Only called when one was supplied.
status_as_user() {
    local code
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time "${CURL_TIMEOUT}" \
            -H "Cookie: ${SESSION_COOKIE}" "${BASE_URL}$1" 2>/dev/null)"
    printf '%s' "${code:-000}"
}

body_as_user() {
    curl -sS --max-time "${CURL_TIMEOUT}" -H "Cookie: ${SESSION_COOKIE}" \
        "${BASE_URL}$1" 2>/dev/null || echo ""
}

# A JSON field, without requiring jq to be installed on the VM.
json_field() {
    printf '%s' "$1" | tr -d '\n' | sed -n "s/.*\"$2\"[[:space:]]*:[[:space:]]*\"\{0,1\}\([^,\"}]*\).*/\1/p"
}

printf '%sNVIS Software Factory — deployment check%s\n' "${DIM}" "${RESET}"
printf '%s%s%s\n' "${DIM}" "${BASE_URL}" "${RESET}"

# ── Reachability and transport ───────────────────────────────────────────────────────────────

head2 "Transport"

if [[ "${BASE_URL}" == https://* ]]; then
    pass "HTTPS"
elif [[ "${BASE_URL}" == http://127.0.0.1* || "${BASE_URL}" == http://localhost* ]]; then
    skip "HTTPS (loopback: development)"
else
    # Not cosmetic. The session cookie is set Secure, and a browser silently discards a Secure
    # cookie delivered over plaintext -- so sign-in appears to do nothing, with no error.
    fail "Plaintext HTTP on a non-loopback host" \
         "Set NVSF_TLS_CERT and NVSF_TLS_KEY; the session cookie is Secure and will be dropped."
fi

# /api/health/live, not /api/health: liveness is the one endpoint on the authentication bypass
# list, precisely so a container healthcheck cannot mistake "no session" for "dead".
live_code="$(status_of /api/health/live)"
if [[ "${live_code}" == "200" ]]; then
    pass "Reachable (/api/health/live → 200)"
elif [[ "${live_code}" == "000" ]]; then
    fail "Not reachable at ${BASE_URL}" \
         "Check 'docker compose ps', the host firewall, and NVSF_HOST_PORT."
    printf '\nNothing else can be checked. Stopping.\n'
    exit 1
else
    fail "/api/health/live returned ${live_code}" "Check 'docker compose logs --tail=100'."
fi

# ── Authentication ───────────────────────────────────────────────────────────────────────────
#
# The most valuable section, and the reason this script runs anonymously by default. Everything
# here asserts that the deployment refuses a caller with no session.

head2 "Authentication"

# The mock check comes first because it changes what everything after it means. With the mock
# provider active, every request is already authenticated as a fixed user, so "refuses anonymous
# requests" cannot be tested at all -- and reporting a pass would be worse than reporting nothing.
me_body="$(body_of /api/auth/me)"
mock_active=0
if printf '%s' "${me_body}" | tr -d ' ' | grep -q '"is_mock":true'; then
    mock_active=1
    fail "Mock identity provider is ACTIVE" \
         "Every request authenticates as a fixed development user with full permissions. Unset NVSF_OIDC_MOCK and restart."
else
    pass "Mock identity provider is off"
fi

# Paths from the published OpenAPI document, which is what a generated client will request. If a
# spelling here 403s while its trailing-slash form works, that is a routing bug, not a policy one.
for path in /api/health /api/assessments /api/contracts/index.json /docs/; do
    code="$(status_of "${path}")"
    if [[ ${mock_active} -eq 1 ]]; then
        skip "${path} (mock provider active — anonymous access cannot be tested)"
        continue
    fi
    case "${code}" in
        401|403)
            pass "${path} refuses anonymous requests (${code})"
            ;;
        200)
            # The worst finding available: anyone who can reach the port can read this.
            fail "${path} answered WITHOUT a session (200)" \
                 "Serious. Check NVSF_OIDC_MOCK is unset and NVSF_ENV=production, then take the service down until it is fixed."
            ;;
        000)
            fail "${path} did not respond" "The service answered /api/health/live but not this."
            ;;
        *)
            warn "${path} returned ${code}" "Expected 401 or 403."
            ;;
    esac
done

login_code="$(status_of /api/auth/login)"
if [[ "${login_code}" =~ ^30[0-9]$ ]]; then
    pass "Sign-in redirects to the identity provider (${login_code})"
else
    warn "/api/auth/login returned ${login_code}, expected a redirect" \
         "Check NVSF_OIDC_ISSUER is reachable and its discovery document loads."
fi

# ── Application health ───────────────────────────────────────────────────────────────────────
#
# Behind the session, so only reachable with a cookie. Skipped rather than guessed at.

head2 "Application"

if [[ -z "${SESSION_COOKIE}" ]]; then
    skip "Per-dependency health (set NVSF_SESSION_COOKIE — see --help)"
    skip "Reasoning endpoint probe (needs a session)"
    skip "Snapshot posture (needs a session)"
else
    health_body="$(body_as_user /api/health)"
    case "$(json_field "${health_body}" status)" in
        healthy)
            pass "Self-reported status: healthy"
            ;;
        unhealthy)
            fail "Self-reported status: unhealthy — failing: $(json_field "${health_body}" failing)" \
                 "See the 'checks' object in /api/health for the detail."
            ;;
        "")
            fail "Could not read /api/health" \
                 "Cookie may be expired. Body: ${health_body:0:160}"
            ;;
        *)
            warn "Unexpected status in /api/health" "Body: ${health_body:0:160}"
            ;;
    esac

    # tr -d '\n' then a targeted grep: the store block is nested, and this avoids depending on jq
    # being installed on the VM.
    if printf '%s' "${health_body}" | tr -d '\n ' | grep -q '"store":{"ok":true'; then
        pass "Store sound and writable"
    else
        fail "Store not reporting ok" \
             "Usually the data directory's owner on the host: chown 10001:10001."
    fi

    if printf '%s' "${health_body}" | tr -d '\n ' | grep -q '"migrations":{"ok":true'; then
        pass "Schema up to date"
    else
        fail "Migrations pending" \
             "The schema is behind the code and requests will fail on missing columns. Restart applies them."
    fi

    if printf '%s' "${health_body}" | tr -d '\n ' | grep -q '"backups":{"ok":true'; then
        pass "Snapshots configured and current"
    else
        warn "Snapshots stale or not configured" \
             "NVSF_BACKUP_INTERVAL_HOURS=0 disables them, which fails the app's own criterion D3."
    fi

    # The one dependency with no degraded mode. An assessment started without it fails several
    # minutes in, after cloning and scanning.
    llm_code="$(status_as_user /api/health/llm)"
    llm_body="$(body_as_user /api/health/llm)"
    if [[ "${llm_code}" == "200" ]] \
       && printf '%s' "${llm_body}" | tr -d ' ' | grep -q '"reachable":true'; then
        pass "Reasoning endpoint reachable ($(json_field "${llm_body}" model))"
    else
        fail "Reasoning endpoint unreachable (probe → ${llm_code})" \
             "Every assessment will fail. Probe from INSIDE the container: an egress rule allowing the VM but not the bridge is the usual cause."
    fi
fi

# ── Response headers ─────────────────────────────────────────────────────────────────────────

head2 "Response headers"

# Against the SPA shell: headers are installed for every response, and this one needs no session.
headers="$(curl -sSI --max-time "${CURL_TIMEOUT}" "${BASE_URL}/" 2>/dev/null || echo "")"
for header in content-security-policy x-content-type-options x-frame-options referrer-policy; do
    if printf '%s' "${headers}" | grep -qi "^${header}:"; then
        pass "${header}"
    else
        fail "Missing ${header}" "security_headers.install() should set it; check for a proxy stripping headers."
    fi
done

if [[ "${BASE_URL}" == https://* ]]; then
    if printf '%s' "${headers}" | grep -qi '^strict-transport-security:'; then
        pass "strict-transport-security"
    else
        warn "No strict-transport-security" "Expected on an HTTPS deployment."
    fi
fi

# ── Served content ───────────────────────────────────────────────────────────────────────────

head2 "Served content"

spa_code="$(status_of /)"
if [[ "${spa_code}" == "200" ]]; then
    pass "SPA served at /"
else
    fail "SPA not served at / (${spa_code})" \
         "static/spa missing from the image; check the build stage."
fi

if [[ -z "${SESSION_COOKIE}" ]]; then
    # Anonymously these correctly return 401, which the authentication section already asserted.
    # Whether they have anything to serve is a different question and needs a session.
    skip "Documentation, contracts and OpenAPI (need a session)"
else
    docs_code="$(status_as_user /docs/)"
    case "${docs_code}" in
        200) pass "Documentation served at /docs/" ;;
        503) fail "Documentation not built into the image" \
                  "The docs build stage did not run. Rebuild with 'docker compose build --no-cache'." ;;
        *)   warn "/docs/ returned ${docs_code}" ;;
    esac

    contracts_code="$(status_as_user /api/contracts/index.json)"
    if [[ "${contracts_code}" == "200" ]]; then
        pass "Contract index published"
    else
        fail "Contract index unavailable (${contracts_code})" "contracts/ missing from the image."
    fi

    openapi_code="$(status_as_user /api/openapi.json)"
    if [[ "${openapi_code}" == "200" ]]; then
        pass "OpenAPI document published"
    else
        warn "OpenAPI document unavailable (${openapi_code})"
    fi
fi

# ── Durability ───────────────────────────────────────────────────────────────────────────────
#
# Requires Docker access on this host. These are the checks that catch the failure this project
# exists because of, so they are worth running from the VM rather than from a laptop.

head2 "Durability"

if ! command -v docker >/dev/null 2>&1; then
    skip "Storage checks (no docker on this host — run this from the VM)"
elif ! docker inspect "${CONTAINER}" >/dev/null 2>&1; then
    skip "Storage checks (no container named '${CONTAINER}' — set NVSF_CONTAINER)"
else
    mount_type="$(docker inspect -f \
        '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Type}}{{end}}{{end}}' \
        "${CONTAINER}" 2>/dev/null)"
    mount_source="$(docker inspect -f \
        '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' \
        "${CONTAINER}" 2>/dev/null)"

    case "${mount_type}" in
        bind)
            pass "Data directory is a bind mount (${mount_source})"
            ;;
        volume)
            # Not a nitpick: a named volume is removable by `docker volume prune`, which is a
            # routine command run by someone who is not thinking about your data.
            fail "Data directory is a NAMED VOLUME, not a bind mount" \
                 "'docker volume prune' can remove it. Move to a host path and set NVSF_HOST_DATA_DIR."
            ;;
        *)
            fail "Nothing is mounted at /data" \
                 "All state is on the container's writable layer and dies with the container. Stop and fix this now."
            ;;
    esac

    if [[ "$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' "${CONTAINER}" 2>/dev/null)" == "true" ]]; then
        pass "Container root filesystem is read-only"
    else
        warn "Container root filesystem is writable" "Set read_only: true in docker-compose.yml."
    fi

    container_user="$(docker inspect -f '{{.Config.User}}' "${CONTAINER}" 2>/dev/null)"
    if [[ "${container_user}" == "10001:10001" || "${container_user}" == "10001" ]]; then
        pass "Running as non-root (${container_user})"
    else
        fail "Running as '${container_user:-root}'" "The image sets USER 10001; something overrode it."
    fi

    if [[ -n "${mount_source}" && -d "${mount_source}/backups" ]]; then
        newest="$(find "${mount_source}/backups" -name '*.db' -mtime -2 2>/dev/null | head -1)"
        count="$(find "${mount_source}/backups" -name '*.db' 2>/dev/null | wc -l | tr -d ' ')"
        if [[ -n "${newest}" ]]; then
            pass "Snapshots present and recent (${count} total)"
        else
            warn "No snapshot in the last 48 hours (${count} total)" \
                 "Check NVSF_BACKUP_INTERVAL_HOURS; 0 disables snapshots entirely."
        fi
        # Stated rather than checked, because it cannot be checked from here -- and an unverified
        # backup is a belief, not a control. This is the app's own criterion D3.
        printf '        %sSnapshots sit on the same volume as the live database. Confirm the VM backup\n' "${DIM}"
        printf '         covers %s, and restore one into a scratch copy to prove the path works.%s\n' "${mount_source}" "${RESET}"
    else
        warn "No backups directory under the data mount" "Expected after the first snapshot interval."
    fi
fi

# ── Summary ──────────────────────────────────────────────────────────────────────────────────

printf '\n'
if [[ ${FAILURES} -gt 0 ]]; then
    printf '%s%d failed%s, %d warning(s), %d checks.\n' "${RED}" "${FAILURES}" "${RESET}" "${WARNINGS}" "${CHECKS}"
    printf 'See docs/how-to/deploy-on-an-itss-vm for what each failure means.\n'
    exit 1
fi

if [[ ${WARNINGS} -gt 0 ]]; then
    printf '%sAll checks passed%s with %d warning(s), %d checks.\n' "${GREEN}" "${RESET}" "${WARNINGS}" "${CHECKS}"
else
    printf '%sAll %d checks passed.%s\n' "${GREEN}" "${CHECKS}" "${RESET}"
fi
exit 0
