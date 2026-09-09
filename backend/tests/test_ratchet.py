# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The ratchet: escalation allowed, downgrade refused, always on the record.

Author: Rafael M. Koike & Cursor Agent ("Ada")

These tests are the specification for the property that makes an AI-first assessment defensible.
Every plausible way a model might try to soften a deterministic finding is enumerated here, and
each one is asserted to leave the severity where the scanner put it.

They deliberately do not call the LLM. The model's output shape is the input to these tests, so
the interesting cases are the awkward ones — a paraphrased title, an invented severity word, a
pillar that does not exist — and those are easier to write by hand than to elicit.
"""

from __future__ import annotations

import pytest
from factory.ratchet import RatchetViolation, merge, verify
from factory.scanners import Fact
from store.models import Origin, Severity

ASSESSMENT = "assess-0001"
PILLARS = {"durability", "data-security", "reliability", "scalability"}


def _blocker(key: str = "container_without_volume") -> Fact:
    return Fact(
        pillar_id="durability", key=key,
        title="Containerized, and no volume or mount is declared anywhere",
        detail="No volumes: key anywhere in the compose file.",
        criterion="D1", severity=Severity.BLOCKER,
        file_path="docker-compose.yml", line_start=1,
        remediation="Bind-mount a host path.",
    )


def _minor(key: str = "named_volume_only") -> Fact:
    return Fact(
        pillar_id="durability", key=key,
        title="State is on a named Docker volume rather than a bind mount",
        detail="A named volume survives a container restart but not `docker volume prune`.",
        criterion="D1", severity=Severity.MINOR,
    )


# ── Downgrades ───────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("proposed", ["major", "minor", "info"])
def test_a_proposed_downgrade_never_lands(proposed):
    report = merge(
        facts=[_blocker()],
        model_findings=[{
            "pillar_id": "durability",
            "title": "Containerized, and no volume or mount is declared anywhere",
            "severity": proposed,
            "detail": "This is an internal prototype, so the data is not critical.",
        }],
        assessment_id=ASSESSMENT,
        valid_pillars=PILLARS,
    )

    assert len(report.findings) == 1
    assert report.findings[0].severity is Severity.BLOCKER
    assert report.findings[0].origin is Origin.SCANNER
    assert len(report.refused_downgrades) == 1
    # The attempt and its reasoning are kept, so a reviewer can decide whether the scanner is
    # wrong -- which is a code change, not a per-run override.
    assert "internal prototype" in report.refused_downgrades[0]["model_reason"]


def test_a_paraphrased_title_still_matches_the_finding_it_is_about():
    """The model does not always echo titles exactly, and a near-miss must not become a new finding.

    If matching were exact-only, a paraphrase would fall through to the additions path and the
    report would show the blocker twice — once as measured and once as the model's softer version,
    which reads as disagreement rather than as a refused downgrade.
    """
    report = merge(
        facts=[_blocker()],
        model_findings=[{
            "pillar_id": "durability",
            "title": "Containerized and no volume or mount is declared anywhere.",
            "severity": "minor",
        }],
        assessment_id=ASSESSMENT,
        valid_pillars=PILLARS,
    )
    assert len(report.findings) == 1
    assert report.findings[0].severity is Severity.BLOCKER
    assert report.model_additions == 0


def test_matching_by_detector_key_when_the_title_diverges():
    report = merge(
        facts=[_blocker()],
        model_findings=[{
            "pillar_id": "durability",
            "detector": "container_without_volume",
            "title": "Something completely different",
            "severity": "info",
        }],
        assessment_id=ASSESSMENT,
        valid_pillars=PILLARS,
    )
    assert report.findings[0].severity is Severity.BLOCKER
    assert len(report.refused_downgrades) == 1


def test_a_finding_cannot_be_dropped_by_omission():
    """Saying nothing about a finding must leave it in place, unchanged."""
    report = merge(
        facts=[_blocker(), _minor()],
        model_findings=[],
        assessment_id=ASSESSMENT,
        valid_pillars=PILLARS,
    )
    assert len(report.findings) == 2
    assert {f.severity for f in report.findings} == {Severity.BLOCKER, Severity.MINOR}


def test_matching_never_crosses_pillars():
    """A model comment attributed to the wrong pillar must not touch another pillar's finding.

    This is the mistake worth being strict about: reasoning about backups attached to a finding
    about TLS produces a report that is wrong in a way that reads as authoritative.
    """
    report = merge(
        facts=[_blocker()],
        model_findings=[{
            "pillar_id": "data-security",
            "title": "Containerized, and no volume or mount is declared anywhere",
            "severity": "minor",
        }],
        assessment_id=ASSESSMENT,
        valid_pillars=PILLARS,
    )
    durability = [f for f in report.findings if f.pillar_id == "durability"]
    assert durability[0].severity is Severity.BLOCKER
    assert not report.refused_downgrades
    # It became a new data-security finding instead, labelled as the model's.
    assert report.model_additions == 1


def test_strict_mode_raises_so_the_property_can_be_asserted():
    with pytest.raises(RatchetViolation, match="lowering"):
        merge(
            facts=[_blocker()],
            model_findings=[{
                "pillar_id": "durability",
                "title": "Containerized, and no volume or mount is declared anywhere",
                "severity": "minor",
            }],
            assessment_id=ASSESSMENT,
            valid_pillars=PILLARS,
            strict=True,
        )


# ── Escalations ──────────────────────────────────────────────────────────────────────────────


def test_an_escalation_lands_and_records_where_it_came_from():
    report = merge(
        facts=[_minor()],
        model_findings=[{
            "pillar_id": "durability",
            "title": "State is on a named Docker volume rather than a bind mount",
            "severity": "blocker",
            "detail": "This volume holds the only copy of the validation record for a customer "
                      "acceptance, so losing it is a contractual problem, not an inconvenience.",
        }],
        assessment_id=ASSESSMENT,
        valid_pillars=PILLARS,
    )

    finding = report.findings[0]
    assert finding.severity is Severity.BLOCKER
    assert finding.escalated_from is Severity.MINOR
    # Still attributed to the scanner: the measurement is the scanner's, the severity is reviewed.
    assert finding.origin is Origin.SCANNER
    assert len(report.escalations) == 1
    # Both voices survive, rather than the model's detail replacing the scanner's. A reviewer
    # needs to see what was measured and what was concluded from it, separately.
    assert "docker volume prune" in (finding.detail or "")
    assert "Raised in review" in (finding.detail or "")
    assert "contractual" in (finding.detail or "")


def test_an_equal_severity_is_neither_an_escalation_nor_a_refusal():
    report = merge(
        facts=[_blocker()],
        model_findings=[{
            "pillar_id": "durability",
            "title": "Containerized, and no volume or mount is declared anywhere",
            "severity": "blocker",
            "detail": "Agreed.",
        }],
        assessment_id=ASSESSMENT,
        valid_pillars=PILLARS,
    )
    assert not report.escalations
    assert not report.refused_downgrades
    assert report.findings[0].severity is Severity.BLOCKER


def test_a_severity_ceiling_caps_the_model_but_not_the_scanner():
    """The prompt promises the ceiling is enforced in code, so it has to be."""
    report = merge(
        facts=[
            Fact(pillar_id="scalability", key="scanner_says_major",
                 title="Sequential fan-out", severity=Severity.MAJOR),
        ],
        model_findings=[{
            "pillar_id": "scalability",
            "title": "A brand new scalability concern",
            "severity": "blocker",
        }],
        assessment_id=ASSESSMENT,
        valid_pillars=PILLARS,
        ceilings={"scalability": Severity.MAJOR},
    )

    addition = next(f for f in report.findings if f.origin is Origin.MODEL)
    assert addition.severity is Severity.MAJOR
    assert len(report.clamped_to_ceiling) == 1
    # The scanner's own severity is untouched by the ceiling.
    scanner = next(f for f in report.findings if f.origin is Origin.SCANNER)
    assert scanner.severity is Severity.MAJOR


# ── Model additions ──────────────────────────────────────────────────────────────────────────


def test_a_genuinely_new_finding_is_added_and_labelled_as_judgement():
    report = merge(
        facts=[],
        model_findings=[{
            "pillar_id": "reliability",
            "severity": "major",
            "title": "A partially applied firmware update leaves the fleet in mixed state",
            "detail": "The loop has no record of which nodes succeeded.",
            "file_path": "update.py",
            "line_start": 40,
            "remediation": "Write a per-node result before moving on.",
        }],
        assessment_id=ASSESSMENT,
        valid_pillars=PILLARS,
    )
    finding = report.findings[0]
    assert finding.origin is Origin.MODEL
    assert finding.severity is Severity.MAJOR
    assert finding.citation == "update.py:40"
    assert report.model_additions == 1


def test_scanner_findings_come_before_model_findings():
    """Persisted order itself shows the provenance boundary."""
    report = merge(
        facts=[_blocker(), _minor()],
        model_findings=[
            {"pillar_id": "reliability", "severity": "minor", "title": "Model thought one"},
            {"pillar_id": "reliability", "severity": "minor", "title": "Model thought two"},
        ],
        assessment_id=ASSESSMENT,
        valid_pillars=PILLARS,
    )
    origins = [f.origin for f in report.findings]
    assert origins == [Origin.SCANNER, Origin.SCANNER, Origin.MODEL, Origin.MODEL]


# ── Malformed model output ───────────────────────────────────────────────────────────────────


def test_an_invented_pillar_is_discarded_with_a_reason():
    report = merge(
        facts=[],
        model_findings=[
            {"pillar_id": "code-elegance", "severity": "major", "title": "Naming is inconsistent"},
        ],
        assessment_id=ASSESSMENT,
        valid_pillars=PILLARS,
    )
    assert report.findings == []
    assert report.rejected_malformed[0]["reason"] == "unknown pillar"


@pytest.mark.parametrize(("given", "expected"), [
    ("BLOCKER", Severity.BLOCKER),
    ("Blocker", Severity.BLOCKER),
    ("  major ", Severity.MAJOR),
    ("critical", Severity.BLOCKER),
    ("high", Severity.MAJOR),
    ("medium", Severity.MINOR),
    ("low", Severity.INFO),
])
def test_severity_spellings_the_model_actually_produces_are_understood(given, expected):
    """Casing and near-synonyms are normalized; rejecting them would discard real signal."""
    report = merge(
        facts=[],
        model_findings=[{"pillar_id": "reliability", "severity": given, "title": "Something"}],
        assessment_id=ASSESSMENT,
        valid_pillars=PILLARS,
    )
    assert report.findings[0].severity is expected


def test_an_unparseable_severity_is_discarded_rather_than_guessed():
    report = merge(
        facts=[],
        model_findings=[
            {"pillar_id": "reliability", "severity": "somewhat concerning", "title": "Hmm"},
            {"pillar_id": "reliability", "title": "No severity at all"},
        ],
        assessment_id=ASSESSMENT,
        valid_pillars=PILLARS,
    )
    assert report.findings == []
    assert len(report.rejected_malformed) == 2


def test_junk_in_the_findings_array_does_not_break_the_merge():
    report = merge(
        facts=[_blocker()],
        model_findings=["a bare string", None, 42, {"pillar_id": "durability"}],
        assessment_id=ASSESSMENT,
        valid_pillars=PILLARS,
    )
    assert len(report.findings) == 1
    assert report.findings[0].severity is Severity.BLOCKER
    assert len(report.rejected_malformed) == 4


# ── The invariant check ──────────────────────────────────────────────────────────────────────


def test_verify_accepts_a_correct_merge():
    facts = [_blocker(), _minor()]
    report = merge(facts, [], ASSESSMENT, PILLARS)
    assert verify(report.findings, facts) == []


def test_verify_catches_a_lowered_finding():
    """Guards against a future refactor breaking the ratchet quietly."""
    facts = [_blocker()]
    report = merge(facts, [], ASSESSMENT, PILLARS)
    tampered = [
        type(report.findings[0])(**{
            **report.findings[0].__dict__, "severity": Severity.MINOR,
        })
    ]
    problems = verify(tampered, facts)
    assert problems
    assert "lowered" in problems[0]


def test_verify_catches_a_missing_finding():
    facts = [_blocker(), _minor()]
    report = merge(facts, [], ASSESSMENT, PILLARS)
    problems = verify(report.findings[:1], facts)
    assert any("missing" in p for p in problems)


def test_observations_are_not_findings():
    """A fact with no severity is evidence for the model, not a finding in the report."""
    observation = Fact(
        pillar_id="durability", key="persistence_inventory",
        title="No database or persistence library found",
    )
    report = merge([observation], [], ASSESSMENT, PILLARS)
    assert report.findings == []
