# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""SQLite connections, configured for durability rather than for defaults.

Author: Rafael M. Koike & Cursor Agent ("Ada")

This is the module the whole durability pillar points at, so it is worth being explicit about each
pragma. SQLite's defaults are tuned for compatibility with very old deployments, and three of them
are wrong for a service that must not lose data.

``journal_mode = WAL``
    The default rollback journal blocks readers during a write and, more importantly, has a crash
    window where the database is being rewritten in place. WAL appends changes and commits by
    writing a frame, so a crash mid-transaction leaves a complete previous state rather than a
    partially updated one. It also lets the assessment worker write while the UI reads, which the
    default mode does not. Criterion D2.

``synchronous = FULL``
    ``NORMAL`` is the common recommendation with WAL, and it is a real trade: it can lose the last
    transaction on a *host* power loss (not on a process crash). We take FULL because the write
    rate here is a handful of rows per assessment, not thousands per second, so the fsync cost is
    invisible and "the last finding is missing" is a confusing failure to debug.

``foreign_keys = ON``
    Off by default, per-connection, and silently. Without it the schema's REFERENCES clauses are
    decoration and orphaned findings accumulate after a deleted assessment.

``busy_timeout``
    Without it a concurrent write raises ``database is locked`` immediately. The assessment worker
    and the request thread do overlap, so this is not hypothetical.

CONNECTIONS ARE PER-THREAD
---------------------------
A sqlite3 connection is not safe to share across threads, and gunicorn runs a thread pool. Rather
than pass ``check_same_thread=False`` and hope, each thread gets its own connection from a
thread-local, and each is configured identically -- the pragmas above are per-connection, so a
connection created without them would silently opt out of foreign keys.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import paths

_logger = logging.getLogger("nvsf.store")

_local = threading.local()

#: Guards schema application so two threads cannot migrate concurrently.
_schema_lock = threading.Lock()


def _configure(conn: sqlite3.Connection) -> None:
    """Apply the pragmas. Per-connection, so this runs for every connection without exception."""
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    # Keeps the WAL from growing without bound on a long-lived connection.
    conn.execute("PRAGMA wal_autocheckpoint = 1000")


def connect(path: Path | None = None) -> sqlite3.Connection:
    """A fresh, configured connection. Callers that hold one are responsible for closing it."""
    target = path or paths.db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=10.0, isolation_level=None)
    _configure(conn)
    return conn


def connection() -> sqlite3.Connection:
    """This thread's connection, created on first use.

    ``isolation_level=None`` puts the connection in autocommit mode, which sounds like the unsafe
    choice and is the opposite: it means transactions are explicit, opened by :func:`transaction`,
    rather than implicitly begun by the driver at a point that depends on the statement type.
    """
    existing = getattr(_local, "conn", None)
    if existing is not None:
        return existing
    conn = connect()
    _local.conn = conn
    return conn


def close_connection() -> None:
    """Close this thread's connection, if any. Used by tests and by worker shutdown."""
    existing = getattr(_local, "conn", None)
    if existing is not None:
        existing.close()
        _local.conn = None


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Explicit transaction. Commits on success, rolls back on any exception.

    ``BEGIN IMMEDIATE`` rather than a bare ``BEGIN``: a deferred transaction takes its write lock
    at the first write, so two writers can both start, both read, and then one fails at commit
    time -- after the caller has already done its work. IMMEDIATE takes the lock up front and waits
    out ``busy_timeout`` instead.
    """
    conn = connection()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def query(sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[sqlite3.Row]:
    """Read helper. Parameterized only -- there is no string-interpolation variant, on purpose."""
    return connection().execute(sql, params).fetchall()


def query_one(sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> sqlite3.Row | None:
    return connection().execute(sql, params).fetchone()


def execute(sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> sqlite3.Cursor:
    """Single-statement write, in its own transaction."""
    with transaction() as conn:
        return conn.execute(sql, params)


def integrity_check() -> tuple[bool, str]:
    """Ask SQLite whether the file is sound. Used by the health endpoint and before a snapshot.

    A backup taken from a corrupt database is a corrupt backup, and the whole point of D3 is that
    the restore path works.
    """
    row = connection().execute("PRAGMA integrity_check").fetchone()
    result = row[0] if row else "unknown"
    return result == "ok", str(result)


def stats() -> dict[str, Any]:
    """Size and shape, for diagnostics."""
    conn = connection()
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    ]
    return {
        "path": str(paths.db_path()),
        "bytes": page_count * page_size,
        "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
        "foreign_keys": bool(conn.execute("PRAGMA foreign_keys").fetchone()[0]),
        "tables": tables,
    }
