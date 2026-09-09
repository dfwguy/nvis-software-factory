# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Data access behaviour: dedup, lifecycle, provenance, resumability.

Author: Rafael M. Koike & Cursor Agent ("Ada")
"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize("url", [
    "https://gitlab-master.nvidia.com/nvis-ova/tool.git",
    "https://gitlab-master.nvidia.com/nvis-ova/tool",
    "http://gitlab-master.nvidia.com/nvis-ova/tool/",
    "git@gitlab-master.nvidia.com:nvis-ova/tool.git",
    "GITLAB-MASTER.NVIDIA.COM/NVIS-OVA/TOOL",
])
def test_spellings_of_one_repository_canonicalize_together(url):
    """People paste https, ssh and bare forms of the same URL. Three spellings must not become
    three repositories with three assessment histories."""
    from store.repo import canonicalize

    canonical, forge, namespace, name = canonicalize(url)
    assert canonical == "gitlab-master.nvidia.com/nvis-ova/tool"
    assert forge == "gitlab"
    assert namespace == "nvis-ova"
    assert name == "tool"


def test_canonicalize_strips_embedded_credentials():
    """A URL pasted with a token in it must not be stored. This is the chokepoint that guarantees
    it, rather than a check at each call site."""
    from store.repo import canonicalize

    canonical, _, _, _ = canonicalize("https://oauth2:glpat-SECRETVALUE@gitlab.com/g/p.git")
    assert "glpat" not in canonical
    assert "SECRETVALUE" not in canonical
    assert canonical == "gitlab.com/g/p"


def test_upsert_is_idempotent(migrated):
    from store import repo

    first = repo.upsert_repository("https://github.com/nvidia/x.git", added_by="a")
    second = repo.upsert_repository("git@github.com:nvidia/x.git", added_by="b")
    assert first.id == second.id
    assert repo.count_repositories() == 1


def test_failed_assessment_must_record_a_reason(migrated):
    """A failed run with no reason is a run nobody can act on."""
    from store import repo

    record = repo.upsert_repository("https://github.com/nvidia/x", added_by="a")
    assessment = repo.create_assessment(record.id, created_by="a")

    with pytest.raises(ValueError, match="must record a reason"):
        repo.fail_assessment(assessment.id, reason="")


def test_llm_unavailable_fails_the_run_retryably(migrated):
    """The AI-first contract: an unreachable endpoint fails the run and says a retry can help. It
    does not produce a thinner report."""
    from store import repo
    from store.models import Status

    record = repo.upsert_repository("https://github.com/nvidia/x", added_by="a")
    assessment = repo.create_assessment(record.id, created_by="a")

    repo.fail_assessment(
        assessment.id, reason="llm_unreachable",
        detail="connection refused to http://nim.internal/v1", retryable=True,
    )

    reloaded = repo.get_assessment(assessment.id)
    assert reloaded.status is Status.FAILED
    assert reloaded.retryable is True
    assert reloaded.to_json()["failure"]["reason"] == "llm_unreachable"


def test_terminal_status_stamps_finished_at(migrated):
    from store import repo
    from store.models import Status

    record = repo.upsert_repository("https://github.com/nvidia/x", added_by="a")
    assessment = repo.create_assessment(record.id, created_by="a")

    repo.set_status(assessment.id, Status.CLONING)
    assert repo.get_assessment(assessment.id).started_at is not None
    assert repo.get_assessment(assessment.id).finished_at is None

    repo.set_status(assessment.id, Status.COMPLETE)
    assert repo.get_assessment(assessment.id).finished_at is not None


def test_active_assessments_finds_a_run_a_crash_left_behind(migrated):
    """A run left 'reasoning' by a crash is not running any more. Startup has to be able to find
    it, or the UI shows a spinner forever."""
    from store import repo
    from store.models import Status

    record = repo.upsert_repository("https://github.com/nvidia/x", added_by="a")
    stuck = repo.create_assessment(record.id, created_by="a")
    done = repo.create_assessment(record.id, created_by="a")

    repo.set_status(stuck.id, Status.REASONING)
    repo.set_status(done.id, Status.COMPLETE)

    active = [a.id for a in repo.active_assessments()]
    assert stuck.id in active
    assert done.id not in active


def test_completed_passes_survive_for_resume(migrated):
    """Per-pass persistence is what makes an outage resume rather than restart."""
    from store import repo

    record = repo.upsert_repository("https://github.com/nvidia/x", added_by="a")
    assessment = repo.create_assessment(record.id, created_by="a")

    first = repo.start_pass(assessment.id, "architecture")
    repo.complete_pass(first, {"summary": "a flask service"})
    second = repo.start_pass(assessment.id, "pillar_judgement")
    repo.fail_pass(second, "endpoint timed out")

    done = repo.completed_passes(assessment.id)
    assert done == {"architecture": {"summary": "a flask service"}}
    states = {p["pass_name"]: p["status"] for p in repo.pass_states(assessment.id)}
    assert states == {"architecture": "complete", "pillar_judgement": "failed"}


