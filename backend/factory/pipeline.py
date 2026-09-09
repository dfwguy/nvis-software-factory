# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The assessment run, end to end.

Author: Rafael M. Koike & Cursor Agent ("Ada")

    acquire -> scan -> evidence -> architecture -> per-pillar judgement -> remediation
            -> open questions -> merge under the ratchet -> render

RESUMABILITY, AND WHY IT IS WORTH THE COMPLEXITY
-------------------------------------------------
A full run is eleven model calls. At internal-endpoint latency that is several minutes, and the
endpoint occasionally returns 503. Without per-pass persistence, a failure on the last pass throws
away ten successful calls and the SA waits again from zero.

So each pass writes its output to the database as it completes, and :func:`run` skips passes that
already have output for this assessment. Retrying a failed run costs only the passes that did not
finish. The clone and the scan are cheap enough to redo, and redoing them is more honest than
persisting a working tree between attempts.

WHAT MAKES A RUN FAIL
----------------------
Fail-closed, in both directions:

* The clone fails, or the LLM endpoint is unreachable: the run **fails**. There is no
  scanners-only mode. A report labelled "partial" would be read as a report, and a repository
  that got a clean-looking assessment because the reasoning pass was skipped is exactly the
  outcome the factory exists to prevent.
* A single pillar judgement fails after retries: the run **still fails**. Seven pillars judged and
  one silently missing is the same problem one level down.

The one exception is a *scanner* crash, which degrades to "this pillar has no evidence" and is
labelled as such throughout. That asymmetry is deliberate: a scanner is one signal among many for
its pillar, whereas the reasoning pass is the thing that turns signals into an assessment.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from store import repo
from store.models import Severity, Status

from factory import acquire, llm, prompts, ratchet, scanners, standards
from factory import evidence as evidence_mod
from factory.report import render_bundle

_logger = logging.getLogger("nvsf.factory.pipeline")

#: Passes in order. Names are persisted, so renaming one orphans prior runs' resume state.
PASS_ARCHITECTURE = "architecture"
PASS_REMEDIATION = "remediation"
PASS_OPEN_QUESTIONS = "open_questions"


def _pillar_pass(pillar_id: str) -> str:
    return f"judgement:{pillar_id}"


class Cancelled(RuntimeError):
    """The run was cancelled while in flight."""


@dataclass
class RunState:
    """Live state for one run, so the API can report progress without polling the database.

    Progress is reported as a stage name and a completed-pass count, not a percentage. A
    percentage would have to be invented, and an invented percentage that sits at 80% for four
    minutes is worse than a stage name that says what is actually happening.
    """

    assessment_id: str
    stage: str = "queued"
    passes_total: int = 0
    passes_done: int = 0
    detail: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)

    def to_json(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "stage": self.stage,
            "passes_total": self.passes_total,
            "passes_done": self.passes_done,
            "detail": self.detail,
        }


_live: dict[str, RunState] = {}
_live_lock = threading.Lock()


def live_state(assessment_id: str) -> RunState | None:
    with _live_lock:
        return _live.get(assessment_id)


def request_cancel(assessment_id: str) -> bool:
    """Ask a running assessment to stop at its next checkpoint.

    Cooperative rather than forceful. Killing a thread mid-write is how a half-written pass row
    ends up in the database, and the checkpoints are frequent enough (between passes) that the
    delay is bounded by one model call.
    """
    with _live_lock:
        state = _live.get(assessment_id)
    if state is None:
        return False
    state.cancel.set()
    return True


def _checkpoint(state: RunState) -> None:
    if state.cancel.is_set():
        raise Cancelled("cancelled by request")


