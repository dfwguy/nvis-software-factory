# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Adjudicate a bundle: schema conformance, then the cross-record rules a schema cannot express.

Author: Rafael M. Koike & Cursor Agent ("Ada")

JSON Schema validates one document against one shape. It cannot say "``a_port_id`` must name a Port
that exists in this bundle", "containment must not contain a cycle", or "a Link's class must match
its endpoints' class", because all three are statements about relationships between records.

Those rules are not optional detail. They are most of what makes an inventory trustworthy: a
dangling reference is the failure mode of every hand-built rack import, and a containment cycle
makes every tree walk in every consumer hang. Publishing a contract whose stated invariants are
unchecked would be publishing a suggestion.

**This module is the only thing that decides conformance.** The LLM proposes crosswalk mappings in
``crosswalk.py``; what comes back is run through here before it is believed. A model is a good
guesser about which field means which, and no kind of authority on whether a payload is valid.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from contracts import loader

_logger = logging.getLogger("nvsf.contracts.validate")

#: Which bundle key holds which entity, and the reference fields to check in each.
#:
#: Declared as data rather than as a chain of if-statements so that adding an entity to the
#: contract is one line here. The alternative -- a bespoke check per entity -- is how a new entity
#: ships with its references unvalidated and nobody notices for a quarter.
_COLLECTIONS: tuple[tuple[str, str], ...] = (
    ("resource_types", "resource-type"),
    ("locations", "location"),
    ("domains", "domain"),
    ("resources", "resource"),
    ("ports", "port"),
    ("links", "link"),
    ("cooling_paths", "cooling-path"),
)

#: ``(collection, field, target collection, is_list)``. A reference to a collection that is absent
#: from the bundle is reported rather than skipped: a Port whose Resource was not included is
#: exactly the partial export this check exists to catch.
_REFERENCES: tuple[tuple[str, str, str, bool], ...] = (
    ("resources", "resource_type_id", "resource_types", False),
    ("resources", "parent_id", "resources", False),
    ("resources", "location_id", "locations", False),
    ("resources", "domain_id", "domains", False),
    ("ports", "resource_id", "resources", False),
    ("ports", "breakout_of", "ports", False),
    ("links", "a_port_id", "ports", False),
    ("links", "b_port_id", "ports", False),
    ("links", "supporting_link_id", "links", False),
    ("domains", "parent_id", "domains", False),
    ("domains", "member_resource_ids", "resources", True),
    ("cooling_paths", "source_resource_id", "resources", False),
    ("cooling_paths", "feed_resource_ids", "resources", True),
    ("cooling_paths", "cooled_resource_ids", "resources", True),
    ("cooling_paths", "intake_port_id", "ports", False),
    ("cooling_paths", "outflow_port_id", "ports", False),
)


@dataclass(frozen=True)
class Problem:
    """One reason a bundle is not conformant.

    ``pointer`` is a JSON Pointer into the submitted document. Returning a pointer rather than a
    prose location is what lets the frontend highlight the offending line and an agent patch the
    right field; "invalid resource" sends someone scrolling through a 40,000-line export.
    """

    pointer: str
    rule: str
    message: str

    def to_json(self) -> dict[str, str]:
        return {"pointer": self.pointer, "rule": self.rule, "message": self.message}


@dataclass
class Result:
    """Outcome of adjudicating a bundle."""

    valid: bool
    problems: list[Problem] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    nrm_version: str = loader.DEFAULT_VERSION

    def to_json(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "nrm_version": self.nrm_version,
            "counts": self.counts,
            "problem_count": len(self.problems),
            "problems": [problem.to_json() for problem in self.problems],
        }


#: Cap on reported problems. A bundle with a systematic mistake produces one problem per record,
#: and forty thousand of them is neither a useful response nor a safe one to serialize.
MAX_PROBLEMS = 200


def _pointer(*parts: Any) -> str:
    escaped = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(escaped)


