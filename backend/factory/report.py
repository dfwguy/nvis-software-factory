# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The deliverable: a Markdown bundle for a human, and one for their coding agent.

Author: Rafael M. Koike & Cursor Agent ("Ada")

The web UI shows the assessment, but the artifact is what leaves the building. An SA drops
``AGENT_PLAN.md`` into their repository, points Cursor or Claude at it, and gets work done. That
is the actual delivery mechanism for everything upstream of here, and it shapes two decisions:

**Two documents, not one.** ``ASSESSMENT.md`` is written for a person deciding what to do:
verdicts, reasoning, what we could not tell. ``AGENT_PLAN.md`` is written for a model that will
edit code: imperative, ordered, one concern per step, acceptance criteria that can be checked. The
same content in one document serves neither reader — the human wades through file paths, and the
agent hedges because the prose hedges.

**Provenance travels with the artifact.** Every bundle carries the commit it assessed, the standard
version, the model, the prompt versions, and the evidence hash. Six weeks later, when someone asks
whether a finding still applies, that footer is the difference between re-reading and re-running.

WHAT IS DELIBERATELY NOT HERE
------------------------------
No score, no grade, no percentage. A repository is not 73% good. A number invites comparison
between unlike tools and gets quoted without its findings; the severity counts already say what a
grade would, without implying a precision we do not have.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Any

from paths import artifacts_dir
from store import repo
from store.models import Finding, Origin, Severity

if TYPE_CHECKING:
    from store.models import Repository

    from factory.acquire import Clone
    from factory.evidence import Evidence
    from factory.ratchet import MergeReport

_logger = logging.getLogger("nvsf.factory.report")

_VERDICT_LABEL = {
    "pass": "Meets the standard",
    "concerns": "Meets it with concerns",
    "fail": "Does not meet the standard",
    "undetermined": "Could not be determined",
}

_SEVERITY_ORDER = (Severity.BLOCKER, Severity.MAJOR, Severity.MINOR, Severity.INFO)


def _by_severity(findings: list[Finding]) -> dict[Severity, list[Finding]]:
    grouped: dict[Severity, list[Finding]] = {s: [] for s in _SEVERITY_ORDER}
    for finding in findings:
        grouped[finding.severity].append(finding)
    return grouped


def _headline(findings: list[Finding], judgements: dict[str, Any]) -> str:
    """One sentence at the top. Written for someone who will read only this.

    Leads with the worst thing rather than a count, because "3 blockers" tells a reader to brace
    and nothing else, whereas naming the blocker tells them whether to act today.
    """
    grouped = _by_severity(findings)
    blockers = grouped[Severity.BLOCKER]
    majors = grouped[Severity.MAJOR]

    if blockers:
        first = blockers[0]
        rest = (
            f" There {'is' if len(blockers) == 2 else 'are'} {len(blockers) - 1} other blocker"
            f"{'s' if len(blockers) > 2 else ''}."
            if len(blockers) > 1 else ""
        )
        return (
            f"**{first.title}**"
            + (f" ({first.citation})" if first.citation else "")
            + f". That is a blocker: it means data loss, a credential exposure, or an "
            f"unauthenticated path to changing state.{rest}"
        )
    if majors:
        return (
            f"No blockers. The most significant issue is **{majors[0].title}**"
            + (f" ({majors[0].citation})" if majors[0].citation else "")
            + f", one of {len(majors)} major finding(s)."
        )
    if findings:
        return (
            f"No blockers or major findings. {len(findings)} smaller item(s) are listed below."
        )
    undetermined = sum(
        1 for j in judgements.values() if j.get("verdict") == "undetermined"
    )
    if undetermined:
        return (
            f"No findings, but {undetermined} pillar(s) could not be determined from the "
            "repository alone. See the open questions before concluding this is clean."
        )
    return "No findings against the current standard."


