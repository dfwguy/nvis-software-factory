# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Load ``standards/`` -- the one definition of what good looks like.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Two consumers read the output of this module: the prompt builder, which injects pillar text into
the reasoning passes, and the docs generator, which renders the same text into the site. That is
the point of loading it rather than restating it. If the guidance an agent receives and the
guidance a human reads could drift, we would have two standards and therefore none.

WHY PARSE MARKDOWN INSTEAD OF KEEPING THIS IN PYTHON
-----------------------------------------------------
Because the pillars are *prose*, and prose is what the model needs. A Python structure holding
criteria as short strings would be easier to parse and would lose the part that does the work --
the explanation of why a criterion matters, and the remediation pattern that tells an agent what
to do about it. So the Markdown is the source, the frontmatter carries the machine-readable part,
and this module extracts enough structure to be useful without pretending the prose is data.

The parse is deliberately strict about frontmatter and deliberately lenient about body structure.
A missing ``id`` is a hard error, because ``id`` is a database value and a prompt key. A criterion
heading that does not match the expected shape is skipped with a warning, because the body is
written by humans and a documentation formatting slip must not take the application down.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import paths
import yaml
from store.models import Severity

_logger = logging.getLogger("nvsf.factory.standards")

#: ``### D1 — State that must survive a restart is written outside ...``
#: Accepts an em dash, an en dash or a hyphen, because all three get typed.
_CRITERION_RE = re.compile(r"^###\s+([A-Z]{1,3}\d+)\s*[—–-]\s*(.+?)\s*$", re.MULTILINE)

#: ``*Detector: yes.*`` / ``*Detector: partial.*`` / ``*Detector: no — judgement.*``
_DETECTOR_RE = re.compile(r"^\*Detector:\s*(yes|partial|no)\b", re.MULTILINE | re.IGNORECASE)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class StandardsError(RuntimeError):
    """A pillar file is malformed in a way that would corrupt an assessment."""


@dataclass(frozen=True)
class Criterion:
    """One checkable statement about a repository."""

    id: str
    title: str
    #: ``yes`` | ``partial`` | ``no``. Whether a deterministic detector exists.
    #:
    #: This is what the prompt uses to tell the model when it is being asked to *confirm* a fact
    #: and when it is being asked to *judge*. Blurring the two is how a model ends up asserting
    #: something it cannot know.
    detector: str
    body: str

    @property
    def judgement_only(self) -> bool:
        return self.detector == "no"


@dataclass(frozen=True)
class Pillar:
    id: str
    title: str
    severity_ceiling: Severity
    order: int
    detectors: tuple[str, ...]
    criteria: tuple[Criterion, ...]
    #: Full Markdown body, frontmatter stripped. What goes into the prompt.
    body: str
    path: Path

    def criterion(self, criterion_id: str) -> Criterion | None:
        return next((c for c in self.criteria if c.id == criterion_id), None)

    def cap(self, severity: Severity) -> Severity:
        """Clamp a severity to this pillar's ceiling.

        A missing README cannot become a blocker no matter how strongly the model feels about it.
        The ceiling is the mechanism, and it lives with the pillar rather than in the ratchet, so
        changing it is a documentation edit that is visible in review.
        """
        return severity if severity.rank <= self.severity_ceiling.rank else self.severity_ceiling


@dataclass(frozen=True)
class Standards:
    """The whole baseline, with a version derived from its content."""

    pillars: tuple[Pillar, ...]
    version: str
    overview: str = field(default="")

    def by_id(self, pillar_id: str) -> Pillar | None:
        return next((p for p in self.pillars if p.id == pillar_id), None)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(p.id for p in self.pillars)


