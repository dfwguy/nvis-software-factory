# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The AI-first contract: required, fail-closed, fully recorded, never authoritative on facts.

Author: Rafael M. Koike & Cursor Agent ("Ada")

The most important test here is ``test_there_is_no_fallback_path``. It asserts a *negative* -- that
no code in the reasoning core produces an answer when the endpoint is unavailable. Negatives are
awkward to test and this one is worth it, because a fallback is exactly the kind of helpful thing
someone adds under deadline pressure, and it would silently defeat the whole design.
"""

from __future__ import annotations

import json

import pytest
import requests


class _Response:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _chat_response(content: str, prompt_tokens: int = 100, completion_tokens: int = 20):
    return _Response(200, {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    })


@pytest.fixture
def llm_configured(monkeypatch, migrated):
    monkeypatch.setenv("NVSF_LLM_BASE_URL", "http://nim.invalid/v1")
    monkeypatch.setenv("NVSF_LLM_MODEL", "test-model")
    monkeypatch.setenv("NVSF_LLM_MAX_RETRIES", "2")
    return migrated


# ── Fail closed ──────────────────────────────────────────────────────────────────────────────

def test_startup_refuses_without_an_endpoint(monkeypatch, tmp_path):
    """The app does not start without a configured endpoint. There is no degraded mode."""
    import startup_gate

    monkeypatch.setenv("NVSF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NVSF_ENV", "development")
    monkeypatch.setenv("NVSF_PUBLIC_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("NVSF_OIDC_MOCK", "true")
    monkeypatch.delenv("NVSF_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NVSF_LLM_MODEL", raising=False)

    with pytest.raises(startup_gate.StartupRefused) as excinfo:
        startup_gate.prepare()
    message = str(excinfo.value)
    assert "NVSF_LLM_BASE_URL" in message
    assert "no degraded mode" in message


def test_startup_reports_every_problem_at_once(monkeypatch, tmp_path):
    """One problem per restart turns a five-minute task into an afternoon."""
    import startup_gate

    monkeypatch.setenv("NVSF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NVSF_ENV", "development")
    monkeypatch.setenv("NVSF_OIDC_MOCK", "true")
    for name in ("NVSF_LLM_BASE_URL", "NVSF_LLM_MODEL", "NVSF_PUBLIC_URL"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(startup_gate.StartupRefused) as excinfo:
        startup_gate.prepare()
    message = str(excinfo.value)
    assert "3." in message, "problems should be enumerated, not reported one at a time"


def test_startup_accepts_a_configured_but_unreachable_endpoint(monkeypatch, tmp_path):
    """Configuration, not reachability. Otherwise a transient upstream outage is a crash loop."""
    import startup_gate

    monkeypatch.setenv("NVSF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NVSF_ENV", "development")
    monkeypatch.setenv("NVSF_PUBLIC_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("NVSF_OIDC_MOCK", "true")
    monkeypatch.setenv("NVSF_LLM_BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("NVSF_LLM_MODEL", "test-model")

    startup_gate.prepare()  # must not raise


def test_mock_identity_is_refused_in_production(monkeypatch, tmp_path):
    import startup_gate

    monkeypatch.setenv("NVSF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NVSF_ENV", "production")
    monkeypatch.setenv("NVSF_PUBLIC_URL", "https://factory.nvidia.com")
    monkeypatch.setenv("NVSF_OIDC_MOCK", "true")
    monkeypatch.setenv("NVSF_LLM_BASE_URL", "https://nim.internal/v1")
    monkeypatch.setenv("NVSF_LLM_MODEL", "m")

    with pytest.raises(startup_gate.StartupRefused, match="NVSF_OIDC_MOCK"):
        startup_gate.prepare()


def test_mock_identity_is_refused_off_loopback(monkeypatch, tmp_path):
    """The second, independent lock: a loopback bind can be fronted by a proxy, and NVSF_ENV can
    be copied from a dev .env, so neither check alone is enough."""
    from authn import mock

    monkeypatch.setenv("NVSF_ENV", "development")
    monkeypatch.setenv("NVSF_OIDC_MOCK", "true")
    monkeypatch.setenv("NVSF_BIND_ADDR", "0.0.0.0")
    assert mock.enabled() is False

    monkeypatch.setenv("NVSF_BIND_ADDR", "127.0.0.1")
    assert mock.enabled() is True


def test_plaintext_endpoint_is_refused_in_production(monkeypatch, tmp_path):
    """The API key would cross the network in the clear on every call."""
    import startup_gate

    monkeypatch.setenv("NVSF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NVSF_ENV", "production")
    monkeypatch.setenv("NVSF_PUBLIC_URL", "https://factory.nvidia.com")
    monkeypatch.setenv("NVSF_OIDC_MOCK", "false")
    monkeypatch.setenv("NVSF_OIDC_ISSUER", "https://idp.nvidia.com")
    monkeypatch.setenv("NVSF_OIDC_CLIENT_ID", "abc")
    monkeypatch.setenv("NVSF_TLS_CERT", str(tmp_path / "c.pem"))
    monkeypatch.setenv("NVSF_TLS_KEY", str(tmp_path / "k.pem"))
    (tmp_path / "c.pem").write_text("x")
    (tmp_path / "k.pem").write_text("x")
    monkeypatch.setenv("NVSF_LLM_BASE_URL", "http://nim.internal/v1")
    monkeypatch.setenv("NVSF_LLM_MODEL", "m")

    with pytest.raises(startup_gate.StartupRefused, match="plaintext http"):
        startup_gate.prepare()


def test_there_is_no_fallback_path(llm_configured, monkeypatch):
    """A negative assertion, deliberately, and stated behaviourally.

    No entry point in the reasoning core may return a value when the endpoint is unreachable. A
    helpful fallback added under deadline pressure would silently defeat the whole design: the
    reader of a report could no longer tell whether a model saw the evidence.

    Asserted by behaviour rather than by scanning the source for words like "fallback" -- a text
    scan trips over the comments that document the absence of one, which is how you end up with a
    test that fails for being right.
    """
    from factory import llm

    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("refused")),
    )
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)

    for label, call in (
        ("complete", lambda: llm.complete("s", "u", prompt_version="t@1")),
        ("complete_json", lambda: llm.complete_json("s", "u", prompt_version="t@1")),
    ):
        with pytest.raises(llm.LlmError) as excinfo:
            call()
        assert isinstance(excinfo.value, llm.LlmUnavailable), (
            f"{label} must raise LlmUnavailable, which marks the run retryable, rather than "
            "any other error"
        )

    # And the failure is retryable rather than terminal, so the run resumes when the endpoint
    # returns instead of being abandoned.
    assert issubclass(llm.LlmUnavailable, llm.LlmError)
    assert not issubclass(llm.LlmBadResponse, llm.LlmUnavailable), (
        "a malformed response is not the same condition as an unreachable endpoint; retrying "
        "the former just produces it again"
    )


# ── Retries, timeouts, provenance ────────────────────────────────────────────────────────────

def test_unreachable_endpoint_raises_rather_than_returning(llm_configured, monkeypatch):
    from factory import llm

    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("refused")),
    )
    with pytest.raises(llm.LlmUnavailable) as excinfo:
        llm.complete("s", "u", prompt_version="test@1")
    assert "retried" in str(excinfo.value)
    assert "partial assessment" in str(excinfo.value)


def test_retries_are_bounded(llm_configured, monkeypatch):
    """Reliability criterion R3, applied to ourselves: bounded, not a while-True."""
    from factory import llm

    calls = []

    def refuse(*_args, **_kwargs):
        calls.append(1)
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "post", refuse)
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)

    with pytest.raises(llm.LlmUnavailable):
        llm.complete("s", "u", prompt_version="test@1")
    assert len(calls) == 2, "NVSF_LLM_MAX_RETRIES=2 should mean exactly two attempts"


def test_a_400_is_not_retried(llm_configured, monkeypatch):
    """Our request is wrong; retrying wastes the endpoint's time and delays the real error."""
    from factory import llm

    calls = []

    def bad_request(*_args, **_kwargs):
        calls.append(1)
        return _Response(400, {"error": {"message": "unknown model"}})

    monkeypatch.setattr(requests, "post", bad_request)
    with pytest.raises(llm.LlmBadResponse):
        llm.complete("s", "u", prompt_version="test@1")
    assert len(calls) == 1


