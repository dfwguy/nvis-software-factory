# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Load NRM schemas from ``contracts/`` and resolve their cross-references.

Author: Rafael M. Koike & Cursor Agent ("Ada")

The schemas are files on disk, not Python literals. That is the whole design: the published
contract and the contract the server validates against are the same bytes, so they cannot drift.
A Python copy of the schema would be a second source of truth, and the one that mattered would be
whichever the reader had not looked at.

Cross-file ``$ref`` is resolved **offline**. The ``$id`` values are ``https://schemas.nvidia.com/...``
URIs, which are identifiers rather than fetch targets, and jsonschema's default resolver would try
to retrieve them over the network -- turning schema validation into an outbound HTTPS call that
fails in an airgapped deployment and hangs in a firewalled one. The registry built here maps every
``$id`` and every relative filename to its local content, so nothing is ever fetched.
"""

from __future__ import annotations

import json
import logging
from functools import cache
from pathlib import Path
from typing import Any

import paths

_logger = logging.getLogger("nvsf.contracts.loader")

#: Entity schemas, in dependency order. Order is meaningful for the docs site and the agent pack:
#: a reader meeting ``Port`` before ``Resource`` has to hold an unexplained reference in their head.
ENTITIES: tuple[str, ...] = (
    "resource-type",
    "location",
    "domain",
    "resource",
    "port",
    "link",
    "cooling-path",
)

#: Not entities. ``common`` holds shared ``$defs`` and has no top-level object; ``bundle`` is the
#: interchange container. Both are fetchable, but neither is a thing you create one of.
SUPPORTING: tuple[str, ...] = ("common", "bundle")

#: The version served when a caller does not name one. Not "latest": a caller that silently follows
#: latest gets a breaking change on our release schedule rather than theirs.
DEFAULT_VERSION = "v0.1"


class ContractError(Exception):
    """Base for contract loading failures."""


class UnknownVersion(ContractError):
    """A contract version that is not published."""


class UnknownEntity(ContractError):
    """An entity name that does not exist in the requested version."""


def _nrm_root() -> Path:
    return paths.CONTRACTS_DIR / "nrm"


@cache
def versions() -> tuple[str, ...]:
    """Published contract versions, newest last.

    Sorted numerically on the parts after ``v`` so ``v0.10`` follows ``v0.9`` instead of preceding
    it, which a plain string sort would get wrong the first time a tenth minor version ships.
    """
    root = _nrm_root()
    if not root.is_dir():
        return ()

    def sort_key(name: str) -> tuple[int, ...]:
        try:
            return tuple(int(part) for part in name.lstrip("v").split("."))
        except ValueError:
            return (0,)

    found = sorted(
        (entry.name for entry in root.iterdir() if entry.is_dir() and entry.name.startswith("v")),
        key=sort_key,
    )
    return tuple(found)


def _require_version(version: str | None) -> str:
    resolved = version or DEFAULT_VERSION
    if resolved not in versions():
        published = ", ".join(versions()) or "none"
        raise UnknownVersion(f"contract version {resolved!r} is not published (have: {published})")
    return resolved


def entity_names(version: str | None = None) -> tuple[str, ...]:
    """Entity names available in a version, excluding the supporting schemas."""
    resolved = _require_version(version)
    directory = _nrm_root() / resolved
    return tuple(name for name in ENTITIES if (directory / f"{name}.schema.json").is_file())


def schema_path(entity: str, version: str | None = None) -> Path:
    """Absolute path to one schema file.

    The entity name is checked against the known lists rather than being interpolated into a path,
    so a caller cannot reach outside the contracts directory with ``../``. This is reached from an
    HTTP route with a user-supplied name, which makes it a traversal surface.
    """
    resolved = _require_version(version)
    if entity not in ENTITIES and entity not in SUPPORTING:
        known = ", ".join((*ENTITIES, *SUPPORTING))
        raise UnknownEntity(f"unknown entity {entity!r} (have: {known})")

    candidate = _nrm_root() / resolved / f"{entity}.schema.json"
    if not candidate.is_file():
        raise UnknownEntity(f"entity {entity!r} is not published in {resolved}")
    return candidate


@cache
def load_schema(entity: str, version: str | None = None) -> dict[str, Any]:
    """Parse one schema file.

    Cached: these are read on every validate call and every docs build, they are a few kilobytes
    each, and they cannot change without a process restart because they ship in the image.
    """
    return json.loads(schema_path(entity, version).read_text(encoding="utf-8"))


@cache
def _all_schemas(version: str) -> tuple[tuple[str, str], ...]:
    """Every schema in a version as ``(filename, raw json)`` pairs, for registry construction."""
    directory = _nrm_root() / _require_version(version)
    return tuple(
        (entry.name, entry.read_text(encoding="utf-8"))
        for entry in sorted(directory.glob("*.schema.json"))
    )


@cache
def registry(version: str | None = None) -> Any:
    """A jsonschema registry that resolves every ``$ref`` in this version locally.

    Each schema is registered under two URIs: its declared ``$id``, and its bare filename. Both are
    needed. The ``$id`` is what a ``$ref`` to an absolute URI resolves to, and the filename is what
    a relative ``$ref`` like ``common.schema.json#/$defs/uuid`` resolves to once the base URI is
    the containing document. Registering only one of them produces an unresolvable-reference error
    at validation time rather than at load time, which is a much worse place to find out.
    """
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    resolved = _require_version(version)
    contents = []
    for filename, raw in _all_schemas(resolved):
        document = json.loads(raw)
        resource = Resource.from_contents(document, default_specification=DRAFT202012)
        contents.append((filename, resource))
        declared = document.get("$id")
        if declared:
            contents.append((declared, resource))

    return Registry().with_resources(contents)


def validator(entity: str, version: str | None = None) -> Any:
    """A compiled validator for one entity, with local ref resolution and format checking.

    Format checking is ON. Without it, ``"format": "date-time"`` is decoration and a bundle with
    ``collected_at: "yesterday"`` validates -- which defeats the purpose of declaring the format
    at all. It costs a dependency on jsonschema's format extras, which is why the requirement
    pins ``jsonschema[format-nongpl]``.
    """
    from jsonschema import Draft202012Validator
    from jsonschema.validators import validator_for

    resolved = _require_version(version)
    schema = load_schema(entity, resolved)
    cls = validator_for(schema, default=Draft202012Validator)
    cls.check_schema(schema)
    return cls(
        schema,
        registry=registry(resolved),
        format_checker=cls.FORMAT_CHECKER,
    )


@cache
def index(version: str | None = None) -> dict[str, Any]:
    """The machine-readable contract index.

    This is what an agent fetches first: it names the version, lists the entities with their titles
    and descriptions, and gives the relative path of each schema. Built from the files rather than
    hand-maintained, so an entity cannot be added without appearing here.
    """
    resolved = _require_version(version)
    entities = []
    for name in entity_names(resolved):
        schema = load_schema(name, resolved)
        entities.append({
            "name": name,
            "title": schema.get("title", name),
            "description": schema.get("description", ""),
            "required": schema.get("required", []),
            "schema": f"{name}.schema.json",
        })

    supporting = []
    for name in SUPPORTING:
        try:
            schema = load_schema(name, resolved)
        except UnknownEntity:
            continue
        supporting.append({
            "name": name,
            "title": schema.get("title", name),
            "description": schema.get("description", ""),
            "schema": f"{name}.schema.json",
        })

    return {
        "nrm_version": resolved,
        "published_versions": list(versions()),
        "default_version": DEFAULT_VERSION,
        "entities": entities,
        "supporting": supporting,
    }


#: Formats the published schemas assert. Checked at startup because jsonschema degrades an
#: unrecognized format to a no-op annotation instead of raising -- so a missing extra makes the
#: contract quietly weaker while every response still says the format is enforced.
REQUIRED_FORMATS: tuple[str, ...] = ("date-time", "uri")


def self_check(version: str | None = None) -> list[str]:
    """Verify the schemas compile, every ``$ref`` resolves, and format assertions are real.

    Called from the startup gate. All three are deployment defects rather than runtime conditions,
    and each should stop the process rather than surface as a 500 -- or worse, as a silent pass --
    for the first team that validates a bundle against us.
    """
    problems: list[str] = []
    try:
        resolved = _require_version(version)
    except UnknownVersion as exc:
        return [str(exc)]

    from jsonschema import Draft202012Validator

    missing = [
        name
        for name in REQUIRED_FORMATS
        if name not in Draft202012Validator.FORMAT_CHECKER.checkers
    ]
    if missing:
        problems.append(
            f"jsonschema cannot check the format(s) {', '.join(missing)}, so those assertions in "
            "the published schemas would silently pass. Install the extra: "
            "pip install 'jsonschema[format-nongpl]'"
        )

    for name in (*entity_names(resolved), *SUPPORTING):
        try:
            validator(name, resolved)
        except UnknownEntity:
            continue
        except Exception as exc:  # noqa: BLE001 - reporting every problem beats stopping at the first
            problems.append(f"{name}.schema.json in {resolved}: {type(exc).__name__}: {exc}")

    return problems
