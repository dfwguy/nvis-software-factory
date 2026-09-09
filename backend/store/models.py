# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Vocabulary shared by the store, the pipeline, and the API.

Author: Rafael M. Koike & Cursor Agent ("Ada")

These are plain dataclasses and string enums, not an ORM. The schema is small and stable, and the
queries are hand-written in ``repo.py`` where they can be read. What this module buys is a single
definition of the *words*: an assessment status spelled two ways in two modules is a bug that only
shows up as a run that never leaves 'queued'.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def new_id() -> str:
    """A fresh identifier.

    UUID4 rather than a sequence: these ids appear in URLs, in downloadable artifacts, and in other
    teams' agent transcripts. A sequential integer leaks how many assessments exist and invites
    enumeration.
    """
    return str(uuid.uuid4())


def now_iso() -> str:
    """UTC, second precision, fixed width so it sorts correctly as text."""
    return datetime.now(UTC).isoformat(timespec="seconds")


class Status(StrEnum):
    """Assessment lifecycle.

    Note there is no 'partial' or 'degraded' terminal state. A run either produced a complete
    assessment or it failed: an assessment that looks finished but skipped its reasoning stage
    would be indistinguishable from a real one to the reader, which is the failure mode this whole
    design exists to avoid.
    """

    QUEUED = "queued"
    CLONING = "cloning"
    SCANNING = "scanning"
    REASONING = "reasoning"
    RENDERING = "rendering"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {Status.COMPLETE, Status.FAILED, Status.CANCELLED}

    @property
    def active(self) -> bool:
        return not self.terminal


class Severity(StrEnum):
    """Shared with ``standards/`` frontmatter and with the ratchet. Ordered by ``rank``."""

    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"

    @property
    def rank(self) -> int:
        """Higher is worse. Used by the ratchet to decide whether a change is an escalation."""
        return {"info": 0, "minor": 1, "major": 2, "blocker": 3}[self.value]


class Origin(StrEnum):
    """Who produced a finding. The ratchet's central distinction.

    ``SCANNER`` findings are facts and may not be downgraded by the model. ``MODEL`` findings are
    judgement, and are labelled as such wherever they are displayed so a reader can weigh them
    differently.
    """

    SCANNER = "scanner"
    MODEL = "model"


class PassStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(frozen=True)
class Repository:
    id: str
    url: str
    canonical_url: str
    forge: str
    name: str
    added_at: str
    added_by: str
    namespace: str | None = None
    default_branch: str | None = None
    notes: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "forge": self.forge,
            "namespace": self.namespace,
            "name": self.name,
            "default_branch": self.default_branch,
            "added_at": self.added_at,
            "added_by": self.added_by,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class Assessment:
    id: str
    repository_id: str
    status: Status
    created_at: str
    created_by: str
    ref: str | None = None
    commit_sha: str | None = None
    evidence_hash: str | None = None
    standards_version: str | None = None
    intake: dict[str, Any] = field(default_factory=dict)
    failure_reason: str | None = None
    failure_detail: str | None = None
    retryable: bool = False
    started_at: str | None = None
    finished_at: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "repository_id": self.repository_id,
            "status": str(self.status),
            "ref": self.ref,
            "commit_sha": self.commit_sha,
            "evidence_hash": self.evidence_hash,
            "standards_version": self.standards_version,
            "intake": self.intake,
            "failure": (
                {
                    "reason": self.failure_reason,
                    "detail": self.failure_detail,
                    "retryable": self.retryable,
                }
                if self.status is Status.FAILED else None
            ),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "created_by": self.created_by,
        }


@dataclass(frozen=True)
class Finding:
    """One judgement about one repository, with a citation.

    ``origin`` and ``escalated_from`` together are the ratchet's audit trail. A reviewer can see
    that the model raised a scanner's ``minor`` to ``blocker`` and decide whether it was right,
    instead of being handed a merged severity with no history.
    """

    id: str
    assessment_id: str
    pillar_id: str
    severity: Severity
    title: str
    origin: Origin
    created_at: str
    criterion: str | None = None
    detail: str | None = None
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    escalated_from: Severity | None = None
    detector: str | None = None
    remediation: str | None = None

    @property
    def citation(self) -> str | None:
        if not self.file_path:
            return None
        if self.line_start and self.line_end and self.line_end != self.line_start:
            return f"{self.file_path}:{self.line_start}-{self.line_end}"
        if self.line_start:
            return f"{self.file_path}:{self.line_start}"
        return self.file_path

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pillar_id": self.pillar_id,
            "criterion": self.criterion,
            "severity": str(self.severity),
            "title": self.title,
            "detail": self.detail,
            "citation": self.citation,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "origin": str(self.origin),
            "escalated_from": str(self.escalated_from) if self.escalated_from else None,
            "detector": self.detector,
            "remediation": self.remediation,
        }


@dataclass(frozen=True)
class LlmCall:
    """The provenance record for one model call. Written whether the call succeeded or not."""

    id: str
    assessment_id: str
    pass_name: str
    model: str
    prompt_version: str
    temperature: float
    status: str
    created_at: str
    evidence_hash: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    duration_ms: int | None = None
    error: str | None = None
    raw_response: str | None = None

    def to_json(self, include_raw: bool = False) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "pass_name": self.pass_name,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "temperature": self.temperature,
            "evidence_hash": self.evidence_hash,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
        }
        if include_raw:
            payload["raw_response"] = self.raw_response
        return payload