def test_a_429_is_retried_then_succeeds(llm_configured, monkeypatch):
    from factory import llm

    responses = [_Response(429, text="slow down"), _chat_response("hello")]
    monkeypatch.setattr(requests, "post", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)

    result = llm.complete("s", "u", prompt_version="test@1")
    assert result.text == "hello"


def test_every_attempt_is_recorded_including_failures(llm_configured, monkeypatch):
    """A timeout is provenance as much as a success is: it is what explains a slow run."""
    from factory import llm
    from store import repo

    record = repo.upsert_repository("https://github.com/nvidia/x", added_by="t")
    assessment = repo.create_assessment(record.id, created_by="t")

    responses = [_Response(503, text="unavailable"), _chat_response("done")]
    monkeypatch.setattr(requests, "post", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)

    llm.complete(
        "s", "u", prompt_version="architecture@1", assessment_id=assessment.id,
        pass_name="architecture", evidence_digest="deadbeef",
    )

    calls = repo.list_llm_calls(assessment.id)
    assert [c.status for c in calls] == ["error", "ok"]
    assert all(c.prompt_version == "architecture@1" for c in calls)
    assert all(c.evidence_hash == "deadbeef" for c in calls)
    assert calls[1].raw_response is not None, "the raw body must be kept for reproducibility"


