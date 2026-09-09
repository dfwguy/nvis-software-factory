# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual property and proprietary
# rights in and to this material, related documentation and any modifications thereto. Any use,
# reproduction, disclosure or distribution of this material and related documentation without an
# express license agreement from NVIDIA CORPORATION or its affiliates is strictly prohibited.
"""The log redaction filter: what it must hide, and what it must not break doing so."""

import logging

from logging_config import RedactionFilter, redact


def _record(msg: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, args or None, None)


def _filtered(msg: str, *args: object) -> str:
    record = _record(msg, *args)
    assert RedactionFilter().filter(record) is True
    return record.getMessage()


# ── Credentials still have to disappear ──────────────────────────────────────────────────────


def test_a_bearer_token_is_removed():
    assert "abc123" not in redact("Authorization: Bearer abc123")


def test_a_named_credential_is_removed():
    for text in (
        "api_key=nvapi-abcdefghijklmnop",
        'NVSF_LLM_API_KEY: "sk-YFksomethingsecret"',
        "password=hunter2",
        "gitlab_token=glpat-xxxxxxxxxxxx",
    ):
        assert "***REDACTED***" in redact(text), text


def test_a_credential_in_a_url_is_removed():
    assert "hunter2" not in redact("cloning https://user:hunter2@gitlab.example.com/x.git")


def test_a_secret_split_across_the_template_and_an_argument_is_still_caught():
    """Only credential-shaped once the two halves are joined, which is an argument for
    interpolating before redacting rather than after."""
    assert "nvapi-realkey" not in _filtered("api_key=%s", "nvapi-realkey")


# ── ...without destroying the record doing it ────────────────────────────────────────────────


def test_a_format_template_survives_redaction():
    """The bug this file exists for.

    `record.msg` is a template, not a message. Redacting it replaced `%d/%d` -- which is the
    *value* of a credential-shaped name -- leaving three specifiers for five arguments. Logging
    raised TypeError inside its own formatting, dropped the record, and printed a traceback
    pointing at the innocent caller.
    """
    message = _filtered(
        "llm: %s pass=%s tokens=%d/%d in %dms", "nemotron", "architecture", 1200, 340, 987
    )

    assert message == "llm: nemotron pass=architecture tokens=1200/340 in 987ms"


def test_a_token_count_is_not_mistaken_for_a_token():
    """`tokens=` matches the credential-name pattern, but a count is not a credential and it is
    the one number worth logging about a reasoning call."""
    assert redact("tokens=1200/340") == "tokens=1200/340"
    assert redact("token_count: 512") == "token_count: 512"


def test_a_short_credential_that_looks_numeric_is_still_redacted_when_it_is_not_one():
    """The measurement exemption is deliberately narrow: digits and separators only."""
    assert "***REDACTED***" in redact("token=12ab34cd56ef")


def test_a_malformed_logging_call_does_not_raise():
    """Too few arguments is the caller's bug. The filter must not turn it into a crash here."""
    record = _record("two placeholders %s %s", "only-one")

    assert RedactionFilter().filter(record) is True
