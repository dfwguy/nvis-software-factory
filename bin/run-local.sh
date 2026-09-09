#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual property and proprietary
# rights in and to this material, related documentation and any modifications thereto. Any use,
# reproduction, disclosure or distribution of this material and related documentation without an
# express license agreement from NVIDIA CORPORATION or its affiliates is strictly prohibited.
#
# run-local.sh — start a loopback development instance and report whether reasoning actually works.
# Author: Rafael M. Koike & Cursor Agent ("Ada")
#
# WHY THIS EXISTS
# ---------------
# Local runs used to be a long command line with the settings inlined in front of gunicorn. One of
# those command lines carried NVSF_LLM_API_KEY=not-set, it got copied forward across restarts, and
# the instance served happily for a day while the reasoning endpoint answered 401 to every call.
# Nothing lied exactly -- the app was up, and reasoning is only exercised when an assessment runs
# -- but nothing told you either.
#
# So this reads settings from a gitignored .env instead of the shell history, and it does not
# consider itself finished until it has probed the reasoning endpoint and told you the answer.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

ENV_FILE="${NVSF_ENV_FILE:-$REPO/.env}"
PORT="${NVSF_PORT:-8000}"

if [[ ! -f "$ENV_FILE" ]]; then
  cat >&2 <<EOF
No $ENV_FILE.

  cp .env.example .env && \$EDITOR .env

At minimum set NVSF_LLM_API_KEY. The file is gitignored; secrets are refused from factory.toml by
design, so the environment is where they belong.
EOF
  exit 1
fi

# Parsed, not sourced. A .env is docker-compose syntax, where a value needs no quoting and is
# taken literally -- `NVSF_OIDC_SCOPES=openid profile email groups` is one value with spaces in it.
# Sourced by bash that same line is an assignment followed by the command `profile`, which under
# `set -e` aborts partway through the file and leaves everything after it unset. The first version
# of this script did exactly that and the LLM settings, which sit below the scopes, silently never
# arrived. Reading the pairs also means a line in .env can never execute anything.
while IFS= read -r line; do
  [[ "$line" =~ ^[[:space:]]*(NVSF_[A-Z0-9_]+)=(.*)$ ]] || continue
  key="${BASH_REMATCH[1]}"
  value="${BASH_REMATCH[2]}"
  # Tolerate quoted values, since people write them out of habit.
  if [[ ${#value} -ge 2 && ( ( "$value" == \"*\" ) || ( "$value" == \'*\' ) ) ]]; then
    value="${value:1:${#value}-2}"
  fi
  export "$key=$value"
done <"$ENV_FILE"

# Loopback development defaults. Anything already in .env wins.
export NVSF_ENV="${NVSF_ENV:-development}"
export NVSF_OIDC_MOCK="${NVSF_OIDC_MOCK:-true}"
export NVSF_BIND_ADDR="${NVSF_BIND_ADDR:-127.0.0.1}"
export NVSF_PORT="$PORT"
export NVSF_PUBLIC_URL="${NVSF_PUBLIC_URL:-http://127.0.0.1:$PORT}"
export NVSF_DATA_DIR="${NVSF_DATA_DIR:-$REPO/var/local}"
# Resolved against the repository, not the process's directory: gunicorn is started from backend/,
# so a relative path in .env would otherwise quietly create a second database under backend/.
[[ "$NVSF_DATA_DIR" = /* ]] || NVSF_DATA_DIR="$REPO/$NVSF_DATA_DIR"

# The placeholder that caused this. An empty key is left alone: an internal NIM on a trusted
# network legitimately has none, and the probe below is what settles it either way.
if [[ "${NVSF_LLM_API_KEY:-}" == "not-set" || "${NVSF_LLM_API_KEY:-}" == "changeme" ]]; then
  echo "NVSF_LLM_API_KEY is the placeholder '${NVSF_LLM_API_KEY}'. Put a real key in $ENV_FILE." >&2
  exit 1
fi

mkdir -p "$NVSF_DATA_DIR"
LOG="${NVSF_LOG_FILE:-/tmp/nvsf-local.log}"

echo "starting on http://127.0.0.1:$PORT  (data: $NVSF_DATA_DIR, log: $LOG)"
( cd backend && exec "$REPO/.venv/bin/gunicorn" --config gunicorn.conf.py app:app ) >"$LOG" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 40); do
  if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/api/health/live" 2>/dev/null; then
    break
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "server exited during startup. Last lines of $LOG:" >&2
    tail -20 "$LOG" >&2
    exit 1
  fi
  sleep 0.5
done

# The point of the script. An instance that is up but cannot reason is not a working deployment of
# this application, and you should not have to go and find that out.
COOKIES="$(mktemp)"
trap 'rm -f "$COOKIES"' EXIT
curl -fsS -c "$COOKIES" -b "$COOKIES" -L -o /dev/null "http://127.0.0.1:$PORT/api/auth/login" || true

PROBE="$(curl -sS -b "$COOKIES" "http://127.0.0.1:$PORT/api/health/llm" || echo '{}')"
python3 - "$PROBE" <<'PY'
import json, sys

try:
    body = json.loads(sys.argv[1])
except json.JSONDecodeError:
    print("reasoning: could not read the probe response")
    sys.exit(0)

if body.get("ok"):
    print(f"reasoning: OK — {body.get('model')} in {body.get('latency_ms')}ms")
else:
    print(f"reasoning: NOT WORKING — {body.get('detail') or 'no detail'}")
    print(f"           endpoint {body.get('endpoint')} model {body.get('model')}")
    print("           assessments will fail. This instance is serving, but it cannot do its job.")
PY

echo "pid $SERVER_PID — stop with: kill $SERVER_PID"
