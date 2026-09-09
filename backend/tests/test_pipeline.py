# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""A full assessment run, against a local git repository and a scripted model.

Author: Rafael M. Koike & Cursor Agent ("Ada")

The repository is a real one — ``git init`` in a temporary directory — because the acquisition
step runs ``git`` and mocking that away would leave the most failure-prone stage untested. The
model is scripted, because the assertions here are about the pipeline's behaviour and a real
model's non-determinism would make them flaky without making them stronger.

The two properties that matter most:

* **Fail closed.** An unreachable model endpoint fails the run. There is no scanners-only report,
  because a report that looks complete but skipped its reasoning stage is indistinguishable from
  a real one to the person reading it.
* **Resume.** Completed passes are reused on retry, so a failure on the last of eleven model calls
  does not throw away the first ten.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest
from factory import llm, pipeline
from factory.llm import Completion, LlmUnavailable, Usage
from store import repo
from store.models import Origin, Severity, Status


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
            "HOME": str(root), "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )


@pytest.fixture
def local_repository(tmp_path) -> Path:
    """A real git repository with the in-memory-state defect, served over file://."""
    root = tmp_path / "subject"
    root.mkdir()
    (root / "app.py").write_text(textwrap.dedent("""
        from flask import Flask, jsonify, request

        app = Flask(__name__)
        results = {}

        @app.route("/results/<rack>", methods=["POST"])
        def record(rack):
            results[rack] = request.json
            return jsonify({"ok": True})

        if __name__ == "__main__":
            app.run(host="0.0.0.0")
    """).lstrip(), encoding="utf-8")
    (root / "docker-compose.yml").write_text(
        "services:\n  api:\n    build: .\n    ports:\n      - \"8080:8080\"\n", encoding="utf-8",
    )
    (root / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")

    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial")
    return root


class ScriptedModel:
    """A stand-in for the LLM that answers each pass plausibly, and counts calls per pass.

    Answers are keyed by pass name rather than being a single canned blob, so the pipeline's
    field wiring is genuinely exercised: a pass whose prompt does not render, or whose required
    keys are missing, fails here rather than in production.
    """

    def __init__(self, downgrade_everything: bool = False, fail_pass: str | None = None):
        self.calls: list[str] = []
        self.downgrade_everything = downgrade_everything
        self.fail_pass = fail_pass

    def __call__(self, system, user, *, prompt_version, **kwargs):
        pass_name = kwargs.get("pass_name", "unknown")
        self.calls.append(pass_name)

        if self.fail_pass and pass_name == self.fail_pass:
            raise LlmUnavailable("scripted failure: endpoint refused the connection")

        payload = self._answer(pass_name, user)
        completion = Completion(
            text=json.dumps(payload),
            model="scripted-model",
            prompt_version=prompt_version,
            temperature=0.2,
            usage=Usage(prompt_tokens=100, completion_tokens=50),
            duration_ms=5,
            raw={},
        )
        # Record the call, because the real client does. Skipping it would leave the provenance
        # section of the report untested, and provenance is a large part of what the report is for.
        self._record(kwargs.get("assessment_id"), completion, pass_name, kwargs)
        return completion

    @staticmethod
    def _record(assessment_id, completion, pass_name, kwargs) -> None:
        if not assessment_id:
            return
        from store.models import LlmCall, new_id, now_iso

        repo.record_llm_call(LlmCall(
            id=new_id(), assessment_id=assessment_id, pass_name=pass_name,
            model=completion.model, prompt_version=completion.prompt_version,
            temperature=completion.temperature, status="ok", created_at=now_iso(),
            evidence_hash=kwargs.get("evidence_digest"),
            prompt_tokens=completion.usage.prompt_tokens,
            completion_tokens=completion.usage.completion_tokens,
            duration_ms=completion.duration_ms, raw_response=completion.text,
        ))

    def _answer(self, pass_name: str, user: str) -> dict:
        if pass_name == "architecture":
            return {
                "summary": "A Flask service that records rack validation results in memory.",
                "archetype": "http-service",
                "purpose": "Collect validation results per rack.",
                "state_management": "A module-level dict.",
                "entry_points": ["app.py"],
            }
        if pass_name.startswith("judgement:"):
            pillar_id = pass_name.split(":", 1)[1]
            answer: dict = {
                "verdict": "fail" if pillar_id == "durability" else "concerns",
                "summary": f"Judgement for {pillar_id}.",
                "criteria": [
                    {"id": "D1", "outcome": "fail", "reasoning": "No volume.",
                     "evidence": "docker-compose.yml:1"},
                ],
                "escalations": [],
                "additional_findings": [],
                "open_questions": [f"Who owns this, for {pillar_id}?"],
            }
            if pillar_id == "durability":
                if self.downgrade_everything:
                    answer["escalations"] = [{
                        "finding_title":
                            "Containerized, and no volume or mount is declared anywhere",
                        "to_severity": "minor",
                        "why": "It is only a prototype.",
                    }]
                else:
                    answer["additional_findings"] = [{
                        "criterion": "D1",
                        "severity": "major",
                        "title": "Nothing reconstructs the results if the process restarts",
                        "detail": "No log, export, or upstream source to replay from.",
                        "file_path": "app.py",
                        "line_start": 4,
                        "remediation": "Write each result to SQLite as it arrives.",
                    }]
            return answer
        if pass_name == "remediation":
            return {
                "steps": [
                    {
                        "title": "Persist results to SQLite on a bind mount",
                        "why": "The dict is the only copy.",
                        "change": "Replace the module dict with a SQLite table.",
                        "files": ["app.py", "docker-compose.yml"],
                        "acceptance": "Results survive `docker compose restart`.",
                        "test": "A test that writes, restarts, and reads back.",
                        "addresses": ["container_without_volume"],
                    },
                ],
            }
        if pass_name == "open_questions":
            return {
                "questions": [
                    {"question": "Is the result data reconstructable from another source?",
                     "why": "It decides whether this is a blocker or an inconvenience."},
                ],
            }
        return {"summary": "unhandled pass", "verdict": "undetermined", "steps": [],
                "questions": []}


@pytest.fixture
def scripted(monkeypatch):
    model = ScriptedModel()
    monkeypatch.setattr(llm, "complete", model)
    return model


@pytest.fixture(scope="module")
def completed_run(tmp_path_factory):
    """One full successful run, shared by the tests that only read its output.

    Module-scoped because a pipeline run clones a real repository, and doing that once per
    assertion about the same report is waste for no additional coverage. The tests that need
    different model behaviour — a downgrade attempt, an unreachable endpoint, a mid-run failure —
    each get their own run below, because for those the run *is* the thing under test.

    Returns ``(assessment_id, scripted_model)``.
    """
    import os
    import subprocess as sp

    from store import db, migrations

    root = tmp_path_factory.mktemp("completed-run")
    previous = os.environ.get("NVSF_DATA_DIR")
    os.environ.update({
        "NVSF_DATA_DIR": str(root), "NVSF_ENV": "development",
        "NVSF_LLM_BASE_URL": "http://127.0.0.1:1/v1", "NVSF_LLM_MODEL": "test-model",
        "NVSF_OIDC_MOCK": "true", "NVSF_BIND_ADDR": "127.0.0.1",
        "NVSF_PUBLIC_URL": "http://127.0.0.1:8000",
    })
    db.close_connection()
    migrations.apply()

    subject = root / "subject"
    subject.mkdir()
    (subject / "app.py").write_text(textwrap.dedent("""
        from flask import Flask, jsonify, request

        app = Flask(__name__)
        results = {}

        @app.route("/results/<rack>", methods=["POST"])
        def record(rack):
            results[rack] = request.json
            return jsonify({"ok": True})
    """).lstrip(), encoding="utf-8")
    (subject / "docker-compose.yml").write_text(
        "services:\n  api:\n    build: .\n", encoding="utf-8",
    )
    (subject / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "initial"]):
        sp.run(["git", *args], cwd=subject, check=True, capture_output=True, env={
            "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "HOME": str(root), "PATH": "/usr/bin:/bin:/usr/local/bin",
        })

    from factory import acquire

    # Widen the URL policy and the model only for the duration of the run itself, and restore both
    # before yielding. Restoring in a `finally` would leave them widened for every test that runs
    # after this fixture is first requested, because module-scoped teardown happens at the end of
    # the module -- which is exactly the leak that
    # `test_the_production_url_policy_still_refuses_file_urls` exists to catch.
    real_validate, real_protocols = acquire._validate, acquire.ALLOWED_GIT_PROTOCOLS
    real_complete = llm.complete
    model = ScriptedModel()
    acquire._validate = lambda url: url.strip()
    acquire.ALLOWED_GIT_PROTOCOLS = ("https", "http", "file")
    llm.complete = model
    try:
        assessment_id = _submit(subject)
        pipeline.run(assessment_id)
    finally:
        llm.complete = real_complete
        acquire._validate, acquire.ALLOWED_GIT_PROTOCOLS = real_validate, real_protocols

    try:
        yield assessment_id, model
    finally:
        db.close_connection()
        if previous is not None:
            os.environ["NVSF_DATA_DIR"] = previous