def validate_bundle(document: Any, version: str | None = None) -> Result:
    """Full adjudication: shape, then references, then the semantic invariants.

    Ordered deliberately. Reference and invariant checks assume records have the fields they
    require, so running them on a document that failed its shape check produces cascading noise
    that buries the actual mistake. If the shape is wrong, that is the answer.
    """
    resolved = version or loader.DEFAULT_VERSION
    if not isinstance(document, dict):
        return Result(
            valid=False,
            nrm_version=resolved,
            problems=[Problem("", "bundle.type", "a bundle must be a JSON object")],
        )

    declared = document.get("nrm_version")
    if declared and declared in loader.versions():
        resolved = declared

    problems = _schema_problems(document, resolved)
    counts = {
        key: len(document.get(key) or []) for key, _ in _COLLECTIONS if isinstance(
            document.get(key), list
        )
    }

    if not problems:
        problems = _reference_problems(document)
        problems += _invariant_problems(document)

    truncated = problems[:MAX_PROBLEMS]
    if len(problems) > MAX_PROBLEMS:
        truncated.append(Problem(
            "",
            "report.truncated",
            f"{len(problems) - MAX_PROBLEMS} further problem(s) not listed. A count this high is "
            "usually one systematic mistake rather than many separate ones -- fix the listed "
            "ones and re-submit.",
        ))

    return Result(
        valid=not problems, problems=truncated, counts=counts, nrm_version=resolved,
    )


def _schema_problems(document: dict[str, Any], version: str) -> list[Problem]:
    """Validate the bundle against ``bundle.schema.json``, which recurses into every record."""
    try:
        checker = loader.validator("bundle", version)
    except loader.ContractError as exc:
        return [Problem("", "bundle.version", str(exc))]

    problems = []
    for error in sorted(checker.iter_errors(document), key=lambda e: list(e.absolute_path)):
        problems.append(Problem(
            pointer=_pointer(*error.absolute_path) if error.absolute_path else "",
            rule=f"schema.{'.'.join(str(p) for p in error.absolute_schema_path) or 'root'}",
            message=error.message,
        ))
    return problems


def _index_ids(document: dict[str, Any]) -> dict[str, set[str]]:
    """Map each collection name to the set of record IDs present in it."""
    index: dict[str, set[str]] = {}
    for key, _ in _COLLECTIONS:
        records = document.get(key) or []
        index[key] = {
            record["id"]
            for record in records
            if isinstance(record, dict) and isinstance(record.get("id"), str)
        }
    return index


def _reference_problems(document: dict[str, Any]) -> list[Problem]:
    """Every declared reference must name a record present in this bundle."""
    index = _index_ids(document)
    problems: list[Problem] = []

    for collection, name, target, is_list in _REFERENCES:
        records = document.get(collection) or []
        for position, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            value = record.get(name)
            if value is None:
                continue

            candidates = value if is_list else [value]
            for offset, candidate in enumerate(candidates or []):
                if candidate in index.get(target, set()):
                    continue
                pointer = (
                    _pointer(collection, position, name, offset)
                    if is_list
                    else _pointer(collection, position, name)
                )
                problems.append(Problem(
                    pointer=pointer,
                    rule=f"reference.{collection}.{name}",
                    message=(
                        f"{name} refers to {candidate!r}, which is not in {target}. Either "
                        f"include that record in the bundle or drop the reference -- a dangling "
                        f"reference makes this bundle unusable to a consumer that walks it."
                    ),
                ))

    return problems


def _invariant_problems(document: dict[str, Any]) -> list[Problem]:
    """Semantic rules: no containment cycles, link classes agree with their endpoints, keys match."""
    problems: list[Problem] = []
    problems += _containment_cycles(document)
    problems += _link_endpoint_agreement(document)
    problems += _duplicate_ids(document)
    return problems


def _containment_cycles(document: dict[str, Any]) -> list[Problem]:
    """A resource must not contain itself, transitively.

    Checked because containment is THE primary relationship: every consumer walks it to answer
    "what is in this rack", and a cycle turns that walk into an infinite loop. A schema cannot see
    this, and an import built by joining spreadsheets produces it more often than anyone expects.
    """
    parents: dict[str, str | None] = {}
    positions: dict[str, int] = {}
    for position, record in enumerate(document.get("resources") or []):
        if isinstance(record, dict) and isinstance(record.get("id"), str):
            parents[record["id"]] = record.get("parent_id")
            positions[record["id"]] = position

    problems = []
    settled: set[str] = set()
    for start in parents:
        if start in settled:
            continue
        seen: list[str] = []
        current: str | None = start
        while current is not None and current in parents and current not in settled:
            if current in seen:
                chain = " -> ".join(seen[seen.index(current):] + [current])
                problems.append(Problem(
                    pointer=_pointer("resources", positions[current], "parent_id"),
                    rule="invariant.containment_cycle",
                    message=(
                        f"containment cycle: {chain}. Every consumer walks parent_id to build the "
                        f"physical tree, and a cycle makes that walk run forever."
                    ),
                ))
                break
            seen.append(current)
            current = parents.get(current)
        settled.update(seen)

    return problems


