# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The evidence document: everything the model is allowed to reason about.

Author: Rafael M. Koike & Cursor Agent ("Ada")

This module is the boundary. Whatever comes out of :func:`build` is exactly what the LLM sees, and
nothing else in the pipeline hands it repository content. That is deliberate: one place to audit
for redaction, one place to bound the size, one place to hash for provenance.

WHY IT IS BOUNDED, AND WHY THE BOUND IS VISIBLE
------------------------------------------------
Repositories do not fit in a context window and never will, so something must be dropped. The
question is whether the model knows it. An evidence document that silently drops half the facts
invites a confident judgement built on a third of the picture -- the model has no way to tell a
quiet pillar from a truncated one.

So every reduction is annotated. ``truncated: 340 more file writes not listed`` in the document is
the difference between the model saying "no backup mechanism exists" and "no backup mechanism
appears in the sampled evidence". The second is the true statement, and it is the one we can put in
front of a customer.

MAP-REDUCE, NOT SUMMARIZE-THE-SUMMARY
--------------------------------------
Reduction here is deterministic selection: rank facts by severity, keep the top N per pillar, keep
counts for the rest. It is not an LLM summarizing the evidence before another LLM judges it -- that
would put a lossy, unauditable, non-reproducible step between the scanners and the judgement, and
the whole point of the deterministic layer is that its output is the same every time.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from store.models import Severity

from factory import standards
from factory.acquire import Clone
from factory.llm import evidence_hash
from factory.scanners import Fact, RepoView, ScanReport

_logger = logging.getLogger("nvsf.factory.evidence")

#: Facts cited in full per pillar. Beyond this, the document keeps a count and a note.
#: Ten is enough to establish a pattern; the eleventh instance of the same finding adds nothing
#: to a judgement and costs context that a different pillar needs.
MAX_FACTS_PER_PILLAR = 10

#: Cap on the whole document, in characters. Roughly 40k tokens, which leaves room in a 128k
#: window for the standard, the prompt, and a substantial response.
MAX_DOCUMENT_CHARS = 160_000

#: Per-fact detail cap. A scanner that writes an essay gets trimmed rather than crowding others.
MAX_DETAIL_CHARS = 1_200

_SEVERITY_RANK = {
    Severity.BLOCKER: 0,
    Severity.MAJOR: 1,
    Severity.MINOR: 2,
    Severity.INFO: 3,
}


def _rank(fact: Fact) -> tuple[int, int, str]:
    """Sort key: findings before observations, worst first, then stable by key."""
    if fact.severity is None:
        return (1, 99, fact.key)
    return (0, _SEVERITY_RANK.get(fact.severity, 50), fact.key)