def render_assessment(
    repository: Repository,
    assessment_id: str,
    clone: Clone,
    evidence: Evidence,
    architecture: dict[str, Any],
    judgements: dict[str, dict[str, Any]],
    findings: list[Finding],
    merge_report: MergeReport,
    open_questions: dict[str, Any],
    standards_version: str,
) -> str:
    """The human-facing report."""
    from factory import standards

    loaded = standards.load()
    grouped = _by_severity(findings)
    out: list[str] = []

    label = f"{repository.namespace or ''}/{repository.name}".strip("/")
    out += [
        f"# Software Factory assessment — {label}",
        "",
        _headline(findings, judgements),
        "",
        "| | |",
        "|---|---|",
        f"| Repository | `{repository.canonical_url}` |",
        f"| Commit | `{clone.commit_sha}` on `{clone.ref}` |",
        f"| Standard | `{standards_version}` |",
        "| Findings | "
        + ", ".join(
            f"{len(grouped[s])} {s}" for s in _SEVERITY_ORDER if grouped[s]
        ) + (" |" if any(grouped.values()) else "none |"),
        "",
    ]

    # ── What this is and is not ──────────────────────────────────────────────────────────────
    out += [
        "## How to read this",
        "",
        (
            "Findings are marked by origin. **Scanner** findings were established by code that "
            "read the repository — they are measurements, and the language model that reviewed "
            "them could raise their severity but not lower it. **Review** findings are the "
            "model's judgement against the written standard; they are reasoned and cited, and "
            "they are opinions."
        ),
        "",
        (
            "There is no score. A number would get quoted without its findings, and it would "
            "imply a precision this does not have."
        ),
        "",
    ]

    if evidence.limits:
        out += ["### What was not examined", ""]
        out += [f"- {limit}" for limit in evidence.limits]
        out += [""]

    # ── Architecture ─────────────────────────────────────────────────────────────────────────
    out += ["## What this software does", ""]
    out += [str(architecture.get("summary", "")).strip() or "_Not determined._", ""]
    for key, heading in (
        ("archetype", "Archetype"),
        ("purpose", "Purpose"),
        ("data_flow", "Data flow"),
        ("state_management", "State"),
        ("external_dependencies", "External dependencies"),
        ("entry_points", "Entry points"),
    ):
        value = architecture.get(key)
        if not value:
            continue
        rendered = (
            "\n".join(f"  - {v}" for v in value) if isinstance(value, list) else f" {value}"
        )
        out += [f"- **{heading}**:" + ("\n" + rendered if isinstance(value, list) else rendered)]
    out += [""]

    if architecture.get("uncertainties"):
        out += ["**The model was unsure about:**", ""]
        out += [f"- {u}" for u in architecture["uncertainties"]]
        out += [""]

    # ── Findings, worst first ────────────────────────────────────────────────────────────────
    out += ["## Findings", ""]
    if not findings:
        out += ["No findings.", ""]
    for severity in _SEVERITY_ORDER:
        bucket = grouped[severity]
        if not bucket:
            continue
        out += [f"### {str(severity).capitalize()} ({len(bucket)})", ""]
        for finding in bucket:
            origin = "scanner" if finding.origin is Origin.SCANNER else "review"
            pillar = next((p.title for p in loaded.pillars if p.id == finding.pillar_id),
                          finding.pillar_id)
            out += [f"#### {finding.title}", ""]
            meta = [f"_{pillar}_", f"origin: {origin}"]
            if finding.criterion:
                meta.append(f"criterion: `{finding.criterion}`")
            if finding.citation:
                meta.append(f"at `{finding.citation}`")
            if finding.escalated_from:
                meta.append(
                    f"raised from `{finding.escalated_from}` in review"
                )
            out += [" · ".join(meta), ""]
            if finding.detail:
                out += [finding.detail, ""]
            if finding.remediation:
                out += ["**Fix:** " + finding.remediation, ""]

    # ── Per-pillar verdicts ──────────────────────────────────────────────────────────────────
    out += ["## Pillar by pillar", ""]
    for pillar in loaded.pillars:
        judgement = judgements.get(pillar.id) or {}
        verdict = str(judgement.get("verdict", "undetermined"))
        out += [
            f"### {pillar.title} — {_VERDICT_LABEL.get(verdict, verdict)}",
            "",
            str(judgement.get("summary", "")).strip() or "_No judgement recorded._",
            "",
        ]
        criteria = judgement.get("criteria") or []
        if criteria:
            out += ["| Criterion | Outcome | Reasoning | Evidence |", "|---|---|---|---|"]
            for criterion in criteria:
                if not isinstance(criterion, dict):
                    continue
                out.append(
                    f"| `{criterion.get('id', '?')}` "
                    f"| {criterion.get('outcome', '?')} "
                    f"| {_cell(criterion.get('reasoning'))} "
                    f"| {_cell(criterion.get('evidence'))} |"
                )
            out += [""]

    # ── Open questions ───────────────────────────────────────────────────────────────────────
    questions = open_questions.get("questions") or []
    out += ["## Open questions", ""]
    if not questions:
        out += ["None.", ""]
    else:
        out += [
            (
                "These are the things the repository cannot answer on its own. Each one would "
                "change part of the assessment above."
            ),
            "",
        ]
        for question in questions:
            if isinstance(question, dict):
                text = question.get("question") or question.get("text") or ""
                why = question.get("why") or question.get("impact") or ""
                out += [f"- **{text}**" + (f"\n  - Why it matters: {why}" if why else "")]
            else:
                out += [f"- {question}"]
        out += [""]

    # ── Provenance ───────────────────────────────────────────────────────────────────────────
    out += _provenance_section(assessment_id, evidence, merge_report, standards_version)
    return "\n".join(out) + "\n"