def _cached_or_run(
    assessment_id: str,
    pass_name: str,
    cached: dict[str, Any],
    runner,
) -> dict[str, Any]:
    """Return a completed pass's output, or run it and persist the result.

    The pass row is written before the model call, so a run that dies mid-call leaves a `running`
    row rather than no row. That distinction matters when reading the database afterwards to work
    out where a run stopped.
    """
    if pass_name in cached:
        _logger.info("pipeline: reusing completed pass %s for %s", pass_name, assessment_id)
        return cached[pass_name]

    pass_id = repo.start_pass(assessment_id, pass_name)
    try:
        output = runner()
    except Exception as error:
        repo.fail_pass(pass_id, f"{type(error).__name__}: {error}")
        raise
    repo.complete_pass(pass_id, output)
    return output


def _scanner_findings_text(facts: list[scanners.Fact], pillar_id: str) -> str:
    """Deterministic findings for one pillar, as the prompt's ratchet floor.

    Rendered as text rather than JSON because the model is being asked to respect these, and
    prose it can read reliably beats a nested structure it has to parse. The titles are echoed
    back by the model to identify escalations, so they are reproduced exactly.
    """
    relevant = [f for f in facts if f.is_finding and f.pillar_id == pillar_id]
    if not relevant:
        return (
            "No deterministic findings for this pillar. That does not mean it passes — the "
            "detectors that exist for it found nothing, and criteria marked `Detector: no` were "
            "never checked by code at all."
        )
    lines: list[str] = []
    for fact in relevant:
        citation = f" ({fact.citation})" if fact.citation else ""
        criterion = f" [{fact.criterion}]" if fact.criterion else ""
        lines.append(
            f"- **{str(fact.severity).upper()}**{criterion} {fact.title}{citation}\n"
            f"  detector: `{fact.key}`\n"
            f"  {fact.detail}"
        )
    return "\n".join(lines)


