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
# check_no_secrets_in_git.sh — fail if a credential-bearing file is tracked by git.
# Author: Rafael M. Koike & Cursor Agent ("Ada")
#
# .gitignore is not a control. It stops a file being added by accident; it does nothing about
# `git add -f`, about a file that was tracked before the ignore rule existed, or about a rule
# somebody deleted. This script asks the only question that matters -- what does git actually
# track right now -- and gates the lint stage on the answer.
#
# It deliberately checks PATHS, not file contents. Content scanning for high-entropy strings is a
# different job with a different false-positive profile; GitLab's secret detection template owns
# that. This is the cheap, zero-false-positive half.

set -euo pipefail

cd "$(dirname "$0")/.."

# Path globs that must never be tracked. Keep in step with the secrets block in .gitignore.
FORBIDDEN_GLOBS=(
    '.env'
    '.env.*'
    'factory.toml'
    '*.pem'
    '*.key'
    '*.p12'
    '*.pfx'
    'oidc-client-secret*'
    'var/*'
)

# Paths that look forbidden but are legitimately tracked. Each needs a reason.
declare -a ALLOWED=(
    '.env.example'          # placeholders only; no real values
    'factory.toml.example'  # generated from config_registry.py, secrets refused by construction
)

is_allowed() {
    local candidate="$1"
    for allowed in "${ALLOWED[@]}"; do
        [[ "$candidate" == "$allowed" ]] && return 0
    done
    # Test fixtures need to contain key-shaped material to be worth anything.
    [[ "$candidate" == *"/testdata/"* ]] && return 0
    return 1
}

violations=()
for glob in "${FORBIDDEN_GLOBS[@]}"; do
    while IFS= read -r tracked; do
        [[ -z "$tracked" ]] && continue
        is_allowed "$tracked" || violations+=("$tracked")
    done < <(git ls-files -- "$glob" 2>/dev/null || true)
done

if [[ ${#violations[@]} -gt 0 ]]; then
    echo "check_no_secrets_in_git: FAIL — credential-bearing files are tracked by git:" >&2
    printf '  %s\n' "${violations[@]}" >&2
    cat >&2 <<'EOF'

Untrack the file and rotate whatever it contained -- it is in the history, so removing it from
HEAD is not sufficient:

    git rm --cached <path>

Treat any credential that reached a commit as compromised, even on an unpushed branch.
EOF
    exit 1
fi

echo "check_no_secrets_in_git: PASS — no credential-bearing paths are tracked"