def _submit(local_repository: Path) -> str:
    # A plain path, not a file:// URL. `clone()` passes `protocol.allow=never` to git and only
    # re-enables http and https, so even with the validator bypassed git itself refuses the file
    # transport — which is the defence working correctly. A bare path uses git's local transport
    # and leaves that hardening intact.
    repository = repo.upsert_repository(url=str(local_repository), added_by="test@nvidia.com")
    assessment = repo.create_assessment(
        repository_id=repository.id, created_by="test@nvidia.com",
        intake={"purpose": "Records rack validation results."},
    )
    return assessment.id


@pytest.fixture
def allow_file_urls(monkeypatch):
    """Let ``clone()`` fetch from a local path for the duration of a test.

    Production refuses everything but http(s) with a real host, and rightly: a repository URL is
    user input and this process can reach the host's filesystem and its network, so ``file://``
    and the metadata address are both refused. That refusal is what has to be bypassed to test
    against a real repository.

    Bypassing the *validator* rather than widening its scheme list keeps the production policy
    exactly as it ships — ``file:///path`` also has no host, so widening schemes alone would not
    have worked without loosening the host check too, and at that point the tested code is no
    longer the deployed code. Everything after validation is real: the git subprocess, the
    hardening flags, the size measurement, the submodule check.
    ``test_the_production_url_policy_still_refuses_file_urls`` pins the real policy.
    """
    from factory import acquire

    monkeypatch.setattr(acquire, "_validate", lambda url: url.strip())
    monkeypatch.setattr(acquire, "ALLOWED_GIT_PROTOCOLS", ("https", "http", "file"))


