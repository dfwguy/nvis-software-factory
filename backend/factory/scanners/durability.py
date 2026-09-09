# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Where does the state live, and what happens when the process dies?

Author: Rafael M. Koike & Cursor Agent ("Ada")

The scanner for the pillar the project was created for. A team kept all of their state in memory
in a container, someone restarted the Docker daemon, and the data was gone -- not in a volume, not
in a database, not reconstructable from logs.

WHAT THIS CAN AND CANNOT ESTABLISH
-----------------------------------
It can establish, with certainty: a containerized service with no volume declared anywhere. That
is a hard finding -- there is no interpretation of a compose file with no ``volumes:`` under which
container-local writes survive ``docker rm``.

It cannot establish whether a module-level dict is the only copy of something important. A cache is
also a module-level dict. So that is emitted as an observation with the surrounding evidence, and
the reasoning pass decides -- which is exactly the division of labour the ratchet describes.
"""

from __future__ import annotations

import re

from store.models import Severity

from .base import Fact, RepoView

PILLAR = "durability"

#: Persistence libraries. Presence of any is strong evidence that state has somewhere to go.
_PERSISTENCE_HINTS = (
    "sqlite3", "sqlalchemy", "psycopg", "asyncpg", "pymongo", "redis", "tinydb",
    "duckdb", "mysql", "mariadb", "peewee", "pony", "tortoise", "prisma",
    "sequelize", "mongoose", "typeorm", "diesel", "gorm", "sqlx", "boto3", "minio",
)

#: Module-level mutable containers. Cheap and noisy alone; useful next to the other facts.
_MODULE_STATE_RE = re.compile(
    r"^(?!\s)(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*[^=]+)?=\s*(?:\{\}|\[\]|dict\(\)|"
    r"list\(\)|set\(\)|OrderedDict\(\)|defaultdict\(|deque\(|\{\s*\}|Queue\(\))"
)

#: In-place rewrite of a file: ``open(path, "w")``. The crash window criterion D2 describes.
_TRUNCATING_WRITE_RE = re.compile(
    r"""open\s*\(\s*[^,)]+,\s*['"](?:w|w\+|wb|wb\+)['"]"""
)

_ATOMIC_WRITE_RE = re.compile(r"os\.replace|os\.rename|shutil\.move|NamedTemporaryFile|\.tmp")

_MIGRATION_HINTS = (
    "alembic", "migrations/", "migrate/", "flyway", "liquibase", "db/migrate",
    "schema_migrations", "django.db.migrations",
)

_BACKUP_HINTS = (
    "pg_dump", "mysqldump", "VACUUM INTO", "sqlite3_backup", ".backup(", "restic",
    "borgbackup", "rsync", "s3 cp", "s3_client.upload", "put_object",
)


def _container_files(view: RepoView) -> dict[str, list[str]]:
    return {
        "dockerfile": view.find_names("Dockerfile", "Containerfile")
        + view.glob("Dockerfile.*"),
        "compose": view.find_names(
            "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
        ),
        "k8s": [
            f for f in view.by_suffix(".yaml", ".yml")
            if (text := view.read(f)) and "kind:" in text
            and re.search(r"kind:\s*(Deployment|StatefulSet|Pod|DaemonSet)", text)
        ],
    }


def _module_state(view: RepoView) -> list[tuple[str, int, str]]:
    """Module-level mutable containers, excluding ALL_CAPS constants.

    Constants are not state, and the convention is reliable enough to filter on. Everything else
    here is only a candidate -- see the module docstring on why this stays an observation.
    """
    found: list[tuple[str, int, str]] = []
    for relative in view.python_files():
        for number, line in enumerate(view.lines(relative), start=1):
            match = _MODULE_STATE_RE.match(line)
            if match and not match.group("name").isupper():
                found.append((relative, number, match.group("name")))
    return found


