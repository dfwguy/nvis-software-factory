---
id: reliability
title: Reliability
severity_ceiling: major
order: 3
detectors:
  - backend/factory/scanners/reliability.py
---

# Reliability

**The question:** what happens when something this depends on misbehaves?

Not "when it fails" — failure is the easy case, because it is obvious. The hard cases are the slow
response, the partial answer, and the call that succeeds but did the wrong thing.

## Criteria

### R1 — Every network call has a timeout

*Detector: yes.*

- **Pass:** an explicit timeout on every HTTP request, SSH connection, and socket operation.
- **Fail:** a default-timeout call. Python's `requests` has **no** timeout by default, so
  `requests.get(url)` can hang until the TCP stack gives up, which can be minutes.

A hung request in a thread pool is worse than an error: it consumes a worker indefinitely and the
symptom appears somewhere unrelated.

### R2 — Failures are distinguished from negative results

*Detector: partial.*

This is the pillar's most important criterion for validation tooling specifically.

- **Pass:** "the check failed", "the check could not run", and "the check passed" are three
  distinct outcomes, and the third is never inferred from the absence of the first.
- **Fail:** an exception handler that returns an empty list, so an unreachable node and a healthy
  node are indistinguishable downstream.

A tool that reports green because it could not reach anything is worse than a tool that crashes.

### R3 — Retries are bounded and backed off

*Detector: yes.*

- **Pass:** a retry limit, exponential backoff, and retries only on transient errors.
- **Fail:** an unbounded `while True` retry, a tight loop with no delay, or retrying a `400`.

Retrying a non-idempotent operation needs an idempotency key or it is not a retry, it is a repeat.

### R4 — Destructive operations are idempotent or guarded

*Detector: no — judgement.*

- **Pass:** running it twice is safe, or the second run is refused with a clear reason.
- **Fail:** a power-cycle or reset endpoint that a double-click fires twice.

### R5 — There is a health endpoint that means something

*Detector: yes.*

- **Pass:** a health check that verifies the dependencies the service actually needs — the
  database, the required upstream — and reports which one is down.
- **Fail:** no health endpoint, or one that returns `200 OK` unconditionally. A health check that
  only proves the process is running is answering a question nobody asked.

### R6 — The service restarts cleanly

*Detector: yes.*

- **Pass:** a restart policy, and startup that either succeeds or exits non-zero. Required
  configuration is validated at startup, not at first use.
- **Fail:** a service that starts happily with missing configuration and fails hours later on the
  first request that needs it.

Failing at startup is a deployment error someone sees immediately. Failing at first use is an
incident.

### R7 — Errors reaching the user are actionable

*Detector: no — judgement.*

- **Pass:** the message says what failed, against what, and what to try.
- **Fail:** a bare stack trace, or `{"error": "error"}`.

## Remediation patterns

**No timeouts.** Wrap the client once with a configured default rather than editing every call
site: a `Session` with an adapter, or a small module-level helper. This also gives you one place to
add retry policy later.

**Exception swallowed into an empty result.** Introduce a result type that can express "unknown"
alongside "empty". Usually this is a two-line dataclass, and it makes the distinction impossible to
lose accidentally downstream.

**Unconditional health endpoint.** Have it check the store with a real query and the required
upstream with a cheap call, and return per-dependency status. Return `503` when a required
dependency is down, so an orchestrator can act on it.
