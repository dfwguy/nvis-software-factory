# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The one-way ratchet: the model may escalate a finding, never downgrade one.

Author: Rafael M. Koike & Cursor Agent ("Ada")

WHY THIS EXISTS
---------------
The factory is AI-first: the reasoning pass is required, not decorative. That creates a specific
risk. A language model asked to judge a repository against a standard is agreeable by
construction — given a plausible-sounding reason ("the data is ephemeral anyway", "this is only a
prototype"), it will soften a finding. Sometimes it is right. But the softening happens invisibly,
and the reader cannot tell which findings survived scrutiny and which were talked away.

So the merge is asymmetric and mechanical:

* A scanner finding is a **floor**. The model can raise its severity, add detail, or reframe it.
  It cannot lower it, cannot drop it, and cannot mark it resolved.
* A model finding is **additive**. It carries ``origin = model`` everywhere it is displayed, so a
  reader weighs it as judgement rather than measurement.
* Every escalation records ``escalated_from``, so the audit trail shows what the scanner said and
  what the model made of it.

WHAT THE RATCHET IS NOT
------------------------
It is not a claim that the scanners are always right. A false deterministic finding is a real
problem, and the fix is to change the scanner — in code, in review, with a test. That is slower
than letting the model override it, and that is the point: the severity of what we tell a customer
about their software should not be renegotiable per run by a non-deterministic process.

The escape hatch is human and explicit: an SA can dismiss a finding on the assessment, which is
recorded as a dismissal with an actor and a reason. It never looks like the finding was not there.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from store.models import Finding, Origin, Severity, new_id, now_iso

from factory.scanners import Fact

_logger = logging.getLogger("nvsf.factory.ratchet")


class RatchetViolation(RuntimeError):
    """The model tried to lower or drop a deterministic finding, and we caught it.

    Raised only when the merge is asked to be strict (tests, and the ``--strict`` self-check).
    In a normal run the violation is corrected and recorded rather than raised: aborting an
    eight-minute assessment because the model got agreeable is the wrong trade, but silently
    accepting the downgrade is worse than either.
    """


@dataclass
class MergeReport:
    """What the merge did, in enough detail to explain it in the report and in the audit log."""

    findings: list[Finding]
    escalations: list[dict[str, Any]]
    #: Attempts by the model to lower or drop a scanner finding. Corrected, and surfaced.
    refused_downgrades: list[dict[str, Any]]
    #: Model findings with no scanner counterpart. The genuine value the reasoning pass adds.
    model_additions: int
    #: Model findings dropped for citing a pillar that does not exist, or no title.
    rejected_malformed: list[dict[str, Any]]
    #: Model severities capped by the pillar's ceiling from the standard.
    clamped_to_ceiling: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "counts": {
                "total": len(self.findings),
                "from_scanner": sum(
                    1 for f in self.findings if f.origin is Origin.SCANNER),
                "from_model": self.model_additions,
                "escalated": len(self.escalations),
                "refused_downgrades": len(self.refused_downgrades),
                "rejected_malformed": len(self.rejected_malformed),
                "clamped_to_ceiling": len(self.clamped_to_ceiling),
            },
            "escalations": self.escalations,
            "refused_downgrades": self.refused_downgrades,
            "rejected_malformed": self.rejected_malformed,
            "clamped_to_ceiling": self.clamped_to_ceiling,
        }


def _severity(value: Any) -> Severity | None:
    """Parse a severity from model output, tolerantly. Unknown values become None.

    Tolerant because the model writes ``"Blocker"``, ``"BLOCKER"``, and occasionally
    ``"critical"``. Rejecting the finding over casing would discard real signal; guessing at
    ``"critical"`` would invent a severity level the standard does not have, so that one maps to
    the worst level we do have and the mapping is logged.
    """
    if isinstance(value, Severity):
        return value
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    aliases = {
        "critical": "blocker", "high": "major", "medium": "minor", "moderate": "minor",
        "low": "info", "informational": "info", "warning": "minor", "note": "info",
    }
    normalized = aliases.get(normalized, normalized)
    try:
        return Severity(normalized)
    except ValueError:
        return None


def fact_to_finding(fact: Fact, assessment_id: str) -> Finding:
    """A scanner fact carrying a severity, as a persisted finding."""
    if fact.severity is None:
        raise ValueError(f"fact {fact.key!r} is an observation, not a finding")
    return Finding(
        id=new_id(),
        assessment_id=assessment_id,
        pillar_id=fact.pillar_id,
        severity=fact.severity,
        title=fact.title,
        origin=Origin.SCANNER,
        created_at=now_iso(),
        criterion=fact.criterion,
        detail=fact.detail or None,
        file_path=fact.file_path,
        line_start=fact.line_start,
        line_end=fact.line_end,
        detector=fact.key,
        remediation=fact.remediation,
    )