def test_timeout_is_recorded_as_a_timeout_not_a_generic_error(llm_configured, monkeypatch):
    from factory import llm
    from store import repo

    record = repo.upsert_repository("https://github.com/nvidia/x", added_by="t")
    assessment = repo.create_assessment(record.id, created_by="t")

    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: (_ for _ in ()).throw(requests.Timeout("read timeout")),
    )
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)

    with pytest.raises(llm.LlmUnavailable):
        llm.complete("s", "u", prompt_version="t@1", assessment_id=assessment.id)

    assert {c.status for c in repo.list_llm_calls(assessment.id)} == {"timeout"}


def test_provenance_failure_does_not_break_the_call(llm_configured, monkeypatch):
    """Provenance must not break the thing it describes."""
    from factory import llm
    from store import repo

    monkeypatch.setattr(requests, "post", lambda *a, **k: _chat_response("fine"))
    monkeypatch.setattr(
        repo, "record_llm_call",
        lambda _c: (_ for _ in ()).throw(RuntimeError("disk full")),
    )
    assert llm.complete(
        "s", "u", prompt_version="t@1", assessment_id="whatever"
    ).text == "fine"


def test_output_limit_produces_an_actionable_message(llm_configured, monkeypatch):
    from factory import llm

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Response(200, {
        "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
    }))
    with pytest.raises(llm.LlmBadResponse, match="NVSF_LLM_MAX_OUTPUT_TOKENS"):
        llm.complete("s", "u", prompt_version="t@1")


# ── Structured output ────────────────────────────────────────────────────────────────────────

def test_json_is_validated_at_the_boundary(llm_configured, monkeypatch):
    """A missing key fails here, naming the pass, rather than as a KeyError in the renderer."""
    from factory import llm

    monkeypatch.setattr(requests, "post", lambda *a, **k: _chat_response('{"purpose": "a tool"}'))
    with pytest.raises(llm.LlmBadResponse, match="missing required key"):
        llm.complete_json("s", "u", prompt_version="architecture@1",
                          require_keys=("purpose", "archetype"))


def test_code_fences_are_tolerated(llm_configured, monkeypatch):
    """Models wrap JSON in ```json constantly. Failing on it would be pedantry, not rigour."""
    from factory import llm

    fenced = '```json\n{"purpose": "a tool", "archetype": "cli-tool"}\n```'
    monkeypatch.setattr(requests, "post", lambda *a, **k: _chat_response(fenced))
    data, _ = llm.complete_json("s", "u", prompt_version="t@1", require_keys=("purpose",))
    assert data["archetype"] == "cli-tool"


def test_unparseable_json_gets_exactly_one_correction_attempt(llm_configured, monkeypatch):
    from factory import llm

    responses = [
        _chat_response('{"purpose": "a tool",}'),          # trailing comma
        _chat_response('{"purpose": "a tool", "archetype": "cli-tool"}'),
    ]
    monkeypatch.setattr(requests, "post", lambda *a, **k: responses.pop(0))

    data, completion = llm.complete_json(
        "s", "u", prompt_version="architecture@1", require_keys=("purpose", "archetype"),
    )
    assert data["purpose"] == "a tool"
    # Usage from both calls, so a correction is not free in the accounting.
    assert completion.usage.prompt_tokens == 200


def test_two_corrections_is_a_failure_not_a_loop(llm_configured, monkeypatch):
    from factory import llm

    monkeypatch.setattr(requests, "post", lambda *a, **k: _chat_response("not json at all"))
    with pytest.raises(llm.LlmBadResponse, match="after a correction attempt"):
        llm.complete_json("s", "u", prompt_version="t@1")


