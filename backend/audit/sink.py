# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Append-only audit trail, as daily JSONL files on the durable volume.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Observability criterion O4: who did what, to what, when, and what happened. On the durable volume
rather than in the application log, so it survives log rotation and a container replacement.

WHY JSONL AND NOT A TABLE
--------------------------
An audit trail should be hard to modify, and the property that gives it value is that it is
append-only. A row in the same database as the application's own data is one ``UPDATE`` away from
being wrong, by an application bug as easily as by anyone's intent. A file opened ``"a"`` and
fsynced is the cheapest thing that resists that.

It is also the format a support bundle wants: ``jq`` over a day's file needs no schema and no
database, which matters when the person reading it is not the person who wrote the app.

WHAT IS NOT AUDITED
--------------------
Reads. Auditing every GET turns the trail into a second access log, and a trail nobody can read
is a trail nobody reads. Mutating actions are declared in ``authz/resources.py`` with
``mutating=True``, so the set is a declaration rather than a decision made per call site.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import paths
from logging_config import redact

_logger = logging.getLogger("nvsf.audit")

#: Serializes appends. One process, several request threads: two interleaved writes would produce
#: a line that is not valid JSON, and a corrupt audit line is worse than a missing one because it
#: breaks every reader downstream.
_lock = threading.Lock()


def _path_for(when: datetime) -> Path:
    return paths.audit_dir() / f"audit-{when.strftime('%Y%m%d')}.jsonl"


def build_event(
    actor: str,
    action: str,
    outcome: str,
    resource: str | None = None,
    detail: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    source_ip: str | None = None,
    is_mock: bool = False,
) -> dict[str, Any]:
    """Assemble one event.

    Separate from :func:`emit` so a caller can build, inspect and test an event without writing
    one, and so the request hook can enrich it before it lands.
    """
    return {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "actor": actor,
        "action": action,
        "resource": resource,
        "outcome": outcome,
        "correlation_id": correlation_id,
        "source_ip": source_ip,
        # Marks an event produced under the development mock identity, so it can never be mistaken
        # for a real one during an investigation.
        "mock_identity": is_mock,
        "detail": detail or {},
    }


def emit(event: dict[str, Any]) -> None:
    """Append one event, durably.

    Failures are logged, not raised. An audit write that takes down the request it is describing
    turns an observability gap into an outage. The failure is loud in the application log, which is
    the right severity: it needs fixing, and it must not break the product.
    """
    line = redact(json.dumps(event, default=str, separators=(",", ":")))
    target = _path_for(datetime.now(UTC))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with _lock, target.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            # fsync per event. The write rate is a handful per minute, so the cost is
            # invisible, and an audit trail that loses its last entries in a crash is missing
            # exactly the entries an investigation wants.
            os.fsync(handle.fileno())
    except OSError as exc:
        _logger.error("audit: could not write to %s: %s", target, exc)


def record(
    actor: str,
    action: str,
    outcome: str,
    resource: str | None = None,
    detail: dict[str, Any] | None = None,
    **kwargs: Any,
) -> None:
    """Build and emit in one call. The convenience form used by non-HTTP callers."""
    emit(build_event(actor, action, outcome, resource, detail, **kwargs))


def read_day(when: datetime | None = None, limit: int = 500) -> list[dict[str, Any]]:
    """Most recent events for a day, newest first.

    A malformed line is reported as an ``unparseable`` entry rather than skipped. Silently dropping
    it would hide the one thing worth knowing about an audit file -- that something wrote garbage
    into it.
    """
    target = _path_for(when or datetime.now(UTC))
    if not target.is_file():
        return []
    events: list[dict[str, Any]] = []
    for raw in target.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            events.append(json.loads(raw))
        except ValueError:
            events.append({"outcome": "unparseable", "raw": raw[:400]})
    return list(reversed(events))[:limit]


def available_days() -> list[str]:
    directory = paths.audit_dir()
    if not directory.is_dir():
        return []
    return sorted(
        (p.stem.removeprefix("audit-") for p in directory.glob("audit-*.jsonl")),
        reverse=True,
    )
