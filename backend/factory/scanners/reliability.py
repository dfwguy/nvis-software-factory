# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Failure handling: swallowed exceptions, missing timeouts, retries, idempotency.

Author: Rafael M. Koike & Cursor Agent ("Ada")

The pillar that matters most for the tooling this team writes, because our scripts talk to BMCs,
switches and UFM over networks that are themselves being commissioned. A request with no timeout
against a BMC that is mid-reboot hangs forever, and a validation run that hangs at rack 40 of 72
at 2am is a lost night.
"""

from __future__ import annotations

import re

from store.models import Severity

from .base import Fact, RepoView

PILLAR = "reliability"

#: Network calls that take a timeout and default to waiting forever without one.
_NETWORK_CALL_RE = re.compile(
    r"""(?ix)
    \b(?:
        requests\.(?:get|post|put|patch|delete|head|request)
      | httpx\.(?:get|post|put|patch|delete|head|request)
      | (?:session|client|s)\.(?:get|post|put|patch|delete|head|request)
      | urlopen
      | socket\.create_connection
      | paramiko\.SSHClient\(\)\.connect
      | \.connect
    )\s*\(
    """
)

_BARE_EXCEPT_RE = re.compile(r"^\s*except\s*(?:Exception|BaseException)?\s*(?:as\s+\w+\s*)?:")

_RETRY_HINTS = (
    "tenacity", "backoff", "urllib3.util.retry", "Retry(", "max_retries", "retry(",
    "@retry", "retrying", "p-retry", "exponential",
)

_CONCURRENCY_HINTS = (
    "threading.Thread", "ThreadPoolExecutor", "ProcessPoolExecutor", "multiprocessing",
    "asyncio.gather", "asyncio.create_task", "go func", "tokio::spawn",
)

_LOCK_HINTS = ("threading.Lock", "threading.RLock", "asyncio.Lock", "Semaphore", "flock",
               "FOR UPDATE", "BEGIN IMMEDIATE", "advisory_lock", "mutex")


def _swallowed_blocks(view: RepoView) -> list[tuple[str, int, str]]:
    """``except`` blocks whose body neither raises, logs, nor returns a failure.

    Looks at the block body rather than matching ``except: pass`` textually, because the shape
    that actually causes the 3am debugging session is the five-line handler that prints something
    friendly and carries on with a half-initialized object.
    """
    swallowed: list[tuple[str, int, str]] = []
    for relative in view.python_files():
        lines = view.lines(relative)
        for index, line in enumerate(lines):
            if not _BARE_EXCEPT_RE.match(line):
                continue
            indent = len(line) - len(line.lstrip())
            body: list[str] = []
            for following in lines[index + 1:]:
                if not following.strip():
                    continue
                if len(following) - len(following.lstrip()) <= indent:
                    break
                body.append(following.strip())
            if not body:
                continue
            joined = " ".join(body)
            handled = re.search(
                r"\braise\b|\blog(?:ger|ging)?\.(?:error|exception|critical|warning)|"
                r"\bsys\.exit\b|\bos\._exit\b|\babort\b|\breturn\s+(?:False|None|fail|-1)|"
                r"capture_exception|report_error|record_failure",
                joined,
            )
            if not handled:
                swallowed.append((relative, index + 1, body[0][:80]))
    return swallowed


def scan(view: RepoView) -> list[Fact]:
    facts: list[Fact] = []
    code = view.code_files()
    python = view.python_files()

    # ── R2: swallowed exceptions ─────────────────────────────────────────────────────────────
    swallowed = _swallowed_blocks(view)
    if swallowed:
        facts.append(Fact(
            pillar_id=PILLAR, key="swallowed_exceptions",
            title=f"{len(swallowed)} exception handler(s) that neither log nor re-raise",
            detail=(
                "Each of these turns a failure into a silent continuation. The caller gets a "
                "success-shaped result and no indication that anything went wrong, and the "
                "eventual symptom shows up somewhere unrelated with no trace back to here."
                + (f" First: {swallowed[0][2]}" if swallowed[0][2] else "")
            ),
            criterion="R2", severity=Severity.MAJOR,
            file_path=swallowed[0][0], line_start=swallowed[0][1],
            excerpt=view.excerpt(swallowed[0][0], swallowed[0][1], context=3),
            remediation=(
                "Catch the specific exception you can handle, log it with `logger.exception` so "
                "the traceback survives, and either recover meaningfully or re-raise. `except "
                "Exception: pass` is only defensible in a cleanup path, and then it needs a "
                "comment saying so."
            ),
            data={"sites": [f"{p}:{n}" for p, n, _ in swallowed[:15]], "count": len(swallowed)},
        ))

    # ── R1: timeouts on network calls ────────────────────────────────────────────────────────
    network_calls = view.grep(_NETWORK_CALL_RE, code, limit=120)
    missing_timeout: list[tuple[str, int]] = []
    for path, number, line in network_calls:
        if "timeout" in line.lower():
            continue
        # The call may span lines; look at the next two before concluding.
        following = view.lines(path)[number:number + 2]
        if any("timeout" in candidate.lower() for candidate in following):
            continue
        # A session with a default timeout mounted globally is a legitimate pattern.
        missing_timeout.append((path, number))

    session_default = view.count_matches(
        r"(?i)session\.(?:request|timeout)\s*=|HTTPAdapter\(|default_timeout|"
        r"Timeout\(|timeout\s*=\s*(?:DEFAULT|TIMEOUT|_TIMEOUT)",
        code,
    )

    if missing_timeout and not session_default:
        facts.append(Fact(
            pillar_id=PILLAR, key="network_call_without_timeout",
            title=f"{len(missing_timeout)} network call(s) with no timeout",
            detail=(
                "`requests` and friends wait indefinitely by default. Against a BMC that is "
                "mid-reboot or a switch behind a silently dropping firewall, the call never "
                "returns and never errors — the run just stops, with no log line explaining why."
            ),
            criterion="R1", severity=Severity.MAJOR,
            file_path=missing_timeout[0][0], line_start=missing_timeout[0][1],
            excerpt=view.excerpt(missing_timeout[0][0], missing_timeout[0][1]),
            remediation=(
                "Pass an explicit `timeout=(connect, read)` to every call, or mount a session "
                "with a default. Two separate values, because a connect timeout should be short "
                "and a read timeout on a slow BMC inventory query legitimately is not."
            ),
            data={
                "sites": [f"{p}:{n}" for p, n in missing_timeout[:15]],
                "count": len(missing_timeout),
                "total_network_calls": len(network_calls),
            },
        ))
    elif network_calls:
        facts.append(Fact(
            pillar_id=PILLAR, key="timeout_posture",
            title="Network calls carry timeouts",
            detail=f"{len(network_calls)} network call site(s); "
                   f"{len(missing_timeout)} without an inline timeout, "
                   f"{session_default} session-level default(s).",
            criterion="R1",
        ))

    # ── R3: retries ──────────────────────────────────────────────────────────────────────────
    haystack = " ".join(view.read(f) or "" for f in code + view.find_names(
        "requirements.txt", "pyproject.toml", "package.json",
    ))
    retry_signals = sorted({h for h in _RETRY_HINTS if h in haystack})
    naive_retry = view.grep(r"for\s+\w+\s+in\s+range\s*\([^)]*\)\s*:.*|while\s+True\s*:",
                            code, limit=40)
    sleep_calls = view.count_matches(r"time\.sleep\s*\(", code)

    if network_calls:
        facts.append(Fact(
            pillar_id=PILLAR, key="retry_posture",
            title=(
                "Retry with backoff is present" if retry_signals else
                "No retry mechanism found around network calls"
            ),
            detail=(
                f"Signals: {', '.join(retry_signals)}." if retry_signals else
                f"{len(network_calls)} network call site(s) and no retry library or backoff "
                f"pattern. {sleep_calls} `time.sleep` call(s) — a fixed sleep in a retry loop "
                "synchronises every caller onto the same schedule, so a recovering service gets "
                "hit by all of them at once."
            ),
            criterion="R3",
            severity=None if retry_signals else Severity.MINOR,
            remediation=(
                "Retry transient failures — connection errors, timeouts, 429, 502/503/504 — with "
                "exponential backoff and jitter. Do not retry 4xx: the request is wrong and will "
                "stay wrong."
            ) if not retry_signals else None,
            data={"signals": retry_signals, "sleep_calls": sleep_calls,
                  "loop_sites": len(naive_retry)},
        ))

    # ── R4: idempotency and partial-failure recovery ─────────────────────────────────────────
    idempotency = sorted({
        h for h in (
            "idempot", "ON CONFLICT", "INSERT OR REPLACE", "upsert", "exist_ok=True",
            "IF NOT EXISTS", "checkpoint", "resume", "--force", "already_", "get_or_create",
        )
        if h.lower() in haystack.lower()
    })
    facts.append(Fact(
        pillar_id=PILLAR, key="idempotency_signals",
        title="Idempotency or resume signals present" if idempotency else
              "No idempotency or resume signals found",
        detail=(
            f"Signals: {', '.join(idempotency)}." if idempotency else
            "Nothing indicates the operation can be re-run safely after a partial failure. For "
            "cluster tooling this is the difference between 'run it again' and 'work out by hand "
            "which of the 72 nodes got the change'."
        ),
        criterion="R4",
        data={"signals": idempotency},
    ))

    # ── R5: concurrency without coordination ─────────────────────────────────────────────────
    concurrency = sorted({h for h in _CONCURRENCY_HINTS if h in haystack})
    locks = sorted({h for h in _LOCK_HINTS if h in haystack})
    if concurrency:
        facts.append(Fact(
            pillar_id=PILLAR, key="concurrency_posture",
            title=(
                f"Concurrency is used ({', '.join(concurrency)})"
                + ("" if locks else " with no locking primitive found")
            ),
            detail=(
                f"Coordination: {', '.join(locks)}." if locks else
                "Concurrent execution with no lock, semaphore, or transactional guard found. "
                "Whether that is a race depends on whether the workers share mutable state, "
                "which needs reading the code."
            ),
            criterion="R5",
            severity=None,
            data={"concurrency": concurrency, "locks": locks},
        ))

    # ── R6: health endpoint ──────────────────────────────────────────────────────────────────
    is_service = bool(view.count_matches(
        r"(?i)Flask\(|FastAPI\(|app\.run\(|uvicorn|gunicorn|express\(|http\.Server|"
        r"ListenAndServe", code,
    ))
    if is_service:
        health = view.grep(r"(?i)['\"]/(?:health|healthz|livez|readyz|ping|status)", code, limit=5)
        facts.append(Fact(
            pillar_id=PILLAR, key="health_endpoint",
            title="Health endpoint present" if health else
                  "Long-running service with no health endpoint",
            detail=(
                f"Found at {health[0][0]}:{health[0][1]}." if health else
                "Nothing distinguishes 'the process is up' from 'the process is working'. A "
                "container that has lost its database connection still passes a process check."
            ),
            criterion="R6",
            severity=None if health else Severity.MINOR,
            file_path=health[0][0] if health else None,
            line_start=health[0][1] if health else None,
            remediation=(
                "Add an endpoint that checks each dependency it actually needs and returns 503 "
                "when a required one is down. Separate liveness from readiness: restarting a "
                "process because its database is unreachable does not help."
            ) if not health else None,
        ))

    # ── Python-specific footgun: mutable default arguments ───────────────────────────────────
    mutable_defaults = view.grep(r"def\s+\w+\s*\([^)]*=\s*(?:\[\]|\{\}|set\(\))", python, limit=20)
    if mutable_defaults:
        facts.append(Fact(
            pillar_id=PILLAR, key="mutable_default_argument",
            title=f"{len(mutable_defaults)} function(s) with a mutable default argument",
            detail=(
                "The default is evaluated once at definition, so the list or dict is shared by "
                "every call that omits the argument. Mutating it leaks state between unrelated "
                "callers."
            ),
            criterion="R2", severity=Severity.MINOR,
            file_path=mutable_defaults[0][0], line_start=mutable_defaults[0][1],
            excerpt=view.excerpt(mutable_defaults[0][0], mutable_defaults[0][1]),
            remediation="Default to `None` and create the container inside the function.",
            data={"sites": [f"{p}:{n}" for p, n, _ in mutable_defaults[:10]]},
        ))

    return facts
