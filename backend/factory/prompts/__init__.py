# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Versioned prompt templates, loaded from files.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Prompts are files, never inline strings. Two reasons, and the second is the one that matters:

1. A prompt change alters **every future assessment**. As a file it is a reviewable diff in a merge
   request; as a string buried in a function it is invisible in review.
2. The version is recorded with every call, so an assessment can be reproduced and two assessments
   can be compared. That is only meaningful if the version identifies specific text.

The version is ``<name>@<n>+<hash>``: the declared revision, plus a short content hash. The
revision is the human signal that something changed on purpose; the hash catches the case where
somebody edited the text and forgot to bump it. Both appear in the provenance record.

A template is Markdown with YAML frontmatter:

    ---
    revision: 1
    description: What this pass asks for
    ---
    ## SYSTEM
    ...
    ## USER
    ...

Substitution is ``str.format``-style with named fields, and a missing field is an error rather
than an empty string -- a prompt silently missing its evidence would produce a confident answer
about nothing at all.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from string import Formatter

import yaml

_logger = logging.getLogger("nvsf.factory.prompts")

TEMPLATES_DIR = Path(__file__).resolve().parent

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SECTION_RE = re.compile(r"^##\s+(SYSTEM|USER)\s*$", re.MULTILINE)


class PromptError(RuntimeError):
    """A template is missing, malformed, or was rendered with the wrong fields."""


@dataclass(frozen=True)
class Prompt:
    name: str
    revision: int
    description: str
    system: str
    user: str
    content_hash: str

    @property
    def version(self) -> str:
        """What gets recorded with every call that uses this template."""
        return f"{self.name}@{self.revision}+{self.content_hash[:8]}"

    def fields(self) -> set[str]:
        """Named substitution fields the template expects."""
        found: set[str] = set()
        for text in (self.system, self.user):
            for _, field_name, _, _ in Formatter().parse(text):
                if field_name:
                    found.add(field_name)
        return found

    def render(self, **values: object) -> tuple[str, str]:
        """``(system, user)`` with fields substituted.

        A missing field raises. Rendering a prompt with an absent ``evidence`` would otherwise ask
        the model to judge a repository it was never shown, and it would answer.
        """
        expected = self.fields()
        missing = expected - set(values)
        if missing:
            raise PromptError(
                f"prompt {self.version} needs field(s) {', '.join(sorted(missing))} and they were "
                "not supplied. Rendering it anyway would ask the model to reason about absent "
                "evidence."
            )
        extra = set(values) - expected
        if extra:
            # Not fatal, but almost always a rename that half-happened.
            _logger.warning(
                "prompts: %s was given unused field(s): %s",
                self.version, ", ".join(sorted(extra)),
            )
        return (
            self.system.format(**values),
            self.user.format(**values),
        )


def _parse(path: Path) -> Prompt:
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise PromptError(f"{path.name} has no frontmatter; it must declare 'revision'")
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise PromptError(f"{path.name} frontmatter is not valid YAML: {exc}") from exc
    if "revision" not in meta:
        raise PromptError(
            f"{path.name} frontmatter has no 'revision'. Bump it whenever the text changes, so a "
            "reader of an old assessment can tell which prompt produced it."
        )

    body = text[match.end():]
    sections = _SECTION_RE.split(body)
    # split() yields ['', 'SYSTEM', '...', 'USER', '...'] when both markers are present.
    parts: dict[str, str] = {}
    for index in range(1, len(sections) - 1, 2):
        parts[sections[index]] = sections[index + 1].strip()

    if "SYSTEM" not in parts or "USER" not in parts:
        raise PromptError(
            f"{path.name} must contain both '## SYSTEM' and '## USER' sections; found "
            f"{', '.join(sorted(parts)) or 'neither'}"
        )

    return Prompt(
        name=path.stem,
        revision=int(meta["revision"]),
        description=str(meta.get("description", "")),
        system=parts["SYSTEM"],
        user=parts["USER"],
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
    )


@cache
def get(name: str) -> Prompt:
    """Load a template by filename stem, cached."""
    path = TEMPLATES_DIR / f"{name}.md"
    if not path.is_file():
        raise PromptError(
            f"no prompt template named {name!r} in {TEMPLATES_DIR.name}/; available: "
            f"{', '.join(available()) or 'none'}"
        )
    return _parse(path)


def available() -> list[str]:
    return sorted(p.stem for p in TEMPLATES_DIR.glob("*.md"))


def reload() -> None:
    """Drop the cache. For development and tests."""
    get.cache_clear()


def versions() -> dict[str, str]:
    """Every template's version. Reported by diagnostics so a deployment can be identified."""
    return {name: get(name).version for name in available()}