def run(assessment_id: str) -> None:
    """Execute one assessment. Blocking; the caller decides about threads.

    Terminal state is written here in every path, including cancellation, so an assessment never
    sits in a non-terminal state after its runner has exited.
    """
    assessment = repo.get_assessment(assessment_id)
    if assessment is None:
        raise ValueError(f"no assessment {assessment_id}")
    repository = repo.get_repository(assessment.repository_id)
    if repository is None:
        raise ValueError(f"assessment {assessment_id} references a missing repository")

    state = RunState(assessment_id=assessment_id)
    with _live_lock:
        _live[assessment_id] = state

    clone: acquire.Clone | None = None
    try:
        loaded = standards.load()
        state.passes_total = 3 + len(loaded.pillars)

        # ── Acquire ──────────────────────────────────────────────────────────────────────────
        state.stage = "cloning"
        repo.set_status(assessment_id, Status.CLONING)
        _checkpoint(state)
        # `url`, not `canonical_url`: the canonical form is a scheme-less dedup key and is not
        # fetchable. `acquire.clone` validates and strips credentials from whatever it is given.
        clone = acquire.clone(repository.url, ref=assessment.ref)
        repo.set_commit(assessment_id, clone.commit_sha)
        state.detail = f"{clone.file_count} files at {clone.commit_sha[:8]}"

        # ── Scan ─────────────────────────────────────────────────────────────────────────────
        state.stage = "scanning"
        repo.set_status(assessment_id, Status.SCANNING)
        _checkpoint(state)
        view = scanners.RepoView(clone.path)
        report = scanners.run_all(view)
        document = evidence_mod.build(
            view, clone, report, repository.canonical_url, name=repository.name,
        )
        evidence_hash = document.hash()
        repo.save_evidence(assessment_id, document.to_json(), evidence_hash)
        evidence_markdown = document.to_markdown()
        state.detail = (
            f"{len(report.facts)} facts, {len(report.findings)} deterministic findings"
        )

        # The clone is no longer needed: everything downstream reads the evidence document. Free
        # it now rather than at the end, because the reasoning stage is the long one and holding a
        # working tree through it for no reason is how the workspace volume fills up.
        clone.cleanup()
        acquired_clone, clone = clone, None

        # ── Reason ───────────────────────────────────────────────────────────────────────────
        state.stage = "reasoning"
        repo.set_status(assessment_id, Status.REASONING)
        cached = repo.completed_passes(assessment_id)
        repository_label = f"{repository.namespace or ''}/{repository.name}".strip("/")

        _checkpoint(state)
        architecture = _cached_or_run(
            assessment_id, PASS_ARCHITECTURE, cached,
            lambda: _run_architecture(
                assessment_id, repository_label, evidence_markdown, evidence_hash,
                document.inventory, assessment.intake,
            ),
        )
        state.passes_done += 1

        judgements: dict[str, dict[str, Any]] = {}
        architecture_summary = _architecture_summary(architecture)
        for pillar in loaded.pillars:
            _checkpoint(state)
            state.detail = f"judging {pillar.title}"
            judgements[pillar.id] = _cached_or_run(
                assessment_id, _pillar_pass(pillar.id), cached,
                lambda p=pillar: _run_pillar(
                    assessment_id, p, repository_label, architecture_summary,
                    _scanner_findings_text(report.facts, p.id), evidence_markdown, evidence_hash,
                ),
            )
            state.passes_done += 1

        # ── Merge under the ratchet, before the remediation pass ─────────────────────────────
        # Order matters: the remediation plan is built from the *merged* findings, so it plans
        # against the severities that will actually appear in the report. Planning from the raw
        # model output would produce an action plan whose priorities disagree with the findings
        # list next to it.
        state.stage = "merging"
        state.detail = "applying the ratchet"
        merge_report = ratchet.merge(
            facts=report.facts,
            model_findings=_model_findings(judgements),
            assessment_id=assessment_id,
            valid_pillars={p.id for p in loaded.pillars},
            ceilings={p.id: p.severity_ceiling for p in loaded.pillars},
        )

        problems = ratchet.verify(merge_report.findings, report.facts)
        if problems:
            # An invariant violation is a bug in this code, not a bad model response — the merge
            # already corrects those. Fail loudly rather than publish a report whose provenance
            # guarantee does not hold.
            raise RuntimeError("ratchet invariant violated: " + "; ".join(problems))

        repo.clear_findings(assessment_id)
        repo.save_findings(merge_report.findings)

        state.stage = "reasoning"
        _checkpoint(state)
        state.detail = "building the remediation plan"
        remediation = _cached_or_run(
            assessment_id, PASS_REMEDIATION, cached,
            lambda: _run_remediation(
                assessment_id, repository_label, architecture_summary,
                merge_report, judgements, evidence_hash,
                str(architecture.get("archetype") or ""),
            ),
        )
        state.passes_done += 1

        _checkpoint(state)
        state.detail = "collecting open questions"
        open_questions = _cached_or_run(
            assessment_id, PASS_OPEN_QUESTIONS, cached,
            lambda: _run_open_questions(
                assessment_id, repository_label, architecture_summary,
                judgements, evidence_hash,
            ),
        )
        state.passes_done += 1

        # ── Render ───────────────────────────────────────────────────────────────────────────
        state.stage = "rendering"
        repo.set_status(assessment_id, Status.RENDERING)
        render_bundle(
            assessment_id=assessment_id,
            repository=repository,
            clone=acquired_clone,
            evidence=document,
            architecture=architecture,
            judgements=judgements,
            findings=merge_report.findings,
            merge_report=merge_report,
            remediation=remediation,
            open_questions=open_questions,
            standards_version=loaded.version,
        )

        repo.set_status(assessment_id, Status.COMPLETE)
        state.stage = "complete"
        _logger.info(
            "pipeline: %s complete — %d finding(s), %d escalation(s), %d refused downgrade(s)",
            assessment_id, len(merge_report.findings), len(merge_report.escalations),
            len(merge_report.refused_downgrades),
        )

    except Cancelled:
        repo.set_status(assessment_id, Status.CANCELLED)
        state.stage = "cancelled"
        _logger.info("pipeline: %s cancelled", assessment_id)

    except acquire.AcquireRefused as error:
        repo.fail_assessment(assessment_id, "clone-refused", str(error), retryable=False)
        state.stage = "failed"
        _logger.warning("pipeline: %s refused: %s", assessment_id, error)

    except acquire.AcquireError as error:
        repo.fail_assessment(assessment_id, "clone-failed", str(error), retryable=True)
        state.stage = "failed"
        _logger.warning("pipeline: %s clone failed: %s", assessment_id, error)

    except llm.LlmUnavailable as error:
        # Retryable, and the retry is cheap because the completed passes are persisted. This is
        # the case that justifies the resume machinery.
        repo.fail_assessment(
            assessment_id, "llm-unavailable",
            f"{error} Completed reasoning passes are kept, so a retry resumes rather than "
            "starting over.",
            retryable=True,
        )
        state.stage = "failed"
        _logger.error("pipeline: %s llm unavailable: %s", assessment_id, error)

    except llm.LlmBadResponse as error:
        repo.fail_assessment(assessment_id, "llm-bad-response", str(error), retryable=True)
        state.stage = "failed"
        _logger.error("pipeline: %s bad llm response: %s", assessment_id, error)

    except Exception as error:
        repo.fail_assessment(
            assessment_id, "internal-error", f"{type(error).__name__}: {error}", retryable=False,
        )
        state.stage = "failed"
        _logger.exception("pipeline: %s failed", assessment_id)

    finally:
        if clone is not None:
            clone.cleanup()
        with _live_lock:
            _live.pop(assessment_id, None)


