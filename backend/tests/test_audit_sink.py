# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The audit trail, which is only worth having if it cannot be lost or quietly stopped.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Two properties matter more than the rest, and both are counter-intuitive enough to be worth
asserting. An event must reach the disk before the request that caused it returns, or a crash
takes the record of what was happening when it crashed. And a failure to write must never
propagate: an audit sink that can fail a mutation turns a logging problem into an outage.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def sink(data_dir):
    from audit import sink as module

    return module


def test_an_event_is_on_disk_before_emit_returns(sink):
    """Buffered would be fine for a log and is not fine for this.

    The trail exists to answer "what was happening when it broke". Anything still in a userspace
    buffer at the moment of a crash is exactly the part that mattered.
    """
    sink.emit(sink.build_event(actor="tester", action="repository:add", outcome="ok"))

    files = list((sink.paths.audit_dir()).glob("audit-*.jsonl"))
    assert len(files) == 1, "emit did not create a day file"
    assert files[0].read_text(encoding="utf-8").strip(), "the file is empty after emit returned"


def test_events_are_one_json_object_per_line(sink):
    for index in range(3):
        sink.record(actor=f"user-{index}", action="assessment:create", outcome="ok")

    path = next(sink.paths.audit_dir().glob("audit-*.jsonl"))
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert len(lines) == 3
    for line in lines:
        # One object per line, so a truncated write costs one event rather than the file.
        assert json.loads(line)["action"] == "assessment:create"


def test_a_write_failure_does_not_reach_the_caller(sink, monkeypatch):
    """The sink is called from a request hook. If it raises, a successful mutation reports failure
    to the user, and they retry something that already happened."""
    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("pathlib.Path.open", explode)
    sink.emit(sink.build_event(actor="tester", action="assessment:cancel", outcome="ok"))


def test_secrets_are_redacted_before_they_are_written(sink):
    """The trail is read by more people than the database is, and kept longer."""
    sink.record(
        actor="tester", action="repository:add", outcome="ok",
        detail={"url": "https://oauth2:glpat-AAAAAAAAAAAAAAAAAAAA@gitlab.example.com/g/p.git"},
    )

    written = next(sink.paths.audit_dir().glob("audit-*.jsonl")).read_text(encoding="utf-8")
    assert "glpat-AAAAAAAAAAAAAAAAAAAA" not in written, "a token was written to the audit trail"


def test_build_event_records_the_fields_an_investigation_needs(sink):
    event = sink.build_event(
        actor="rkoike", action="assessment:create", outcome="ok",
        resource="/api/assessments", correlation_id="abc123", source_ip="10.0.0.1",
        is_mock=True,
    )

    assert event["actor"] == "rkoike"
    assert event["outcome"] == "ok"
    assert event["correlation_id"] == "abc123"
    # Named mock_identity rather than is_mock: in a trail, the question being answered is "was
    # this a real person", and the answer should not depend on knowing our configuration flags.
    assert event["mock_identity"] is True
    assert event["ts"].endswith("Z") or "+00:00" in event["ts"], "timestamps must be UTC"


def test_read_day_returns_newest_first_and_respects_the_limit(sink):
    for index in range(5):
        sink.record(actor=f"user-{index}", action="repository:add", outcome="ok")

    recent = sink.read_day(limit=2)
    assert len(recent) == 2
    assert recent[0]["actor"] == "user-4", "the most recent event should be first"


def test_read_day_survives_a_corrupt_line(sink):
    """A half-written line from a crash must not make the whole day unreadable."""
    sink.record(actor="tester", action="repository:add", outcome="ok")
    path = next(sink.paths.audit_dir().glob("audit-*.jsonl"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"ts": "2026-01-01T00:00:00Z", "act\n')

    events = sink.read_day()
    assert len(events) == 2
    assert any(e.get("outcome") == "unparseable" for e in events), (
        "a corrupt line should be surfaced as unparseable, not silently dropped"
    )


def test_read_day_and_available_days_are_empty_before_anything_is_written(sink):
    assert sink.read_day() == []
    assert sink.available_days() == []


def test_available_days_lists_what_is_on_disk(sink):
    sink.record(actor="tester", action="repository:add", outcome="ok")

    days = sink.available_days()
    assert len(days) == 1
    assert len(days[0]) == 8 and days[0].isdigit(), f"expected YYYYMMDD, got {days[0]!r}"