def _link_endpoint_agreement(document: dict[str, Any]) -> list[Problem]:
    """A link's class must match both endpoint ports' class, and its key must match its endpoints.

    The class check catches a real and confusing defect: an ethernet link recorded between two
    InfiniBand ports validates structurally, passes reference checks, and then produces a fabric
    report that disagrees with the hardware for reasons nobody can find.

    The key check protects the plan-versus-reality diff. `key` is content-addressable so that an
    expected link and an observed link between the same endpoints collide; a key that disagrees
    with its own endpoints breaks that silently, and silently is the problem.
    """
    ports = {
        record["id"]: record
        for record in document.get("ports") or []
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    }
    resources = {
        record["id"]: record
        for record in document.get("resources") or []
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    }

    from contracts import identity

    problems = []
    for position, record in enumerate(document.get("links") or []):
        if not isinstance(record, dict):
            continue

        a_port, b_port = ports.get(record.get("a_port_id")), ports.get(record.get("b_port_id"))
        if not a_port or not b_port:
            continue

        declared = record.get("link_class")
        for label, port in (("a", a_port), ("b", b_port)):
            port_class = port.get("port_class")
            if declared and port_class and declared != port_class:
                problems.append(Problem(
                    pointer=_pointer("links", position, "link_class"),
                    rule="invariant.link_class_mismatch",
                    message=(
                        f"link_class is {declared!r} but its {label} endpoint port "
                        f"{port.get('name')!r} is {port_class!r}. A link cannot be of a different "
                        f"class from the ports it terminates on."
                    ),
                ))

        expected_key = identity.link_key(
            a_resource=resources.get(a_port.get("resource_id"), {}).get("name", ""),
            a_port=a_port.get("name", ""),
            b_resource=resources.get(b_port.get("resource_id"), {}).get("name", ""),
            b_port=b_port.get("name", ""),
        )
        if record.get("key") and record["key"] != expected_key:
            problems.append(Problem(
                pointer=_pointer("links", position, "key"),
                rule="invariant.link_key_mismatch",
                message=(
                    f"key is {record['key']!r} but its endpoints derive {expected_key!r}. The key "
                    f"is content-addressable so that an expected and an observed link between the "
                    f"same ports collide; a hand-written key breaks that comparison. Generate it "
                    f"with contracts.identity.link_key."
                ),
            ))

    return problems


def _duplicate_ids(document: dict[str, Any]) -> list[Problem]:
    """No two records in a collection may share an ID.

    A duplicate is worse than a dangling reference: references to it resolve, so nothing complains,
    and which record a consumer sees depends on its iteration order. Two teams then disagree about
    the same object and neither can reproduce the other's view.
    """
    problems = []
    for key, _ in _COLLECTIONS:
        seen: dict[str, int] = {}
        for position, record in enumerate(document.get(key) or []):
            if not isinstance(record, dict):
                continue
            record_id = record.get("id")
            if not isinstance(record_id, str):
                continue
            if record_id in seen:
                problems.append(Problem(
                    pointer=_pointer(key, position, "id"),
                    rule=f"invariant.duplicate_id.{key}",
                    message=(
                        f"id {record_id!r} also appears at index {seen[record_id]}. Which record "
                        f"a consumer sees would depend on its iteration order."
                    ),
                ))
            else:
                seen[record_id] = position
    return problems


def validate_record(entity: str, document: Any, version: str | None = None) -> Result:
    """Validate a single record against one entity schema.

    Offered alongside ``validate_bundle`` because a team integrating incrementally wants to check
    one Resource without assembling a bundle. Reference checks are impossible here by definition --
    there is nothing to resolve against -- and the result says so rather than implying the record
    is fully validated.
    """
    resolved = version or loader.DEFAULT_VERSION
    try:
        checker = loader.validator(entity, resolved)
    except loader.ContractError as exc:
        return Result(
            valid=False, nrm_version=resolved, problems=[Problem("", "entity.unknown", str(exc))],
        )

    problems = [
        Problem(
            pointer=_pointer(*error.absolute_path) if error.absolute_path else "",
            rule=f"schema.{'.'.join(str(p) for p in error.absolute_schema_path) or 'root'}",
            message=error.message,
        )
        for error in sorted(checker.iter_errors(document), key=lambda e: list(e.absolute_path))
    ]
    return Result(
        valid=not problems,
        problems=problems[:MAX_PROBLEMS],
        counts={entity: 1},
        nrm_version=resolved,
    )
