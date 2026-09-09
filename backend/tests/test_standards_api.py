# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The published baseline is the same baseline the prompts use.

Author: Rafael M. Koike & Cursor Agent ("Ada")

The risk this file exists for: the website publishing one version of "what good looks like" while
assessments judge against another. An SA who fixes what the site told them to fix and then gets a
finding for it has been actively misled, which is worse than not publishing the baseline at all.
"""

from __future__ import annotations


def test_the_published_baseline_is_the_one_the_prompts_use(app_client):
    """Same version string, same pillar ids, same criteria -- because it is the same loader."""
    from factory import standards

    body = app_client.get("/api/standards/").get_json()
    loaded = standards.load()

    assert body["version"] == loaded.version
    assert [p["id"] for p in body["pillars"]] == list(loaded.ids)

    for published, pillar in zip(body["pillars"], loaded.pillars, strict=True):
        assert [c["id"] for c in published["criteria"]] == [c.id for c in pillar.criteria]


def test_the_baseline_is_ordered_the_way_it_is_meant_to_be_read(app_client):
    """Pillars carry an explicit order, and the API honours it.

    Durability first is deliberate: it is the pillar the initiative exists for. Alphabetical
    order would put contract-conformance first, which buries the point.
    """
    pillars = app_client.get("/api/standards/").get_json()["pillars"]

    assert [p["order"] for p in pillars] == sorted(p["order"] for p in pillars)
    assert pillars[0]["id"] == "durability"


def test_every_criterion_says_whether_it_was_measured_or_judged(app_client):
    """A reader has to be able to tell a scanner result from a model opinion.

    Without it the whole report reads at one confidence level, and the level a reader picks will
    be either too high for the judgements or too low for the facts.
    """
    for pillar in app_client.get("/api/standards/").get_json()["pillars"]:
        for criterion in pillar["criteria"]:
            assert criterion["detector"] in {"yes", "partial", "no"}
            assert criterion["judgement_only"] == (criterion["detector"] == "no")
            assert criterion["title"], f"{pillar['id']}/{criterion['id']} has no title"
            assert criterion["body"].strip(), f"{pillar['id']}/{criterion['id']} has no body"


def test_at_least_one_pillar_is_measurable_and_at_least_one_is_not(app_client):
    """A guard against the baseline drifting into one mode or the other.

    All-detectors would mean the reasoning stage has nothing to add; no-detectors would mean
    nothing is checked and every conclusion is an opinion. Both are real failure modes for a
    document maintained by hand over time.
    """
    detectors = {
        criterion["detector"]
        for pillar in app_client.get("/api/standards/").get_json()["pillars"]
        for criterion in pillar["criteria"]
    }
    assert "yes" in detectors, "nothing in the baseline is deterministically checked"
    assert "no" in detectors, "nothing in the baseline requires judgement"


def test_the_index_omits_the_long_body_and_the_detail_view_carries_it(app_client):
    """The remediation patterns are the part an SA acts on, and they are long.

    Splitting them out keeps the index cheap enough to fetch on every page load, which is what
    makes the version string cheap to display everywhere.
    """
    index = app_client.get("/api/standards/").get_json()
    assert all("body" not in pillar for pillar in index["pillars"])

    detail = app_client.get("/api/standards/durability").get_json()
    assert detail["pillar"]["body"].strip()
    assert detail["version"] == index["version"]


def test_an_unknown_pillar_is_told_what_does_exist(app_client):
    """A 404 that lists the real ids saves the reader a second request."""
    response = app_client.get("/api/standards/data-integrity")
    assert response.status_code == 404

    body = response.get_json()
    assert body["reason"] == "not-found"
    assert "durability" in body["error"], "the error should name the pillars that do exist"


def test_a_severity_ceiling_is_published_because_it_bounds_every_finding(app_client):
    """The ceiling is why a missing README cannot be reported as a blocker.

    Publishing it lets a reader check that a severity they disagree with was even reachable.
    """
    pillars = {p["id"]: p for p in app_client.get("/api/standards/").get_json()["pillars"]}

    assert pillars["durability"]["severity_ceiling"] == "blocker"
    assert pillars["provenance"]["severity_ceiling"] in {"major", "minor", "info"}
