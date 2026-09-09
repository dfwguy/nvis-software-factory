# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Does this repository produce data anyone else can consume?

Author: Rafael M. Koike & Cursor Agent ("Ada")

The pillar that addresses the duplication half of the problem, and the one where the factory has
something concrete to offer: it publishes the NVIS Resource Model, so a finding here comes with a
schema rather than only advice.

The interesting signal is *bespoke identity*. A repository that keeps its own list of node names
with its own spelling is a repository whose data cannot be joined to anyone else's. That is how
four teams end up with four inventories that disagree about how many trays a rack has.
"""

from __future__ import annotations

import re

from store.models import Severity

from .base import Fact, RepoView

PILLAR = "contract-conformance"

#: Identifier fields the NRM covers. If a repository names these, it has an identity model, and the
#: question is whether it is ours.
_IDENTITY_FIELDS = (
    "serial", "serial_number", "sn", "asset_tag", "uuid", "guid", "node_id", "host_id",
    "rack_id", "rack_name", "hostname", "bmc_ip", "gpu_uuid", "device_id", "port_id",
    "switch_name", "cable_id", "transceiver", "tray", "slot", "chassis_id", "nvlink",
)

_EXPORT_RE = re.compile(
    r"(?i)json\.dump|to_json|jsonify|csv\.(?:writer|DictWriter)|to_csv|yaml\.(?:safe_)?dump|"
    r"\.to_dict\(|dataclasses\.asdict|model_dump|\.json\(\)|write_parquet|to_excel"
)

_SCHEMA_RE = re.compile(
    r"(?i)jsonschema|pydantic|BaseModel|marshmallow|attrs|dataclass|TypedDict|voluptuous|"
    r"cerberus|zod|joi|ajv|openapi|swagger|protobuf|avro|\.proto\b|graphql"
)

_NRM_ADJACENT_SOURCES = (
    ("nautobot", "Nautobot"),
    ("netbox", "NetBox"),
    ("redfish", "Redfish"),
    ("ufm", "UFM"),
    ("dcgm", "DCGM"),
    ("bcm", "Base Command Manager"),
    ("ipmitool", "IPMI"),
    ("nvidia-smi", "nvidia-smi"),
    ("slurm", "Slurm"),
    ("sinfo", "Slurm"),
    ("mlxlink", "mlxlink"),
    ("ibdiagnet", "ibdiagnet"),
    ("nvlsm", "NVLink Subnet Manager"),
    ("prometheus", "Prometheus"),
    ("grafana", "Grafana"),
)

#: Ad-hoc rack or node naming in string literals. The specific spellings that do not join.
_AD_HOC_NAMING_RE = re.compile(
    r"""(?ix)
    ["'] (?:
        (?: rack | rk | r ) [-_ ]? \d+
      | (?: node | nd | n ) [-_ ]? \d+
      | (?: tray | tr ) [-_ ]? \d+
      | (?: gb | nvl ) \d+ [-_ ]? \w*
    ) ["']
    """
)


def scan(view: RepoView) -> list[Fact]:
    facts: list[Fact] = []
    code = view.code_files()
    haystack = " ".join(view.read(f) or "" for f in code)
    manifests = " ".join(view.read(f) or "" for f in view.find_names(
        "requirements.txt", "pyproject.toml", "package.json", "go.mod",
    ))

    # ── K1: does it export data, and is the shape defined ────────────────────────────────────
    exports = view.grep(_EXPORT_RE, code, limit=40)
    schema_signals = sorted({
        match.group(0).lower()
        for relative in code
        for match in [_SCHEMA_RE.search(view.read(relative) or "")]
        if match
    })
    openapi_files = view.find_names("openapi.json", "openapi.yaml", "openapi.yml",
                                    "swagger.json", "swagger.yaml")
    schema_files = [f for f in view.files()
                    if re.search(r"(?i)schema.*\.(?:json|ya?ml)$|\.schema\.json$", f)]

    if exports:
        defined = bool(schema_signals or openapi_files or schema_files)
        facts.append(Fact(
            pillar_id=PILLAR, key="export_without_schema" if not defined else "export_with_schema",
            title=(
                f"Data is exported at {len(exports)} site(s) with no declared schema"
                if not defined else
                f"Data is exported at {len(exports)} site(s); schema definitions present"
            ),
            detail=(
                "The output shape is whatever the code happens to produce, so a consumer has to "
                "infer it from a sample, and a rename in this repository silently breaks them. "
                "That is how two teams end up parsing each other's output with regular "
                "expressions."
                if not defined else
                f"Signals: {', '.join(sorted(set(schema_signals))[:6]) or 'schema files'}. "
                f"{', '.join(openapi_files + schema_files[:3]) if openapi_files or schema_files else ''}"
            ),
            criterion="K1",
            severity=Severity.MINOR if not defined else None,
            file_path=exports[0][0], line_start=exports[0][1],
            remediation=(
                "Declare the output shape and validate against it before writing. The NVIS "
                "Resource Model at /contracts covers physical inventory; a repository that emits "
                "it becomes joinable to every other team's data instead of a parsing exercise."
            ) if not defined else None,
            data={
                "export_sites": [f"{p}:{n}" for p, n, _ in exports[:12]],
                "schema_signals": sorted(set(schema_signals))[:10],
                "schema_files": openapi_files + schema_files[:5],
            },
        ))

    # ── K2: identity fields, and whether they are ours ───────────────────────────────────────
    identity_hits: dict[str, int] = {}
    for name in _IDENTITY_FIELDS:
        count = view.count_matches(rf"['\"]?\b{re.escape(name)}\b['\"]?\s*[:=]", code)
        if count:
            identity_hits[name] = count

    if identity_hits:
        uses_nrm = bool(re.search(r"(?i)nvis[-_ ]?resource[-_ ]?model|\bNRM\b|nrm/v\d",
                                  haystack))
        top = sorted(identity_hits.items(), key=lambda kv: -kv[1])[:10]
        facts.append(Fact(
            pillar_id=PILLAR, key="identity_model",
            title=(
                f"{len(identity_hits)} identity field(s) with a repository-local naming scheme"
                if not uses_nrm else
                "Identity fields reference the NVIS Resource Model"
            ),
            detail=(
                "Fields: " + ", ".join(f"{name} ({count})" for name, count in top)
                + (". These name the same physical things every other team names, with a "
                   "spelling chosen here. Joining this data to another team's requires a "
                   "hand-written mapping per pair of tools, which is where the duplicated "
                   "sources of truth come from."
                   if not uses_nrm else ".")
            ),
            criterion="K2",
            severity=Severity.MINOR if not uses_nrm else None,
            remediation=(
                "Adopt the NRM identifier envelope: a stable internal id plus an `identifiers[]` "
                "list carrying the real-world names (serial, GPU UUID, IB GUID) with their type. "
                "That keeps your local names working while making the data joinable. Fetch the "
                "schema from /api/contracts and hand the agent pack to your coding agent."
            ) if not uses_nrm else None,
            data={"fields": dict(top), "references_nrm": uses_nrm},
        ))

    ad_hoc = view.grep(_AD_HOC_NAMING_RE, code, limit=30)
    if ad_hoc and len(ad_hoc) > 3:
        facts.append(Fact(
            pillar_id=PILLAR, key="ad_hoc_resource_naming",
            title=f"{len(ad_hoc)} literal rack/node/tray name(s) in source",
            detail=(
                "Physical topology encoded as string literals. Beyond the portability problem, "
                "each spelling is a private convention that has to be reconciled by hand when "
                "the data meets another team's."
            ),
            criterion="K2",
            file_path=ad_hoc[0][0], line_start=ad_hoc[0][1],
            excerpt=view.excerpt(ad_hoc[0][0], ad_hoc[0][1]),
            data={"sites": [f"{p}:{n}" for p, n, _ in ad_hoc[:12]]},
        ))

    # ── K3: input validation at the boundary ─────────────────────────────────────────────────
    ingests = view.grep(
        r"(?i)json\.load|yaml\.(?:safe_)?load|csv\.(?:reader|DictReader)|read_csv|"
        r"request\.(?:json|form|args|data)|argparse|sys\.argv",
        code, limit=40,
    )
    if ingests:
        validates = bool(re.search(
            r"(?i)jsonschema\.validate|validate\(|BaseModel|model_validate|parse_obj|"
            r"schema\.load|Draft\d+Validator|ajv|zod\.|assert_valid",
            haystack,
        ))
        facts.append(Fact(
            pillar_id=PILLAR, key="input_validation",
            title=(
                f"External input read at {len(ingests)} site(s) with no schema validation"
                if not validates else
                "External input is validated against a schema"
            ),
            detail=(
                "Malformed input fails somewhere downstream, as an AttributeError or a KeyError "
                "on a line that has nothing to do with the actual problem. The person debugging "
                "it is usually not the person who produced the file."
                if not validates else
                "Validation signals found in the repository."
            ),
            criterion="K3",
            severity=Severity.MINOR if not validates else None,
            file_path=ingests[0][0], line_start=ingests[0][1],
            remediation=(
                "Validate at the boundary and reject with a message naming the field and the "
                "expected type. `jsonschema.validate` against a published schema turns a "
                "confusing traceback into a sentence the producer can act on."
            ) if not validates else None,
            data={"ingest_sites": [f"{p}:{n}" for p, n, _ in ingests[:12]]},
        ))

    # ── K4: API versioning ───────────────────────────────────────────────────────────────────
    routes = view.grep(r"""(?i)@\w+\.route\s*\(\s*["']|@(?:app|router)\.(?:get|post)\s*\(\s*["']""",
                       code, limit=60)
    if routes:
        versioned = view.count_matches(r"""(?i)["']/(?:api/)?v\d|/v\d/|version\s*=\s*["']v?\d""",
                                       code)
        facts.append(Fact(
            pillar_id=PILLAR, key="api_versioning",
            title=f"{len(routes)} route(s), " + (
                "versioned" if versioned else "with no version in the path"),
            detail=(
                "Without a version, the only way to change a response shape is to break every "
                "consumer at once, so in practice the shape never changes and workarounds "
                "accumulate on the client side."
                if not versioned else
                f"{versioned} version marker(s) found."
            ),
            criterion="K4",
            severity=Severity.MINOR if not versioned else None,
            remediation=(
                "Put a version in the path. Additive changes stay in place; a breaking change "
                "gets a new version and the old one keeps working while consumers migrate."
            ) if not versioned else None,
            data={"route_count": len(routes), "version_markers": versioned},
        ))

    # ── K5: which NVIS data sources this repository already touches ──────────────────────────
    touched = sorted({
        label for token, label in _NRM_ADJACENT_SOURCES
        if token in haystack.lower() or token in manifests.lower()
    })
    if touched:
        facts.append(Fact(
            pillar_id=PILLAR, key="nvis_data_sources",
            title=f"Touches {len(touched)} known NVIS data source(s): {', '.join(touched)}",
            detail=(
                "Each of these has a crosswalk in the NRM, so mapping this repository's data onto "
                "the contract is largely a lookup rather than a design exercise. This is also the "
                "strongest signal that the repository is in scope for the contract at all."
            ),
            criterion="K5",
            data={"sources": touched},
        ))

    return facts
