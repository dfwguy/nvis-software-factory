# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Snapshots, retention, and a restore path that has actually been exercised.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Durability criterion D3, which is the one most often satisfied on paper and not in fact. An
unverified backup is a belief, so this module does three things rather than one:

* takes the snapshot with ``VACUUM INTO``,
* verifies the snapshot is a readable, intact database *before* reporting success,
* is exercised by a test that restores a snapshot and reads a row back out of it.

WHY ``VACUUM INTO`` AND NOT A FILE COPY
----------------------------------------
Copying a live SQLite file is a coin flip. With WAL enabled the file on disk is not the current
state -- recent commits live in the ``-wal`` sidecar -- so ``cp factory.db backup.db`` produces a
database missing its most recent transactions, and does so silently. Copying all three files
without a lock can catch them mid-checkpoint and produce a corrupt set.

``VACUUM INTO`` runs inside the engine, takes a consistent read, and writes a single compacted file
with no sidecars. The result is a complete database that opens cleanly. It needs no downtime and
holds no write lock for the duration.

WHERE SNAPSHOTS GO
-------------------
Under the data directory, which means the same volume as the live database. That is a real
limitation and it is stated rather than hidden: it protects against corruption, a bad migration and
an accidental delete, and does **not** protect against losing the volume or the host. Offsite copy
is the operator's job, and the deployment guide says so. A backup written next to the live data and
described as a backup, with nothing saying what it does not cover, is worse than none -- it buys
false confidence.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import paths
import settings

from . import db

_logger = logging.getLogger("nvsf.store.backup")

_STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_PREFIX = "factory-"
_SUFFIX = ".db"


@dataclass(frozen=True)
class Snapshot:
    path: Path
    taken_at: datetime
    bytes: int

    @property
    def age(self) -> timedelta:
        return datetime.now(UTC) - self.taken_at


class BackupError(RuntimeError):
    """The snapshot could not be taken, or could not be verified once taken."""


def _verify(path: Path) -> None:
    """Open the snapshot and ask SQLite whether it is sound.

    This is the step that turns a backup from a belief into a fact, and it is cheap. A snapshot
    that fails here is deleted rather than left in place, because a corrupt file with a plausible
    name is exactly what someone will reach for in an emergency.
    """
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
    except sqlite3.Error as exc:
        raise BackupError(f"snapshot {path.name} cannot be opened: {exc}") from exc
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise BackupError(
                f"snapshot {path.name} failed integrity_check: {result[0] if result else 'no result'}"
            )
        # A structurally valid but empty file would pass integrity_check. Confirm the schema is
        # there, which is the thing a restore actually needs.
        tables = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()[0]
        if not tables:
            raise BackupError(f"snapshot {path.name} has no schema_migrations table")
    finally:
        conn.close()


def take(destination: Path | None = None) -> Snapshot:
    """Take and verify a snapshot. Raises :class:`BackupError` on any failure."""
    now = datetime.now(UTC)
    target_dir = destination or paths.backups_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{_PREFIX}{now.strftime(_STAMP_FORMAT)}{_SUFFIX}"

    if target.exists():
        # Same-second collision. Not worth a retry loop; the caller is a scheduler.
        raise BackupError(f"{target.name} already exists")

    sound, detail = db.integrity_check()
    if not sound:
        # A snapshot of a corrupt database is a corrupt snapshot, and taking it would rotate a good
        # one out of the retention window.
        raise BackupError(
            f"refusing to snapshot: the live database failed integrity_check ({detail}). "
            "Restore from the most recent good snapshot instead of overwriting the window."
        )

    started = time.monotonic()
    try:
        # Parameter binding is not available for VACUUM INTO -- SQLite requires a literal. The path
        # is constructed above from a timestamp and a fixed directory, never from input, so there
        # is no injection surface; the quote-doubling is belt and braces.
        literal = str(target).replace("'", "''")
        db.connection().execute(f"VACUUM INTO '{literal}'")
    except sqlite3.Error as exc:
        target.unlink(missing_ok=True)
        raise BackupError(f"VACUUM INTO failed: {exc}") from exc

    try:
        _verify(target)
    except BackupError:
        target.unlink(missing_ok=True)
        raise

    size = target.stat().st_size
    _logger.info(
        "store: snapshot %s (%.1f MB) verified in %.2fs",
        target.name, size / 1_048_576, time.monotonic() - started,
    )
    return Snapshot(path=target, taken_at=now, bytes=size)