def _cell(value: Any) -> str:
    """Markdown table cells cannot contain pipes or newlines."""
    text = str(value or "").replace("|", "\\|").replace("\n", " ").strip()
    return text[:300] or "—"


def _provenance_section(
    assessment_id: str,
    evidence: Evidence,
    merge_report: MergeReport,
    standards_version: str,
) -> list[str]:
    calls = repo.list_llm_calls(assessment_id)
    usage = repo.token_usage(assessment_id)
    models = sorted({c.model for c in calls})
    prompt_versions = sorted({c.prompt_version for c in calls})

    out = [
        "## Provenance",
        "",
        "Everything needed to reproduce or re-examine this run.",
        "",
        f"- Assessment: `{assessment_id}`",
        f"- Evidence hash: `{evidence.hash()}`",
        f"- Standard version: `{standards_version}`",
        f"- Model(s): {', '.join(f'`{m}`' for m in models) or 'none recorded'}",
        f"- Prompt versions: {', '.join(f'`{v}`' for v in prompt_versions) or 'none recorded'}",
        (
            f"- Model calls: {len(calls)} "
            f"({sum(1 for c in calls if c.status != 'ok')} failed attempt(s))"
        ),
        (
            f"- Tokens: {usage.get('prompt_tokens', 0)} in, "
            f"{usage.get('completion_tokens', 0)} out"
        ),
        "",
    ]

    counts = merge_report.to_json()["counts"]
    out += [
        "### What the review changed",
        "",
        f"- Deterministic findings from scanners: {counts['from_scanner']}",
        f"- Findings added by the model: {counts['from_model']}",
        f"- Severities the model raised: {counts['escalated']}",
        f"- Downgrades refused by the ratchet: {counts['refused_downgrades']}",
        "",
    ]

    if merge_report.escalations:
        out += ["**Escalations:**", ""]
        for escalation in merge_report.escalations:
            out.append(
                f"- `{escalation['detector']}`: {escalation['from']} → {escalation['to']} — "
                f"{escalation['reason']}"
            )
        out += [""]

    if merge_report.refused_downgrades:
        out += [
            (
                "**Downgrades the model proposed and the ratchet refused.** These are recorded "
                "rather than hidden: if one of them is a genuine false positive, the fix is to "
                "change the scanner, which is a code review, not a per-run decision."
            ),
            "",
        ]
        for refusal in merge_report.refused_downgrades:
            out.append(
                f"- `{refusal['detector']}`: kept at {refusal['kept']}, model proposed "
                f"{refusal['model_proposed']} — {refusal['model_reason']}"
            )
        out += [""]

    if merge_report.rejected_malformed:
        out += [
            (
                f"**{len(merge_report.rejected_malformed)} model finding(s) were discarded** as "
                "malformed (unknown pillar, missing title, or unparseable severity)."
            ),
            "",
        ]

    return out


