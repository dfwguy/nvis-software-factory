# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The background runner, and what happens to work in flight when the process dies.

Author: Rafael M. Koike & Cursor Agent ("Ada")

An assessment takes minutes and runs in a thread, which means a restart lands in the middle of
one. The states that follow are the interesting ones: a run left mid-pipeline is not running any
more, but the database still says it is, and the UI will spin on it forever unless something
reconciles. ``recover_orphans`` is that something, and it only works if the runner's failure
handling is exhaustive -- a pass that dies without recording why leaves the same stuck row.
"""

from __future__ import annotations

import threading

import pytest


@pytest.fixture
def runner(migrated):
    from factory import runner as module

    module.start()
    yield module
    module.shutdown(wait=True)


def _repository(url="https://gitlab.example.com/nvis/example.git"):
    from store import repo

    return repo.upsert_repository(url, added_by="tester")


def test_submit_before_start_is_refused(migrated):
    """Silently dropping the work would be worse: the row says queued and nothing is running."""
    from factory import runner as module

    module.shutdown(wait=True)
    with pytest.raises(RuntimeError):
        module.submit("some-id")


def test_a_submitted_assessment_runs(runner, monkeypatch):
    from store import repo

    ran = threading.Event()
    monkeypatch.setattr("factory.pipeline.run", lambda _id: ran.set())

    record = repo.create_assessment(_repository().id, created_by="tester", ref="main")
    runner.submit(record.id)

    assert ran.wait(timeout=10), "the pipeline was never called"


def test_submitting_the_same_assessment_twice_runs_it_once(runner, monkeypatch):
    """Two clicks on Retry, or a client that retries a 202 it did not see, must not start two
    pipelines writing the same rows."""
    from store import repo

    started = threading.Event()
    release = threading.Event()
    calls = []

    def slow(assessment_id):
        calls.append(assessment_id)
        started.set()
        release.wait(timeout=10)

    monkeypatch.setattr("factory.pipeline.run", slow)

    record = repo.create_assessment(_repository().id, created_by="tester", ref="main")
    runner.submit(record.id)
    assert started.wait(timeout=10)

    runner.submit(record.id)
    release.set()
    runner.shutdown(wait=True)

    assert calls == [record.id]


def test_a_crashing_pass_fails_the_run_as_retryable(runner, monkeypatch):
    """The failure that would otherwise be invisible.

    An unhandled exception inside a worker thread is swallowed by the executor -- the future holds
    it and nobody looks. The row stays in whatever state it was in, and the UI polls it forever.
    Marked retryable because an unexpected crash is exactly the case where a human should be able
    to press the button again rather than file a bug first.
    """
    from store import repo
    from store.models import Status

    done = threading.Event()

    def explode(_id):
        raise RuntimeError("a pass blew up")

    monkeypatch.setattr("factory.pipeline.run", explode)

    record = repo.create_assessment(_repository().id, created_by="tester", ref="main")
    runner.submit(record.id)

    for _ in range(100):
        refreshed = repo.get_assessment(record.id)
        if refreshed and refreshed.status is Status.FAILED:
            done.set()
            break
        threading.Event().wait(0.05)

    assert done.is_set(), "a crashing pipeline left the assessment in a non-terminal state"
    refreshed = repo.get_assessment(record.id)
    assert refreshed.retryable is True


def test_in_flight_reports_what_is_running(runner, monkeypatch):
    from store import repo

    started = threading.Event()
    release = threading.Event()

    def slow(_id):
        started.set()
        release.wait(timeout=10)

    monkeypatch.setattr("factory.pipeline.run", slow)

    record = repo.create_assessment(_repository().id, created_by="tester", ref="main")
    runner.submit(record.id)
    assert started.wait(timeout=10)

    assert record.id in runner.in_flight()

    release.set()
    runner.shutdown(wait=True)


def test_recover_orphans_requeues_a_run_stranded_by_a_restart(runner, monkeypatch):
    """The reconciliation that makes a restart survivable.

    A row reading 'reasoning' after a boot is a lie -- nothing is reasoning, the thread that was
    died with the process. Left alone it is a permanent spinner, which is the worst of both
    worlds: no result and no error either.
    """
    from store import repo
    from store.models import Status

    record = repo.create_assessment(_repository().id, created_by="tester", ref="main")
    repo.set_status(record.id, Status.REASONING)

    submitted = []
    monkeypatch.setattr(runner, "submit", submitted.append)

    recovered = runner.recover_orphans()

    assert record.id in recovered
    assert record.id in submitted
    assert repo.get_assessment(record.id).status is Status.QUEUED, (
        "a recovered run must be put back to queued, or the UI still shows it mid-flight"
    )


def test_a_run_already_owned_by_another_process_is_not_started_twice(runner, monkeypatch):
    """The duplicate every worker used to be capable of starting.

    ``_futures`` is this process's dictionary, so it cannot see a run owned by a sibling worker.
    Holding the file lock here is what that sibling looks like from the outside. Starting anyway
    would repeat all eleven model calls and race the first copy on the findings write.
    """
    from factory import runlock
    from store import repo

    record = repo.create_assessment(_repository().id, created_by="tester", ref="main")
    calls = []
    monkeypatch.setattr("factory.pipeline.run", calls.append)

    with runlock.hold(record.id) as owned:
        assert owned, "the test must be the one holding it"
        runner._guarded(record.id)

    assert calls == [], "the pipeline ran despite another process owning the run"
    assert repo.get_assessment(record.id).failure_reason is None, (
        "stepping aside is not a failure -- the run is proceeding, just not here"
    )


def test_recovery_leaves_a_run_that_is_alive_in_another_process_alone(runner, monkeypatch):
    """Worker recycling, which reaches this without any restart at all.

    A recycled worker re-imports the composition root and recovers, while its siblings keep
    serving. A healthy run in one of them is non-terminal, so it looks exactly like an orphan --
    and resetting it to ``queued`` would rewind the progress of a run that is still going.
    """
    from factory import runlock
    from store import repo
    from store.models import Status

    record = repo.create_assessment(_repository().id, created_by="tester", ref="main")
    repo.set_status(record.id, Status.REASONING)
    monkeypatch.setattr(runner, "submit", lambda _id: None)

    with runlock.hold(record.id) as owned:
        assert owned
        recovered = runner.recover_orphans()

    assert record.id not in recovered
    assert repo.get_assessment(record.id).status is Status.REASONING, (
        "a live run was rewound to queued by another worker's recovery"
    )


def test_recover_orphans_leaves_finished_runs_alone(runner, monkeypatch):
    from store import repo
    from store.models import Status

    record = repo.create_assessment(_repository().id, created_by="tester", ref="main")
    repo.set_status(record.id, Status.COMPLETE)

    monkeypatch.setattr(runner, "submit", lambda _id: None)

    assert record.id not in runner.recover_orphans()
    assert repo.get_assessment(record.id).status is Status.COMPLETE


def test_start_is_idempotent(runner):
    """Called from the composition root, which gunicorn imports once per worker -- but tests and
    the recovery path call it too, and a second executor would double the concurrency limit."""
    runner.start()
    runner.start()
    assert runner.in_flight() == []
