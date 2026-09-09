# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Load and check the crosswalk files.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Crosswalks are versioned YAML data rather than prose, and this module is what cashes that in. Two
checks run in CI:

1. Each file conforms to ``crosswalk.schema.json``.
2. Every NRM field path a crosswalk names actually exists in the NRM schema it claims to map.

The second is the one that earns its keep. A crosswalk is written once and read for years, usually
by someone integrating under time pressure who has no way to tell a correct mapping from a stale
one. When a field is renamed in the contract, the crosswalk that still names the old field is
indistinguishable from a working one until an import silently drops the value. Checking the paths
mechanically is the only way that stays true.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import paths

from contracts import loader

_logger = logging.getLogger("nvsf.contracts.crosswalk")

#: An array-member filter in an NRM field path: ``identifiers[format=SERIAL].value``. The filter
#: selects which member a value maps to; for existence checking, only the base name matters.
_FILTER = re.compile(r"\[[^\]]*\]")


class CrosswalkError(Exception):
    """A crosswalk file is missing or unusable."""


def _crosswalk_dir() -> Path:
    return paths.CONTRACTS_DIR / "crosswalk"


@cache
def systems() -> tuple[str, ...]:
    """Names of the published crosswalks, which are the file stems."""
    directory = _crosswalk_dir()
    if not directory.is_dir():
        return ()
    return tuple(sorted(
        entry.stem for entry in directory.glob("*.yaml") if entry.stem != "crosswalk"
    ))


@cache
def load(system: str) -> dict[str, Any]:
    """Parse one crosswalk file.

    The system name is matched against the discovered list rather than interpolated into a path.
    This is reached from an HTTP route with a caller-supplied name, so it is a traversal surface.
    """
    if system not in systems():
        known = ", ".join(systems()) or "none"
        raise CrosswalkError(f"no crosswalk for {system!r} (have: {known})")

    import yaml

    text = (_crosswalk_dir() / f"{system}.yaml").read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    if not isinstance(document, dict):
        raise CrosswalkError(f"crosswalk {system!r} is not a YAML mapping")
    return document