# ── Individual passes ────────────────────────────────────────────────────────────────────────


def _run_architecture(
    assessment_id: str,
    repository: str,
    evidence: str,
    evidence_hash: str,
    inventory: dict[str, Any],
    intake: dict[str, Any],
) -> dict[str, Any]:
    prompt = prompts.get("architecture")
    system, user = prompt.render(
        repository=repository,
        evidence=evidence,
        file_count=inventory.get("file_count", 0),
        languages=", ".join(
            f"{lang} ({count})" for lang, count in (inventory.get("languages") or {}).items()
        ) or "none detected",
        # What the SA said the tool is for, when they said anything. Free text, so it is labelled
        # as the submitter's claim rather than presented as established fact.
        intake=_intake_text(intake),
    )
    data, _ = llm.complete_json(
        system, user,
        prompt_version=prompt.version,
        assessment_id=assessment_id,
        pass_name=PASS_ARCHITECTURE,
        evidence_digest=evidence_hash,
        # These are the template's own keys. It asks for `purpose`, and has never asked for a
        # `summary` -- requiring one failed every assessment at the first pass with the model
        # blamed for a malformed reply, when the reply matched the prompt exactly.
        require_keys=("purpose", "archetype"),
    )
    return data


def _intake_text(intake: dict[str, Any]) -> str:
    if not intake:
        return (
            "The submitter provided no description. Infer the purpose from the evidence and say "
            "that you inferred it."
        )
    return "\n".join(
        f"- {key.replace('_', ' ')}: {value}"
        for key, value in intake.items()
        if value not in (None, "", [], {})
    ) or "The submitter provided no description."


