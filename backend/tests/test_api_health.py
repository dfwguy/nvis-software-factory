# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Health endpoints, and the line between "restart me" and "come and look".

Author: Rafael M. Koike & Cursor Agent ("Ada")

Two endpoints exist because two different callers ask two different questions. A container
runtime asks "is this process alive", and the only honest answers are yes and no -- if it reports
unhealthy for a reason a restart cannot fix, the runtime restarts forever and turns one problem
into an outage. An operator asks "is anything wrong", and wants every dependency named.

Conflating them is a common and expensive mistake, so the separation is asserted here rather than
left to a comment. The deployment already made it once: the Dockerfile's healthcheck pointed at
the deep endpoint, which requires a session, so a healthy container reported itself dying.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def unreachable_llm(monkeypatch):
    monkeypatch.setattr(
        "factory.llm.probe",
        lambda: {"reachable": False, "endpoint": "http://127.0.0.1:1/v1", "model": "test-model",
                 "api_key_configured": False, "detail": "connection refused", "latency_ms": 1},
    )


@pytest.fixture
def reachable_llm(monkeypatch):
    monkeypatch.setattr(
        "factory.llm.probe",
        lambda: {"reachable": True, "endpoint": "http://test/v1", "model": "test-model",
                 "api_key_configured": True, "detail": "ok", "latency_ms": 12},
    )


# ── Liveness ─────────────────────────────────────────────────────────────────────────────────


def test_liveness_answers_without_a_session(anonymous_client):
    """The property the container healthcheck depends on.

    Everything else is behind authorization. If liveness were too, `curl -f` in the healthcheck
    would get a 403 forever and Docker would restart a working container every thirty seconds.
    """
    response = anonymous_client.get("/api/health/live")

    assert response.status_code == 200
    assert response.get_json()["status"] == "live"


def test_liveness_does_not_touch_the_database(anonymous_client, monkeypatch):
    """A liveness probe that consults dependencies is a readiness probe wearing the wrong name.

    If the store is broken, restarting the container does not fix it -- so reporting dead makes
    the runtime destroy the one process that could still serve the health page explaining why.
    """
    def explode(*args, **kwargs):
        raise AssertionError("liveness touched the store")

    monkeypatch.setattr("store.db.integrity_check", explode)
    monkeypatch.setattr("store.db.stats", explode)

    assert anonymous_client.get("/api/health/live").status_code == 200


def test_liveness_stays_up_when_the_reasoning_endpoint_is_down(
    anonymous_client, unreachable_llm
):
    """The LLM being unreachable stops assessments and must not stop the process."""
    assert anonymous_client.get("/api/health/live").status_code == 200


# ── Deep health ──────────────────────────────────────────────────────────────────────────────


def test_deep_health_needs_a_session(anonymous_client):
    """It names internal paths, schema versions and the identity provider."""
    assert anonymous_client.get("/api/health").status_code in {401, 403}


def test_deep_health_reports_every_dependency(app_client, reachable_llm):
    body = app_client.get("/api/health").get_json()

    assert body["status"] in {"healthy", "unhealthy"}
    for dependency in ("store", "migrations", "backups", "llm", "identity"):
        assert dependency in body["checks"], f"{dependency} is not reported"


