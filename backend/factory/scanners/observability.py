# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Can you tell what happened without reproducing it?

Author: Rafael M. Koike & Cursor Agent ("Ada")

The pillar that pays for itself the first time something fails at a customer site, where "reproduce
it locally" is not available and the maintenance window closed an hour ago.

The signature failure this scanner looks for is ``print()`` as the only output mechanism. Print
writes to stdout with no level, no timestamp, and no way to turn it up or down. In a container it
lands in the daemon's log, unstructured, interleaved across threads.
"""

from __future__ import annotations

import re

from store.models import Severity

from .base import Fact, RepoView

PILLAR = "observability"

_PRINT_RE = re.compile(r"^\s*print\s*\(|(?<![\w.])console\.log\s*\(|\bfmt\.Print")
_LOGGING_RE = re.compile(
    r"(?i)\b(?:logging\.|logger\.|log\.|structlog|loguru|winston|pino|bunyan|zap\.|slog\.|"
    r"tracing::|log::)"
)
_LOGGING_CONFIG_RE = re.compile(
    r"(?i)logging\.(?:basicConfig|config\.|dictConfig|fileConfig)|getLogger\(|"
    r"structlog\.configure|createLogger|logging\.yaml|logging\.ini|addHandler"
)

_STRUCTURED_RE = re.compile(
    r"(?i)json.*[Ff]ormatter|JsonFormatter|structlog|python-json-logger|jsonlogger|"
    r"format.*%\(asctime\)|extra\s*=\s*\{|winston\.format\.json"
)

_CORRELATION_RE = re.compile(
    r"(?i)correlation[_-]?id|request[_-]?id|trace[_-]?id|X-Request-Id|X-Correlation-Id|"
    r"contextvars|traceparent|span"
)

_METRICS_RE = re.compile(
    r"(?i)prometheus_client|prom-client|Counter\(|Histogram\(|Gauge\(|statsd|"
    r"opentelemetry|otel|/metrics|micrometer|expvar"
)

_STDOUT_ONLY_RE = re.compile(r"(?i)StreamHandler\s*\(\s*\)|StreamHandler\s*\(\s*sys\.std")

_ERROR_MESSAGE_RE = re.compile(
    r"""(?ix)
    (?: raise \s+ \w*(?:Error|Exception) \s* \(
      | logger? \. (?:error|exception|critical) \s* \(
    )
    \s* (?: f?["'] )
    (?P<message> [^"']{0,120} )
    """
)


def scan(view: RepoView) -> list[Fact]:
    facts: list[Fact] = []
    code = view.code_files()
    # Exclude tests and scripts: a print in a CLI entry point is output, not logging.
    production = [
        f for f in code
        if not re.search(r"(?i)(^|/)(tests?|__tests__|spec|examples?|scripts?|bin)(/|$)", f)
    ]
    haystack = " ".join(view.read(f) or "" for f in code)

    # ── O1: print versus logging ─────────────────────────────────────────────────────────────
    prints = view.grep(_PRINT_RE, production, limit=100)
    log_calls = view.count_matches(_LOGGING_RE, production)
    configured = view.grep(_LOGGING_CONFIG_RE, code, limit=5)

    if prints and log_calls == 0:
        facts.append(Fact(
            pillar_id=PILLAR, key="print_only_output",
            title=f"{len(prints)} print statement(s) and no logging framework",
            detail=(
                "Print has no level, so nothing can be turned down in normal operation or up "
                "during an incident; no timestamp, so ordering across a fleet is guesswork; and "
                "no structure, so grep is the only query language available. Interleaved across "
                "threads it is worse than that."
            ),
            criterion="O1", severity=Severity.MAJOR,
            file_path=prints[0][0], line_start=prints[0][1],
            excerpt=view.excerpt(prints[0][0], prints[0][1]),
            remediation=(
                "Configure `logging` once at the entry point and replace print with a "
                "module-level `logger`. Mechanical change, and it makes every later "
                "observability improvement a configuration edit rather than a code edit."
            ),
            data={"sites": [f"{p}:{n}" for p, n, _ in prints[:15]], "count": len(prints)},
        ))
    elif prints and log_calls:
        facts.append(Fact(
            pillar_id=PILLAR, key="mixed_print_and_logging",
            title=f"Both logging ({log_calls} call(s)) and print ({len(prints)} statement(s))",
            detail=(
                "Mixed output means half the diagnostic trail is missing from the log sink, and "
                "which half depends on which module you are in."
            ),
            criterion="O1", severity=Severity.MINOR,
            file_path=prints[0][0], line_start=prints[0][1],
            data={"print_sites": [f"{p}:{n}" for p, n, _ in prints[:12]]},
        ))
    elif log_calls:
        facts.append(Fact(
            pillar_id=PILLAR, key="logging_present",
            title=f"Logging framework in use ({log_calls} call site(s))",
            detail=(
                f"Configuration found at {configured[0][0]}:{configured[0][1]}."
                if configured else
                "No `basicConfig` or handler setup found, so log records may be going to the "
                "last-resort handler at WARNING and anything below is silently dropped."
            ),
            criterion="O1",
            severity=None if configured else Severity.MINOR,
            remediation=(
                "Configure logging explicitly at the entry point. Without it, `logger.info` calls "
                "produce nothing and look like they are working."
            ) if not configured else None,
        ))

    # ── O2: structured output ────────────────────────────────────────────────────────────────
    if log_calls:
        structured = bool(_STRUCTURED_RE.search(haystack))
        facts.append(Fact(
            pillar_id=PILLAR, key="structured_logging",
            title="Structured log output" if structured else "Log output is unstructured text",
            detail=(
                "JSON lines can be queried by field in an aggregator. Free text can only be "
                "grepped, which stops working as soon as you want 'all failures for rack 14 in "
                "the last hour'."
            ),
            criterion="O2",
            data={"structured": structured},
        ))

        stdout_only = bool(_STDOUT_ONLY_RE.search(haystack))
        file_handler = bool(re.search(r"(?i)FileHandler|RotatingFileHandler|TimedRotating|"
                                      r"WatchedFileHandler", haystack))
        if stdout_only and not file_handler:
            facts.append(Fact(
                pillar_id=PILLAR, key="logs_to_stdout_only",
                title="Logs go to stdout only",
                detail=(
                    "Correct for a container, as long as something downstream retains them. If "
                    "the Docker default json-file driver is in use with no rotation policy, the "
                    "logs are on the host disk until it fills."
                ),
                criterion="O2",
                data={"stdout_only": True},
            ))

    # ── O3: correlation ──────────────────────────────────────────────────────────────────────
    is_service = bool(view.count_matches(
        r"(?i)Flask\(|FastAPI\(|app\.run\(|uvicorn|gunicorn|express\(|ListenAndServe", code,
    ))
    if is_service or log_calls > 20:
        correlation = view.grep(_CORRELATION_RE, code, limit=5)
        facts.append(Fact(
            pillar_id=PILLAR, key="correlation_id",
            title="Correlation identifier present" if correlation else
                  "No correlation identifier",
            detail=(
                f"Found at {correlation[0][0]}:{correlation[0][1]}." if correlation else
                "Log lines from concurrent operations interleave with nothing to tie them "
                "together, so reconstructing one request means guessing from timestamps."
            ),
            criterion="O3",
            severity=None if correlation else Severity.MINOR,
            file_path=correlation[0][0] if correlation else None,
            remediation=(
                "Generate an id per request or per run, put it in a contextvar, and add it to "
                "every log record via a filter. Return it in the response so a user can quote it."
            ) if not correlation else None,
        ))

    # ── O4: metrics ──────────────────────────────────────────────────────────────────────────
    if is_service:
        metrics = view.grep(_METRICS_RE, code, limit=5)
        facts.append(Fact(
            pillar_id=PILLAR, key="metrics",
            title="Metrics instrumentation present" if metrics else
                  "No metrics instrumentation",
            detail=(
                f"Found at {metrics[0][0]}:{metrics[0][1]}." if metrics else
                "Nothing exports counters or latencies, so degradation is invisible until it "
                "becomes an outage. For OVA tooling specifically, this is what would let the "
                "validation posture of a fleet show up on a dashboard instead of in a spreadsheet."
            ),
            criterion="O4",
            data={"instrumented": bool(metrics)},
        ))

    # ── O5: error messages that carry context ────────────────────────────────────────────────
    contextless: list[tuple[str, int, str]] = []
    for relative in production:
        for number, line in enumerate(view.lines(relative), start=1):
            match = _ERROR_MESSAGE_RE.search(line)
            if not match:
                continue
            message = match.group("message")
            # No interpolation of any kind: no f-string field, no %, no format, no concatenation.
            # The length bound keeps long prose messages out; those carry their own context.
            no_interpolation = not re.search(
                r"\{|%[sdr]|\}|\+\s*\w|,\s*\w+\s*\)", line[match.start():]
            )
            if no_interpolation and len(message) < 60:
                contextless.append((relative, number, message))

    if contextless:
        facts.append(Fact(
            pillar_id=PILLAR, key="contextless_errors",
            title=f"{len(contextless)} error message(s) with no interpolated context",
            detail=(
                "Messages like \"connection failed\" or \"invalid input\" identify the code path "
                "and nothing else — not which host, not which value, not which attempt. "
                + (f"For example: \"{contextless[0][2]}\" at "
                   f"{contextless[0][0]}:{contextless[0][1]}.")
            ),
            criterion="O5", severity=Severity.MINOR,
            file_path=contextless[0][0], line_start=contextless[0][1],
            excerpt=view.excerpt(contextless[0][0], contextless[0][1]),
            remediation=(
                "Include the identifiers needed to act: which target, which value, which attempt "
                "of how many. The test is whether someone could start fixing it from the log line "
                "alone."
            ),
            data={"examples": [f"{p}:{n} \"{m}\"" for p, n, m in contextless[:12]]},
        ))

    # ── O6: exception tracebacks preserved ───────────────────────────────────────────────────
    lost_traceback = view.grep(
        r"(?i)log(?:ger|ging)?\.error\s*\(\s*(?:f?['\"][^'\"]*['\"]\s*(?:%|\.format|\+)?\s*)?"
        r"(?:str\s*\(\s*e\w*\s*\)|e\w*)\s*\)",
        production, limit=20,
    )
    if lost_traceback:
        facts.append(Fact(
            pillar_id=PILLAR, key="traceback_discarded",
            title=f"{len(lost_traceback)} handler(s) log the exception message without the "
                  "traceback",
            detail=(
                "`logger.error(str(e))` records what went wrong and discards where. The "
                "traceback is the part that saves the hour."
            ),
            criterion="O6", severity=Severity.MINOR,
            file_path=lost_traceback[0][0], line_start=lost_traceback[0][1],
            excerpt=view.excerpt(lost_traceback[0][0], lost_traceback[0][1]),
            remediation="Use `logger.exception(...)`, or pass `exc_info=True`.",
            data={"sites": [f"{p}:{n}" for p, n, _ in lost_traceback[:10]]},
        ))

    return facts
