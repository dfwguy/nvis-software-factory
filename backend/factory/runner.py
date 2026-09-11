# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Running assessments off the request thread.

Author: Rafael M. Koike & Cursor Agent ("Ada")

An assessment takes minutes and a request must return in milliseconds, so ``POST /api/assessments``
enqueues and returns 202 with a run id. This module owns the queue.

WHY A THREAD POOL AND NOT CELERY
---------------------------------
A broker plus a worker fleet is the right answer at a scale this will not reach. The work here is
almost entirely waiting on a network — git fetch, then eleven HTTP calls to the LLM endpoint — so
threads are not fighting the GIL for anything that matters, and a handful of concurrent
assessments is the realistic ceiling for a tool used by one team.

What matters more is that the work is **restartable**, and that comes from per-pass persistence in
the pipeline rather than from the queue. A container restart loses whatever was in flight, and
:func:`recover_orphans` picks those up at startup, which is a property a broker would have given us
at the cost of a second service to operate on the ITSS VM.

CONCURRENCY IS BOUNDED, AND THE BOUND IS DELIBERATE
----------------------------------------------------
The pool is small. The constraint is not local CPU, it is the shared LLM endpoint: ten concurrent
assessments is a hundred-odd in-flight completions against an endpoint other teams use too. A
queued run that starts in two minutes is fine; rate-limiting the endpoint for everyone is not.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor

import settings
from store import repo
from store.models import Status

from factory import pipeline, runlock

_logger = logging.getLogger("nvsf.factory.runner")

_executor: ThreadPoolExecutor | None = None
_futures: dict[str, Future] = {}
_lock = threading.Lock()


def start() -> None:
    """Create the pool. Called once from the composition root."""
    global _executor
    with _lock:
        if _executor is not None:
            return
        workers = max(1, settings.get_int("NVSF_ASSESSMENT_WORKERS", 2))
        _executor = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="nvsf-assess",
        )
        _logger.info("runner: started with %d worker(s)", workers)


def shutdown(wait: bool = False) -> None:
    """Stop accepting work.

    ``wait=False`` by default: on SIGTERM the container has a limited grace period, and an
    assessment mid-flight will resume from its completed passes on the next start. Blocking the
    shutdown for minutes to finish one run buys nothing and risks a SIGKILL in the middle of a
    database write instead of between passes.
    """
    global _executor
    with _lock:
        executor, _executor = _executor, None
    if executor is not None:
        executor.shutdown(wait=wait, cancel_futures=True)
        _logger.info("runner: shut down")


def submit(assessment_id: str) -> None:
    """Queue an assessment. Idempotent for an id already in flight."""
    with _lock:
        if _executor is None:
            raise RuntimeError("runner: submit before start()")
        existing = _futures.get(assessment_id)
        if existing is not None and not existing.done():
            _logger.info("runner: %s already in flight", assessment_id)
            return
        future = _executor.submit(_guarded, assessment_id)
        _futures[assessment_id] = future


def _guarded(assessment_id: str) -> None:
    """Run one assessment, guaranteeing a terminal status even on an unexpected failure.

    ``pipeline.run`` already handles its own exceptions and writes terminal state. This second
    layer exists for the failures that happen outside that handling — an import error, a database
    connection that cannot be opened, a MemoryError. Without it, such a run would sit in
    ``queued`` forever and the UI would show a spinner with no explanation.

    The run lock is taken here rather than in :func:`submit` because it must be held for the whole
    run, and :func:`submit` returns as soon as the work is queued. Stepping aside when another
    process holds it is not a failure and must not be recorded as one: the run is proceeding, just
    not here.
    """
    try:
        with runlock.hold(assessment_id) as owned:
            if not owned:
                _logger.info(
                    "runner: %s is already running in another process; not starting a second",
                    assessment_id,
                )
                return
            pipeline.run(assessment_id)
    except BaseException as error:
        _logger.exception("runner: %s died outside the pipeline's own handling", assessment_id)
        try:
            repo.fail_assessment(
                assessment_id, "runner-error", f"{type(error).__name__}: {error}",
                retryable=True,
            )
        except Exception:
            _logger.exception("runner: could not even record the failure for %s", assessment_id)
    finally:
        with _lock:
            _futures.pop(assessment_id, None)


def in_flight() -> list[str]:
    with _lock:
        return sorted(k for k, f in _futures.items() if not f.done())


def recover_orphans() -> list[str]:
    """Re-queue runs left non-terminal by a restart.

    A container that stops mid-run leaves an assessment in ``cloning`` or ``reasoning`` with no
    thread behind it. Left alone it shows as running forever, which is the worst of the options —
    the SA waits for something that will never finish.

    Re-queueing rather than failing them is possible precisely because completed passes are
    persisted: the retry costs only the passes that did not finish.
    """
    # Every non-terminal assessment is an orphan, including the ones still marked `queued`: the
    # queue lives in this process's memory, so nothing survived the restart to pick them up.
    active = repo.active_assessments()
    mid_run = sum(1 for a in active if a.status is not Status.QUEUED)
    recovered: list[str] = []

    for assessment in active:
        try:
            # Not every non-terminal run is an orphan. A recycled worker re-imports this module
            # while its siblings are still serving, so a run that is alive in another process
            # would otherwise be "recovered" -- its status reset to `queued` underneath it, and a
            # second copy of it started.
            if runlock.held_elsewhere(assessment.id):
                _logger.info(
                    "runner: %s is running in another process, leaving it alone", assessment.id,
                )
                continue
            if assessment.status is not Status.QUEUED:
                repo.set_status(assessment.id, Status.QUEUED)
            submit(assessment.id)
            recovered.append(assessment.id)
        except Exception:
            # One unrecoverable row must not stop the others from being recovered.
            _logger.exception("runner: could not recover %s", assessment.id)

    if recovered:
        _logger.warning(
            "runner: re-queued %d assessment(s) orphaned by a restart; %d had already started",
            len(recovered), mid_run,
        )
    return recovered
