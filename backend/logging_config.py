# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Logging, configured once, with redaction and correlation built in.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Three things this owns, corresponding to observability criteria O1, O2 and O3:

* one configuration point, applied before other modules emit anything;
* a correlation id stamped onto every record, from a context variable, so one operation's records
  can be pulled out of an interleaved log without threading an argument through every call;
* a redaction filter on every sink.

REDACTION IS A FILTER, NOT A CALL-SITE DISCIPLINE
--------------------------------------------------
Redacting at the point of logging works until somebody adds a log line, which is to say it does not
work. The filter runs on every record on its way to every handler, so a new call site is covered by
construction. It rewrites both the format arguments and the already-rendered message, because a
caller can produce either.

It cannot catch everything -- a credential with no recognisable shape, embedded mid-sentence in a
free-text message, will pass. It is a net, not a wall, and the wall is not logging the value.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from typing import Any

#: Correlation id for the operation currently being handled. Set by the request hook and by the
#: assessment worker; read by the log filter.
correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="-")

_REDACTED = "***REDACTED***"

#: Patterns for credential-shaped substrings. Ordered most specific first, because an earlier
#: match consumes the text and a general pattern would swallow the specific ones' context.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Authorization: Bearer <token> / Basic <blob>
    re.compile(r"(?i)\b(authorization\s*[:=]\s*)(bearer|basic|token)\s+\S+"),
    # key=value and "key": "value" for anything named like a credential
    re.compile(
        r"(?i)\b([a-z0-9_.-]*(?:password|passwd|secret|token|api[_-]?key|credential|private[_-]?key)"
        r"[a-z0-9_.-]*)\b(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|\S+)"
    ),
    # Credentials embedded in a URL: scheme://user:pass@host
    re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s:/@]+:)([^\s@]+)(@)"),
    # PEM blocks, which are multi-line and unmistakable
    re.compile(r"(?s)-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----"),
)


def redact(text: str) -> str:
    """Replace credential-shaped substrings, preserving the surrounding message."""
    if not text:
        return text
    result = text
    result = _PATTERNS[0].sub(lambda m: f"{m.group(1)}{m.group(2)} {_REDACTED}", result)
    result = _PATTERNS[1].sub(lambda m: f"{m.group(1)}{m.group(2)}{_REDACTED}", result)
    result = _PATTERNS[2].sub(lambda m: f"{m.group(1)}{_REDACTED}{m.group(3)}", result)
    result = _PATTERNS[3].sub(_REDACTED, result)
    return result


class RedactionFilter(logging.Filter):
    """Scrub credential-shaped text from the message and its arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._scrub(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._scrub(a) for a in record.args)
        return True

    @staticmethod
    def _scrub(value: Any) -> Any:
        return redact(value) if isinstance(value, str) else value


class CorrelationFilter(logging.Filter):
    """Stamp the current correlation id onto every record, so formatters can use it."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for a log shipper."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "correlation_id": getattr(record, "correlation_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_TEXT_FORMAT = "%(asctime)s %(levelname)-7s [%(correlation_id)s] %(name)s: %(message)s"

_configured = False


def configure(force: bool = False) -> None:
    """Install handlers, filters and level on the root logger.

    Idempotent: called twice, the second call is a no-op unless ``force``. Gunicorn imports the
    application module in a way that can run module-level code more than once, and duplicated
    handlers mean duplicated lines.

    Settings are read **directly from the environment** rather than through the settings module, on
    purpose: this runs before the registry is necessarily populated, and a logging configuration
    that depends on the thing it is meant to help debug is a bad trade.
    """
    global _configured
    if _configured and not force:
        return

    level_name = (os.environ.get("NVSF_LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    sinks = {s.strip().lower() for s in (os.environ.get("NVSF_LOG_SINKS") or "stdout").split(",")}
    as_json = (os.environ.get("NVSF_LOG_JSON") or "false").lower() in {"1", "true", "yes", "on"}

    formatter: logging.Formatter = JsonFormatter() if as_json else logging.Formatter(_TEXT_FORMAT)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(level)

    handlers: list[logging.Handler] = []
    if "stdout" in sinks:
        handlers.append(logging.StreamHandler(sys.stdout))
    if "file" in sinks:
        import paths  # local import: paths reads NVSF_DATA_DIR, which load() may have just set

        log_dir = paths.logs_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(
            log_dir / "factory.log", maxBytes=16 * 1024 * 1024, backupCount=5, encoding="utf-8",
        ))
    if not handlers:
        # An empty sink list is a configuration mistake, and silence is the worst way to report it.
        handlers.append(logging.StreamHandler(sys.stdout))

    redaction = RedactionFilter()
    correlation = CorrelationFilter()
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(redaction)
        handler.addFilter(correlation)
        root.addHandler(handler)

    # Werkzeug's request log duplicates gunicorn's access log and is noisier.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    # urllib3 logs a line per connection at DEBUG, which drowns everything during a fan-out.
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    _configured = True


def set_correlation_id(value: str) -> contextvars.Token[str]:
    return correlation_id.set(value)


def reset_correlation_id(token: contextvars.Token[str]) -> None:
    correlation_id.reset(token)