def _architecture_summary(architecture: dict[str, Any]) -> str:
    """The architecture pass, condensed for reuse as context in later passes.

    Passing the whole object forward would spend a few thousand tokens per pillar restating what
    the pillar prompt does not use. What a pillar judgement needs is the purpose and shape of the
    thing, so it does not misread a CLI as a service.

    The keys here are the ones ``prompts/architecture.md`` actually asks for. They drifted once --
    this read `summary`, `data_flow` and `state_management`, none of which the template has ever
    emitted -- so the context handed to all eight pillar passes was silently near-empty. Keep the
    two in step: the template is the contract, and it is versioned for that reason.
    """
    parts: list[str] = []

    for key in ("purpose", "archetype", "who_depends_on_it"):
        if value := str(architecture.get(key) or "").strip():
            parts.append(f"{key.replace('_', ' ').capitalize()}: {value}")

    # State is what the durability pillar turns on, so it is worth spelling out rather than
    # stringifying the dict and hoping the next model reads Python repr.
    state = architecture.get("state")
    if isinstance(state, dict):
        exists = str(state.get("what_state_exists") or "").strip()
        lives = str(state.get("where_it_lives") or "").strip()
        if exists or lives:
            parts.append(f"State: {exists or 'unspecified'} (lives: {lives or 'undetermined'})")

    for key, fields in (
        ("components", ("name", "role")),
        ("entry_points", ("kind", "name")),
        ("external_dependencies", ("what", "how")),
    ):
        items = architecture.get(key)
        if not isinstance(items, list) or not items:
            continue
        rendered = [
            " — ".join(str(item.get(f) or "").strip() for f in fields if item.get(f))
            if isinstance(item, dict)
            else str(item)
            for item in items[:8]
        ]
        if joined := "; ".join(r for r in rendered if r):
            parts.append(f"{key.replace('_', ' ').capitalize()}: {joined}")

    # Carried forward deliberately: a pillar must be able to tell "the evidence says no" from
    # "the evidence does not say", and this is the only place that distinction survives.
    unknowns = architecture.get("not_determinable")
    if isinstance(unknowns, list) and unknowns:
        parts.append("Not determinable: " + "; ".join(str(u) for u in unknowns[:8]))

    return "\n".join(parts)[:6000]


def _run_pillar(
    assessment_id: str,
    pillar: standards.Pillar,
    repository: str,
    architecture: str,
    scanner_findings: str,
    evidence: str,
    evidence_hash: str,
) -> dict[str, Any]:
    prompt = prompts.get("pillar_judgement")
    system, user = prompt.render(
        pillar_title=pillar.title,
        pillar_body=pillar.body,
        severity_ceiling=str(pillar.severity_ceiling),
        repository=repository,
        architecture=architecture,
        scanner_findings=scanner_findings,
        evidence=evidence,
    )
    data, _ = llm.complete_json(
        system, user,
        prompt_version=prompt.version,
        assessment_id=assessment_id,
        pass_name=_pillar_pass(pillar.id),
        evidence_digest=evidence_hash,
        require_keys=("verdict", "summary"),
    )
    data["pillar_id"] = pillar.id
    return data


