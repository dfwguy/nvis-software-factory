# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Filesystem layout. One module decides where things live, so nothing guesses.

Author: Rafael M. Koike & Cursor Agent ("Ada")

The container mirrors the repository layout -- Python under ``/app/backend``, everything else at
``/app`` -- so ``REPO_ROOT`` resolves identically in development and in production. That is worth
the small amount of care it takes: a path that is correct in one context and silently wrong in the
other is the most common deployment bug in this family of tools.

``DATA_DIR`` is the only writable location, and it is a **bind mount** rather than a named volume.
That is a durability decision, not a preference: ``docker volume prune`` removes unused named
volumes without asking what is in them, and "unused" includes "the container is currently
recreated". A host path cannot be pruned by accident.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Repository root. ``backend/paths.py`` -> ``backend`` -> repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent

#: Published contract source. Read-only at runtime; this is the deliverable, not state.
CONTRACTS_DIR = REPO_ROOT / "contracts"

#: The eight quality pillars, read by both the prompt builder and the docs generator.
STANDARDS_DIR = REPO_ROOT / "standards"

#: Built SPA, produced by ``npm run build`` and copied into the image.
SPA_DIR = REPO_ROOT / "static" / "spa"

#: Built Sphinx HTML, served at ``/docs``.
DOCS_DIR = REPO_ROOT / "static" / "docs"


def data_dir() -> Path:
    """Root of all durable state. Overridable so tests never touch the real one.

    Read through a function rather than bound at import: the settings ladder materializes
    ``NVSF_DATA_DIR`` into the environment during launch, which happens after this module may
    already have been imported.
    """
    return Path(os.environ.get("NVSF_DATA_DIR") or (REPO_ROOT / "var")).expanduser()


def db_path() -> Path:
    """The SQLite database. Everything durable that is not a large artifact lives here."""
    return data_dir() / "store" / "factory.db"


def backups_dir() -> Path:
    """Snapshot destination for ``VACUUM INTO``."""
    return data_dir() / "backups"


def artifacts_dir() -> Path:
    """Rendered assessment documents, kept out of the database because they are large and blob-y."""
    return data_dir() / "artifacts"


def workspace_dir() -> Path:
    """Scratch space for clones. Disposable by definition -- nothing durable may live here."""
    return data_dir() / "workspace"


def audit_dir() -> Path:
    """Append-only audit trail, on the durable volume so it survives log rotation."""
    return data_dir() / "audit"


def logs_dir() -> Path:
    return data_dir() / "logs"


def runtime_dirs() -> tuple[Path, ...]:
    """Every directory the app needs to be able to write.

    Resolved on call, not bound at import, because the data directory is only known after the
    settings ladder has run.
    """
    return (
        db_path().parent,
        backups_dir(),
        artifacts_dir(),
        workspace_dir(),
        audit_dir(),
        logs_dir(),
    )


def ensure_runtime_dirs() -> list[Path]:
    """Create the writable tree. Returns what exists, so the caller can log or verify it.

    Deliberately not wrapped in try/except. If the data directory is not writable the app must not
    start: a service that silently falls back to a path inside the container looks healthy right up
    until the restart that discards everything.
    """
    created = []
    for entry in runtime_dirs():
        entry.mkdir(parents=True, exist_ok=True)
        created.append(entry)
    return created
