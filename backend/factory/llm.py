# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The reasoning client. OpenAI-compatible, against an internal NIM endpoint.

Author: Rafael M. Koike & Cursor Agent ("Ada")

This is a required dependency, not an optional one, and the design follows from that in ways worth
being explicit about.

**No fallback.** There is no code path here that returns a templated answer when the endpoint is
unavailable. :class:`LlmUnavailable` propagates, the run fails, and the failure says a retry can
help. A thinner report that looks like a real report is worse than no report, because the reader
cannot tell the difference.

**Every call is recorded.** Model id, prompt version, temperature, evidence hash, token usage,
duration, and the raw response body -- for failures as much as successes. A timeout is provenance
too: it is what explains a nine-minute run.

**Structured output is validated, not trusted.** :func:`complete_json` parses and checks the shape
before returning. A model that returns prose where a list was asked for is a failure of that call,
surfaced as one, rather than something the caller discovers three layers later as a
``TypeError``.

WHY ``requests`` AND NOT THE ``openai`` SDK
-------------------------------------------
The wire protocol used here is one POST to ``/chat/completions``. The SDK brings a dependency with
its own retry, timeout and telemetry behaviour that would have to be understood and configured to
match the reliability criteria this project enforces on other people -- explicit timeouts, bounded
backoff, no unpinned surprises. Forty lines of ``requests`` is less code to reason about than the
configuration required to make a larger client behave the same way.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

import requests
import settings
from store.models import LlmCall, new_id, now_iso

_logger = logging.getLogger("nvsf.factory.llm")

#: Status codes worth retrying. 429 is rate limiting; 5xx is the endpoint's problem, not the
#: request's. A 400 is our prompt being wrong and retrying it just wastes the endpoint's time.
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class LlmError(RuntimeError):
    """A call failed. Base class, so a caller can catch the family."""


class LlmUnavailable(LlmError):
    """The endpoint could not be reached, or refused, after exhausting retries.

    Distinct from :class:`LlmBadResponse` because this one is *retryable*: the run is marked
    failed-retryable and can resume from its last completed pass once the endpoint returns.
    """


class LlmBadResponse(LlmError):
    """The endpoint answered, but not with something usable.

    Not retryable by itself -- retrying the same prompt against the same model usually produces
    the same shape. This surfaces as a run failure that needs a prompt or model change.
    """


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add(self, other: Usage) -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens


@dataclass
class Completion:
    """One model response, with everything needed to reproduce it."""

    text: str
    model: str
    prompt_version: str
    temperature: float
    usage: Usage
    duration_ms: int
    raw: dict[str, Any] = field(default_factory=dict)