# ── The happy path ───────────────────────────────────────────────────────────────────────────


def test_a_full_run_produces_a_complete_assessment(completed_run):
    assessment_id, model = completed_run

    assessment = repo.get_assessment(assessment_id)
    assert assessment.status is Status.COMPLETE, assessment.failure_detail
    assert assessment.commit_sha
    assert assessment.evidence_hash

    # Every pass ran: architecture, eight pillars, remediation, open questions.
    from factory import standards
    expected = 3 + len(standards.load().pillars)
    assert len(model.calls) == expected
    assert model.calls[0] == "architecture"
    assert model.calls[-1] == "open_questions"


def test_the_deterministic_blocker_survives_the_whole_pipeline(completed_run):
    """End to end, the thing that motivated the project is still a blocker in the output."""
    assessment_id, _ = completed_run
    findings = repo.list_findings(assessment_id)
    volume = [f for f in findings if f.detector == "container_without_volume"]
    assert volume, [f.title for f in findings]
    assert volume[0].severity is Severity.BLOCKER
    assert volume[0].origin is Origin.SCANNER

    # And the model's own addition is present, labelled as judgement.
    model_findings = [f for f in findings if f.origin is Origin.MODEL]
    assert any("reconstructs" in f.title for f in model_findings)


def test_artifacts_are_written_and_readable(completed_run):
    from factory import report

    assessment_id, _ = completed_run
    artifacts = {a["filename"] for a in repo.list_artifacts(assessment_id)}
    assert artifacts == {
        "ASSESSMENT.md", "AGENT_PLAN.md", "EVIDENCE.md", "evidence.json", "findings.json",
    }

    assessment_md = report.artifact_path(assessment_id, "ASSESSMENT.md").read_text()
    # The headline names the worst thing rather than counting.
    assert "no volume or mount is declared" in assessment_md
    # Origin is visible, so a reader can weigh measurement against judgement.
    assert "origin: scanner" in assessment_md
    assert "origin: review" in assessment_md
    # Provenance travels with the artifact.
    assert "Evidence hash" in assessment_md
    assert "scripted-model" in assessment_md

    plan_md = report.artifact_path(assessment_id, "AGENT_PLAN.md").read_text()
    assert "One step, one commit" in plan_md
    assert "Persist results to SQLite on a bind mount" in plan_md
    assert "Done when" in plan_md