def list_snapshots(source: Path | None = None) -> list[Snapshot]:
    """Existing snapshots, newest first. Unparseable filenames are ignored, not an error --
    an operator's manual copy sitting in the directory should not break rotation."""
    target_dir = source or paths.backups_dir()
    if not target_dir.is_dir():
        return []
    found: list[Snapshot] = []
    for path in target_dir.glob(f"{_PREFIX}*{_SUFFIX}"):
        stamp = path.name[len(_PREFIX):-len(_SUFFIX)]
        try:
            taken = datetime.strptime(stamp, _STAMP_FORMAT).replace(tzinfo=UTC)
        except ValueError:
            continue
        found.append(Snapshot(path=path, taken_at=taken, bytes=path.stat().st_size))
    return sorted(found, key=lambda s: s.taken_at, reverse=True)


def prune(retain_days: int | None = None, source: Path | None = None) -> list[Path]:
    """Delete snapshots older than the retention window. Returns what was removed.

    **The newest snapshot is never deleted**, whatever its age. Without that rule, a service that
    has been down for longer than the retention window prunes its way to zero backups on the first
    boot -- which is the exact moment the backups matter most.
    """
    days = retain_days if retain_days is not None else settings.get_int("NVSF_BACKUP_RETAIN_DAYS", 14)
    if days <= 0:
        return []

    snapshots = list_snapshots(source)
    if len(snapshots) <= 1:
        return []

    cutoff = datetime.now(UTC) - timedelta(days=days)
    removed: list[Path] = []
    for snapshot in snapshots[1:]:
        if snapshot.taken_at < cutoff:
            snapshot.path.unlink(missing_ok=True)
            removed.append(snapshot.path)
    if removed:
        _logger.info("store: pruned %d snapshot(s) older than %d days", len(removed), days)
    return removed


def due(source: Path | None = None) -> bool:
    """Whether a snapshot is due, per the configured interval. ``0`` disables snapshots."""
    interval = settings.get_int("NVSF_BACKUP_INTERVAL_HOURS", 24)
    if interval <= 0:
        return False
    snapshots = list_snapshots(source)
    if not snapshots:
        return True
    return snapshots[0].age >= timedelta(hours=interval)


def run_if_due() -> Snapshot | None:
    """Snapshot and prune if the interval has elapsed. Called by the background scheduler.

    Failures are logged and swallowed here, deliberately: a failed snapshot must not take the
    application down. It is reported through the health endpoint instead, so it surfaces as a
    degraded state rather than as an outage or as silence.
    """
    if not due():
        return None
    try:
        snapshot = take()
    except BackupError as exc:
        _logger.error("store: snapshot failed: %s", exc)
        return None
    prune()
    return snapshot


def health() -> dict[str, object]:
    """Backup posture, for the health endpoint.

    Reports ``configured: False`` when the interval is 0, rather than reporting healthy. Durability
    criterion D3 is not met by a deployment with snapshots switched off, and the app should say so
    about itself.
    """
    interval = settings.get_int("NVSF_BACKUP_INTERVAL_HOURS", 24)
    snapshots = list_snapshots()
    newest = snapshots[0] if snapshots else None
    return {
        "configured": interval > 0,
        "interval_hours": interval,
        "retain_days": settings.get_int("NVSF_BACKUP_RETAIN_DAYS", 14),
        "count": len(snapshots),
        "newest": newest.path.name if newest else None,
        "newest_age_hours": round(newest.age.total_seconds() / 3600, 1) if newest else None,
        "stale": bool(interval > 0 and (newest is None or newest.age > timedelta(hours=interval * 2))),
        "same_volume_as_live_data": True,
    }