def _endpoint() -> str:
    base = settings.get_str("NVSF_LLM_BASE_URL").rstrip("/")
    if not base:
        # Should be unreachable: the startup gate refuses to boot without this. Kept as a real
        # error rather than an assert, because a clear message beats an AttributeError if some
        # future code path reaches here before the gate.
        raise LlmUnavailable(
            "NVSF_LLM_BASE_URL is not configured. Reasoning is a required stage and there is no "
            "degraded mode; the application should not have started."
        )
    # Accept both "https://host/v1" and "https://host", so an operator does not have to guess.
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    key = settings.get("NVSF_LLM_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def evidence_hash(payload: Any) -> str:
    """Stable hash of whatever was sent as evidence.

    ``sort_keys`` so two structurally identical documents hash the same regardless of insertion
    order. Two assessments with the same hash saw the same facts, which makes any difference in
    their conclusions a question about the model rather than about the code.
    """
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _sleep_for(attempt: int) -> float:
    """Exponential backoff with jitter, bounded.

    Jitter matters even for one client: several passes retrying in lockstep against an endpoint
    that is recovering is how a recovering endpoint gets knocked back down.
    """
    return min(2.0 ** attempt, 30.0) * (0.5 + random.random() / 2)


def complete(
    system: str,
    user: str,
    *,
    prompt_version: str,
    assessment_id: str | None = None,
    pass_name: str = "unknown",
    evidence_digest: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format_json: bool = False,
) -> Completion:
    """One chat completion, with retries, provenance capture, and no fallback.

    ``assessment_id`` is optional so this can be called outside a run (the health probe, the
    contract mapping assistant). When it is given, every attempt is recorded against that run.
    """
    model = settings.get_str("NVSF_LLM_MODEL")
    temp = temperature if temperature is not None else settings.get_float(
        "NVSF_LLM_TEMPERATURE", 0.2
    )
    timeout = settings.get_int("NVSF_LLM_TIMEOUT_SEC", 180)
    attempts = max(1, settings.get_int("NVSF_LLM_MAX_RETRIES", 3))

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temp,
        "max_tokens": max_tokens or settings.get_int("NVSF_LLM_MAX_OUTPUT_TOKENS", 4096),
        "stream": False,
    }
    if response_format_json:
        # Honoured by NIM and by OpenAI-compatible servers generally. Harmless where it is not:
        # complete_json validates the result either way, so this is an optimization rather than
        # something the correctness depends on.
        payload["response_format"] = {"type": "json_object"}

    last_error = ""
    for attempt in range(attempts):
        started = time.monotonic()
        status = "error"
        raw_text = ""
        usage = Usage()
        body: dict[str, Any] = {}

        try:
            response = requests.post(
                _endpoint(), json=payload, headers=_headers(), timeout=timeout,
            )
            raw_text = response.text[:200_000]

            if response.status_code in _RETRYABLE_STATUS:
                last_error = f"HTTP {response.status_code}"
                status = "error"
                raise _Retry(last_error, response)
            if response.status_code >= 400:
                # Not retryable: our request is wrong. Do not echo the body -- an error response
                # from some gateways reflects the request headers back, including the bearer token.
                raise LlmBadResponse(
                    f"the reasoning endpoint rejected the request with HTTP "
                    f"{response.status_code}. This is usually a model name that does not exist at "
                    f"this endpoint, or a prompt exceeding the model's context window."
                )

            body = response.json()
            text, usage = _extract(body)
            status = "ok"

            duration_ms = int((time.monotonic() - started) * 1000)
            _record(assessment_id, pass_name, model, prompt_version, temp, evidence_digest,
                    usage, duration_ms, status, None, raw_text)
            _logger.info(
                "llm: %s pass=%s tokens=%d/%d in %dms",
                model, pass_name, usage.prompt_tokens, usage.completion_tokens, duration_ms,
            )
            return Completion(
                text=text, model=model, prompt_version=prompt_version, temperature=temp,
                usage=usage, duration_ms=duration_ms, raw=body,
            )

        except (_Retry, requests.Timeout, requests.ConnectionError) as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            is_timeout = isinstance(exc, requests.Timeout)
            last_error = "read timeout" if is_timeout else str(exc)
            _record(assessment_id, pass_name, model, prompt_version, temp, evidence_digest,
                    usage, duration_ms, "timeout" if is_timeout else "error", last_error,
                    raw_text)
            if attempt + 1 >= attempts:
                break
            delay = _sleep_for(attempt)
            _logger.warning(
                "llm: attempt %d/%d failed (%s); retrying in %.1fs",
                attempt + 1, attempts, last_error, delay,
            )
            time.sleep(delay)

        except LlmBadResponse as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            _record(assessment_id, pass_name, model, prompt_version, temp, evidence_digest,
                    usage, duration_ms, "error", str(exc), raw_text)
            raise

        except ValueError as exc:  # json decode
            duration_ms = int((time.monotonic() - started) * 1000)
            _record(assessment_id, pass_name, model, prompt_version, temp, evidence_digest,
                    usage, duration_ms, "error", f"non-JSON response: {exc}", raw_text)
            raise LlmBadResponse(
                f"the reasoning endpoint returned a body that is not JSON: {exc}"
            ) from exc

    raise LlmUnavailable(
        f"the reasoning endpoint at {settings.get_str('NVSF_LLM_BASE_URL')} was unreachable after "
        f"{attempts} attempt(s): {last_error}. The run has been marked failed and can be retried "
        "from its last completed pass once the endpoint is available -- it will not produce a "
        "partial assessment."
    )


class _Retry(Exception):
    """Internal: a retryable HTTP status. Never escapes this module."""

    def __init__(self, message: str, response: requests.Response) -> None:
        super().__init__(message)
        self.response = response


def _extract(body: dict[str, Any]) -> tuple[str, Usage]:
    """Pull the message text and token usage out of an OpenAI-shaped response."""
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LlmBadResponse("the response has no choices; nothing was generated")

    message = choices[0].get("message") or {}
    text = message.get("content")
    if not isinstance(text, str) or not text.strip():
        finish = choices[0].get("finish_reason")
        if finish == "length":
            raise LlmBadResponse(
                "the model hit its output limit before producing anything usable. Raise "
                "NVSF_LLM_MAX_OUTPUT_TOKENS or reduce the evidence budget."
            )
        raise LlmBadResponse(f"the response carried no content (finish_reason={finish!r})")

    reported = body.get("usage") or {}
    return text, Usage(
        prompt_tokens=int(reported.get("prompt_tokens") or 0),
        completion_tokens=int(reported.get("completion_tokens") or 0),
    )


def _record(
    assessment_id: str | None, pass_name: str, model: str, prompt_version: str,
    temperature: float, evidence_digest: str | None, usage: Usage, duration_ms: int,
    status: str, error: str | None, raw: str,
) -> None:
    """Persist one attempt. Never raises -- provenance must not break the thing it describes."""
    if not assessment_id:
        return
    try:
        from store import repo

        repo.record_llm_call(LlmCall(
            id=new_id(), assessment_id=assessment_id, pass_name=pass_name, model=model,
            prompt_version=prompt_version, temperature=temperature,
            evidence_hash=evidence_digest,
            prompt_tokens=usage.prompt_tokens or None,
            completion_tokens=usage.completion_tokens or None,
            duration_ms=duration_ms, status=status, error=error,
            raw_response=raw or None, created_at=now_iso(),
        ))
    except Exception as exc:  # noqa: BLE001 - see docstring
        _logger.error("llm: could not record provenance for %s: %s", assessment_id, exc)