@dataclass
class Evidence:
    """The document, plus the provenance needed to reproduce the run that produced it."""

    repository: dict[str, Any]
    inventory: dict[str, Any]
    pillars: dict[str, Any]
    scan: dict[str, Any]
    standards_version: str
    #: Notes about what this document does *not* contain. Rendered prominently for the model.
    limits: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "inventory": self.inventory,
            "pillars": self.pillars,
            "scan": self.scan,
            "standards_version": self.standards_version,
            "limits": self.limits,
        }

    def hash(self) -> str:
        """Content address of the document. Ties a judgement to the exact input it saw.

        Scanner wall-clock timings are excluded. They are provenance worth keeping in the run
        record, but they differ between two runs over identical input, and a hash that changes
        when nothing about the evidence changed cannot answer "did the model see this exact
        input?" -- which is the only question it exists to answer.
        """
        payload = self.to_json()
        scan = dict(payload.get("scan") or {})
        scan.pop("durations_seconds", None)
        payload["scan"] = scan
        return evidence_hash(payload)

    def to_markdown(self) -> str:
        """Markdown rendering, which is what actually goes into the prompt.

        Markdown rather than JSON because models follow prose structure more reliably than nested
        objects, and because the same text can be shown to a human reviewing why the model said
        what it said. A judgement nobody can audit is not usable in front of a customer.
        """
        out: list[str] = []
        repo = self.repository
        out.append(f"# Evidence for {repo.get('name') or repo.get('url')}")
        out.append("")
        out.append(f"- Repository: `{repo.get('url')}`")
        out.append(f"- Commit: `{repo.get('commit_sha')}` on `{repo.get('ref')}`")
        out.append(f"- Standard version: `{self.standards_version}`")
        out.append("")

        if self.limits:
            out.append("## What this evidence does not cover")
            out.append("")
            out.append(
                "Read these before judging. A pillar with no findings below may be clean, or it "
                "may be one of these gaps. Say which, rather than assuming the first."
            )
            out.append("")
            for limit in self.limits:
                out.append(f"- {limit}")
            out.append("")

        out.append("## Repository shape")
        out.append("")
        for key, value in self.inventory.items():
            if isinstance(value, dict):
                rendered = ", ".join(f"{k} ({v})" for k, v in list(value.items())[:12]) or "none"
            elif isinstance(value, list):
                rendered = ", ".join(str(v) for v in value[:12]) or "none"
            else:
                rendered = str(value)
            out.append(f"- **{key.replace('_', ' ')}**: {rendered}")
        out.append("")

        out.append("## Findings and observations by pillar")
        out.append("")
        for pillar_id, block in self.pillars.items():
            title = block.get("title", pillar_id)
            out.append(f"### {title} (`{pillar_id}`)")
            out.append("")
            counts = block.get("counts", {})
            out.append(
                f"Deterministic findings: {counts.get('findings', 0)} "
                f"(blocker {counts.get('blocker', 0)}, major {counts.get('major', 0)}, "
                f"minor {counts.get('minor', 0)}). "
                f"Observations: {counts.get('observations', 0)}."
            )
            out.append("")

            if not block.get("facts"):
                out.append(
                    "_No facts were collected for this pillar. That is an absence of evidence, "
                    "not evidence of compliance._"
                )
                out.append("")
                continue

            for fact in block["facts"]:
                marker = (
                    f"**[{str(fact['severity']).upper()}]** " if fact.get("severity")
                    else "_(observation)_ "
                )
                citation = f" — `{fact['at']}`" if fact.get("at") else ""
                criterion = f" [{fact['criterion']}]" if fact.get("criterion") else ""
                out.append(f"- {marker}{fact['title']}{criterion}{citation}")
                if fact.get("detail"):
                    out.append(f"  - {fact['detail']}")
                if fact.get("excerpt"):
                    out.append("  - Excerpt (credentials already redacted):")
                    out.append("    ```")
                    for line in str(fact["excerpt"]).splitlines()[:8]:
                        out.append(f"    {line}")
                    out.append("    ```")
                if fact.get("data"):
                    compact = json.dumps(fact["data"], default=str)
                    if len(compact) > 600:
                        compact = compact[:600] + " …(trimmed)"
                    out.append(f"  - Data: `{compact}`")
            if block.get("truncated"):
                out.append(f"- _{block['truncated']}_")
            out.append("")

        if self.scan.get("failures"):
            out.append("## Scanners that failed")
            out.append("")
            out.append(
                "These pillars were not evaluated. Their absence of findings means nothing."
            )
            out.append("")
            for name, error in self.scan["failures"].items():
                out.append(f"- `{name}`: {error}")
            out.append("")

        return "\n".join(out)


def _fact_payload(fact: Fact) -> dict[str, Any]:
    payload = fact.to_json()
    detail = payload.get("detail")
    if isinstance(detail, str) and len(detail) > MAX_DETAIL_CHARS:
        payload["detail"] = detail[:MAX_DETAIL_CHARS] + " …(trimmed)"
    return payload


def _inventory(view: RepoView, clone: Clone) -> dict[str, Any]:
    """Cheap structural facts, useful to every pillar and worth stating once."""
    files = view.files()
    entry_points = [
        f for f in files
        if f.rsplit("/", 1)[-1] in {
            "main.py", "app.py", "__main__.py", "cli.py", "manage.py", "wsgi.py", "asgi.py",
            "index.js", "index.ts", "server.js", "server.ts", "main.go", "main.rs",
        }
    ]
    return {
        "file_count": len(files),
        "clone_bytes": clone.bytes,
        "languages": view.languages(),
        "top_level_entries": sorted({f.split("/", 1)[0] for f in files})[:30],
        "entry_points": entry_points[:12],
        "has_dockerfile": bool(view.find_names("Dockerfile", "Containerfile")),
        "has_compose": bool(view.find_names(
            "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")),
        "has_ci": bool([f for f in files if f.startswith((".gitlab-ci", ".github/workflows"))]),
        "has_tests": bool([f for f in files if "test" in f.lower()]),
        "readme_files": view.find_names("README.md", "README.rst", "README", "readme.md")[:3],
    }


