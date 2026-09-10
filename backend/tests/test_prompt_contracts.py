# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual property and proprietary
# rights in and to this material, related documentation and any modifications thereto. Any use,
# reproduction, disclosure or distribution of this material and related documentation without an
# express license agreement from NVIDIA CORPORATION or its affiliates is strictly prohibited.
"""The prompt templates and the code that reads their answers must agree.

Nothing checked this, and they drifted. The architecture pass required a `summary` from a template
that asks for `purpose`; remediation required a flat `steps` list from a template that buckets work
into `immediate` / `next` / `later`. Both failed *every* assessment at runtime, reported as the
model returning a malformed response -- when the model had returned precisely what it was asked
for. The evidence pointed at the one component that was behaving correctly.

A prompt is a contract with two sides in two different languages, and only one side is executable.
This is the test that reads both.
"""

import re
from pathlib import Path

import pytest
from factory import prompts
from factory.pipeline import REQUIRED_KEYS

PROMPT_DIR = Path(prompts.__file__).parent


def _template_keys(name: str) -> set[str]:
    """Top-level keys of the JSON object a template instructs the model to return.

    The templates use doubled braces for `str.format`, and the object is the last brace block in
    the file. Top-level keys are the ones at exactly two spaces of indentation.
    """
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    body = text.split("Return this JSON object:", 1)
    assert len(body) == 2, f"{name}.md does not end with a 'Return this JSON object:' block"
    return set(re.findall(r'^\s{2}"([a-z_]+)"\s*:', body[1], re.MULTILINE))


@pytest.mark.parametrize("template", sorted(REQUIRED_KEYS))
def test_every_required_key_is_one_the_template_asks_for(template: str):
    """The failure this file exists to prevent, checked statically instead of per assessment."""
    required = set(REQUIRED_KEYS[template])
    available = _template_keys(template)

    missing = required - available
    assert not missing, (
        f"{template}.md never asks the model for {sorted(missing)}, but the pipeline refuses any "
        f"response without them, so every run fails. The template asks for {sorted(available)}."
    )


@pytest.mark.parametrize("template", sorted(REQUIRED_KEYS))
def test_every_template_has_a_parseable_response_contract(template: str):
    """A template whose keys cannot be read here is one this test cannot protect."""
    assert _template_keys(template), f"{template}.md declares no top-level response keys"


def test_the_declared_templates_all_exist():
    for template in REQUIRED_KEYS:
        assert (PROMPT_DIR / f"{template}.md").is_file(), f"no template named {template}.md"


def test_the_architecture_summary_reads_keys_the_template_produces():
    """The quieter half of the same bug.

    `_architecture_summary` condenses the architecture pass into the context every pillar
    judgement receives. It used to read `summary`, `data_flow` and `state_management` -- none of
    which that template emits -- so had the required-key check not failed first, all eight pillars
    would have judged the repository against almost no context. Nothing would have errored.
    """
    from factory.pipeline import _architecture_summary

    architecture = {
        "purpose": "Records rack validation results.",
        "archetype": "web-service",
        "who_depends_on_it": "one team",
        "state": {"what_state_exists": "results", "where_it_lives": "in-memory"},
        "components": [{"name": "app", "role": "HTTP entry point"}],
        "entry_points": [{"kind": "http-route", "name": "POST /results"}],
        "external_dependencies": [{"what": "DCGM", "how": "HTTP"}],
        "not_determinable": ["whether results exist upstream"],
    }

    summary = _architecture_summary(architecture)

    for expected in (
        "Records rack validation results.",
        "web-service",
        "one team",
        "in-memory",
        "HTTP entry point",
        "POST /results",
        "DCGM",
        "whether results exist upstream",
    ):
        assert expected in summary, f"{expected!r} did not survive into the pillar context"


def test_the_architecture_summary_tolerates_a_short_answer():
    """Models omit keys. That is a thinner report, not a crash."""
    assert _architecture_summary_safe({"purpose": "A CLI."}) == "Purpose: A CLI."
    assert _architecture_summary_safe({}) == ""


def _architecture_summary_safe(data: dict) -> str:
    from factory.pipeline import _architecture_summary

    return _architecture_summary(data)