def test_restarting_a_pass_clears_its_previous_error(migrated):
    from store import repo

    record = repo.upsert_repository("https://github.com/nvidia/x", added_by="a")
    assessment = repo.create_assessment(record.id, created_by="a")

    pass_id = repo.start_pass(assessment.id, "architecture")
    repo.fail_pass(pass_id, "timed out")
    again = repo.start_pass(assessment.id, "architecture")

    assert again == pass_id, "a retried pass must reuse its row, not accumulate duplicates"
    state = repo.pass_states(assessment.id)[0]
    assert state["status"] == "running"
    assert state["error"] is None


def test_failed_llm_calls_are_recorded_too(migrated):
    """A timeout is provenance as much as a success is -- it is what explains a nine-minute run."""
    from store import repo
    from store.models import LlmCall, new_id, now_iso

    record = repo.upsert_repository("https://github.com/nvidia/x", added_by="a")
    assessment = repo.create_assessment(record.id, created_by="a")

    for status, error, tokens in (("ok", None, 1200), ("timeout", "read timeout after 180s", None)):
        repo.record_llm_call(LlmCall(
            id=new_id(), assessment_id=assessment.id, pass_name="architecture",
            model="test-model", prompt_version="architecture@1", temperature=0.2,
            status=status, created_at=now_iso(), prompt_tokens=tokens, completion_tokens=40,
            error=error, raw_response='{"choices": []}',
        ))

    calls = repo.list_llm_calls(assessment.id)
    assert [c.status for c in calls] == ["ok", "timeout"]
    assert repo.token_usage(assessment.id) == {
        "prompt_tokens": 1200, "completion_tokens": 80, "calls": 2,
    }
    # The raw response is retained but not exposed by default -- it can be large.
    assert "raw_response" not in calls[0].to_json()
    assert calls[0].to_json(include_raw=True)["raw_response"] == '{"choices": []}'


def test_findings_record_the_ratchet_audit_trail(migrated):
    """origin + escalated_from is what lets a reviewer check the model's escalation instead of
    being handed a merged severity with no history."""
    from store import repo
    from store.models import Finding, Origin, Severity, new_id, now_iso

    record = repo.upsert_repository("https://github.com/nvidia/x", added_by="a")
    assessment = repo.create_assessment(record.id, created_by="a")

    repo.save_findings([
        Finding(
            id=new_id(), assessment_id=assessment.id, pillar_id="durability", criterion="D1",
            severity=Severity.BLOCKER, title="State is in-memory only", origin=Origin.SCANNER,
            created_at=now_iso(), file_path="app.py", line_start=42,
            escalated_from=Severity.MAJOR, detector="scanners/durability.py",
        ),
        Finding(
            id=new_id(), assessment_id=assessment.id, pillar_id="reliability", criterion="R2",
            severity=Severity.MAJOR, title="Unreachable node reported as healthy",
            origin=Origin.MODEL, created_at=now_iso(), file_path="check.py",
            line_start=10, line_end=24,
        ),
    ])

    findings = {f.criterion: f for f in repo.list_findings(assessment.id)}
    assert findings["D1"].citation == "app.py:42"
    assert findings["D1"].escalated_from is Severity.MAJOR
    assert findings["R2"].citation == "check.py:10-24"
    assert findings["R2"].origin is Origin.MODEL
    assert repo.severity_counts(assessment.id)["blocker"] == 1


def test_severity_ranks_are_ordered():
    """The ratchet compares ranks, so the ordering is behaviour rather than presentation."""
    from store.models import Severity

    ranks = [Severity.INFO.rank, Severity.MINOR.rank, Severity.MAJOR.rank, Severity.BLOCKER.rank]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == 4


def test_evidence_round_trips_and_upserts(migrated):
    from store import repo

    record = repo.upsert_repository("https://github.com/nvidia/x", added_by="a")
    assessment = repo.create_assessment(record.id, created_by="a")

    repo.save_evidence(assessment.id, {"files": 12}, "hash-a")
    repo.save_evidence(assessment.id, {"files": 13}, "hash-b")

    assert repo.get_evidence(assessment.id) == {"files": 13}


def test_findings_can_be_cleared_for_a_re_reason(migrated):
    from store import repo
    from store.models import Finding, Origin, Severity, new_id, now_iso

    record = repo.upsert_repository("https://github.com/nvidia/x", added_by="a")
    assessment = repo.create_assessment(record.id, created_by="a")
    repo.save_findings([Finding(
        id=new_id(), assessment_id=assessment.id, pillar_id="durability",
        severity=Severity.MINOR, title="t", origin=Origin.SCANNER, created_at=now_iso(),
    )])

    repo.clear_findings(assessment.id)
    assert repo.list_findings(assessment.id) == []


def test_artifacts_upsert_by_kind(migrated):
    from store import repo

    record = repo.upsert_repository("https://github.com/nvidia/x", added_by="a")
    assessment = repo.create_assessment(record.id, created_by="a")

    repo.record_artifact(assessment.id, "scorecard", "SCORECARD.md", 100, "aa")
    repo.record_artifact(assessment.id, "scorecard", "SCORECARD.md", 250, "bb")

    artifacts = repo.list_artifacts(assessment.id)
    assert len(artifacts) == 1
    assert artifacts[0]["bytes"] == 250