def build(view: RepoView, clone: Clone, report: ScanReport, repository_url: str,
          name: str | None = None) -> Evidence:
    """Assemble the evidence document from a scan report.

    Deterministic: the same clone and the same scanners produce the same document, byte for byte,
    which is what makes ``Evidence.hash`` a meaningful provenance record rather than a timestamp.
    """
    loaded = standards.load()
    limits: list[str] = []

    if clone.truncated:
        limits.append(
            "The clone was truncated at the configured size limit, so some files were never "
            "read. Treat file counts as lower bounds."
        )
    if clone.submodules:
        limits.append(
            f"{len(clone.submodules)} submodule(s) were not cloned "
            f"({', '.join(clone.submodules[:5])}), so any code they contain was not scanned."
        )
    limits.append(
        "Only the checked-out tree at this commit was examined. Git history was not scanned, so a "
        "credential committed and later removed would not appear here."
    )
    limits.append(
        "Nothing in the repository was executed. Runtime behaviour, actual latency, and actual "
        "resource use are outside what this evidence can establish."
    )
    if report.failures:
        limits.append(
            f"{len(report.failures)} scanner(s) failed: {', '.join(report.failures)}. Those "
            "pillars have no evidence at all."
        )

    grouped = report.by_pillar()
    pillars: dict[str, Any] = {}

    # Iterate the standard rather than the scan results, so a pillar with no scanner output still
    # appears -- as an explicit empty block. Silence should be visible.
    for pillar in loaded.pillars:
        facts = sorted(grouped.get(pillar.id, []), key=_rank)
        findings = [f for f in facts if f.is_finding]
        kept = facts[:MAX_FACTS_PER_PILLAR]
        dropped = len(facts) - len(kept)

        pillars[pillar.id] = {
            "title": pillar.title,
            "severity_ceiling": str(pillar.severity_ceiling),
            "counts": {
                "facts": len(facts),
                "findings": len(findings),
                "observations": len(facts) - len(findings),
                "blocker": sum(1 for f in findings if f.severity == Severity.BLOCKER),
                "major": sum(1 for f in findings if f.severity == Severity.MAJOR),
                "minor": sum(1 for f in findings if f.severity == Severity.MINOR),
            },
            "facts": [_fact_payload(f) for f in kept],
            "truncated": (
                f"{dropped} further fact(s) for this pillar are not listed; they were ranked "
                "below the ones above by severity."
                if dropped > 0 else None
            ),
        }

    evidence = Evidence(
        repository={
            "url": repository_url,
            "name": name,
            "commit_sha": clone.commit_sha,
            "ref": clone.ref,
        },
        inventory=_inventory(view, clone),
        pillars=pillars,
        scan=report.to_json() | {"facts": None},  # facts live under pillars; do not duplicate
        standards_version=loaded.version,
        limits=limits,
    )

    rendered = evidence.to_markdown()
    if len(rendered) > MAX_DOCUMENT_CHARS:
        evidence = _shrink(evidence)
        _logger.info(
            "evidence: document was %d chars, shrank to %d",
            len(rendered), len(evidence.to_markdown()),
        )

    return evidence


def _shrink(evidence: Evidence) -> Evidence:
    """Drop excerpts and data blobs, then trim facts, until the document fits.

    Order matters and reflects what a judgement actually needs. An excerpt is a convenience -- the
    citation still points at the file and line. A dropped fact is information the model will never
    know it was missing, so facts go last and the drop is always announced.
    """
    for pillar in evidence.pillars.values():
        for fact in pillar["facts"]:
            fact.pop("excerpt", None)
    evidence.limits.append(
        "Code excerpts were removed to fit the context budget. Citations still name the file and "
        "line."
    )
    if len(evidence.to_markdown()) <= MAX_DOCUMENT_CHARS:
        return evidence

    for pillar in evidence.pillars.values():
        for fact in pillar["facts"]:
            fact.pop("data", None)
    evidence.limits.append("Structured data blocks were removed to fit the context budget.")
    if len(evidence.to_markdown()) <= MAX_DOCUMENT_CHARS:
        return evidence

    limit = MAX_FACTS_PER_PILLAR
    while limit > 2 and len(evidence.to_markdown()) > MAX_DOCUMENT_CHARS:
        limit -= 2
        for pillar in evidence.pillars.values():
            total = pillar["counts"]["facts"]
            pillar["facts"] = pillar["facts"][:limit]
            if total > limit:
                pillar["truncated"] = (
                    f"{total - limit} further fact(s) for this pillar are not listed (context "
                    "budget). They were ranked below the ones above by severity."
                )
    return evidence