@cache
def _crosswalk_validator() -> Any:
    from jsonschema import Draft202012Validator

    schema = _crosswalk_dir() / "crosswalk.schema.json"
    if not schema.is_file():
        raise CrosswalkError("crosswalk.schema.json is missing")

    import json

    document = json.loads(schema.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(document)
    return Draft202012Validator(document, format_checker=Draft202012Validator.FORMAT_CHECKER)


@dataclass(frozen=True)
class Problem:
    """One defect in a crosswalk file."""

    system: str
    location: str
    message: str

    def __str__(self) -> str:
        return f"{self.system}.yaml {self.location}: {self.message}"


def _resolve_object(definition: Any, version: str) -> dict[str, Any]:
    """Follow a one-hop ``$ref`` into ``common.schema.json`` so shared shapes are inspectable.

    ``external_refs``, ``labels`` and ``timestamps`` are all ``$ref``s into the common schema. An
    unresolved ref looks like a property with no structure, which would make every path into one
    of them read as unknown -- the exact false positive that trains people to ignore this check.
    """
    if not isinstance(definition, dict):
        return {}
    reference = definition.get("$ref")
    if not reference or "common.schema.json" not in reference:
        return definition

    _, _, pointer = reference.partition("#")
    node: Any = loader.load_schema("common", version)
    for part in pointer.strip("/").split("/"):
        if not part:
            continue
        node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            return definition
    return node if isinstance(node, dict) else definition


def _is_open_map(definition: dict[str, Any]) -> bool:
    """Whether a property is a free-keyed map rather than a fixed set of fields.

    ``attributes`` and ``external_refs`` are deliberately open: a team needs somewhere to put a
    fact the contract does not model. Any key under one is therefore a legitimate path, and
    checking it against a property list would reject correct mappings.
    """
    if definition.get("type") not in (None, "object"):
        return False
    return definition.get("additionalProperties") not in (None, False) or bool(
        definition.get("propertyNames")
    )


@cache
def _schema_fields(entity: str, version: str) -> tuple[frozenset[str], frozenset[str]]:
    """``(checkable paths, open-map property names)`` for one NRM entity.

    Nested paths are returned dotted (``design.flow_lpm``, ``cable.length_m``) because that is how
    a crosswalk writes them. One level deep, which covers every nested object in v0.1 without
    turning this into a general JSON Schema walker.
    """
    schema = loader.load_schema(entity, version)
    names: set[str] = set()
    open_maps: set[str] = set()

    for name, raw in (schema.get("properties") or {}).items():
        names.add(name)
        definition = _resolve_object(raw, version)
        if _is_open_map(definition):
            open_maps.add(name)
            continue
        nested = definition.get("properties")
        if isinstance(nested, dict):
            names.update(f"{name}.{child}" for child in nested)

    return frozenset(names), frozenset(open_maps)


def _base_path(field_path: str) -> str:
    """Reduce an NRM field path to the part that must exist as a schema property.

    ``identifiers[format=SERIAL].value`` reduces to ``identifiers``: the filter and the member
    field are addressing inside an array whose item shape lives in ``common.schema.json``, and
    following that would mean resolving refs for no additional safety. ``design.flow_lpm`` stays
    whole, because both halves are checkable properties.
    """
    stripped = _FILTER.sub("", field_path)
    if "[" in field_path or field_path.endswith("[]"):
        return stripped.split(".", maxsplit=1)[0]
    return stripped.rstrip(".")


def check(system: str, version: str | None = None) -> list[Problem]:
    """Validate one crosswalk: shape, NRM field existence, transform resolution.

    Returns every problem rather than raising on the first. A crosswalk that has drifted from the
    contract has usually drifted in several places at once, and fixing them one CI run at a time is
    how a check becomes something people disable.
    """
    problems: list[Problem] = []
    try:
        document = load(system)
    except CrosswalkError as exc:
        return [Problem(system, "", str(exc))]

    for error in sorted(
        _crosswalk_validator().iter_errors(document), key=lambda e: list(e.absolute_path)
    ):
        pointer = "/".join(str(part) for part in error.absolute_path) or "(root)"
        problems.append(Problem(system, pointer, error.message))
    if problems:
        # Path and transform checks below assume the declared shape. Running them on a malformed
        # file buries the actual mistake under consequences of it.
        return problems

    declared_version = document.get("nrm_version")
    resolved = version or declared_version or loader.DEFAULT_VERSION
    if declared_version and declared_version not in loader.versions():
        problems.append(Problem(
            system,
            "nrm_version",
            f"claims NRM {declared_version}, which is not published. A crosswalk against an "
            f"unpublished version cannot be checked, so it cannot be trusted.",
        ))
        return problems

    transforms = set(document.get("transforms") or {})
    known_entities = set(loader.entity_names(resolved))

    for position, mapping in enumerate(document.get("entities") or []):
        entity = mapping.get("nrm_entity")
        where = f"entities/{position} ({entity})"

        if entity not in known_entities:
            problems.append(Problem(
                system, where, f"maps entity {entity!r}, which is not in NRM {resolved}",
            ))
            continue

        available, open_maps = _schema_fields(entity, resolved)

        def unknown(field_path: str, known=available, maps=open_maps) -> str | None:
            """The property name to complain about, or None if the path is legitimate."""
            base = _base_path(field_path)
            if not base or base in known or base.split(".", maxsplit=1)[0] in maps:
                return None
            return base

        for field_position, field_map in enumerate(mapping.get("fields") or []):
            declared_field = field_map.get("nrm", "")
            base = unknown(declared_field)
            if base:
                problems.append(Problem(
                    system,
                    f"{where}/fields/{field_position}",
                    f"maps NRM field {declared_field!r}, but {entity!r} has no property "
                    f"{base!r}. Either the contract renamed it or the crosswalk guessed.",
                ))

            transform = field_map.get("transform")
            if transform and transform not in transforms:
                problems.append(Problem(
                    system,
                    f"{where}/fields/{field_position}",
                    f"references transform {transform!r}, which is not defined in the file's "
                    f"`transforms` map. An importer would have nothing to implement.",
                ))

        for unmapped_position, unmapped in enumerate(mapping.get("unmapped_nrm") or []):
            declared_field = unmapped.get("field", "")
            base = unknown(declared_field)
            if base:
                problems.append(Problem(
                    system,
                    f"{where}/unmapped_nrm/{unmapped_position}",
                    f"documents {declared_field!r} as unmapped, but {entity!r} has no such "
                    f"property. A stale gap note is as misleading as a stale mapping.",
                ))

    return problems


def check_all(version: str | None = None) -> list[Problem]:
    """Check every published crosswalk. Called from CI and from the startup gate."""
    problems: list[Problem] = []
    for system in systems():
        problems.extend(check(system, version))
    return problems


def coverage(version: str | None = None) -> dict[str, Any]:
    """Per-entity mapping coverage across all crosswalks.

    Published so an integrating team can see, before they commit to anything, which entities have a
    mapping for their system and which do not. Counting `unmapped_nrm` alongside `fields` is
    deliberate: a crosswalk with two mapped fields and eleven documented gaps is honest, and a
    coverage figure that hid the gaps would make it look like the opposite.
    """
    resolved = version or loader.DEFAULT_VERSION
    entities = loader.entity_names(resolved)
    table: dict[str, Any] = {}

    for system in systems():
        try:
            document = load(system)
        except CrosswalkError:
            continue

        per_entity = {}
        for mapping in document.get("entities") or []:
            name = mapping.get("nrm_entity")
            if name not in entities:
                continue
            per_entity[name] = {
                "direction": mapping.get("direction"),
                "mapped_fields": len(mapping.get("fields") or []),
                "documented_gaps": len(mapping.get("unmapped_nrm") or []),
                "unreliable_fields": sum(
                    1 for field_map in mapping.get("fields") or [] if field_map.get("unreliable")
                ),
            }

        table[system] = {
            "role": document.get("role"),
            "system_version": document.get("system_version"),
            "join": document.get("join"),
            "entities": per_entity,
            "missing_entities": [name for name in entities if name not in per_entity],
        }

    return {"nrm_version": resolved, "systems": table}
