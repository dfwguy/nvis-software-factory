# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Who owns this, how do you run it, and can the next person take it over?

Author: Rafael M. Koike & Cursor Agent ("Ada")

The pillar with no interesting algorithms and the highest hit rate. Most of what makes a tool
unmaintainable is not in the code: no README, no named owner, no way to reproduce the environment,
and no record of which commit is running in production.

For an SA team this is the pillar that decides whether tooling survives a re-org. A tool nobody
can run is rewritten, and the rewrite has the same problem.
"""

from __future__ import annotations

import re

from store.models import Severity

from .base import Fact, RepoView

PILLAR = "provenance"

_ENV_MANIFESTS = (
    "requirements.txt", "pyproject.toml", "Pipfile", "environment.yml", "environment.yaml",
    "package.json", "go.mod", "Cargo.toml", "Gemfile", "pom.xml", "build.gradle",
    "setup.py", "conda.yaml", "uv.lock", "Dockerfile", "Containerfile",
)

_OWNER_FILES = ("CODEOWNERS", ".gitlab/CODEOWNERS", ".github/CODEOWNERS", "OWNERS", "MAINTAINERS")

_RUN_SECTION_RE = re.compile(
    r"(?im)^#{1,4}\s*(?:usage|getting started|quick ?start|installation|install|running|"
    r"how to run|setup|development)\b"
)

_VERSION_SIGNAL_RE = re.compile(
    r"(?i)__version__|version\s*=\s*['\"]|\"version\":|git rev-parse|GIT_SHA|BUILD_SHA|"
    r"VERSION_FILE|importlib\.metadata\.version|setuptools_scm|GIT_COMMIT|IMAGE_TAG"
)


def _readme(view: RepoView) -> tuple[str | None, str]:
    for candidate in view.find_names("README.md", "README.rst", "README.txt", "README",
                                     "readme.md"):
        text = view.read(candidate)
        if text:
            return candidate, text
    return None, ""


def scan(view: RepoView) -> list[Fact]:
    facts: list[Fact] = []
    all_files = view.files()
    code = view.code_files()

    # ── P1: README that says how to run it ───────────────────────────────────────────────────
    readme_path, readme = _readme(view)
    if not readme_path:
        facts.append(Fact(
            pillar_id=PILLAR, key="no_readme",
            title="No README",
            detail=(
                "Nothing states what this does or how to run it. Everything about operating it "
                "lives in the author's head, which is the definition of a single point of "
                "failure that reboots do not fix."
            ),
            criterion="P1", severity=Severity.MAJOR,
            remediation=(
                "One page: what it does, who owns it, how to run it, what it needs. Written so "
                "someone who has never seen it can get it running — that reader is the point."
            ),
        ))
    else:
        words = len(readme.split())
        has_run = bool(_RUN_SECTION_RE.search(readme))
        has_command = bool(re.search(r"```|^\s{4}\S|\$ ", readme, re.MULTILINE))
        thin = words < 80 or not (has_run or has_command)
        facts.append(Fact(
            pillar_id=PILLAR, key="readme_quality",
            title=(
                f"README is thin ({words} words)" if thin else
                f"README present ({words} words)"
            ),
            detail=(
                f"Has a usage or installation section: {has_run}. Contains a runnable command: "
                f"{has_command}."
                + ("" if not thin else
                   " Without a command someone can copy, 'how do I run this' is still a question "
                   "for the author.")
            ),
            criterion="P1",
            severity=Severity.MINOR if thin else None,
            file_path=readme_path,
            data={"words": words, "usage_section": has_run, "has_command": has_command},
        ))

    # ── P2: named owner ──────────────────────────────────────────────────────────────────────
    owner_files = [f for f in all_files if f in _OWNER_FILES or f.endswith("/CODEOWNERS")]
    owner_in_readme = bool(re.search(
        r"(?i)\b(?:owner|maintainer|contact|point of contact|team|author)\b\s*[:\-]|"
        r"@[a-z][a-z0-9_.-]+\b|[a-z0-9._%-]+@nvidia\.com",
        readme,
    ))
    if not owner_files and not owner_in_readme:
        facts.append(Fact(
            pillar_id=PILLAR, key="no_named_owner",
            title="No named owner",
            detail=(
                "No CODEOWNERS and no contact in the README. When this breaks during a "
                "deployment, finding who to ask is the first task, and git log is the only lead."
            ),
            criterion="P2", severity=Severity.MINOR,
            remediation=(
                "Name a person or a team, in CODEOWNERS or at the top of the README. A team "
                "alias survives people changing roles; an individual name does not."
            ),
        ))
    else:
        facts.append(Fact(
            pillar_id=PILLAR, key="owner_declared",
            title="Owner or maintainer is identified",
            detail=(
                f"CODEOWNERS: {', '.join(owner_files) or 'none'}. "
                f"Contact in README: {owner_in_readme}."
            ),
            criterion="P2",
            data={"codeowners": owner_files, "readme_contact": owner_in_readme},
        ))

    # ── P3: reproducible environment ─────────────────────────────────────────────────────────
    manifests = [f for f in all_files if f.rsplit("/", 1)[-1] in _ENV_MANIFESTS]
    if code and not manifests:
        facts.append(Fact(
            pillar_id=PILLAR, key="no_environment_manifest",
            title="No dependency manifest or container definition",
            detail=(
                f"{len(code)} source file(s) and nothing declaring what they need to run. "
                "Reproducing the environment means installing until the import errors stop, and "
                "the resulting environment differs per machine."
            ),
            criterion="P3", severity=Severity.MAJOR,
            remediation=(
                "Add a manifest with pinned versions. If it is currently 'whatever is on the head "
                "node', capture that with `pip freeze` as a starting point rather than "
                "reconstructing it from memory."
            ),
        ))
    elif manifests:
        facts.append(Fact(
            pillar_id=PILLAR, key="environment_manifest",
            title=f"{len(manifests)} environment manifest(s)",
            detail=", ".join(manifests[:10]),
            criterion="P3",
            data={"manifests": manifests},
        ))

    # ── P4: version and build identity ───────────────────────────────────────────────────────
    version_signals = view.grep(_VERSION_SIGNAL_RE, all_files, limit=6)
    is_deployed = bool(
        view.find_names("Dockerfile", "Containerfile", "docker-compose.yml", "compose.yml")
        or view.count_matches(r"(?i)Flask\(|FastAPI\(|uvicorn|gunicorn|ListenAndServe", code)
    )
    if is_deployed:
        facts.append(Fact(
            pillar_id=PILLAR, key="version_identity",
            title="Version or build identity present" if version_signals else
                  "Deployed artifact carries no version or commit identity",
            detail=(
                f"Found at {version_signals[0][0]}:{version_signals[0][1]}."
                if version_signals else
                "Nothing reports which commit is running. Answering 'is the fix deployed' "
                "requires shelling into the container and reading the code."
            ),
            criterion="P4",
            severity=None if version_signals else Severity.MINOR,
            file_path=version_signals[0][0] if version_signals else None,
            remediation=(
                "Stamp the commit SHA at build time and expose it on a health or version "
                "endpoint. Cheap, and it removes a whole class of confused incident calls."
            ) if not version_signals else None,
        ))

    # ── P5: licence and copyright posture ────────────────────────────────────────────────────
    licence = view.find_names("LICENSE", "LICENCE", "LICENSE.md", "LICENSE.txt", "COPYING")
    spdx = view.count_matches(r"SPDX-(?:License-Identifier|FileCopyrightText)", code)
    facts.append(Fact(
        pillar_id=PILLAR, key="license_posture",
        title=(
            "License file present" if licence else
            f"No license file ({spdx} SPDX header(s) in source)" if spdx else
            "No license file and no SPDX headers"
        ),
        detail=(
            "For internal NVIDIA tooling this is usually the proprietary header rather than an "
            "open licence, but it should be stated either way — an unmarked repository is "
            "ambiguous the moment it is shared with a partner."
        ),
        criterion="P5",
        data={"license_files": licence, "spdx_headers": spdx},
    ))

    # ── P6: documented operational procedures ────────────────────────────────────────────────
    docs = [f for f in all_files
            if f.lower().endswith((".md", ".rst")) and not f.lower().startswith("readme")]
    doc_text = readme + " ".join(view.read(f) or "" for f in docs)
    procedures = {
        "deploy": bool(re.search(r"(?i)\bdeploy|\bupgrade\b|\brollout\b", doc_text)),
        "backup or restore": bool(re.search(r"(?i)\bbackup\b|\brestore\b|\bsnapshot\b", doc_text)),
        "rollback": bool(re.search(r"(?i)\brollback\b|\brevert\b|\bdowngrade\b", doc_text)),
        "troubleshooting": bool(re.search(r"(?i)troubleshoot|\bdebug|known issue|\bFAQ\b",
                                          doc_text)),
    }
    missing = [name for name, present in procedures.items() if not present]
    facts.append(Fact(
        pillar_id=PILLAR, key="operational_documentation",
        title=(
            f"{len(docs)} documentation file(s) beyond the README"
            if docs else "No documentation beyond the README"
        ),
        detail=(
            f"Procedures not documented anywhere: {', '.join(missing)}." if missing else
            "Deploy, backup, rollback, and troubleshooting are all covered."
        ),
        criterion="P6",
        severity=Severity.MINOR if len(missing) >= 3 else None,
        data={"doc_files": docs[:15], "procedures": procedures},
    ))

    # ── Repository hygiene: files that should not be tracked ──────────────────────────────────
    junk = [
        f for f in all_files
        if re.search(
            r"(?i)(^|/)(?:\.DS_Store|Thumbs\.db|__pycache__/|\.pyc$|node_modules/|\.idea/|"
            r"\.vscode/settings\.json|venv/|\.venv/|dist/|build/|\.pytest_cache/|"
            r"\.mypy_cache/|\.coverage$|.*\.log$|.*\.swp$|.*\.orig$|.*\.rej$)",
            f,
        )
    ]
    if junk:
        facts.append(Fact(
            pillar_id=PILLAR, key="tracked_artifacts",
            title=f"{len(junk)} build artifact or editor file(s) tracked",
            detail=(
                ", ".join(junk[:10])
                + ". Noise in every diff, and a signal that .gitignore was added after the fact."
            ),
            criterion="P6", severity=Severity.MINOR,
            remediation="`git rm --cached` them and extend .gitignore.",
            data={"paths": junk[:30]},
        ))

    return facts