def scan(view: RepoView) -> list[Fact]:
    facts: list[Fact] = []
    containers = _container_files(view)
    containerized = any(containers.values())
    code = view.code_files()
    module_state = _module_state(view)

    # A long-running process is what makes in-memory state dangerous. A script that runs, prints,
    # and exits has no state to lose in the first place.
    is_service = bool(view.count_matches(
        r"(?i)Flask\(|FastAPI\(|app\.run\(|uvicorn|gunicorn|celery|express\(|http\.Server|"
        r"ListenAndServe|while\s+True|schedule\.every|BackgroundScheduler",
        code,
    ))

    # ── Is there a persistence mechanism at all? ─────────────────────────────────────────────
    dependency_text = " ".join(
        (view.read(f) or "").lower()
        for f in view.find_names(
            "requirements.txt", "pyproject.toml", "Pipfile", "package.json", "go.mod",
            "Cargo.toml", "Gemfile", "setup.py", "setup.cfg", "environment.yml",
        )
    )
    libraries = sorted({h for h in _PERSISTENCE_HINTS if h in dependency_text})

    # Also look for use in code, since plenty of repos have no dependency manifest at all.
    sqlite_use = view.grep(r"\bsqlite3\.connect\b|\bcreate_engine\(", code, limit=10)
    file_writes = view.grep(r"\bopen\s*\([^)]*['\"][aw]", code, limit=20)

    has_persistence = bool(libraries or sqlite_use)

    facts.append(Fact(
        pillar_id=PILLAR, key="persistence_inventory",
        title="Persistence mechanisms found" if has_persistence else
              "No database or persistence library found",
        detail=(
            f"Libraries in dependency manifests: {', '.join(libraries) or 'none'}. "
            f"Direct database use in code: {len(sqlite_use)} site(s). "
            f"File writes in code: {len(file_writes)} site(s)."
        ),
        criterion="D1",
        data={
            "libraries": libraries,
            "db_call_sites": [f"{p}:{n}" for p, n, _ in sqlite_use],
            "file_write_sites": [f"{p}:{n}" for p, n, _ in file_writes[:10]],
            "file_write_count": len(file_writes),
        },
    ))

    # ── The hard finding: containerized, writes state, no volume anywhere ────────────────────
    if containerized:
        volume_declarations = []
        for kind, files in containers.items():
            for relative in files:
                text = view.read(relative) or ""
                if re.search(r"^\s*(volumes|VOLUME|volumeMounts|persistentVolumeClaim)",
                             text, re.MULTILINE | re.IGNORECASE):
                    volume_declarations.append(f"{relative} ({kind})")

        if not volume_declarations:
            # What is at stake. Note that *no* persistence mechanism plus module-level mutable
            # state is the worst case, not the safe one: it is the incident this pillar exists
            # for, where the dict in the process was the only copy.
            if has_persistence or file_writes:
                stake = (
                    f"The code writes durable data ({len(file_writes)} file write site(s), "
                    f"{'a database is in use' if has_persistence else 'no database'}), so there "
                    "is state to lose."
                )
            elif module_state and is_service:
                stake = (
                    f"There is no database and no file write anywhere, and {len(module_state)} "
                    "module-level mutable container(s) sit in a long-running service. That is "
                    "the shape where the process memory is the only copy: a restart of the "
                    "container, or of the Docker daemon underneath it, loses everything with "
                    "nothing to recover from."
                )
            else:
                stake = (
                    "No database, file write, or module-level state was found either, so this may "
                    "be genuinely stateless — worth confirming with the owner."
                )

            has_state = bool(has_persistence or file_writes or (module_state and is_service))
            facts.append(Fact(
                pillar_id=PILLAR, key="container_without_volume",
                title="Containerized, and no volume or mount is declared anywhere",
                detail=(
                    "No `volumes:`, `VOLUME`, or `volumeMounts:` appears in any container "
                    "definition, so everything this service writes goes to the container's "
                    "writable layer. That layer is discarded by `docker rm`, by an image update, "
                    "and by most orchestrator reschedules. " + stake
                ),
                criterion="D1",
                # Certain when there is state: no reading of a compose file with no volumes makes
                # container-local writes survive. An observation when no state was found, because
                # a stateless service legitimately needs no volume.
                severity=Severity.BLOCKER if has_state else None,
                file_path=next(iter(containers["compose"] or containers["dockerfile"]), None),
                remediation=(
                    (
                        "Two changes, in this order. First give the state somewhere to live: "
                        "SQLite in a file is enough for this shape and needs no extra service. "
                        "Then bind-mount a host path and put the file there.\n\n"
                        if not has_persistence and module_state else
                        "Bind-mount a host path and write durable state there.\n\n"
                    )
                    + "A bind mount rather than a named volume, because `docker volume prune` "
                    "removes unused named volumes without asking what is in them — and a volume "
                    "counts as unused while its container is being recreated. Then make the "
                    "application refuse to start if the path is not writable: without that, a "
                    "mount typo silently degrades to container-local storage and looks correct "
                    "right up until the restart."
                ),
                data={"container_files": {k: v for k, v in containers.items() if v}},
            ))
        else:
            facts.append(Fact(
                pillar_id=PILLAR, key="volumes_declared",
                title="Volumes are declared",
                detail="; ".join(volume_declarations),
                criterion="D1",
                data={"declarations": volume_declarations},
            ))

        # Named volume versus bind mount. Better than nothing, worse than a host path.
        for relative in containers["compose"]:
            text = view.read(relative) or ""
            named = re.search(r"^volumes:\s*$", text, re.MULTILINE)
            bind = re.search(r"^\s+-\s+[./~]", text, re.MULTILINE)
            if named and not bind:
                facts.append(Fact(
                    pillar_id=PILLAR, key="named_volume_only",
                    title="State is on a named Docker volume rather than a bind mount",
                    detail=(
                        "A named volume survives a container restart, which is the main thing. It "
                        "does not survive `docker volume prune`, which removes unused volumes "
                        "without prompting — and a volume counts as unused while the container "
                        "that uses it is being recreated."
                    ),
                    criterion="D1", severity=Severity.MINOR, file_path=relative,
                    remediation="Change the volume to a host path bind mount.",
                ))

    # ── Module-level mutable state ───────────────────────────────────────────────────────────
    if module_state:
        facts.append(Fact(
            pillar_id=PILLAR, key="module_level_mutable_state",
            title=f"{len(module_state)} module-level mutable container(s)",
            detail=(
                "These may be caches, which is fine, or they may be the only copy of something, "
                "which is the failure this pillar exists for. Deciding needs to look at whether "
                "anything writes to them and whether that data is reconstructable."
            ),
            criterion="D1",
            file_path=module_state[0][0],
            line_start=module_state[0][1],
            excerpt=view.excerpt(module_state[0][0], module_state[0][1]),
            data={
                "sites": [f"{p}:{n} ({name})" for p, n, name in module_state[:15]],
                "count": len(module_state),
            },
        ))

    # ── D2: in-place rewrites ────────────────────────────────────────────────────────────────
    truncating = view.grep(_TRUNCATING_WRITE_RE, view.python_files(), limit=30)
    atomic = view.count_matches(_ATOMIC_WRITE_RE, view.python_files())
    if truncating and not atomic:
        facts.append(Fact(
            pillar_id=PILLAR, key="non_atomic_file_write",
            title=f"{len(truncating)} file(s) rewritten in place with no atomic-replace pattern",
            detail=(
                "`open(path, \"w\")` truncates immediately, so the file is empty for the duration "
                "of the write. A crash in that window leaves a truncated file where the data used "
                "to be. No `os.replace`, temporary file, or equivalent appears anywhere in the "
                "repository."
            ),
            criterion="D2", severity=Severity.MAJOR,
            file_path=truncating[0][0], line_start=truncating[0][1],
            excerpt=view.excerpt(truncating[0][0], truncating[0][1]),
            remediation=(
                "Write to `path.tmp`, then `flush()`, `os.fsync()`, then "
                "`os.replace(tmp, path)`. `os.replace` is atomic on POSIX and Windows, so a crash "
                "leaves either the old file or the new one — never half of either."
            ),
            data={"sites": [f"{p}:{n}" for p, n, _ in truncating[:10]]},
        ))
    elif truncating:
        facts.append(Fact(
            pillar_id=PILLAR, key="atomic_write_present",
            title="Atomic-replace pattern is present alongside in-place writes",
            detail=f"{atomic} atomic-write reference(s) found; {len(truncating)} truncating "
                   "write(s). Which paths hold the durable data needs judgement.",
            criterion="D2",
        ))

    # ── D3: backups ──────────────────────────────────────────────────────────────────────────
    haystack = " ".join(view.read(f) or "" for f in code + view.by_suffix(".yaml", ".yml", ".md"))
    backup_signals = sorted({h for h in _BACKUP_HINTS if h in haystack})
    facts.append(Fact(
        pillar_id=PILLAR, key="backup_signals",
        title="Backup mechanism referenced" if backup_signals else
              "No backup mechanism found anywhere in the repository",
        detail=(
            f"Signals: {', '.join(backup_signals)}." if backup_signals else
            "No dump command, snapshot call, or sync-to-remote appears in the code, the "
            "configuration, or the documentation. Whether that matters depends on whether the "
            "data is reconstructable."
        ),
        criterion="D3",
        severity=Severity.MAJOR if (has_persistence and not backup_signals) else None,
        remediation=(
            "Add a scheduled snapshot to a location that is not the same disk, a retention "
            "window, and a documented restore procedure. Then run the restore once — an "
            "unverified backup is a belief, not a control."
        ) if (has_persistence and not backup_signals) else None,
        data={"signals": backup_signals},
    ))

    # ── D4: migrations ───────────────────────────────────────────────────────────────────────
    all_paths = " ".join(view.files())
    migration_signals = sorted({h for h in _MIGRATION_HINTS if h in all_paths or h in haystack})
    if has_persistence:
        facts.append(Fact(
            pillar_id=PILLAR, key="migration_signals",
            title="Schema migrations present" if migration_signals else
                  "A database is used, but no migration mechanism was found",
            detail=(
                f"Signals: {', '.join(migration_signals)}." if migration_signals else
                "Without migrations, a schema change is a manual step — which means it gets "
                "skipped, or handled by deleting the database and letting it recreate."
            ),
            criterion="D4",
            severity=None if migration_signals else Severity.MINOR,
            data={"signals": migration_signals},
        ))

    return facts