def test_the_report_contains_no_score(completed_run):
    """A grade gets quoted without its findings and implies a precision we do not have."""
    from factory import report

    assessment_id, _ = completed_run
    text = report.artifact_path(assessment_id, "ASSESSMENT.md").read_text()

    assert "%" not in text
    assert "There is no score" in text


def test_artifact_paths_cannot_escape_the_bundle(completed_run):
    from factory import report

    assessment_id, _ = completed_run
    assert report.artifact_path(assessment_id, "../../../etc/passwd") is None
    assert report.artifact_path(assessment_id, "/etc/passwd") is None
    assert report.artifact_path(assessment_id, "ASSESSMENT.md") is not None


# ── The ratchet, end to end ──────────────────────────────────────────────────────────────────


def test_a_model_downgrade_does_not_reach_the_report(
    migrated, llm_env, local_repository, monkeypatch, allow_file_urls,
):
    """The property under realistic conditions: the model asks nicely and is refused."""
    from factory import report

    model = ScriptedModel(downgrade_everything=True)
    monkeypatch.setattr(llm, "complete", model)

    assessment_id = _submit(local_repository)
    pipeline.run(assessment_id)

    assert repo.get_assessment(assessment_id).status is Status.COMPLETE
    volume = [
        f for f in repo.list_findings(assessment_id)
        if f.detector == "container_without_volume"
    ]
    assert volume[0].severity is Severity.BLOCKER

    # And the refusal is on the record rather than hidden.
    text = report.artifact_path(assessment_id, "ASSESSMENT.md").read_text()
    assert "refused" in text.lower()
    assert "only a prototype" in text


# ── Failing closed ───────────────────────────────────────────────────────────────────────────


def test_an_unreachable_model_fails_the_run(
    migrated, llm_env, local_repository, monkeypatch, allow_file_urls,
):
    """No scanners-only report. This is the AI-first commitment, enforced."""
    def unreachable(*args, **kwargs):
        raise LlmUnavailable("connection refused")

    monkeypatch.setattr(llm, "complete", unreachable)

    assessment_id = _submit(local_repository)
    pipeline.run(assessment_id)

    assessment = repo.get_assessment(assessment_id)
    assert assessment.status is Status.FAILED
    assert assessment.failure_reason == "llm-unavailable"
    assert assessment.retryable is True
    # Nothing was published.
    assert repo.list_artifacts(assessment_id) == []
    assert repo.list_findings(assessment_id) == []


def test_a_failure_partway_through_keeps_the_completed_passes(
    migrated, llm_env, local_repository, monkeypatch, allow_file_urls,
):
    """The resume property. A failure on a late pass must not discard the early ones."""
    failing = ScriptedModel(fail_pass="remediation")
    monkeypatch.setattr(llm, "complete", failing)

    assessment_id = _submit(local_repository)
    pipeline.run(assessment_id)

    assert repo.get_assessment(assessment_id).status is Status.FAILED
    completed = repo.completed_passes(assessment_id)
    assert "architecture" in completed
    assert "judgement:durability" in completed
    assert "remediation" not in completed

    # Retry with a working model: only the unfinished passes are called again.
    working = ScriptedModel()
    monkeypatch.setattr(llm, "complete", working)
    repo.set_status(assessment_id, Status.QUEUED)
    pipeline.run(assessment_id)

    assert repo.get_assessment(assessment_id).status is Status.COMPLETE
    assert working.calls == ["remediation", "open_questions"]


