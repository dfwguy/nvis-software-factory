# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""One process per run, enforced by the filesystem.

Author: Rafael M. Koike & Cursor Agent ("Ada")

WHY THIS EXISTS
---------------
The runner's own guard against starting a run twice is a dictionary of futures, and that
dictionary belongs to one process. Gunicorn runs several. Nothing about that mattered while the
only way to start a run was the request that created it, since one worker handled that request and
owned the run.

Startup recovery broke the assumption. ``recover_orphans`` runs at import, so **every** worker
performs it, and each one re-queues and submits the same orphaned assessment. ``start_pass`` is an
upsert rather than a conflict, so the second process does not collide with the first -- it
proceeds, repeating all eleven model calls, and the two runs race each other on the findings
write, where one clears the table the other is filling. The result is a doubled bill and a report
assembled from two interleaved runs.

Worker recycling makes the same collision reachable without a restart: a recycled worker re-imports
the module while a healthy run is still going in a sibling worker, and recovery would reset that
live run to ``queued``.

WHY flock AND NOT A LEASE IN THE DATABASE
------------------------------------------
A lease column means choosing a duration, renewing it from a heartbeat while a run holds it, and
deciding what to do about a lease that expired because the endpoint was slow rather than because
the owner died. Every one of those is a way to either kill a healthy run or leave a dead one
locked.

``flock`` has none of that bookkeeping. The kernel releases the lock when the file descriptor
closes, which includes the process being killed, so a crashed run is immediately recoverable and a
live one cannot be stolen. The cost is that it is confined to one host -- which is where this
application already lives, for the same reason its database is a single SQLite file.
"""

from __future__ import annotations

import fcntl
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import paths

_logger = logging.getLogger("nvsf.factory.runlock")


def _lock_path(assessment_id: str) -> Path:
    directory = paths.data_dir() / "locks"
    directory.mkdir(parents=True, exist_ok=True)
    # The files are empty and are left behind deliberately. Unlinking on release races another
    # process that has already opened the same path and is about to lock an inode nobody else can
    # reach any more, which would hand the same run to two owners -- the exact failure this
    # module exists to prevent.
    return directory / f"{assessment_id}.lock"


@contextmanager
def hold(assessment_id: str) -> Iterator[bool]:
    """Take the run lock, yielding whether this process got it.

    Yields rather than raising so the caller can decide: the runner logs and steps aside, while
    recovery treats a refusal as proof the run is alive.
    """
    handle = _lock_path(assessment_id).open("w")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def held_elsewhere(assessment_id: str) -> bool:
    """True when some other process is running this assessment right now.

    Answered by trying to take the lock and giving it straight back, so it is a reading of one
    instant and not a reservation. That is enough for its one caller: recovery only needs to tell
    an abandoned run from a live one, and a run that starts in the moment after this returns is
    stopped by the lock itself when it reaches :func:`hold`.
    """
    with hold(assessment_id) as acquired:
        return not acquired