def test_a_configured_but_unprobed_llm_is_not_reported_as_passing(app_client, monkeypatch):
    """Configured is not working, and this endpoint must not blur the two.

    /api/health does not spend a round trip on the reasoning endpoint, so all it can honestly say
    is that settings are present. It used to say `ok: true` for that, which put a green tick in
    the platform dashboard against an endpoint that was answering 401 to every call -- a
    deployment that could not complete a single assessment, reporting itself healthy.
    """
    monkeypatch.setenv("NVSF_LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("NVSF_LLM_MODEL", "some-model")

    check = app_client.get("/api/health").get_json()["checks"]["llm"]

    assert check["ok"] is None, "unverified must be null, never true"
    assert check["configured"] is True
    assert check["verified"] is False


def test_an_unprobed_llm_is_not_reported_as_failing_either(app_client, monkeypatch):
    """Unknown is not the same as broken. Dropping an instance out of a load balancer over
    something never measured would be the same error in the other direction."""
    monkeypatch.setenv("NVSF_LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("NVSF_LLM_MODEL", "some-model")

    body = app_client.get("/api/health").get_json()

    assert "llm" not in body["failing"]


def test_an_unconfigured_llm_is_a_hard_failure(app_client, monkeypatch):
    """No endpoint means no assessment can ever run, and there is no degraded mode by design."""
    monkeypatch.delenv("NVSF_LLM_BASE_URL", raising=False)
    monkeypatch.setenv("NVSF_LLM_BASE_URL", "")

    response = app_client.get("/api/health")

    assert response.status_code == 503
    body = response.get_json()
    assert body["checks"]["llm"]["ok"] is False
    assert "llm" in body["failing"]


def test_deep_health_is_503_when_something_required_is_broken(app_client, monkeypatch):
    """A monitor that only reads the status code still learns the truth. Returning 200 with a
    body saying "unhealthy" is how an outage goes unnoticed for a day."""
    monkeypatch.setattr(
        "store.db.integrity_check", lambda: (_ for _ in ()).throw(RuntimeError("corrupt"))
    )

    response = app_client.get("/api/health")

    assert response.status_code == 503
    body = response.get_json()
    assert body["status"] == "unhealthy"
    assert "store" in body["failing"]


def test_pending_migrations_make_the_deployment_unhealthy(app_client, monkeypatch):
    """The schema is behind the code. Requests will fail on missing columns, one endpoint at a
    time, which is far harder to diagnose than a single failing health check."""
    monkeypatch.setattr("store.migrations.pending", lambda conn=None: ["0002_something"])

    response = app_client.get("/api/health")

    assert response.status_code == 503
    assert "migrations" in response.get_json()["failing"]


def test_stale_backups_are_reported_without_failing_the_deployment(app_client, monkeypatch):
    """A warning, not a failure. Snapshots being stale is serious and does not mean the service
    should be taken out of a load balancer -- and a health check that cries wolf gets muted."""
    monkeypatch.setattr(
        "store.backup.health",
        lambda: {"ok": False, "configured": True, "interval_hours": 24, "retain_days": 14,
                 "count": 0, "newest": None, "newest_age_hours": None, "stale": True,
                 "same_volume_as_live_data": True},
    )

    response = app_client.get("/api/health")

    assert "backups" not in response.get_json().get("failing", [])


def test_the_mock_identity_provider_is_surfaced_in_health(app_client):
    """An operator looking at a deployment that authenticates everyone as the same user should be
    able to see that from the health page rather than deducing it."""
    identity = app_client.get("/api/health").get_json()["checks"]["identity"]

    assert identity["mode"] == "mock"
    assert identity.get("warning"), "the mock provider should carry a warning"


# ── The reasoning endpoint probe ─────────────────────────────────────────────────────────────


def test_the_llm_probe_reports_reachable(app_client, reachable_llm):
    response = app_client.get("/api/health/llm")

    assert response.status_code == 200
    assert response.get_json()["reachable"] is True


def test_the_llm_probe_is_503_when_unreachable(app_client, unreachable_llm):
    """Assessments cannot run. Saying so in the status code means a monitor catches it without
    anyone having taught it to read this particular body."""
    response = app_client.get("/api/health/llm")

    assert response.status_code == 503
    assert response.get_json()["detail"], "an unreachable probe must say why"


def test_the_llm_probe_does_not_leak_the_api_key(app_client, monkeypatch):
    """It reports the endpoint and whether authentication was accepted, which is the useful part
    without being the dangerous part."""
    monkeypatch.setenv("NVSF_LLM_API_KEY", "nvapi-secret-value-here")

    assert "nvapi-secret-value-here" not in app_client.get(
        "/api/health/llm"
    ).get_data(as_text=True)


# ── The standards baseline ───────────────────────────────────────────────────────────────────


def test_the_standards_endpoint_reports_the_loaded_baseline(app_client):
    """The version is what an assessment records, so an old report stays interpretable after the
    criteria change."""
    body = app_client.get("/api/health/standards").get_json()

    assert body["version"]
    assert len(body["pillars"]) == 8, "the baseline is eight pillars"
    for pillar in body["pillars"]:
        assert pillar["id"] and pillar["severity_ceiling"]
        assert pillar["criteria"] > 0, f"{pillar['id']} has no criteria"
