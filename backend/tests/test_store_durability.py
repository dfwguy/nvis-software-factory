# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The durability promises in store/__init__.py, asserted rather than claimed.

Author: Rafael M. Koike & Cursor Agent ("Ada")

The application tells other teams their backup is a belief until the restore path has been
exercised. This file exercises ours: ``test_snapshot_restores_and_reads`` opens a snapshot as a
database and reads a row back out of it, which is the only version of that claim worth making.
"""

from __future__ import annotations

import os
import sqlite3

import pytest


def test_pragmas_are_applied_to_every_connection(migrated):
    """The pragmas are per-connection, so a connection made without them silently opts out."""
    from store import db

    stats = db.stats()
    assert stats["journal_mode"] == "wal"
    assert stats["foreign_keys"] is True


def test_foreign_keys_are_enforced(migrated):
    """Without PRAGMA foreign_keys the REFERENCES clauses are decoration."""
    from store import db

    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO assessments (id, repository_id, status, created_at, created_by, "
            "retryable) VALUES ('a', 'no-such-repo', 'queued', '2026-01-01T00:00:00+00:00', "
            "'tester', 0)"
        )


def test_transaction_rolls_back_on_exception(migrated):
    from store import db, repo

    record = repo.upsert_repository("https://gitlab.example.com/g/p.git", added_by="tester")

    with pytest.raises(RuntimeError), db.transaction() as conn:
        conn.execute("UPDATE repositories SET name = 'changed' WHERE id = ?", (record.id,))
        raise RuntimeError("boom")

    assert repo.get_repository(record.id).name == "p"


def test_migrations_are_idempotent(migrated):
    from store import migrations

    assert migrations.apply() == []
    assert migrations.current_version() >= 1


def test_concurrent_processes_can_migrate_a_cold_database(data_dir):
    """Several processes applying migrations at once must produce one winner and no casualties.

    A regression test for a deployment failure, not a theoretical race. Gunicorn forks its
    workers, each imports the application, each calls ``apply()``. On a cold boot they all read an
    empty ``schema_migrations``, all decide 0001 is pending, and the ones that lose the race die
    with ``table repositories already exists`` -- which gunicorn reports only as "Worker failed to
    boot".

    Real subprocesses, because that is the whole point: the threading lock that used to guard this
    is invisible across a fork, so a thread-based test would have passed while the deployment
    failed.
    """
    import concurrent.futures
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parent.parent
    program = (
        f"import sys; sys.path.insert(0, {str(backend)!r});"
        "from store import migrations;"
        "print(len(migrations.apply()))"
    )

    def migrate() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True, text=True, timeout=60, check=False,
            env={**os.environ, "NVSF_DATA_DIR": str(data_dir)},
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: migrate(), range(4)))

    failed = [r for r in results if r.returncode != 0]
    assert not failed, (
        "a process failed to apply migrations concurrently:\n"
        + "\n".join(r.stderr[-600:] for r in failed)
    )

    # Exactly one process should report having applied anything. More than one means two
    # processes both ran the DDL and the second only appeared to succeed.
    applied = [int(r.stdout.strip()) for r in results]
    assert sum(1 for count in applied if count > 0) == 1, (
        f"expected exactly one process to apply migrations, got counts {applied}"
    )


def test_edited_migration_is_refused(migrated, monkeypatch):
    """An applied migration is history. Editing one means every later migration was written
    against a schema that no longer describes the database."""
    from store import migrations

    original = migrations.discover

    def tampered():
        found = original()
        first = found[0]
        return [
            migrations.Migration(
                version=first.version, name=first.name, path=first.path,
                sql=first.sql + "\n-- an edit after the fact\n",
            ),
            *found[1:],
        ]

    monkeypatch.setattr(migrations, "discover", tampered)
    with pytest.raises(migrations.MigrationError, match="has changed since it was applied"):
        migrations.pending()


def test_snapshot_restores_and_reads(migrated):
    """The restore path, exercised. This is what turns D3 from a belief into a fact."""
    from store import backup, repo

    record = repo.upsert_repository("https://github.com/nvidia/example", added_by="tester")
    assessment = repo.create_assessment(record.id, created_by="tester", ref="main")

    snapshot = backup.take()
    assert snapshot.path.is_file()
    assert snapshot.bytes > 0
    # VACUUM INTO produces a single file with no -wal/-shm sidecars, which is the property that
    # makes it safe to copy elsewhere.
    assert not snapshot.path.with_suffix(".db-wal").exists()

    restored = sqlite3.connect(f"file:{snapshot.path}?mode=ro", uri=True)
    restored.row_factory = sqlite3.Row
    try:
        row = restored.execute(
            "SELECT status, ref FROM assessments WHERE id = ?", (assessment.id,)
        ).fetchone()
        assert row is not None, "the snapshot does not contain data committed before it was taken"
        assert row["status"] == "queued"
        assert row["ref"] == "main"
    finally:
        restored.close()


def test_prune_never_deletes_the_newest_snapshot(migrated):
    """A service down longer than the retention window must not prune its way to zero backups on
    the first boot -- which is exactly when the backups matter."""
    from datetime import UTC, datetime, timedelta

    from store import backup

    snapshot = backup.take()
    ancient = datetime.now(UTC) - timedelta(days=400)
    aged = snapshot.path.parent / f"factory-{ancient.strftime('%Y%m%dT%H%M%SZ')}.db"
    snapshot.path.rename(aged)

    assert backup.prune(retain_days=1) == []
    assert aged.is_file()


def test_prune_removes_snapshots_past_the_window(migrated):
    from datetime import UTC, datetime, timedelta

    from store import backup

    newest = backup.take()
    stale_paths = []
    for days in (30, 60):
        when = datetime.now(UTC) - timedelta(days=days)
        stale = newest.path.parent / f"factory-{when.strftime('%Y%m%dT%H%M%SZ')}.db"
        stale.write_bytes(newest.path.read_bytes())
        stale_paths.append(stale)

    removed = backup.prune(retain_days=7)
    assert sorted(p.name for p in removed) == sorted(p.name for p in stale_paths)
    assert newest.path.is_file()


def test_backup_health_reports_disabled_rather_than_healthy(migrated, monkeypatch):
    """A deployment with snapshots switched off does not meet D3, and the app says so about
    itself rather than reporting green."""
    from store import backup

    monkeypatch.setenv("NVSF_BACKUP_INTERVAL_HOURS", "0")
    health = backup.health()
    assert health["configured"] is False
    assert health["same_volume_as_live_data"] is True


def test_corrupt_live_database_is_not_snapshotted(migrated, monkeypatch):
    """Snapshotting a corrupt database would rotate a good snapshot out of the window."""
    from store import backup, db

    monkeypatch.setattr(db, "integrity_check", lambda: (False, "malformed database"))
    with pytest.raises(backup.BackupError, match="integrity_check"):
        backup.take()