def _strip_fences(text: str) -> str:
    """Remove a ```json fence if the model wrapped its object in one, which they often do."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 3:
        return stripped
    return "\n".join(lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:]).strip()


def complete_json(
    system: str,
    user: str,
    *,
    prompt_version: str,
    require_keys: tuple[str, ...] = (),
    **kwargs: Any,
) -> tuple[dict[str, Any], Completion]:
    """A completion parsed as a JSON object, with its shape checked.

    ``require_keys`` is checked here rather than by the caller so a malformed response fails at
    the boundary, naming the pass and the missing key, instead of surfacing as a ``KeyError`` in
    the renderer two steps later.

    One retry on unparseable JSON, with the parse error fed back to the model -- which in practice
    fixes it, because the failure is usually a stray trailing comma or a missing brace rather than
    a misunderstanding of the task.
    """
    completion = complete(
        system, user, prompt_version=prompt_version, response_format_json=True, **kwargs
    )

    def _parse(text: str) -> dict[str, Any]:
        parsed = json.loads(_strip_fences(text))
        if not isinstance(parsed, dict):
            # ValueError, not TypeError, so the caller's single `except ValueError` covers both
            # this and json.JSONDecodeError. A model returning a list is the same class of
            # problem as one returning prose, and both get the same correction retry.
            raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")  # noqa: TRY004
        return parsed

    try:
        data = _parse(completion.text)
    except ValueError as first_error:
        _logger.warning(
            "llm: %s returned unparseable JSON (%s); asking once for a correction",
            prompt_version, first_error,
        )
        retry = complete(
            system,
            f"{user}\n\n---\n\nYour previous reply could not be parsed as JSON: {first_error}\n"
            "Reply with the JSON object only. No prose, no code fence, no commentary.",
            prompt_version=f"{prompt_version}+jsonfix",
            response_format_json=True,
            **kwargs,
        )
        try:
            data = _parse(retry.text)
        except ValueError as second_error:
            raise LlmBadResponse(
                f"{prompt_version} did not return parseable JSON after a correction attempt: "
                f"{second_error}"
            ) from second_error
        completion.usage.add(retry.usage)
        completion = Completion(
            text=retry.text, model=retry.model, prompt_version=prompt_version,
            temperature=retry.temperature, usage=completion.usage,
            duration_ms=completion.duration_ms + retry.duration_ms, raw=retry.raw,
        )

    missing = [k for k in require_keys if k not in data]
    if missing:
        raise LlmBadResponse(
            f"{prompt_version} response is missing required key(s): {', '.join(missing)}. "
            f"Got: {', '.join(sorted(data)) or 'nothing'}"
        )
    return data, completion


def probe() -> dict[str, Any]:
    """Is the endpoint reachable, and does it know the configured model?

    Used by ``/api/health/llm``. Returns a report rather than raising, because a health check that
    raises is a health check that returns 500 and tells the operator nothing.

    Deliberately cheap: a one-token completion, not a full reasoning pass. It answers "could an
    assessment start", which is the question being asked.
    """
    base = settings.get_str("NVSF_LLM_BASE_URL")
    model = settings.get_str("NVSF_LLM_MODEL")
    report: dict[str, Any] = {
        "reachable": False,
        "endpoint": base,
        "model": model,
        "authenticated": bool(settings.get("NVSF_LLM_API_KEY")),
    }
    if not base or not model:
        report["detail"] = "not configured"
        return report

    started = time.monotonic()
    try:
        response = requests.post(
            _endpoint(),
            json={
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "temperature": 0,
                "stream": False,
            },
            headers=_headers(),
            timeout=(5, 20),  # much shorter than a reasoning call; this is a liveness question
        )
    except requests.RequestException as exc:
        report["detail"] = f"{type(exc).__name__}: {exc}"
        report["latency_ms"] = int((time.monotonic() - started) * 1000)
        return report

    report["latency_ms"] = int((time.monotonic() - started) * 1000)
    report["status_code"] = response.status_code

    if response.status_code == 200:
        report["reachable"] = True
        report["detail"] = "ok"
        return report
    if response.status_code in {401, 403}:
        report["detail"] = (
            "the endpoint rejected our credentials. Check NVSF_LLM_API_KEY."
        )
        return report
    if response.status_code == 404:
        report["detail"] = (
            f"the endpoint answered but does not know model {model!r}, or the base URL is not an "
            "OpenAI-compatible root. Check NVSF_LLM_BASE_URL and NVSF_LLM_MODEL."
        )
        return report
    report["detail"] = f"unexpected HTTP {response.status_code}"
    return report