def test_a_run_that_cannot_get_the_source_fails_before_reasoning(
    migrated, llm_env, scripted,
):
    """A refused URL fails the run without touching the network or the model.

    Loopback is used deliberately: `_validate` refuses it as an SSRF target before any DNS lookup
    or connect, so this test has no network dependency and no timeout to wait out.
    """
    repository = repo.upsert_repository(
        url="https://127.0.0.1/nope/nothing-here.git", added_by="test@nvidia.com",
    )
    assessment = repo.create_assessment(
        repository_id=repository.id, created_by="test@nvidia.com",
    )
    pipeline.run(assessment.id)

    result = repo.get_assessment(assessment.id)
    assert result.status is Status.FAILED
    assert result.failure_reason == "clone-refused"
    # Not retryable: retrying a refused URL fails identically, so offering a retry would be a lie.
    assert result.retryable is False
    # The model was never called: a run that cannot get the source has nothing to reason about.
    assert scripted.calls == []


def test_the_production_url_policy_still_refuses_file_urls(migrated, llm_env):
    """Guards the widening that the local-repository fixture performs."""
    from factory.acquire import AcquireRefused, validate_url

    with pytest.raises(AcquireRefused):
        validate_url("file:///etc/passwd")
    with pytest.raises(AcquireRefused):
        validate_url("git@gitlab.com:group/project.git")
    with pytest.raises(AcquireRefused):
        validate_url("https://169.254.169.254/latest/meta-data/")


# ── Cancellation ─────────────────────────────────────────────────────────────────────────────


def test_cancelling_mid_run_reaches_a_terminal_state(
    migrated, llm_env, local_repository, monkeypatch, allow_file_urls,
):
    """A cancelled run must not be left looking active."""
    assessment_id = _submit(local_repository)

    class CancelAfterArchitecture(ScriptedModel):
        def __call__(self, *args, **kwargs):
            result = super().__call__(*args, **kwargs)
            if kwargs.get("pass_name") == "architecture":
                pipeline.request_cancel(assessment_id)
            return result

    monkeypatch.setattr(llm, "complete", CancelAfterArchitecture())
    pipeline.run(assessment_id)

    assessment = repo.get_assessment(assessment_id)
    assert assessment.status is Status.CANCELLED
    assert assessment.status.terminal
    # The completed pass is kept, so resuming later is cheap.
    assert "architecture" in repo.completed_passes(assessment_id)


# ── Provenance ───────────────────────────────────────────────────────────────────────────────


def test_every_model_call_is_recorded_against_the_run(completed_run):
    assessment_id, model = completed_run

    states = {p["pass_name"]: p["status"] for p in repo.pass_states(assessment_id)}
    from factory import standards
    for pillar in standards.load().pillars:
        assert states[f"judgement:{pillar.id}"] == "complete"
    assert states["architecture"] == "complete"
    assert states["remediation"] == "complete"
    assert states["open_questions"] == "complete"

    # Passes and recorded calls have to agree, or the provenance section is telling a story
    # that does not match what actually ran.
    calls = repo.list_llm_calls(assessment_id)
    assert len(calls) == len(model.calls)
    assert {c.pass_name for c in calls} == set(states)
    assert all(c.model == "scripted-model" for c in calls)
    assert all(c.prompt_version for c in calls)


def test_the_evidence_document_is_persisted_with_its_hash(completed_run):
    assessment_id, _ = completed_run
    document = repo.get_evidence(assessment_id)
    assert document is not None
    assert document["standards_version"]
    assert "durability" in document["pillars"]
    assert repo.get_assessment(assessment_id).evidence_hash


def test_the_api_summary_exposes_findings_and_progress(completed_run):
    assessment_id, _ = completed_run
    summary = pipeline.summarize_for_api(assessment_id)
    assert summary["assessment"]["status"] == "complete"
    assert summary["architecture"]["archetype"] == "http-service"
    assert "durability" in summary["judgements"]
    assert summary["remediation"]["steps"]
    assert summary["severity_counts"].get("blocker", 0) >= 1
    assert len(summary["artifacts"]) == 5
