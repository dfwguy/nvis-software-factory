# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Transport security, authentication surface, and injection.

Author: Rafael M. Koike & Cursor Agent ("Ada")

The rest of the data-security pillar: is the wire encrypted, is anything checking who is calling,
and does user input reach a shell or a query by concatenation.

The unauthenticated-mutating-endpoint check deserves a note on why it is deliberately conservative.
Detecting authentication statically is hard -- it can be a decorator, a middleware, a
``before_request`` hook, a reverse proxy, or a framework default. So the scanner asks the narrow
question it can answer: are there mutating routes, and is there *any* authentication signal
anywhere in the repository? Both answers together are a strong hint and not a proof, so it emits a
finding only in the clearest case and an observation otherwise.
"""

from __future__ import annotations

import re

from store.models import Severity

from .base import Fact, RepoView

PILLAR = "data-security"

_VERIFY_DISABLED = (
    (re.compile(r"verify\s*=\s*False"), "requests verify=False"),
    (re.compile(r"InsecureSkipVerify\s*:\s*true"), "Go InsecureSkipVerify"),
    (re.compile(r"rejectUnauthorized\s*:\s*false"), "Node rejectUnauthorized: false"),
    (re.compile(r"NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0"), "NODE_TLS_REJECT_UNAUTHORIZED=0"),
    (re.compile(r"ssl\._create_unverified_context|_create_default_https_context\s*=\s*"
                r"ssl\._create_unverified_context"), "unverified SSL context"),
    (re.compile(r"curl\s+(-k|--insecure)\b"), "curl --insecure"),
    (re.compile(r"CERT_NONE"), "ssl.CERT_NONE"),
    (re.compile(r"StrictHostKeyChecking[= ]no"), "SSH StrictHostKeyChecking=no"),
    (re.compile(r"AutoAddPolicy"), "paramiko AutoAddPolicy"),
)

_AUTH_SIGNALS = (
    "login_required", "require_auth", "@auth", "authenticate", "Authorization",
    "current_user", "jwt", "oauth", "oidc", "session[", "before_request",
    "HTTPBasicAuth", "api_key", "verify_token", "permission_classes",
    "IsAuthenticated", "passport", "authMiddleware", "requireAuth", "keycloak",
)

_MUTATING_ROUTE_RE = re.compile(
    r"""(?ix)
    (?: @\w+ \. (?: route | post | put | patch | delete ) \s* \(
      | @ (?:app|bp|router|blueprint) \. (?:post|put|patch|delete) \s* \(
      | methods \s* = \s* \[ [^\]]* ['"] (?:POST|PUT|PATCH|DELETE) ['"]
      | (?:app|router) \. (?:post|put|patch|delete) \s* \(
    )
    """
)

_SQL_FSTRING_RE = re.compile(
    r"""(?ix)
    (?: execute | executemany | cursor\.execute | \.query | raw )
    \s* \( \s*
    (?: f["'] | ["'][^"']*["']\s*(?:%|\+|\.format) | .*?\{ )
    .*?
    (?: select | insert | update | delete | drop | where )
    """
)

_SHELL_TRUE_RE = re.compile(r"shell\s*=\s*True")
_OS_SYSTEM_RE = re.compile(r"\bos\.(?:system|popen)\s*\(")
_EVAL_RE = re.compile(r"\b(?:eval|exec)\s*\(|pickle\.loads?\s*\(|yaml\.load\s*\((?![^)]*Loader)")


def scan(view: RepoView) -> list[Fact]:
    facts: list[Fact] = []
    code = view.code_files()
    everything = view.files()

    # ── S5: TLS verification disabled ────────────────────────────────────────────────────────
    disabled: list[tuple[str, str, int]] = []
    for pattern, label in _VERIFY_DISABLED:
        for path, number, _ in view.grep(pattern, everything, limit=20):
            disabled.append((label, path, number))

    if disabled:
        facts.append(Fact(
            pillar_id=PILLAR, key="tls_verification_disabled",
            title=f"TLS or host-key verification is disabled at {len(disabled)} site(s)",
            detail=(
                "; ".join(f"{label} at {path}:{n}" for label, path, n in disabled[:8])
                + ". Disabling verification does not weaken encryption, it removes the check that "
                "you are talking to who you think — which is the part that stops interception."
            ),
            criterion="S5", severity=Severity.MAJOR,
            file_path=disabled[0][1], line_start=disabled[0][2],
            excerpt=view.excerpt(disabled[0][1], disabled[0][2]),
            remediation=(
                "This is almost always a self-signed certificate. Ship the CA certificate with "
                "the client and point `verify` at it: the connection still works offline and an "
                "interception is still detected."
            ),
            data={"sites": [f"{label} {path}:{n}" for label, path, n in disabled]},
        ))

    # ── S5: plaintext http to non-local hosts ────────────────────────────────────────────────
    plaintext = [
        (p, n, line) for p, n, line in view.grep(
            r"http://(?!localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|\{|\$)", everything, limit=30,
        )
        # A URL in a comment or a doc link is not a transport decision.
        if not p.lower().endswith((".md", ".rst", ".txt")) and not line.strip().startswith("#")
    ]
    if plaintext:
        facts.append(Fact(
            pillar_id=PILLAR, key="plaintext_http",
            title=f"{len(plaintext)} plaintext http:// URL(s) to non-local hosts",
            detail="Anything crossing a host boundary in the clear can be read and modified.",
            criterion="S5", severity=Severity.MINOR,
            file_path=plaintext[0][0], line_start=plaintext[0][1],
            data={"sites": [f"{p}:{n}" for p, n, _ in plaintext[:10]]},
        ))

    # ── S2/S3: authentication surface ────────────────────────────────────────────────────────
    mutating = view.grep(_MUTATING_ROUTE_RE, code, limit=60)
    auth_hits = [
        signal for signal in _AUTH_SIGNALS
        if view.count_matches(re.escape(signal), code) > 0
    ]

    if mutating:
        facts.append(Fact(
            pillar_id=PILLAR, key="mutating_endpoints_without_auth"
            if not auth_hits else "mutating_endpoints_with_auth_signal",
            title=(
                f"{len(mutating)} state-changing endpoint(s) and no authentication anywhere"
                if not auth_hits else
                f"{len(mutating)} state-changing endpoint(s); authentication signals present"
            ),
            detail=(
                "No decorator, middleware, session use, or token check appears anywhere in the "
                "code, so these endpoints are reachable by anyone who can reach the port. "
                "'It is only on the internal network' is not authentication — it is an "
                "assumption about a boundary that has been wrong before."
                if not auth_hits else
                f"Signals found: {', '.join(auth_hits[:8])}. Whether they cover every mutating "
                "route needs judgement — a per-route check means forgetting one is silent, "
                "whereas a central gate makes the default 'denied'."
            ),
            criterion="S2",
            # Certain enough: mutating routes exist and there is no authentication token anywhere
            # in the repository. The converse (signals present) is not certain, so it is an
            # observation.
            severity=Severity.BLOCKER if not auth_hits else None,
            file_path=mutating[0][0], line_start=mutating[0][1],
            excerpt=view.excerpt(mutating[0][0], mutating[0][1]),
            remediation=(
                "Add a single `before_request`-style gate that authenticates once and authorizes "
                "against a per-route declaration. The win over per-route decorators is that the "
                "default for a new route becomes 'denied' rather than 'whatever the author "
                "remembered'."
            ) if not auth_hits else None,
            data={
                "mutating_routes": [f"{p}:{n}" for p, n, _ in mutating[:15]],
                "auth_signals": auth_hits,
            },
        ))

    # ── S7: injection ────────────────────────────────────────────────────────────────────────
    sql_concat = view.grep(_SQL_FSTRING_RE, code, limit=20)
    if sql_concat:
        facts.append(Fact(
            pillar_id=PILLAR, key="sql_string_interpolation",
            title=f"{len(sql_concat)} SQL statement(s) built by string interpolation",
            detail=(
                "In our tooling the interpolated value is usually a hostname or node list that "
                "came from a file somebody else generated, which is exactly the input you cannot "
                "vouch for."
            ),
            criterion="S7", severity=Severity.MAJOR,
            file_path=sql_concat[0][0], line_start=sql_concat[0][1],
            excerpt=view.excerpt(sql_concat[0][0], sql_concat[0][1]),
            remediation="Use parameter binding: `execute(\"... WHERE id = ?\", (value,))`.",
            data={"sites": [f"{p}:{n}" for p, n, _ in sql_concat[:10]]},
        ))

    shell_true = view.grep(_SHELL_TRUE_RE, code, limit=20)
    os_system = view.grep(_OS_SYSTEM_RE, code, limit=20)
    if shell_true or os_system:
        first = (shell_true or os_system)[0]
        facts.append(Fact(
            pillar_id=PILLAR, key="shell_invocation",
            title=f"{len(shell_true)} `shell=True` and {len(os_system)} `os.system`/`os.popen` "
                  "call(s)",
            detail=(
                "A shell parses its argument, so any interpolated value can contain `;`, "
                "backticks or `$()`. Whether that is reachable from input needs judgement, which "
                "is why this is reported rather than asserted."
            ),
            criterion="S7",
            file_path=first[0], line_start=first[1],
            excerpt=view.excerpt(first[0], first[1]),
            remediation=(
                "Pass an argument list to `subprocess.run` without `shell=True`. Where a shell is "
                "genuinely needed, `shlex.quote` every interpolated value."
            ),
            data={
                "shell_true": [f"{p}:{n}" for p, n, _ in shell_true[:10]],
                "os_system": [f"{p}:{n}" for p, n, _ in os_system[:10]],
            },
        ))

    dangerous = view.grep(_EVAL_RE, code, limit=20)
    if dangerous:
        facts.append(Fact(
            pillar_id=PILLAR, key="dynamic_evaluation",
            title=f"{len(dangerous)} use(s) of eval/exec/pickle.loads/yaml.load",
            detail=(
                "Each of these turns data into code. `pickle.loads` and `yaml.load` without a "
                "safe loader are remote code execution if the input is not fully trusted."
            ),
            criterion="S7", severity=Severity.MAJOR,
            file_path=dangerous[0][0], line_start=dangerous[0][1],
            excerpt=view.excerpt(dangerous[0][0], dangerous[0][1]),
            remediation=(
                "`yaml.safe_load` instead of `yaml.load`. JSON instead of pickle for anything "
                "crossing a trust boundary."
            ),
            data={"sites": [f"{p}:{n}" for p, n, _ in dangerous[:10]]},
        ))

    # ── S6: dependency pinning ───────────────────────────────────────────────────────────────
    lockfiles = view.find_names(
        "poetry.lock", "Pipfile.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
        "Cargo.lock", "go.sum", "Gemfile.lock", "uv.lock", "requirements.lock",
    )
    requirements = view.find_names("requirements.txt", "requirements-dev.txt")
    unpinned: list[str] = []
    for relative in requirements:
        for number, line in enumerate(view.lines(relative), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "-r", "--", "-e", "git+")):
                continue
            if not re.search(r"[=<>~!]", stripped):
                unpinned.append(f"{relative}:{number} {stripped}")

    facts.append(Fact(
        pillar_id=PILLAR, key="dependency_pinning",
        title=(
            "Dependencies are locked" if lockfiles else
            f"{len(unpinned)} unpinned dependency line(s)" if unpinned else
            "Dependencies carry version constraints"
        ),
        detail=(
            f"Lockfiles: {', '.join(lockfiles)}." if lockfiles else
            "; ".join(unpinned[:10]) if unpinned else
            "No lockfile, but the manifests carry constraints."
        ),
        criterion="S6",
        severity=Severity.MINOR if (unpinned and not lockfiles) else None,
        remediation=(
            "Pin or lock every dependency. Unpinned, the vulnerability status of what actually "
            "shipped is unknown, and a rebuild is not reproducible."
        ) if (unpinned and not lockfiles) else None,
        data={"lockfiles": lockfiles, "unpinned": unpinned[:20]},
    ))

    return facts
