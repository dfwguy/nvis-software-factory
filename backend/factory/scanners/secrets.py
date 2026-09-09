# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Committed credentials, and credential-shaped paths that are tracked.

Author: Rafael M. Koike & Cursor Agent ("Ada")

The scanner most likely to produce a false positive, so the design leans hard on the placeholder
suppression in ``factory/redact.py``. A scanner that flags every ``password = "changeme"`` in a
README gets ignored wholesale, and then the real credential is missed too. Credibility is the
feature.

Nothing this scanner emits contains a credential. Every value passes through ``redact.classify``
first, so the finding says ``AWS-access-key-shaped, 20 chars`` and the value stays in the clone,
which is deleted.
"""

from __future__ import annotations

import re

from store.models import Severity

from ..redact import ASSIGNMENT_RE, classify
from .base import Fact, RepoView

PILLAR = "data-security"

#: Paths that should never be tracked. Checked as paths, which is the zero-false-positive half of
#: secret scanning; content scanning is the other half and has a very different error profile.
_FORBIDDEN_PATHS = (
    (re.compile(r"(^|/)\.env$"), ".env"),
    (re.compile(r"(^|/)\.env\.(?!example|template|sample|dist)[a-z0-9_.-]+$"), ".env variant"),
    (re.compile(r"\.pem$"), "PEM file"),
    (re.compile(r"\.p12$|\.pfx$"), "PKCS#12 keystore"),
    (re.compile(r"(^|/)id_(rsa|dsa|ecdsa|ed25519)$"), "SSH private key"),
    (re.compile(r"(^|/)\.netrc$|(^|/)_netrc$"), "netrc"),
    (re.compile(r"(^|/)\.npmrc$"), "npmrc (often holds a registry token)"),
    (re.compile(r"(^|/)\.pypirc$"), "pypirc"),
    (re.compile(r"(^|/)kubeconfig$|\.kube/config$"), "kubeconfig"),
    (re.compile(r"(^|/)credentials$"), "credentials file"),
    (re.compile(r"service[_-]?account.*\.json$"), "service account key"),
    (re.compile(r"\.jks$|\.keystore$"), "Java keystore"),
)

#: A .key that is a test fixture is normal; one at the repository root is not.
_KEY_SUFFIX_RE = re.compile(r"\.key$")
_TEST_PATH_RE = re.compile(r"(^|/)(tests?|testdata|fixtures?|__tests__|spec|examples?)(/|$)")

#: Connection strings with an inline password.
_DSN_RE = re.compile(
    r"(?i)\b(postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp|mssql|clickhouse)"
    r"://[^\s:/@'\"]+:(?P<secret>[^\s@'\"]{3,})@"
)


def _is_documentation(relative: str) -> bool:
    """Markdown and friends. A credential-shaped string here is usually an example."""
    return relative.lower().endswith((".md", ".rst", ".txt", ".adoc", ".ipynb"))


def scan(view: RepoView) -> list[Fact]:
    facts: list[Fact] = []

    # ── S1a: forbidden paths that are tracked ────────────────────────────────────────────────
    tracked_violations: list[tuple[str, str]] = []
    for relative in view.files():
        for pattern, label in _FORBIDDEN_PATHS:
            if pattern.search(relative):
                tracked_violations.append((relative, label))
                break
        else:
            if _KEY_SUFFIX_RE.search(relative) and not _TEST_PATH_RE.search(relative):
                tracked_violations.append((relative, "private key by extension"))

    if tracked_violations:
        facts.append(Fact(
            pillar_id=PILLAR, key="credential_paths_tracked",
            title=f"{len(tracked_violations)} credential-bearing file(s) are in the repository",
            detail=(
                "; ".join(f"{p} ({label})" for p, label in tracked_violations[:10])
                + ". These are in the repository's history and in every clone, so removing them "
                "from the current tree is not sufficient — any credential they contained must be "
                "treated as compromised and rotated."
            ),
            criterion="S1", severity=Severity.BLOCKER,
            file_path=tracked_violations[0][0],
            remediation=(
                "Rotate the credentials first — that is the urgent part. Then `git rm --cached` "
                "the files, add them to .gitignore, and add a CI check on tracked paths so the "
                "class cannot recur. .gitignore alone is not a control: it does nothing about "
                "`git add -f`, a file tracked before the rule existed, or history."
            ),
            data={"paths": [p for p, _ in tracked_violations]},
        ))

    # ── S1b: .gitignore posture ──────────────────────────────────────────────────────────────
    gitignore = view.read(".gitignore") or ""
    if not gitignore:
        facts.append(Fact(
            pillar_id=PILLAR, key="no_gitignore",
            title="No .gitignore",
            detail="Nothing prevents a credential file, a virtualenv, or build output from being "
                   "added by accident.",
            criterion="S1", severity=Severity.MINOR,
            remediation="Add a .gitignore covering .env, keys, and the language's build output.",
        ))
    else:
        ignores_env = bool(re.search(r"^\s*\.env", gitignore, re.MULTILINE))
        facts.append(Fact(
            pillar_id=PILLAR, key="gitignore_posture",
            title=".gitignore present",
            detail=f"{'Covers' if ignores_env else 'Does not cover'} .env files.",
            criterion="S1",
            data={"ignores_env": ignores_env, "lines": len(gitignore.splitlines())},
        ))

    # ── S1c: hardcoded values in content ─────────────────────────────────────────────────────
    real_secrets: list[dict[str, object]] = []
    placeholders = 0

    for relative in view.files():
        documentation = _is_documentation(relative)
        for number, line in enumerate(view.lines(relative), start=1):
            for match in ASSIGNMENT_RE.finditer(line):
                classified = classify(match.group("value"))
                if classified.placeholder:
                    placeholders += 1
                    continue
                # A recognised credential prefix in documentation is still a real leak -- nobody
                # writes a plausible glpat- token as an example. An unrecognised high-entropy
                # string in a README usually is an example.
                if documentation and classified.shape.startswith("high-entropy"):
                    placeholders += 1
                    continue
                real_secrets.append({
                    "at": f"{relative}:{number}",
                    "variable": match.group("name"),
                    "shape": classified.shape,
                    "length": classified.length,
                    "entropy": classified.entropy,
                    "in_documentation": documentation,
                })

    for relative in view.files():
        for number, line in enumerate(view.lines(relative), start=1):
            for match in _DSN_RE.finditer(line):
                classified = classify(match.group("secret"))
                if classified.placeholder:
                    placeholders += 1
                    continue
                real_secrets.append({
                    "at": f"{relative}:{number}",
                    "variable": "connection string",
                    "shape": f"{classified.shape} in a DSN",
                    "length": classified.length,
                    "entropy": classified.entropy,
                    "in_documentation": _is_documentation(relative),
                })

    if real_secrets:
        named_shapes = sorted({
            str(s["shape"]) for s in real_secrets
            if not str(s["shape"]).startswith(("high-entropy", "unrecognised"))
        })
        first = real_secrets[0]
        path, _, line_number = str(first["at"]).rpartition(":")
        facts.append(Fact(
            pillar_id=PILLAR, key="hardcoded_credentials",
            title=f"{len(real_secrets)} hardcoded credential(s), by shape and entropy",
            detail=(
                "Values are reported by shape only; none of them appear in this report or in "
                "anything sent to the reasoning model. "
                + (f"Recognised credential types: {', '.join(named_shapes)}. "
                   if named_shapes else "")
                + f"({placeholders} additional match(es) were suppressed as placeholders or "
                  "documentation examples.)"
            ),
            criterion="S1",
            # Certain when the shape is a recognised credential prefix: nothing else produces a
            # string starting `glpat-` or `AKIA`. High-entropy-only matches are an observation,
            # because a random-looking string is not necessarily a secret.
            severity=Severity.BLOCKER if named_shapes else Severity.MAJOR,
            file_path=path or None,
            line_start=int(line_number) if line_number.isdigit() else None,
            excerpt=view.excerpt(path, int(line_number)) if line_number.isdigit() else None,
            remediation=(
                "Rotate every value found, then read them from the environment or a mounted "
                "secret file. Rotation is not optional: the values are in the git history."
            ),
            data={"findings": real_secrets[:20], "total": len(real_secrets),
                  "suppressed_placeholders": placeholders},
        ))
    else:
        facts.append(Fact(
            pillar_id=PILLAR, key="no_hardcoded_credentials",
            title="No hardcoded credentials detected",
            detail=(
                f"{placeholders} credential-shaped assignment(s) were found and all read as "
                "placeholders or documentation. Note this is pattern and entropy matching: a "
                "credential with no recognisable shape, in a variable not named like one, would "
                "not be caught."
            ),
            criterion="S1",
            data={"suppressed_placeholders": placeholders},
        ))

    # ── S4: credentials reaching logs ────────────────────────────────────────────────────────
    log_leaks = view.grep(
        r"(?i)(?:log|logger|logging|print)\s*(?:\.\w+)?\s*\(.*"
        r"(?:request\.headers|os\.environ|dict\(os\.environ\)|authorization|token|password|"
        r"secret|api_key)",
        view.code_files(), limit=20,
    )
    if log_leaks:
        facts.append(Fact(
            pillar_id=PILLAR, key="credentials_in_logs",
            title=f"{len(log_leaks)} log call(s) appear to include credential-bearing data",
            detail=(
                "Logging a headers dict, the environment, or a variable named like a credential "
                "puts the value in every log sink and every log aggregator downstream."
            ),
            criterion="S4", severity=Severity.MAJOR,
            file_path=log_leaks[0][0], line_start=log_leaks[0][1],
            excerpt=view.excerpt(log_leaks[0][0], log_leaks[0][1]),
            remediation=(
                "Add a redaction filter to the logging configuration, applied to every handler. "
                "Redacting at call sites works until somebody adds a call site."
            ),
            data={"sites": [f"{p}:{n}" for p, n, _ in log_leaks[:10]]},
        ))

    return facts