class _Index:
    """Scanner findings, looked up the several ways the model might refer to one.

    The prompt asks the model to echo a finding's exact title. It mostly does, and when it does
    not it usually paraphrases or supplies the detector key instead. So the index accepts a
    detector key, an exact title, and a normalized title, in that order of confidence.

    Every lookup is scoped to a pillar. That is the one thing worth being strict about: matching
    across pillars would attach the model's reasoning about backups to a finding about TLS, and
    the resulting report would be wrong in a way that reads as authoritative.
    """

    def __init__(self, findings: list[Finding]) -> None:
        self._by_detector: dict[tuple[str, str], Finding] = {}
        self._by_title: dict[tuple[str, str], Finding] = {}
        for finding in findings:
            self.add(finding)

    @staticmethod
    def _normalize(title: str) -> str:
        return "".join(ch for ch in title.lower() if ch.isalnum() or ch == " ").strip()

    def add(self, finding: Finding) -> None:
        if finding.detector:
            self._by_detector[(finding.pillar_id, finding.detector)] = finding
        self._by_title[(finding.pillar_id, self._normalize(finding.title))] = finding

    def find(self, pillar_id: str, detector: Any, title: str) -> Finding | None:
        if detector:
            hit = self._by_detector.get((pillar_id, str(detector)))
            if hit is not None:
                return hit
        return self._by_title.get((pillar_id, self._normalize(title)))


def merge(
    facts: list[Fact],
    model_findings: list[dict[str, Any]],
    assessment_id: str,
    valid_pillars: set[str],
    ceilings: dict[str, Severity] | None = None,
    strict: bool = False,
) -> MergeReport:
    """Merge deterministic findings with the model's judgement, ratchet-side up.

    *facts* is everything the scanners produced; observations are ignored here since they are not
    findings. *model_findings* is the parsed per-pillar judgement output.

    *ceilings* caps model severity per pillar, from the standard's frontmatter. The prompt tells
    the model this is enforced in code, so it has to actually be enforced here — a promise in a
    prompt that the code does not keep is how a model learns the rules are advisory. Note the cap
    applies to the model only: a scanner finding above the ceiling means the *standard* is wrong
    about that pillar, which is a conversation, not a clamp.
    """
    ceilings = ceilings or {}
    deterministic = [f for f in facts if f.is_finding]
    findings: list[Finding] = [fact_to_finding(f, assessment_id) for f in deterministic]
    index = _Index(findings)

    escalations: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    clamped: list[dict[str, Any]] = []
    additions: list[Finding] = []

    for raw in model_findings:
        if not isinstance(raw, dict):
            rejected.append({"reason": "not an object", "value": str(raw)[:200]})
            continue

        pillar_id = str(raw.get("pillar_id") or raw.get("pillar") or "").strip()
        title = str(raw.get("title") or "").strip()
        severity = _severity(raw.get("severity"))

        if pillar_id not in valid_pillars:
            # A pillar the standard does not define means the model invented a category. Dropping
            # it is right: the report's structure is the standard's structure, and a finding with
            # nowhere to live would be silently lost at render time anyway.
            rejected.append({"reason": "unknown pillar", "pillar_id": pillar_id, "title": title})
            continue
        if not title:
            rejected.append({"reason": "no title", "pillar_id": pillar_id})
            continue
        if severity is None:
            rejected.append({
                "reason": "unparseable severity", "pillar_id": pillar_id, "title": title,
                "value": str(raw.get("severity"))[:80],
            })
            continue

        ceiling = ceilings.get(pillar_id)
        if ceiling is not None and severity.rank > ceiling.rank:
            clamped.append({
                "pillar_id": pillar_id, "title": title,
                "model_proposed": str(severity), "ceiling": str(ceiling),
            })
            severity = ceiling

        detector = raw.get("detector") or raw.get("detector_key")
        criterion = raw.get("criterion")
        existing = index.find(pillar_id, detector, title)

        if existing is None:
            additions.append(Finding(
                id=new_id(),
                assessment_id=assessment_id,
                pillar_id=pillar_id,
                severity=severity,
                title=title,
                origin=Origin.MODEL,
                created_at=now_iso(),
                criterion=str(criterion) if criterion else None,
                detail=str(raw.get("detail") or raw.get("rationale") or "") or None,
                file_path=str(raw["file_path"]) if raw.get("file_path") else None,
                line_start=_int(raw.get("line_start")),
                line_end=_int(raw.get("line_end")),
                remediation=str(raw.get("remediation") or "") or None,
            ))
            continue

        # The finding already exists deterministically. Only direction matters now.
        if severity.rank > existing.severity.rank:
            escalated = Finding(
                id=existing.id,
                assessment_id=assessment_id,
                pillar_id=existing.pillar_id,
                severity=severity,
                title=existing.title,
                origin=Origin.SCANNER,
                created_at=existing.created_at,
                criterion=existing.criterion,
                # Both voices are kept. The scanner said what it measured; the model said why it
                # is worse than that. Collapsing them into one paragraph loses the distinction a
                # reviewer needs.
                detail=_combine(existing.detail, raw.get("detail") or raw.get("rationale")),
                file_path=existing.file_path,
                line_start=existing.line_start,
                line_end=existing.line_end,
                escalated_from=existing.severity,
                detector=existing.detector,
                remediation=existing.remediation or (
                    str(raw.get("remediation")) if raw.get("remediation") else None),
            )
            _replace(findings, existing.id, escalated)
            index.add(escalated)
            escalations.append({
                "detector": existing.detector,
                "pillar_id": pillar_id,
                "from": str(existing.severity),
                "to": str(severity),
                "title": existing.title,
                "reason": str(raw.get("detail") or raw.get("rationale") or "")[:400],
            })

        elif severity.rank < existing.severity.rank:
            record = {
                "detector": existing.detector,
                "pillar_id": pillar_id,
                "kept": str(existing.severity),
                "model_proposed": str(severity),
                "title": existing.title,
                "model_reason": str(raw.get("detail") or raw.get("rationale") or "")[:400],
            }
            refused.append(record)
            _logger.warning(
                "ratchet: refused downgrade of %s from %s to %s",
                existing.detector, existing.severity, severity,
            )
            if strict:
                raise RatchetViolation(
                    f"model proposed lowering {existing.detector!r} from "
                    f"{existing.severity} to {severity}"
                )

    # Model additions are appended rather than interleaved, so the persisted order itself shows
    # the provenance boundary.
    findings.extend(additions)

    _logger.info(
        "ratchet: %d scanner finding(s), %d model addition(s), %d escalation(s), "
        "%d refused downgrade(s), %d rejected",
        len(deterministic), len(additions), len(escalations), len(refused), len(rejected),
    )
    return MergeReport(
        findings=findings,
        escalations=escalations,
        refused_downgrades=refused,
        model_additions=len(additions),
        rejected_malformed=rejected,
        clamped_to_ceiling=clamped,
    )