def render_agent_plan(
    repository: Repository,
    clone: Clone,
    remediation: dict[str, Any],
    findings: list[Finding],
    open_questions: dict[str, Any],
    standards_version: str,
) -> str:
    """The document an SA hands to their coding agent.

    Written as instructions to a model that will edit this repository, which is why it opens with
    constraints rather than context. An agent given a list of problems and no boundaries will
    refactor the whole tree; the framing here is "make these specific changes, one commit each,
    stop and ask where the answer is not in the repository".
    """
    label = f"{repository.namespace or ''}/{repository.name}".strip("/")
    grouped = _by_severity(findings)
    out: list[str] = [
        f"# Action plan — {label}",
        "",
        (
            "You are working in this repository. This plan came from an automated assessment "
            f"against the NVIS software quality standard (`{standards_version}`) at commit "
            f"`{clone.commit_sha[:12]}`."
        ),
        "",
        "## How to work through this",
        "",
        (
            "1. **One step, one commit.** Do not batch steps. Each has its own acceptance check, "
            "and a reviewer needs to be able to revert one without unpicking the others."
        ),
        (
            "2. **Do not refactor beyond the step.** Renaming, reformatting, or restructuring "
            "code the step does not mention makes the diff unreviewable and hides the actual "
            "change."
        ),
        (
            "3. **Add a test with each behavioural change.** A durability fix with no test "
            "proving the data survives a restart is a claim, not a fix."
        ),
        (
            "4. **Stop and ask** where a step depends on something not in the repository — a "
            "deployment detail, an owner decision, an environment fact. The open questions at "
            "the end list the ones already identified. Guessing produces a plausible change that "
            "is wrong in a way nobody notices."
        ),
        (
            "5. **Do not change severity judgements or delete the findings file.** If you believe "
            "a finding is wrong, say so in your summary and leave it."
        ),
        "",
    ]

    # The model writes this specifically to be pasted at the top of an agent session: what the
    # repository is and what an agent must respect while changing it. The template has always
    # produced it and nothing rendered it, so it was paid for on every run and thrown away.
    posture = str(remediation.get("posture") or "").strip()
    posture_reason = str(remediation.get("posture_reason") or "").strip()
    if posture:
        out += [
            "## Posture",
            "",
            f"**{posture}**" + (f" — {posture_reason}" if posture_reason else ""),
            "",
        ]

    preamble = str(remediation.get("agent_preamble") or "").strip()
    if preamble:
        out += ["## Context for the agent", "", preamble, ""]

    if grouped[Severity.BLOCKER]:
        out += [
            "## Do these first",
            "",
            (
                "Each of these means data loss, credential exposure, or an unauthenticated path "
                "to changing state. Nothing else in this plan matters as much."
            ),
            "",
        ]
        for finding in grouped[Severity.BLOCKER]:
            out += [
                f"- **{finding.title}**"
                + (f" — `{finding.citation}`" if finding.citation else ""),
            ]
            if finding.remediation:
                out += [f"  - {finding.remediation}"]
        out += [""]

    # `prompts/remediation.md` buckets work by urgency rather than returning one flat list, and
    # the bucket is information: it tells the agent what has to land before anyone else depends on
    # this repository. Numbering runs across the buckets so "one step, one commit" above still
    # refers to something unambiguous.
    buckets: list[tuple[str, str, list[Any]]] = [
        ("Do first", "Before anyone else depends on this.", remediation.get("immediate") or []),
        ("Do next", "Once the immediate items are done.", remediation.get("next") or []),
        ("Later", "Worth doing, not urgent.", remediation.get("later") or []),
    ]

    if not any(items for _, _, items in buckets):
        out += ["## Steps", "", "_No remediation steps were produced._", ""]

    index = 0
    for heading, blurb, items in buckets:
        if not items:
            continue
        out += [f"## {heading}", "", blurb, ""]
        for step in items:
            index += 1
            if not isinstance(step, dict):
                out += [f"### Step {index}", "", str(step), ""]
                continue

            title = step.get("title") or step.get("action") or f"Step {index}"
            effort = step.get("effort")
            out += [f"### Step {index}. {title}" + (f" _({effort})_" if effort else ""), ""]

            for key, label in (
                ("why", "Why"),
                ("where", "Where"),
                ("what_to_do", "What to change"),
                ("verify", "Done when"),
                ("risk", "Risk"),
            ):
                value = step.get(key)
                if not value:
                    continue
                if isinstance(value, list):
                    out += [f"**{label}:**", ""]
                    out += [f"- {item}" for item in value]
                    out += [""]
                else:
                    out += [f"**{label}:** {value}", ""]

            related = step.get("addresses") or step.get("findings") or []
            if related:
                out += ["**Addresses:** " + ", ".join(f"`{r}`" for r in related if r), ""]

    # Named wrong turns. An agent handed a list of problems will reach for the obvious fix, and
    # the obvious fix is sometimes the one this repository specifically cannot take.
    do_not_do = remediation.get("do_not_do") or []
    if do_not_do:
        out += ["## Do not do these", ""]
        for item in do_not_do:
            if isinstance(item, dict):
                suggestion = item.get("suggestion") or ""
                why_not = item.get("why_not") or ""
                out += [f"- **{suggestion}** — {why_not}" if why_not else f"- **{suggestion}**"]
            else:
                out += [f"- {item}"]
        out += [""]

    questions = open_questions.get("questions") or []
    if questions:
        out += [
            "## Ask before implementing",
            "",
            (
                "These have no answer in the repository. Where a step depends on one, stop and "
                "ask rather than choosing for the owner."
            ),
            "",
        ]
        for question in questions:
            text = (
                question.get("question") or question.get("text") or ""
                if isinstance(question, dict) else str(question)
            )
            out += [f"- {text}"]
        out += [""]

    out += [
        "## All findings, for reference",
        "",
        "| Severity | Pillar | Finding | Where | Origin |",
        "|---|---|---|---|---|",
    ]
    for severity in _SEVERITY_ORDER:
        for finding in grouped[severity]:
            out.append(
                f"| {severity} | {finding.pillar_id} | {_cell(finding.title)} "
                f"| {f'`{finding.citation}`' if finding.citation else '—'} "
                f"| {'scanner' if finding.origin is Origin.SCANNER else 'review'} |"
            )
    out += [""]
    return "\n".join(out) + "\n"


