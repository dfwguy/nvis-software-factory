# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The assessment endpoints: starting a run, reading it, and the states in between.

Author: Rafael M. Koike & Cursor Agent ("Ada")

An assessment is a long, expensive, side-effecting operation started by an HTTP request, which
makes the endpoints around it mostly about refusing things. Refusing to start a second run against
a repository already being assessed. Refusing to start at all when the reasoning endpoint is
unreachable, rather than finding out after the clone and the scan. Refusing to retry something
that did not fail.

``factory.pipeline.run`` is faked throughout. A real run clones over the network and calls an LLM;
what is under test here is the HTTP surface, and the pipeline has its own tests.
"""

from __future__ import annotations

import uuid

import pytest


@pytest.fixture(autouse=True)
def no_real_pipeline(monkeypatch):
    """Nothing in this file should reach the network or spend a minute in a thread."""
    monkeypatch.setattr("factory.pipeline.run", lambda _id: None)


@pytest.fixture
def reachable_llm(monkeypatch):
    """The reasoning endpoint reports itself healthy.

    Needed by every create test: the endpoint probes before accepting, which is the whole point of
    the fail-closed design, and the test configuration points at a port with nothing on it.
    """
    monkeypatch.setattr(
        "factory.llm.probe",
        lambda: {"reachable": True, "endpoint": "http://test/v1", "model": "test-model",
                 "api_key_configured": True, "detail": "ok", "latency_ms": 1},
    )


def _repository(app_client):
    url = f"https://gitlab.example.com/nvis/example-{uuid.uuid4().hex[:10]}.git"
    return app_client.post("/api/repositories/", json={"url": url}).get_json()["repository"]


def _start(app_client, **body):
    return app_client.post("/api/assessments/", json=body)


# ── Starting a run ───────────────────────────────────────────────────────────────────────────


def test_starting_a_run_by_repository_id_returns_202(app_client, reachable_llm):
    """202, not 200: the work has been accepted and is not done. A client that treats this as a
    completed operation will poll for a report that is minutes away."""
    repository = _repository(app_client)

    response = _start(app_client, repository_id=repository["id"])

    assert response.status_code == 202
    body = response.get_json()
    assert body["assessment"]["status"] in {"queued", "cloning"}
    assert body["assessment"]["created_by"]


def test_starting_a_run_by_url_creates_the_repository_too(app_client, reachable_llm):
    """The common path from the UI: an SA pastes a URL and expects one action, not two."""
    url = f"https://gitlab.example.com/nvis/fresh-{uuid.uuid4().hex[:10]}.git"

    body = _start(app_client, url=url).get_json()

    assert body["repository"]["url"].startswith("https://gitlab.example.com/nvis/fresh-")
    assert body["assessment"]["repository_id"] == body["repository"]["id"]


def test_starting_a_run_with_neither_target_is_a_400(app_client, reachable_llm):
    response = _start(app_client)

    assert response.status_code == 400
    assert response.get_json()["reason"] == "missing-target"


def test_starting_a_run_against_an_unknown_repository_is_a_404(app_client, reachable_llm):
    response = _start(app_client, repository_id=str(uuid.uuid4()))

    assert response.status_code == 404


def test_starting_a_run_against_a_refused_url_is_a_422(app_client, reachable_llm):
    response = _start(app_client, url="https://127.0.0.1/x/y.git")

    assert response.status_code == 422
    assert response.get_json()["reason"] == "url-refused"


def test_a_second_run_against_the_same_repository_is_refused(app_client, reachable_llm):
    """Two pipelines writing one repository's rows is a race with no useful outcome, and the
    409 names the run already in progress so the UI can navigate to it instead of erroring."""
    repository = _repository(app_client)
    _start(app_client, repository_id=repository["id"])

    response = _start(app_client, repository_id=repository["id"])

    assert response.status_code == 409
    body = response.get_json()
    assert body["reason"] == "already-running"
    assert body["assessment_id"], "the refusal should point at the run that is already going"


def test_a_run_is_refused_when_the_reasoning_endpoint_is_unreachable(app_client, monkeypatch):
    """Fail closed, and fail early.

    The LLM is a required stage with no degraded mode. Accepting the run would mean cloning the
    repository and running every scanner before failing several minutes later -- and the report
    that never arrives looks, to the person waiting, exactly like one that is still running.
    """
    monkeypatch.setattr(
        "factory.llm.probe",
        lambda: {"reachable": False, "endpoint": "http://test/v1", "model": "test-model",
                 "api_key_configured": False, "detail": "connection refused"},
    )
    repository = _repository(app_client)

    response = _start(app_client, repository_id=repository["id"])

    assert response.status_code == 503
    body = response.get_json()
    assert body["reason"] == "llm-unavailable"
    assert body["probe"]["detail"], "the refusal must say what was wrong, or nobody can fix it"


def test_the_intake_answers_are_kept_with_the_run(app_client, reachable_llm):
    """These are the questions a scanner cannot answer -- what the software is for, who uses it,
    what happens if it is wrong -- and they are what the reasoning stage judges severity against."""
    repository = _repository(app_client)

    body = _start(
        app_client, repository_id=repository["id"],
        purpose="Validate NVL72 racks before handover",
        audience="NVIS SAs and the customer's operations team",
        criticality="high",
        data_handled="Serial numbers and BMC credentials",
    ).get_json()

    intake = body["assessment"]["intake"]
    assert intake["criticality"] == "high"
    assert "NVL72" in intake["purpose"]


def test_a_ref_can_be_pinned(app_client, reachable_llm):
    """An assessment names a commit. Without a ref the answer is "whatever main was that day",
    which makes two assessments of the same repository incomparable."""
    repository = _repository(app_client)

    body = _start(app_client, repository_id=repository["id"], ref="release/2.1").get_json()

    assert body["assessment"]["ref"] == "release/2.1"


# ── Reading a run ────────────────────────────────────────────────────────────────────────────


def test_listing_runs(app_client, reachable_llm):
    repository = _repository(app_client)
    _start(app_client, repository_id=repository["id"])

    body = app_client.get("/api/assessments/").get_json()

    assert isinstance(body["assessments"], list)
    assert "in_flight" in body, "the UI needs to know which of these are actually running"


def test_listing_can_be_filtered_to_one_repository(app_client, reachable_llm):
    first = _repository(app_client)
    second = _repository(app_client)
    _start(app_client, repository_id=first["id"])
    _start(app_client, repository_id=second["id"])

    body = app_client.get(f"/api/assessments/?repository_id={first['id']}").get_json()

    assert body["assessments"], "the filter returned nothing"
    assert {a["repository_id"] for a in body["assessments"]} == {first["id"]}


def test_reading_a_run_returns_the_shape_the_ui_renders(app_client, reachable_llm):
    repository = _repository(app_client)
    created = _start(app_client, repository_id=repository["id"]).get_json()["assessment"]

    body = app_client.get(f"/api/assessments/{created['id']}").get_json()

    for key in ("assessment", "progress", "pass_states", "findings", "severity_counts"):
        assert key in body, f"the detail response is missing {key!r}"


def test_reading_a_run_does_not_include_raw_model_responses(app_client, reachable_llm):
    """They belong in the provenance endpoint, which is a separate permission.

    A raw response is the largest field in the system and the one most likely to contain something
    a reader did not expect; the detail endpoint is polled every few seconds by every open tab.
    """
    repository = _repository(app_client)
    created = _start(app_client, repository_id=repository["id"]).get_json()["assessment"]

    assert "llm_calls" not in app_client.get(f"/api/assessments/{created['id']}").get_json()


def test_an_unknown_run_is_a_404(app_client):
    assert app_client.get(f"/api/assessments/{uuid.uuid4()}").status_code == 404


def test_provenance_is_available_for_a_run(app_client, reachable_llm):
    """What makes an assessment reproducible, and two assessments comparable."""
    repository = _repository(app_client)
    created = _start(app_client, repository_id=repository["id"]).get_json()["assessment"]

    body = app_client.get(f"/api/assessments/{created['id']}/provenance").get_json()

    assert "llm_calls" in body
    assert "token_usage" in body


def test_provenance_for_an_unknown_run_is_a_404(app_client):
    assert app_client.get(f"/api/assessments/{uuid.uuid4()}/provenance").status_code == 404


# ── Retry and cancel ─────────────────────────────────────────────────────────────────────────


def test_retrying_a_run_that_did_not_fail_is_refused(app_client, reachable_llm):
    """Retry resumes from the last completed pass. Applied to a healthy run it would start a
    second pipeline writing the same rows."""
    repository = _repository(app_client)
    created = _start(app_client, repository_id=repository["id"]).get_json()["assessment"]

    response = app_client.post(f"/api/assessments/{created['id']}/retry")

    assert response.status_code == 409
    assert response.get_json()["reason"] == "not-failed"


def test_retrying_an_unknown_run_is_a_404(app_client):
    assert app_client.post(f"/api/assessments/{uuid.uuid4()}/retry").status_code == 404


def test_a_run_that_failed_unretryably_cannot_be_retried(app_client, reachable_llm):
    """The distinction the UI shows as an enabled or disabled button. A repository that does not
    exist will not start existing because someone pressed retry; a timeout might."""
    from store import repo

    repository = _repository(app_client)
    created = _start(app_client, repository_id=repository["id"]).get_json()["assessment"]
    repo.fail_assessment(created["id"], reason="clone-failed", detail="404", retryable=False)

    response = app_client.post(f"/api/assessments/{created['id']}/retry")

    assert response.status_code == 409
    assert response.get_json()["reason"] == "not-retryable"


def test_a_retryable_failure_can_be_retried(app_client, reachable_llm):
    from store import repo

    repository = _repository(app_client)
    created = _start(app_client, repository_id=repository["id"]).get_json()["assessment"]
    repo.fail_assessment(
        created["id"], reason="llm-unreachable", detail="timeout", retryable=True
    )

    response = app_client.post(f"/api/assessments/{created['id']}/retry")

    assert response.status_code == 202
    assert "resuming_from" in response.get_json(), (
        "a retry that silently restarts from the beginning throws away completed passes"
    )


def test_cancelling_a_queued_run_succeeds(app_client, reachable_llm):
    repository = _repository(app_client)
    created = _start(app_client, repository_id=repository["id"]).get_json()["assessment"]

    assert app_client.post(f"/api/assessments/{created['id']}/cancel").status_code == 200


def test_cancelling_a_finished_run_is_refused(app_client, reachable_llm):
    from store import repo
    from store.models import Status

    repository = _repository(app_client)
    created = _start(app_client, repository_id=repository["id"]).get_json()["assessment"]
    repo.set_status(created["id"], Status.COMPLETE)

    response = app_client.post(f"/api/assessments/{created['id']}/cancel")

    assert response.status_code == 409
    assert response.get_json()["reason"] == "already-terminal"


def test_cancelling_an_unknown_run_is_a_404(app_client):
    assert app_client.post(f"/api/assessments/{uuid.uuid4()}/cancel").status_code == 404


# ── Artifacts ────────────────────────────────────────────────────────────────────────────────


def test_listing_artifacts_of_a_run_with_none_yet(app_client, reachable_llm):
    repository = _repository(app_client)
    created = _start(app_client, repository_id=repository["id"]).get_json()["assessment"]

    body = app_client.get(f"/api/assessments/{created['id']}/artifacts").get_json()

    assert body["artifacts"] == []


def test_requesting_an_artifact_that_does_not_exist_is_a_404(app_client, reachable_llm):
    repository = _repository(app_client)
    created = _start(app_client, repository_id=repository["id"]).get_json()["assessment"]

    assert app_client.get(
        f"/api/assessments/{created['id']}/artifacts/AGENT_PLAN.md"
    ).status_code == 404


def test_an_artifact_name_cannot_escape_the_run_directory(app_client, reachable_llm):
    """Path traversal, against an endpoint whose whole job is to return a file by name."""
    repository = _repository(app_client)
    created = _start(app_client, repository_id=repository["id"]).get_json()["assessment"]

    for name in ("../../../../etc/passwd", "..%2f..%2fetc%2fpasswd", "....//etc/passwd"):
        response = app_client.get(f"/api/assessments/{created['id']}/artifacts/{name}")
        assert response.status_code in {400, 404}, f"{name} returned {response.status_code}"
        assert b"root:" not in response.get_data(), f"{name} read a file outside the run directory"


# ── Authorization ────────────────────────────────────────────────────────────────────────────


def test_an_anonymous_caller_cannot_reach_any_of_this(anonymous_client):
    paths = [
        ("get", "/api/assessments/"),
        ("post", "/api/assessments/"),
        ("get", f"/api/assessments/{uuid.uuid4()}"),
        ("get", f"/api/assessments/{uuid.uuid4()}/provenance"),
        ("post", f"/api/assessments/{uuid.uuid4()}/retry"),
        ("post", f"/api/assessments/{uuid.uuid4()}/cancel"),
    ]
    for method, path in paths:
        status = getattr(anonymous_client, method)(path).status_code
        assert status in {401, 403}, f"{method.upper()} {path} answered {status} anonymously"