def _model_findings(judgements: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten the per-pillar judgements into what :func:`ratchet.merge` consumes.

    Escalations and additions arrive in separate arrays because that is the shape the prompt asks
    for, and separating them makes the model's intent explicit rather than inferred from whether
    a title happens to match. Both become the same kind of record here; the ratchet decides which
    is which by looking for an existing finding.
    """
    flattened: list[dict[str, Any]] = []
    for pillar_id, judgement in judgements.items():
        for raw in judgement.get("escalations") or []:
            if not isinstance(raw, dict):
                continue
            flattened.append({
                "pillar_id": pillar_id,
                "title": raw.get("finding_title") or raw.get("title") or "",
                "severity": raw.get("to_severity") or raw.get("severity"),
                "detail": raw.get("why") or raw.get("detail"),
                "detector": raw.get("detector"),
            })
        for raw in judgement.get("additional_findings") or []:
            if not isinstance(raw, dict):
                continue
            flattened.append({"pillar_id": pillar_id, **raw})
    return flattened


def _run_remediation(
    assessment_id: str,
    repository: str,
    architecture: str,
    merge_report: ratchet.MergeReport,
    judgements: dict[str, dict[str, Any]],
    evidence_hash: str,
    archetype: str,
) -> dict[str, Any]:
    prompt = prompts.get("remediation")
    findings_text = "\n".join(
        f"- **{str(f.severity).upper()}** [{f.pillar_id}"
        + (f"/{f.criterion}" if f.criterion else "")
        + f"] {f.title}"
        + (f" ({f.citation})" if f.citation else "")
        + f" — origin: {f.origin}"
        + (f"\n  {f.detail}" if f.detail else "")
        + (f"\n  Suggested fix from the standard: {f.remediation}" if f.remediation else "")
        for f in sorted(merge_report.findings, key=lambda f: -f.severity.rank)
    ) or "No findings."
    verdicts = "\n".join(
        f"- {pillar_id}: {j.get('verdict', 'unknown')} — {str(j.get('summary', ''))[:300]}"
        for pillar_id, j in judgements.items()
    )
    system, user = prompt.render(
        repository=repository,
        architecture=architecture,
        archetype=archetype or "not determined",
        findings=findings_text,
        judgements=verdicts,
    )
    data, _ = llm.complete_json(
        system, user,
        prompt_version=prompt.version,
        assessment_id=assessment_id,
        pass_name=PASS_REMEDIATION,
        evidence_digest=evidence_hash,
        require_keys=("steps",),
    )
    return data


def _run_open_questions(
    assessment_id: str,
    repository: str,
    architecture: str,
    judgements: dict[str, dict[str, Any]],
    evidence_hash: str,
) -> dict[str, Any]:
    prompt = prompts.get("open_questions")
    collected: list[str] = []
    for pillar_id, judgement in judgements.items():
        for question in judgement.get("open_questions") or []:
            collected.append(f"[{pillar_id}] {question}")
    undetermined = [
        f"[{pillar_id}/{c.get('id')}] {c.get('reasoning', '')}"
        for pillar_id, judgement in judgements.items()
        for c in judgement.get("criteria") or []
        if isinstance(c, dict) and c.get("outcome") == "undetermined"
    ]
    system, user = prompt.render(
        repository=repository,
        architecture=architecture,
        pillar_questions="\n".join(f"- {q}" for q in collected) or "None raised.",
        undetermined="\n".join(f"- {u}" for u in undetermined) or "None.",
    )
    data, _ = llm.complete_json(
        system, user,
        prompt_version=prompt.version,
        assessment_id=assessment_id,
        pass_name=PASS_OPEN_QUESTIONS,
        evidence_digest=evidence_hash,
        require_keys=("questions",),
    )
    return data


def summarize_for_api(assessment_id: str) -> dict[str, Any]:
    """Everything the assessment detail view needs, in one read.

    Assembled here rather than in the blueprint because the shape is dictated by what the pipeline
    produces, and keeping it next to the producer means a new pass shows up in the API without a
    second edit somewhere else.
    """
    assessment = repo.get_assessment(assessment_id)
    if assessment is None:
        return {}
    passes = repo.completed_passes(assessment_id)
    findings = repo.list_findings(assessment_id)
    return {
        "assessment": assessment.to_json(),
        "progress": (live_state(assessment_id) or RunState(assessment_id)).to_json(),
        "pass_states": repo.pass_states(assessment_id),
        "architecture": passes.get(PASS_ARCHITECTURE),
        "judgements": {
            name.split(":", 1)[1]: output
            for name, output in passes.items() if name.startswith("judgement:")
        },
        "remediation": passes.get(PASS_REMEDIATION),
        "open_questions": passes.get(PASS_OPEN_QUESTIONS),
        "findings": [f.to_json() for f in findings],
        "severity_counts": repo.severity_counts(assessment_id),
        "artifacts": repo.list_artifacts(assessment_id),
        "token_usage": repo.token_usage(assessment_id),
        "llm_calls": [c.to_json() for c in repo.list_llm_calls(assessment_id)],
    }


def _severity_from(value: str) -> Severity:
    return Severity(value)


def evidence_json(assessment_id: str) -> str | None:
    document = repo.get_evidence(assessment_id)
    return json.dumps(document, indent=2, default=str) if document else None