def render_bundle(
    assessment_id: str,
    repository: Repository,
    clone: Clone,
    evidence: Evidence,
    architecture: dict[str, Any],
    judgements: dict[str, dict[str, Any]],
    findings: list[Finding],
    merge_report: MergeReport,
    remediation: dict[str, Any],
    open_questions: dict[str, Any],
    standards_version: str,
) -> list[str]:
    """Write every artifact to the durable volume and record it. Returns the names written.

    Artifacts go to disk rather than being rendered on request because they are the deliverable:
    an SA who downloaded a plan and acted on it must be able to get the identical bytes back, even
    after the standard or the renderer has changed. Re-rendering on demand would quietly hand them
    a different document.
    """
    directory = artifacts_dir() / assessment_id
    directory.mkdir(parents=True, exist_ok=True)

    documents = {
        "ASSESSMENT.md": render_assessment(
            repository, assessment_id, clone, evidence, architecture, judgements, findings,
            merge_report, open_questions, standards_version,
        ),
        "AGENT_PLAN.md": render_agent_plan(
            repository, clone, remediation, findings, open_questions, standards_version,
        ),
        "EVIDENCE.md": evidence.to_markdown(),
        "evidence.json": json.dumps(evidence.to_json(), indent=2, default=str),
        "findings.json": json.dumps(
            [f.to_json() for f in findings], indent=2, default=str,
        ),
    }

    written: list[str] = []
    for name, content in documents.items():
        path = directory / name
        encoded = content.encode("utf-8")
        # Atomic replace, for the same reason the durability pillar asks other people's code to do
        # it: a crash mid-write should leave the previous artifact, not a truncated one.
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(encoded)
        temporary.replace(path)
        # The digest is what makes "is this the document I downloaded last month" answerable
        # without keeping a copy to compare against.
        repo.record_artifact(
            assessment_id=assessment_id,
            kind=name,
            filename=name,
            size=len(encoded),
            sha256=hashlib.sha256(encoded).hexdigest(),
        )
        written.append(name)

    _logger.info("report: wrote %d artifact(s) for %s", len(written), assessment_id)
    return written


def artifact_path(assessment_id: str, name: str):
    """Resolve an artifact by name, refusing anything that escapes the directory.

    The name comes from a URL, so traversal is the obvious attack. Resolving and then checking
    containment handles ``..``, absolute paths, and symlinks in one check.
    """
    base = (artifacts_dir() / assessment_id).resolve()
    candidate = (base / name).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        _logger.warning("report: refused artifact path outside the bundle: %r", name)
        return None
    return candidate if candidate.is_file() else None
