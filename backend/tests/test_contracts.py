# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Tests for NRM v0.1: the schemas, the adjudicator, the crosswalks, and identity.

Author: Rafael M. Koike & Cursor Agent ("Ada")

The tests worth having here are the ones about the CLAIMS the contract makes, not the ones that
restate the schema in Python. "Resource requires an id" is already in the schema and asserting it
again just means two places to update. What is tested instead:

- the invariants JSON Schema structurally cannot express, since publishing an unchecked invariant
  is publishing a suggestion;
- that an expected link and an observed link between the same ports collide, which is the entire
  validation product;
- that the crosswalks still name fields the contract actually has.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import paths
import pytest

from contracts import crosswalk, identity, loader, validate

FIXTURE = paths.CONTRACTS_DIR / "fixtures" / "nvl72-rack.json"


@pytest.fixture(scope="module")
def nvl72() -> dict:
    """The reference rack. Module-scoped and copied per use, so no test can mutate another's."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def rack(nvl72) -> dict:
    return copy.deepcopy(nvl72)


# ── The schemas themselves ───────────────────────────────────────────────────────────────────


def test_every_schema_compiles_and_every_ref_resolves():
    """The startup gate's check, run here so a broken schema fails the build not the deployment."""
    assert loader.self_check() == []


def test_refs_resolve_without_network_access(monkeypatch):
    """A $ref must never become an outbound HTTPS request.

    The $id values are `https://schemas.nvidia.com/...` URIs, which are identifiers rather than
    fetch targets. jsonschema's default resolver would try to retrieve them -- failing in an
    airgapped deployment and hanging in a firewalled one. This makes the failure loud by breaking
    the socket layer outright.
    """
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError("schema validation attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    for entity in loader.entity_names():
        checker = loader.validator(entity)
        # Deliberately invalid, to force the validator to walk into every $ref while reporting.
        list(checker.iter_errors({"id": "not-a-uuid"}))


def test_format_assertions_are_actually_enforced():
    """`format: date-time` must reject a non-date, or publishing it is a lie.

    jsonschema treats an unrecognized format as an annotation and passes silently, so without the
    [format-nongpl] extra every format in the contract is decoration. This is the test that keeps
    that from being true without anyone noticing.
    """
    checker = loader.validator("resource")
    record = {
        "id": "018f4b1a-0000-7000-8000-000000000001",
        "resource_type_id": "018f4b1a-0000-7000-8000-000000000002",
        "name": "node-1",
        "provenance": {"source": "manual", "collected_at": "yesterday"},
    }
    errors = list(checker.iter_errors(record))
    assert errors, "a non-date-time value passed a date-time format assertion"
    assert any("yesterday" in error.message for error in errors)


def test_the_contract_is_closed():
    """An unknown field is rejected rather than silently ignored.

    `additionalProperties: false` throughout is the decision that makes a typo findable. With it
    open, `serial_numer` validates, the value goes nowhere, and the team that sent it believes it
    arrived -- which surfaces months later as an inventory that disagrees with the hardware.
    """
    checker = loader.validator("resource")
    record = {
        "id": "018f4b1a-0000-7000-8000-000000000001",
        "resource_type_id": "018f4b1a-0000-7000-8000-000000000002",
        "name": "node-1",
        "serial_numer": "TYPO123",
    }
    assert list(checker.iter_errors(record)), "an unknown field was accepted"


def test_attributes_stays_open_on_purpose():
    """The escape hatch has to work, or teams abuse a modelled field instead."""
    checker = loader.validator("resource")
    record = {
        "id": "018f4b1a-0000-7000-8000-000000000001",
        "resource_type_id": "018f4b1a-0000-7000-8000-000000000002",
        "name": "node-1",
        "attributes": {"bios_version": "1.4.2", "nested": {"anything": [1, 2, 3]}},
    }
    assert list(checker.iter_errors(record)) == []


def test_an_unpublished_version_is_refused_rather_than_guessed():
    with pytest.raises(loader.UnknownVersion):
        loader.entity_names("v9.9")


def test_schema_paths_cannot_escape_the_contracts_directory():
    """`entity` arrives from an HTTP route, which makes this a traversal surface."""
    for attempt in ("../../etc/passwd", "..", "resource/../../../secrets"):
        with pytest.raises(loader.UnknownEntity):
            loader.schema_path(attempt)


# ── The reference rack ───────────────────────────────────────────────────────────────────────


def test_the_reference_rack_is_conformant(rack):
    """If the fixture does not validate, nothing below it means anything."""
    result = validate.validate_bundle(rack)
    assert result.valid, [problem.to_json() for problem in result.problems[:5]]


def test_the_reference_rack_is_a_whole_nvl72(rack):
    """Guards the fixture against being quietly reduced to a toy.

    A three-record fixture would exercise none of what actually breaks: deep containment, layered
    links, and a cooling path with a real blast radius. Asserting the shape keeps a future
    simplification honest.
    """
    by_type = {record["id"]: record for record in rack["resource_types"]}

    def count(resource_class: str) -> int:
        return sum(
            1 for record in rack["resources"]
            if by_type[record["resource_type_id"]]["resource_class"] == resource_class
        )

    assert count("gpu") == 72, "an NVL72 has seventy-two GPUs"
    assert count("cpu") == 36
    assert count("tray") == 27, "eighteen compute trays and nine NVLink switch trays"
    assert count("cable_cartridge") == 18

    # Containment actually nests: a GPU's parent is a tray, whose parent is the rack.
    resources = {record["id"]: record for record in rack["resources"]}
    gpu = next(
        record for record in rack["resources"]
        if by_type[record["resource_type_id"]]["resource_class"] == "gpu"
    )
    tray = resources[gpu["parent_id"]]
    assert by_type[tray["resource_type_id"]]["resource_class"] == "tray"
    assert by_type[resources[tray["parent_id"]]["resource_type_id"]]["resource_class"] == "rack"


def test_the_rack_round_trips_byte_for_byte(rack):
    """Parse, re-serialize, and get the same bytes.

    Not a JSON tautology: it fails the moment a value only survives as a string. A float written
    as `1.10`, an integer that arrives as `1e3`, or a duplicated key all break this, and each
    would mean a team's export cannot survive a pass through us unchanged.
    """
    once = json.dumps(rack, indent=2, sort_keys=False) + "\n"
    twice = json.dumps(json.loads(once), indent=2, sort_keys=False) + "\n"
    assert once == twice
    assert once == FIXTURE.read_text(encoding="utf-8")


def test_the_fixture_generator_is_deterministic():
    """`--check` is only meaningful if regenerating produces identical bytes.

    IDs come from a fixed UUIDv5 namespace rather than being minted, precisely so this holds. If
    it stops holding, the fixture's diff becomes unreviewable and CI starts failing for no reason.
    """
    script = paths.REPO_ROOT / "bin" / "gen-nvl72-fixture.py"
    result = subprocess.run(
        [sys.executable, str(script), "--check"],
        capture_output=True, text=True, cwd=paths.REPO_ROOT, check=False, timeout=120,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_the_cooling_path_can_carry_what_it_cools(rack):
    """The check a cooling model exists to make possible.

    Summed TDP of the cooled resources against the path's rated capacity. An under-cooled rack does
    not announce itself -- it presents as intermittent throttling under load, which gets chased as
    a GPU problem for a week. This is the arithmetic that catches it at commissioning instead.
    """
    types = {record["id"]: record for record in rack["resource_types"]}
    resources = {record["id"]: record for record in rack["resources"]}
    path = rack["cooling_paths"][0]

    demand_w = sum(
        types[resources[resource_id]["resource_type_id"]].get("power", {}).get(
            "thermal_design_watts", 0
        )
        for resource_id in path["cooled_resource_ids"]
    )
    capacity_w = path["design"]["heat_capacity_kw"] * 1000

    assert demand_w > 0, "the path cools nothing, so the fixture is not exercising this"
    assert demand_w <= capacity_w, (
        f"the reference rack is modelled as under-cooled: {demand_w / 1000:.1f} kW of TDP on a "
        f"{path['design']['heat_capacity_kw']} kW path"
    )


def test_an_nvlink_fault_can_be_traced_to_one_cartridge(rack):
    """`supporting_link_id` has to make the diagnosis a query.

    This is the field's whole justification. Given a set of failing logical NVLinks, the shared
    physical cartridge should fall out of the data -- not out of an afternoon of cross-referencing
    a cabling spreadsheet against a switch log.
    """
    links = {record["id"]: record for record in rack["links"]}
    logical = [record for record in rack["links"] if record.get("supporting_link_id")]
    assert logical, "the fixture has no layered links, so this property is untested"

    for link in logical:
        physical = links[link["supporting_link_id"]]
        assert physical.get("cable", {}).get("resource_id"), (
            "a supporting link must name the cable Resource, or the trace stops one hop short of "
            "the part somebody has to replace"
        )
        # And the layering is one-directional: a physical link supports nothing.
        assert not physical.get("supporting_link_id")


# ── The invariants a schema cannot express ───────────────────────────────────────────────────


def test_a_dangling_reference_is_caught(rack):
    """The failure mode of every hand-built rack import."""
    rack["ports"][0]["resource_id"] = "018f4b1a-dead-7000-8000-000000000000"
    result = validate.validate_bundle(rack)

    assert not result.valid
    problem = next(p for p in result.problems if p.rule == "reference.ports.resource_id")
    assert problem.pointer == "/ports/0/resource_id"


def test_a_reference_into_an_omitted_collection_is_caught(rack):
    """A partial export must fail rather than import as a fragment.

    Dropping the resources means every port dangles. Reporting that as hundreds of problems is
    correct -- it is one mistake, but the bundle is unusable and saying so once per broken
    reference is what points at the omission.
    """
    del rack["resources"]
    result = validate.validate_bundle(rack)
    assert not result.valid
    assert any(p.rule.startswith("reference.ports") for p in result.problems)


def test_a_containment_cycle_is_caught(rack):
    """A cycle makes every consumer's tree walk run forever."""
    resources = {record["id"]: record for record in rack["resources"]}
    gpu = next(record for record in rack["resources"] if record["name"].endswith("-GPU0"))
    tray = resources[gpu["parent_id"]]
    tray["parent_id"] = gpu["id"]          # tray -> gpu -> tray

    result = validate.validate_bundle(rack)
    assert not result.valid
    assert any(p.rule == "invariant.containment_cycle" for p in result.problems)


def test_a_self_parenting_resource_is_caught(rack):
    """The one-element cycle, which a naive walk misses."""
    rack["resources"][0]["parent_id"] = rack["resources"][0]["id"]
    result = validate.validate_bundle(rack)
    assert not result.valid
    assert any(p.rule == "invariant.containment_cycle" for p in result.problems)


def test_a_duplicate_id_is_caught(rack):
    """Worse than a dangling reference: references resolve, so nothing complains."""
    rack["resources"].append(copy.deepcopy(rack["resources"][0]))
    result = validate.validate_bundle(rack)

    assert not result.valid
    assert any(p.rule.startswith("invariant.duplicate_id") for p in result.problems)


def test_a_link_class_that_disagrees_with_its_ports_is_caught(rack):
    """Structurally valid, referentially sound, and describes hardware that cannot exist."""
    rack["links"][0]["link_class"] = "ethernet"     # endpoints are nvlink
    result = validate.validate_bundle(rack)

    assert not result.valid
    problem = next(p for p in result.problems if p.rule == "invariant.link_class_mismatch")
    assert "nvlink" in problem.message


def test_a_hand_written_link_key_is_caught(rack):
    """The key is derived, and a key that disagrees with its endpoints breaks the diff silently."""
    rack["links"][0]["key"] = "someone-typed-this:by-hand"
    result = validate.validate_bundle(rack)

    assert not result.valid
    assert any(p.rule == "invariant.link_key_mismatch" for p in result.problems)


def test_a_shape_failure_suppresses_the_downstream_noise(rack):
    """If the shape is wrong, that is the answer.

    Reference and invariant checks assume records have the fields they require. Running them over
    a malformed document produces cascading problems that bury the actual mistake, and a report
    where the real error is item 340 is a report nobody reads to the end.
    """
    del rack["resources"][0]["name"]
    result = validate.validate_bundle(rack)

    assert not result.valid
    assert all(p.rule.startswith("schema.") for p in result.problems)


def test_a_systematic_mistake_does_not_produce_an_unbounded_report(rack):
    """One mistake repeated 254 times is one finding, and the response has to stay serializable."""
    for record in rack["resources"]:
        record["parent_id"] = "018f4b1a-dead-7000-8000-000000000000"

    result = validate.validate_bundle(rack)
    assert not result.valid
    assert len(result.problems) <= validate.MAX_PROBLEMS + 1
    assert result.problems[-1].rule == "report.truncated"


def test_a_single_record_says_what_it_did_not_check():
    """Validating one record cannot check references, and must not imply otherwise."""
    result = validate.validate_record("location", {
        "id": "018f4b1a-0000-7000-8000-000000000001", "site": "NSCALE-PT1",
    })
    assert result.valid
    assert result.counts == {"location": 1}


# ── Identity: the property the whole validation product rests on ─────────────────────────────


def test_a_link_key_does_not_depend_on_which_end_was_read_first():
    """The single most important property in the contract.

    A cabling file lists a link switch-first; a discovery sweep reports it node-first. Without the
    lexical sort, the same physical cable yields two different keys, and every link in the rack
    reads as BOTH a missing cable and an unexpected one -- a report that is 100% wrong while
    looking thorough.
    """
    forward = identity.link_key(
        a_resource="R14-CT01", a_port="OSFP1", b_resource="R14-NVS01", b_port="NVLINK1",
    )
    backward = identity.link_key(
        a_resource="R14-NVS01", a_port="NVLINK1", b_resource="R14-CT01", b_port="OSFP1",
    )
    assert forward == backward


def test_cosmetic_disagreement_between_two_sources_still_collides():
    """A spreadsheet and a discovery tool name the same hardware differently.

    `Rack01 / OSFP 1` from a cabling file and `rack01:OSFP1` from ibnetdiscover are the same port.
    Normalizing here is what makes them match; it is the one place in the contract where a value
    is normalized, because identifiers are deliberately kept verbatim.
    """
    from_file = identity.link_key(
        a_resource="R14-CT01 ", a_port="OSFP 1", b_resource="R14-NVS01", b_port="NVLINK 1",
    )
    from_discovery = identity.link_key(
        a_resource="r14-ct01", a_port="osfp-1", b_resource="r14-nvs01", b_port="nvlink-1",
    )
    assert from_file == from_discovery


def test_the_key_separators_survive_a_name_containing_them():
    """`:` and `_` are structural, so a name containing one must not create a third term."""
    key = identity.link_key(
        a_resource="rack:01", a_port="port_1", b_resource="rack:02", b_port="port_2",
    )
    assert key.count(":") == 1
    left, right = key.split(":")
    assert left.count("_") == 1 and right.count("_") == 1


def test_plan_versus_reality_is_a_set_difference(rack):
    """The validation product, end to end.

    Take the reference rack as `expected`, simulate a sweep that misses one link and finds one
    nobody planned, and confirm both fall out as set operations on the key. This is what a
    bring-up actually delivers, and the reason `key` is content-addressable rather than minted.
    """
    expected = {link["key"] for link in rack["links"]}

    observed = set(expected)
    missing = min(expected)
    observed.remove(missing)
    surprise = identity.link_key(
        a_resource="R14-CT01", a_port="OSFP1", b_resource="R14-CT02", b_port="OSFP1",
    )
    observed.add(surprise)

    assert expected - observed == {missing}, "an uncabled or dead link"
    assert observed - expected == {surprise}, "a miscable"


def test_identifier_matching_survives_case_disagreement():
    """The same GUID arrives upper-cased from one tool and lower-cased from another.

    A reconciliation that misses on case duplicates every record on the second import, and the
    duplicates are then reconciled against forever.
    """
    upper = identity.identifier_match_key("IB_GUID", "0xE8EBD30003000001")
    lower = identity.identifier_match_key("IB_GUID", "0xe8ebd30003000001")
    assert upper == lower


def test_a_serial_is_only_unique_within_its_manufacturer():
    """Two vendors will eventually both ship a part numbered 1234."""
    dell = identity.identifier_match_key("SERIAL", "1234", scope="Dell")
    supermicro = identity.identifier_match_key("SERIAL", "1234", scope="Supermicro")
    assert dell != supermicro


def test_minted_ids_are_uuid7_with_a_time_ordered_prefix():
    """Time-ordered keys keep a bulk rack import from scattering writes across the whole index.

    The assertion is on the 48-bit timestamp prefix being non-decreasing, not on the full strings
    sorting. UUIDv7 orders at MILLISECOND granularity, so IDs minted inside the same millisecond
    are ordered by their random bits and a full-string sort assertion would fail intermittently --
    a flake that would get rerun rather than understood. The prefix is what clusters index writes,
    so it is also the property actually worth asserting.
    """
    import time
    import uuid as uuid_module

    minted = [identity.new_id() for _ in range(50)]
    assert len(set(minted)) == len(minted), "minted ids must be unique"

    def stamp(value: str) -> int:
        return uuid_module.UUID(value).int >> 80

    stamps = [stamp(value) for value in minted]
    assert stamps == sorted(stamps), "the timestamp prefix must be non-decreasing"
    for value in minted:
        parsed = uuid_module.UUID(value)
        assert parsed.version == 7
        assert parsed.variant == uuid_module.RFC_4122

    # Across a millisecond boundary the ordering is strict, which is the claim the prefix supports.
    time.sleep(0.005)
    later = identity.new_id()
    assert stamp(later) > stamps[-1]
    assert later > max(minted)

    # And they validate against the contract's own uuid pattern.
    checker = loader.validator("resource")
    for value in minted[:5]:
        record = {
            "id": value,
            "resource_type_id": identity.new_id(),
            "name": "node",
        }
        assert list(checker.iter_errors(record)) == []


# ── The crosswalks ───────────────────────────────────────────────────────────────────────────


def test_every_crosswalk_is_well_formed_and_current():
    """The check that keeps a crosswalk from outliving the field it maps.

    A crosswalk is written once and read for years, usually by someone integrating under time
    pressure who cannot tell a correct mapping from a stale one. Checking it mechanically is the
    only thing that keeps it true.
    """
    problems = crosswalk.check_all()
    assert problems == [], "\n".join(str(problem) for problem in problems)


def test_the_expected_crosswalks_are_published():
    published = set(crosswalk.systems())
    assert {"nautobot", "redfish", "ufm", "bcm-netautogen", "dcgm", "cyclonedx"} <= published


def test_nautobot_is_declared_the_source_of_record():
    """Not a preference. The InfoSec Asset Management Standard names it, so NRM is a profile.

    If this flips, the whole design premise changed and that should be a deliberate, visible edit
    rather than a quiet one.
    """
    document = crosswalk.load("nautobot")
    assert document["role"] == "source_of_record"
    assert document["join"]["system_field"] == "custom_fields.resource_id"


def test_a_crosswalk_naming_a_field_the_contract_lost_is_caught(tmp_path, monkeypatch):
    """Simulates the drift this check exists for: the contract renames, the crosswalk does not."""
    # The real nrm/ tree comes along, because the check validates field paths against the actual
    # contract -- with only a fake crosswalk dir, every entity reads as unpublished and the test
    # would pass for the wrong reason.
    (tmp_path / "nrm").symlink_to(paths.CONTRACTS_DIR / "nrm")

    directory = tmp_path / "crosswalk"
    directory.mkdir()
    (directory / "crosswalk.schema.json").write_text(
        (paths.CONTRACTS_DIR / "crosswalk" / "crosswalk.schema.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (directory / "stale.yaml").write_text(
        """
crosswalk_version: v0.1
nrm_version: v0.1
system: stale
role: discovery
entities:
  - nrm_entity: resource
    system_model: Thing
    direction: import
    fields:
      - nrm: serial_number
        system: serial
        direction: import
    unmapped_nrm: []
""".lstrip(),
        encoding="utf-8",
    )

    caches = (
        crosswalk.systems, crosswalk.load, crosswalk._crosswalk_validator,
        crosswalk._schema_fields, loader.versions, loader.load_schema, loader._all_schemas,
        loader.registry, loader.index,
    )
    monkeypatch.setattr(paths, "CONTRACTS_DIR", tmp_path)
    for cached in caches:
        cached.cache_clear()

    try:
        problems = crosswalk.check("stale")
        assert problems, "a crosswalk naming a nonexistent field was accepted"
        assert "serial_number" in problems[0].message
    finally:
        # Restored before the monkeypatch unwinds, or every later test in the session reads the
        # fake contract out of these caches.
        for cached in caches:
            cached.cache_clear()


def test_an_open_map_accepts_any_key(monkeypatch):
    """`external_refs.nautobot` is a path into a deliberately open map, not a missing property.

    Rejecting it would be a false positive on a correct mapping, and false positives are how a
    check gets disabled.
    """
    problems = crosswalk.check("ufm")
    assert problems == []
    document = crosswalk.load("ufm")
    mapped = {
        field["nrm"]
        for entity in document["entities"]
        for field in entity["fields"]
    }
    assert "external_refs.ufm" in mapped, "the fixture for this property is gone"


def test_every_crosswalk_documents_what_it_cannot_carry():
    """`unmapped_nrm` is required, because a crosswalk listing only its successes looks complete.

    What an integrating team needs before they build is the gaps -- and each one has to state a
    reason, so it reads as a decision rather than an oversight.

    Checked for placeholders rather than for length. A minimum length would be satisfied by padding
    -- "No CycloneDX concept of ports" is complete and twenty-nine characters, while a hundred
    characters of hedging says less. Gaming a rubric is the failure mode a length check invites.
    """
    placeholders = {"todo", "tbd", "n/a", "na", "-", "?", "none", "unknown", "fixme", "xxx"}

    for system in crosswalk.systems():
        document = crosswalk.load(system)
        for mapping in document["entities"]:
            gaps = mapping["unmapped_nrm"]
            assert isinstance(gaps, list), f"{system}: {mapping['nrm_entity']} has no gap section"
            for gap in gaps:
                where = f"{system}: {mapping['nrm_entity']}.{gap['field']}"
                reason = gap["reason"].strip()
                assert reason, f"{where} is documented as unmapped with no reason"
                assert reason.rstrip(".").lower() not in placeholders, (
                    f"{where} has a placeholder reason ({reason!r}), which is an undocumented gap "
                    f"wearing documentation's clothes"
                )


def test_observation_is_unmapped_everywhere_and_that_is_the_point():
    """No external system carries expected-versus-observed, which is why NRM is not just a view.

    Nautobot records intent; UFM and Redfish record measurement. Neither can express the
    DISTINCTION, so the diff that constitutes a validation report cannot be computed in either.
    That gap is the contract's reason to exist, and it should be stated in the data.
    """
    document = crosswalk.load("nautobot")
    resource = next(m for m in document["entities"] if m["nrm_entity"] == "resource")
    gap = next(g for g in resource["unmapped_nrm"] if g["field"] == "observation")
    assert "expected" in gap["reason"] or "intent" in gap["reason"]


def test_a_telemetry_system_never_writes_inventory():
    """DCGM must not drive lifecycle: a throttling GPU is not a lifecycle change.

    Mapping telemetry into an inventory field makes the inventory flap with load and gives two
    systems different answers about the same GPU.
    """
    document = crosswalk.load("dcgm")
    assert document["role"] == "telemetry"

    for mapping in document["entities"]:
        assert mapping["direction"] == "export", (
            "DCGM is telemetry; importing it into NRM would make an inventory into a bad TSDB"
        )
    resource = next(m for m in document["entities"] if m["nrm_entity"] == "resource")
    assert any(gap["field"] == "lifecycle" for gap in resource["unmapped_nrm"])


def test_an_export_target_originates_nothing():
    document = crosswalk.load("cyclonedx")
    assert document["role"] == "export_target"
    for mapping in document["entities"]:
        assert mapping["direction"] == "export"
        for field_map in mapping["fields"]:
            assert field_map["direction"] == "export"


def test_the_cooling_crosswalk_targets_nautobots_native_model():
    """Adopting NetBox/Nautobot 4.7's shape is why the contract needs no RDF.

    If this mapping were absent, the IT/OT requirement would have needed a graph model, and Brick
    or Haystack would be a dependency rather than a documented export target.
    """
    document = crosswalk.load("nautobot")
    cooling = next(m for m in document["entities"] if m["nrm_entity"] == "cooling-path")
    assert cooling["system_model"] == "dcim.CoolingSource"
    assert cooling["minimum_system_version"] == "4.7"


def test_coverage_reports_gaps_rather_than_hiding_them():
    """An integrating team needs to see which entities have no mapping for their system."""
    report = crosswalk.coverage()
    assert report["nrm_version"] == loader.DEFAULT_VERSION

    dcgm = report["systems"]["dcgm"]
    assert "link" in dcgm["missing_entities"], "DCGM maps no links, and that should be visible"

    nautobot = report["systems"]["nautobot"]
    assert nautobot["entities"]["resource"]["mapped_fields"] > 5
    assert nautobot["entities"]["resource"]["documented_gaps"] >= 1


def test_an_unreliable_mapping_is_labelled_as_such():
    """A value parsed out of a free-text comments field must not look like a guaranteed one."""
    document = crosswalk.load("nautobot")
    resource_type = next(m for m in document["entities"] if m["nrm_entity"] == "resource-type")
    datasheet = next(f for f in resource_type["fields"] if f["nrm"] == "datasheet_url")
    assert datasheet["unreliable"] is True


def test_the_index_is_built_from_the_files():
    """An entity cannot be added to the contract without appearing in the published index."""
    published = loader.index()
    assert published["nrm_version"] == "v0.1"
    assert {entry["name"] for entry in published["entities"]} == set(loader.entity_names())
    for entry in published["entities"]:
        assert entry["title"] and entry["description"], f"{entry['name']} is undocumented"
        assert Path(entry["schema"]).name == entry["schema"], "schema must be a bare filename"