def test_a_json_array_is_rejected(llm_configured, monkeypatch):
    """The callers index by key. An array would surface as a confusing TypeError later."""
    from factory import llm

    monkeypatch.setattr(requests, "post", lambda *a, **k: _chat_response('[1, 2, 3]'))
    with pytest.raises(llm.LlmBadResponse):
        llm.complete_json("s", "u", prompt_version="t@1")


# ── Hashing and probing ──────────────────────────────────────────────────────────────────────

def test_evidence_hash_is_order_independent():
    """Two structurally identical documents must hash the same, or 'same evidence, different
    conclusion' becomes untestable."""
    from factory.llm import evidence_hash

    assert evidence_hash({"a": 1, "b": [1, 2]}) == evidence_hash({"b": [1, 2], "a": 1})
    assert evidence_hash({"a": 1}) != evidence_hash({"a": 2})


def test_endpoint_accepts_either_base_url_spelling(llm_configured, monkeypatch):
    """An operator should not have to guess whether to include /v1."""
    from factory import llm

    seen = []
    monkeypatch.setattr(
        requests, "post",
        lambda url, **k: (seen.append(url), _chat_response("ok"))[1],
    )
    for base in ("http://nim.invalid", "http://nim.invalid/v1",
                 "http://nim.invalid/v1/chat/completions"):
        monkeypatch.setenv("NVSF_LLM_BASE_URL", base)
        llm.complete("s", "u", prompt_version="t@1")
    assert seen == ["http://nim.invalid/v1/chat/completions"] * 3


def test_probe_reports_instead_of_raising(llm_configured, monkeypatch):
    """A health check that raises returns 500 and tells the operator nothing."""
    from factory import llm

    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("refused")),
    )
    report = llm.probe()
    assert report["reachable"] is False
    assert "ConnectionError" in report["detail"]


def test_probe_explains_a_404_in_terms_of_the_two_likely_causes(llm_configured, monkeypatch):
    from factory import llm

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Response(404, text="not found"))
    report = llm.probe()
    assert report["reachable"] is False
    assert "NVSF_LLM_MODEL" in report["detail"]


def test_probe_distinguishes_a_credential_problem(llm_configured, monkeypatch):
    from factory import llm

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Response(401, text="unauthorized"))
    assert "NVSF_LLM_API_KEY" in llm.probe()["detail"]


def test_probe_explains_a_retired_model(llm_configured, monkeypatch):
    """What a deployment that worked for a year says on the day it stops.

    The hosted catalog retires models on published end-of-life dates and answers 410 afterwards.
    This is not hypothetical: the whole Llama 3.3 family went end-of-life on 2026-08-26, and the
    generic "unexpected HTTP 410" it produced before sent the reader hunting for a network fault
    when the fix is one setting.
    """
    from factory import llm

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Response(410, {
        "type": "about:blank", "title": "Gone", "status": 410,
        "detail": "The model 'meta/llama-3.3-70b-instruct' has reached its end of life on "
                  "2026-08-26T09:00:00Z and is no longer available.",
    }))

    detail = llm.probe()["detail"]

    assert "retired" in detail
    assert "NVSF_LLM_MODEL" in detail, "the message must name the setting to change"
    assert "end of life" in detail, "the provider's own explanation should survive"


def test_probe_surfaces_the_error_body_of_an_unexpected_status(llm_configured, monkeypatch):
    """The body of a 4xx usually says exactly what is wrong. Reporting only the status code
    throws away the actionable half and leaves a number to search the internet for."""
    from factory import llm

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Response(422, {
        "error": {"message": "temperature must be between 0 and 2"},
    }))

    assert "temperature must be between 0 and 2" in llm.probe()["detail"]


def test_probe_survives_an_error_body_that_is_not_json(llm_configured, monkeypatch):
    """A proxy in the path returns HTML, and a health probe must not raise on it."""
    from factory import llm

    monkeypatch.setattr(
        requests, "post", lambda *a, **k: _Response(502, text="<html>Bad Gateway</html>")
    )

    report = llm.probe()

    assert report["reachable"] is False
    assert "502" in report["detail"]


def test_health_llm_returns_503_when_unreachable(app_client, monkeypatch):
    """503, not 500: nothing is broken, a dependency is unavailable, and an assessment cannot
    run. That distinction is what lets monitoring act correctly."""
    response = app_client.get("/api/health/llm")
    assert response.status_code == 503
    assert response.get_json()["ok"] is False