def _combine(scanner_detail: str | None, model_detail: Any) -> str | None:
    model_text = str(model_detail).strip() if model_detail else ""
    if not model_text:
        return scanner_detail
    if not scanner_detail:
        return model_text
    return f"{scanner_detail}\n\nRaised in review: {model_text}"


def _replace(findings: list[Finding], finding_id: str, replacement: Finding) -> None:
    for index, existing in enumerate(findings):
        if existing.id == finding_id:
            findings[index] = replacement
            return


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def verify(findings: list[Finding], facts: list[Fact]) -> list[str]:
    """Post-merge invariant check. Returns a list of problems; empty means the ratchet held.

    Called after the merge and again before rendering, because the ratchet is the one property of
    this pipeline that must not be quietly broken by a later refactor. Cheap enough to run twice.
    """
    problems: list[str] = []
    by_detector = {f.detector: f for f in findings if f.detector}

    for fact in facts:
        if not fact.is_finding:
            continue
        finding = by_detector.get(fact.key)
        if finding is None:
            problems.append(f"scanner finding {fact.key!r} is missing from the merged set")
            continue
        if fact.severity is None:
            # `is_finding` is defined as having a severity, so this cannot happen -- and this
            # function is the audit that proves the ratchet held, so it reports rather than
            # asserts. An assert vanishes under -O, and the one place that must not silently stop
            # checking is the check itself.
            problems.append(f"scanner fact {fact.key!r} claims to be a finding with no severity")
            continue
        if finding.severity.rank < fact.severity.rank:
            problems.append(
                f"{fact.key!r} was lowered from {fact.severity} to {finding.severity}"
            )
        if finding.origin is not Origin.SCANNER:
            problems.append(f"{fact.key!r} lost its scanner origin")
    return problems