def _parse_frontmatter(text: str, path: Path) -> tuple[dict, str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise StandardsError(
            f"{path.name} has no YAML frontmatter. Every pillar must declare at least 'id', "
            "'title' and 'severity_ceiling' -- those are parsed, not decorative."
        )
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise StandardsError(f"{path.name} frontmatter is not valid YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise StandardsError(f"{path.name} frontmatter is not a mapping")
    return meta, text[match.end():]


def _parse_criteria(body: str, path: Path) -> tuple[Criterion, ...]:
    """Extract criteria from ``###`` headings, with each one's detector status and prose."""
    matches = list(_CRITERION_RE.finditer(body))
    criteria: list[Criterion] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        section = body[start:end].strip()

        detector_match = _DETECTOR_RE.search(section)
        if detector_match is None:
            # Lenient by design: a documentation formatting slip must not break the app. But say
            # so, because the prompt relies on this to tell 'confirm' from 'judge'.
            _logger.warning(
                "standards: %s criterion %s does not declare a detector status; treating it as "
                "judgement-only. Add a '*Detector: yes|partial|no*' line.",
                path.name, match.group(1),
            )
            detector = "no"
        else:
            detector = detector_match.group(1).lower()

        criteria.append(Criterion(
            id=match.group(1), title=match.group(2).strip(), detector=detector, body=section,
        ))
    return tuple(criteria)


def load_pillar(path: Path) -> Pillar:
    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text, path)

    for required in ("id", "title", "severity_ceiling"):
        if not meta.get(required):
            raise StandardsError(f"{path.name} frontmatter has no '{required}'")

    try:
        ceiling = Severity(str(meta["severity_ceiling"]))
    except ValueError as exc:
        raise StandardsError(
            f"{path.name} declares severity_ceiling={meta['severity_ceiling']!r}, which is not "
            f"one of {', '.join(str(s) for s in Severity)}"
        ) from exc

    detectors = meta.get("detectors") or []
    if isinstance(detectors, str):
        detectors = [detectors]

    return Pillar(
        id=str(meta["id"]),
        title=str(meta["title"]),
        severity_ceiling=ceiling,
        order=int(meta.get("order", 999)),
        detectors=tuple(str(d) for d in detectors),
        criteria=_parse_criteria(body, path),
        body=body.strip(),
        path=path,
    )


@lru_cache(maxsize=1)
def load() -> Standards:
    """The whole baseline, cached.

    Cached because it is read on every assessment and every docs build, and the files do not change
    under a running process. Call :func:`reload` after editing one in development.
    """
    directory = paths.STANDARDS_DIR / "pillars"
    if not directory.is_dir():
        raise StandardsError(
            f"{directory} does not exist. standards/ is the single definition of the quality "
            "baseline; the application cannot judge a repository without it."
        )

    files = sorted(directory.glob("*.md"))
    if not files:
        raise StandardsError(f"{directory} contains no pillar files")

    pillars = sorted((load_pillar(p) for p in files), key=lambda p: (p.order, p.id))

    seen: dict[str, str] = {}
    for pillar in pillars:
        if pillar.id in seen:
            raise StandardsError(
                f"pillar id {pillar.id!r} is declared twice: {seen[pillar.id]} and "
                f"{pillar.path.name}. Ids are database values and prompt keys, so they must be "
                "unique."
            )
        seen[pillar.id] = pillar.path.name

    # Content-addressed version. An assessment records this, so a pillar edit makes previous
    # results identifiable as judged against a different baseline rather than silently stale.
    digest = hashlib.sha256()
    for pillar in pillars:
        digest.update(pillar.id.encode("utf-8"))
        digest.update(pillar.body.encode("utf-8"))

    overview_path = paths.STANDARDS_DIR / "README.md"
    overview = overview_path.read_text(encoding="utf-8") if overview_path.is_file() else ""

    return Standards(
        pillars=tuple(pillars),
        version=f"{len(pillars)}p-{digest.hexdigest()[:12]}",
        overview=overview,
    )


def reload() -> Standards:
    """Drop the cache and re-read. For development and for tests."""
    load.cache_clear()
    return load()


def load_all() -> tuple[Pillar, ...]:
    return load().pillars


def version() -> str:
    return load().version


def get(pillar_id: str) -> Pillar:
    pillar = load().by_id(pillar_id)
    if pillar is None:
        raise StandardsError(
            f"no pillar with id {pillar_id!r}; known: {', '.join(load().ids)}"
        )
    return pillar
