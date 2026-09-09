#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Generate the GB200 NVL72 reference fixture for NRM v0.1.

Author: Rafael M. Koike & Cursor Agent ("Ada")

The reference fixture is a whole GB200 NVL72 rack expressed in NRM: 18 compute trays, 72 GPUs, 36
Grace CPUs, 9 NVLink switch trays, the compute-side IB fabric ports, power shelves, and the liquid
cooling path serving the rack.

It is GENERATED rather than hand-written for one reason: a hand-written fixture of this size is
wrong in ways nobody notices. Seventy-two GPUs means seventy-two UUIDs, seventy-two parent
references and seventy-two part locations, and a transposed digit in any of them produces a fixture
that validates but does not describe a real rack. Generating it means the rack's structure is
stated once, as code, where it can be read and argued with.

IDs are deterministic -- derived from a fixed seed, not minted -- so regenerating produces a
byte-identical file and the fixture's diff stays empty when nothing about the rack changed. That is
what makes `--check` meaningful in CI.

Why a real rack and not a toy: this fixture is the round-trip test's input, and a three-record toy
would exercise none of the things that actually break. Deep containment, breakout ports, links that
layer over a physical cartridge, and a cooling path with a real blast radius are the whole point.

Usage:
    bin/gen-nvl72-fixture.py            # write the fixture
    bin/gen-nvl72-fixture.py --check    # exit non-zero if the committed file is stale
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from contracts import identity  # noqa: E402  (path must be set first)

OUTPUT = REPO_ROOT / "contracts" / "fixtures" / "nvl72-rack.json"

#: Fixed namespace for deterministic IDs. UUIDv5 of a stable name gives the same UUID every run,
#: which is what keeps the generated file byte-identical. Real records get a minted UUIDv7 from
#: contracts.identity.new_id; a fixture deliberately does not, because a fixture whose IDs churn
#: on every regeneration produces a diff nobody can review.
_NAMESPACE = uuid.UUID("6f0d1e2a-8b3c-4d5e-9f70-1a2b3c4d5e6f")

# ── The rack, stated once ────────────────────────────────────────────────────────────────────
#
# Figures are the published GB200 NVL72 configuration. Where a number here is wrong, this is the
# one place to fix it.

SITE = "NSCALE-PT1"
RACK = "R14"
COMPUTE_TRAYS = 18
GPUS_PER_TRAY = 4
CPUS_PER_TRAY = 2
NVSWITCH_TRAYS = 9
NVSWITCH_ASICS_PER_TRAY = 2
POWER_SHELVES = 8
#: Compute-fabric ports per tray: 4x ConnectX-7/8 for the east-west fabric.
IB_PORTS_PER_TRAY = 4
#: One NVLink cable cartridge per compute tray connecting it to the switch spine.
CARTRIDGES = COMPUTE_TRAYS


def ident(*parts: Any) -> str:
    """A deterministic UUID for a fixture record, from its logical path."""
    return str(uuid.uuid5(_NAMESPACE, ":".join(str(part) for part in parts)))


def serial(prefix: str, index: int) -> str:
    """A plausible, obviously-fake serial. Fake on purpose: a fixture must not carry a real one."""
    return f"{prefix}{1440000 + index:07d}"


def build() -> dict[str, Any]:
    """Assemble the bundle. Order within each collection is stable, so the diff is readable."""
    resource_types: list[dict[str, Any]] = []
    locations: list[dict[str, Any]] = []
    domains: list[dict[str, Any]] = []
    resources: list[dict[str, Any]] = []
    ports: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    cooling_paths: list[dict[str, Any]] = []

    provenance = {
        "source": "manual",
        "source_ref": "bin/gen-nvl72-fixture.py",
        "collected_at": "2026-01-15T00:00:00Z",
        "collected_by": "gen-nvl72-fixture.py 0.1",
    }

    # ── Types ────────────────────────────────────────────────────────────────────────────────
    type_ids = {
        name: ident("resource-type", name)
        for name in (
            "rack", "compute-tray", "gpu", "cpu", "nvswitch-tray", "nvswitch-asic",
            "cx7", "power-shelf", "cdu", "manifold", "cartridge",
        )
    }

    resource_types += [
        {
            "id": type_ids["rack"],
            "resource_class": "rack",
            "manufacturer": "NVIDIA",
            "model": "GB200 NVL72",
            "part_number": "NVL72-GB200",
            "u_height": 48,
            "is_full_depth": True,
            "power": {"max_watts": 132000, "thermal_design_watts": 120000},
            "cooling": {
                "method": "liquid_dlc",
                "coolant": "pg25",
                "min_flow_lpm": 180,
                "max_inlet_temp_c": 32,
            },
            "lifecycle": "shipping",
            "provenance": provenance,
        },
        {
            "id": type_ids["compute-tray"],
            "resource_class": "tray",
            "manufacturer": "NVIDIA",
            "model": "GB200 Compute Tray",
            "part_number": "NVL72-CT-GB200",
            "u_height": 1,
            "power": {"max_watts": 5600, "thermal_design_watts": 5400},
            "cooling": {"method": "liquid_dlc", "coolant": "pg25", "min_flow_lpm": 9},
            "port_templates": [
                {
                    "name": "OSFP{n}",
                    "port_class": "infiniband",
                    "count": IB_PORTS_PER_TRAY,
                    "media": "osfp",
                    "speed_gbps": 400,
                    "lanes": 4,
                },
                {"name": "NVLINK", "port_class": "nvlink", "media": "nvlink_cartridge"},
                {"name": "INLET", "port_class": "coolant", "media": "quick_disconnect"},
                {"name": "OUTLET", "port_class": "coolant", "media": "quick_disconnect"},
                {"name": "BMC", "port_class": "management", "media": "rj45", "speed_gbps": 1},
            ],
            "lifecycle": "shipping",
            "provenance": provenance,
        },
        {
            "id": type_ids["gpu"],
            "resource_class": "gpu",
            "manufacturer": "NVIDIA",
            "model": "Blackwell B200",
            "power": {"max_watts": 1200, "thermal_design_watts": 1000},
            "cooling": {"method": "liquid_dlc", "coolant": "pg25"},
            "lifecycle": "shipping",
            "provenance": provenance,
        },
        {
            "id": type_ids["cpu"],
            "resource_class": "cpu",
            "manufacturer": "NVIDIA",
            "model": "Grace CPU",
            "power": {"max_watts": 500, "thermal_design_watts": 400},
            "lifecycle": "shipping",
            "provenance": provenance,
        },
        {
            "id": type_ids["nvswitch-tray"],
            "resource_class": "tray",
            "manufacturer": "NVIDIA",
            "model": "NVLink Switch Tray",
            "part_number": "NVL72-NVS",
            "u_height": 1,
            "power": {"max_watts": 1600, "thermal_design_watts": 1500},
            "cooling": {"method": "liquid_dlc", "coolant": "pg25", "min_flow_lpm": 4},
            "lifecycle": "shipping",
            "provenance": provenance,
        },
        {
            "id": type_ids["nvswitch-asic"],
            "resource_class": "nvlink_switch",
            "manufacturer": "NVIDIA",
            "model": "NVSwitch4",
            "power": {"thermal_design_watts": 700},
            "lifecycle": "shipping",
            "provenance": provenance,
        },
        {
            "id": type_ids["cx7"],
            "resource_class": "nic",
            "manufacturer": "NVIDIA",
            "model": "ConnectX-7 400G",
            "part_number": "MCX75310AAS-NEAT",
            "port_templates": [
                {"name": "OSFP1", "port_class": "infiniband", "media": "osfp", "speed_gbps": 400}
            ],
            "lifecycle": "shipping",
            "provenance": provenance,
        },
        {
            "id": type_ids["power-shelf"],
            "resource_class": "power_shelf",
            "manufacturer": "NVIDIA",
            "model": "NVL72 Power Shelf",
            "u_height": 1,
            "power": {"max_watts": 33000, "input_voltage": "415VAC", "phases": 3},
            "lifecycle": "shipping",
            "provenance": provenance,
        },
        {
            "id": type_ids["cdu"],
            "resource_class": "cdu",
            "manufacturer": "Vertiv",
            "model": "CDU-1MW",
            "cooling": {
                "method": "liquid_dlc", "coolant": "pg25", "min_flow_lpm": 400,
                "max_inlet_temp_c": 32, "max_pressure_kpa": 600,
            },
            "lifecycle": "shipping",
            "provenance": provenance,
        },
        {
            "id": type_ids["manifold"],
            "resource_class": "manifold",
            "manufacturer": "NVIDIA",
            "model": "NVL72 Rack Manifold",
            "u_height": 0,
            "lifecycle": "shipping",
            "provenance": provenance,
        },
        {
            "id": type_ids["cartridge"],
            "resource_class": "cable_cartridge",
            "manufacturer": "Amphenol",
            "model": "NVLink Cable Cartridge",
            "part_number": "NVL72-NVLC",
            "lifecycle": "shipping",
            "provenance": provenance,
        },
    ]

    # ── Location and domains ─────────────────────────────────────────────────────────────────
    rack_location_id = ident("location", SITE, RACK)
    locations.append({
        "id": rack_location_id,
        "site": SITE,
        "room": "DH1",
        "row": "R",
        "rack": RACK,
        "rack_unit": 1,
        "rack_face": "front",
        "power_zone": "PZ-A",
        "cooling_zone": "CDU-01",
        "observation": "observed",
        "provenance": provenance,
    })

    compute_domain_id = ident("domain", "compute", RACK)
    nvlink_domain_id = ident("domain", "nvlink", RACK)
    ib_domain_id = ident("domain", "ib_fabric", SITE)
    domains += [
        {
            "id": compute_domain_id,
            "name": f"{RACK}-compute",
            "domain_class": "compute",
            "scope": SITE,
            "owner": "NVIS OVA",
            "observation": "observed",
            "provenance": provenance,
        },
        {
            "id": nvlink_domain_id,
            "name": f"{RACK}-nvlink",
            "domain_class": "nvlink",
            "scope": RACK,
            "owner": "NVIS OVA",
            "observation": "observed",
            "provenance": provenance,
            "attributes": {
                "note": (
                    "An NVL72's NVLink domain is coextensive with the rack, which is why the rack "
                    "is the unit a validation campaign is scoped to."
                ),
            },
        },
        {
            "id": ib_domain_id,
            "name": f"{SITE}-compute-fabric",
            "domain_class": "ib_fabric",
            "scope": SITE,
            "owner": "NVIS IB",
            "observation": "observed",
            "provenance": provenance,
        },
    ]

    # ── The rack itself ──────────────────────────────────────────────────────────────────────
    rack_id = ident("resource", "rack", RACK)
    resources.append({
        "id": rack_id,
        "resource_type_id": type_ids["rack"],
        "parent_id": None,
        "name": RACK,
        "location_id": rack_location_id,
        "domain_id": compute_domain_id,
        "lifecycle": "active",
        "observation": "observed",
        "identifiers": [
            {"format": "SERIAL", "value": serial("NVL", 14), "scope": "NVIDIA", "source": "packing-list"},
        ],
        "provenance": provenance,
    })

    manifold_id = ident("resource", "manifold", RACK)
    resources.append({
        "id": manifold_id,
        "resource_type_id": type_ids["manifold"],
        "parent_id": rack_id,
        "name": f"{RACK}-MANIFOLD",
        "lifecycle": "active",
        "observation": "observed",
        "provenance": provenance,
    })

    # ── Compute trays, and everything inside them ────────────────────────────────────────────
    for tray in range(1, COMPUTE_TRAYS + 1):
        tray_name = f"{RACK}-CT{tray:02d}"
        tray_id = ident("resource", "compute-tray", tray)
        resources.append({
            "id": tray_id,
            "resource_type_id": type_ids["compute-tray"],
            "parent_id": rack_id,
            "name": tray_name,
            "domain_id": compute_domain_id,
            "lifecycle": "active",
            "observation": "observed",
            "part_location": {
                "service_label": f"CT{tray:02d}",
                "location_type": "Slot",
                "location_ordinal_value": tray - 1,
            },
            "identifiers": [
                {"format": "SERIAL", "value": serial("CT", tray), "scope": "NVIDIA"},
                {
                    "format": "MACAddress",
                    "value": f"48:b0:2d:{RACK[1:]:>02}:{tray:02x}:00",
                    "source": "bcm-netautogen",
                },
            ],
            "provenance": provenance,
        })

        for cpu in range(CPUS_PER_TRAY):
            resources.append({
                "id": ident("resource", "cpu", tray, cpu),
                "resource_type_id": type_ids["cpu"],
                "parent_id": tray_id,
                "name": f"{tray_name}-CPU{cpu}",
                "lifecycle": "active",
                "observation": "observed",
                "part_location": {
                    "location_type": "Socket", "location_ordinal_value": cpu,
                },
                "provenance": provenance,
            })

        for gpu in range(GPUS_PER_TRAY):
            index = (tray - 1) * GPUS_PER_TRAY + gpu
            resources.append({
                "id": ident("resource", "gpu", tray, gpu),
                "resource_type_id": type_ids["gpu"],
                "parent_id": tray_id,
                "name": f"{tray_name}-GPU{gpu}",
                "domain_id": nvlink_domain_id,
                "lifecycle": "active",
                "observation": "observed",
                "part_location": {
                    "location_type": "Socket", "location_ordinal_value": gpu,
                },
                "identifiers": [
                    {
                        # The GPU- prefix is kept verbatim: it is present in nvidia-smi, in DCGM
                        # labels and in NVML, so stripping it would break every existing join.
                        "format": "GPU_UUID",
                        "value": f"GPU-{uuid.uuid5(_NAMESPACE, f'gpu:{tray}:{gpu}')}",
                        "source": "dcgm",
                    },
                    {"format": "SERIAL", "value": serial("GB", index), "scope": "NVIDIA"},
                ],
                "provenance": provenance,
            })

        # Coolant ports. Modelled as Ports so the cooling path traverses the same graph as the
        # fabric -- this is the IT/OT convergence expressed in data rather than in a dashboard.
        for role, label in (("INLET", "inlet"), ("OUTLET", "outlet")):
            ports.append({
                "id": ident("port", "coolant", tray, role),
                "resource_id": tray_id,
                "name": role,
                "port_class": "coolant",
                "media": "quick_disconnect",
                "observation": "observed",
                "labels": {"role": label},
                "provenance": provenance,
            })

        # Compute-fabric ports, one per ConnectX adapter.
        for nic_index in range(1, IB_PORTS_PER_TRAY + 1):
            nic_id = ident("resource", "cx7", tray, nic_index)
            resources.append({
                "id": nic_id,
                "resource_type_id": type_ids["cx7"],
                "parent_id": tray_id,
                "name": f"{tray_name}-CX{nic_index}",
                "domain_id": ib_domain_id,
                "lifecycle": "active",
                "observation": "observed",
                "part_location": {
                    "location_type": "Slot", "location_ordinal_value": nic_index - 1,
                },
                "provenance": provenance,
            })
            ports.append({
                "id": ident("port", "ib", tray, nic_index),
                "resource_id": nic_id,
                "name": f"OSFP{nic_index}",
                "port_class": "infiniband",
                "media": "osfp",
                "index": nic_index,
                "speed_gbps": 400,
                "lanes": 4,
                "admin_state": "enabled",
                "observation": "observed",
                "identifiers": [{
                    "format": "IB_GUID",
                    "value": f"0x{(0xe8ebd30003000000 + tray * 16 + nic_index):016x}",
                    "source": "ufm",
                }],
                "provenance": provenance,
            })

        # NVLink port, and the physical cartridge carrying it.
        ports.append({
            "id": ident("port", "nvlink", tray),
            "resource_id": tray_id,
            "name": "NVLINK",
            "port_class": "nvlink",
            "media": "nvlink_cartridge",
            "observation": "observed",
            "provenance": provenance,
        })

    # ── NVLink switch trays ──────────────────────────────────────────────────────────────────
    for switch in range(1, NVSWITCH_TRAYS + 1):
        switch_name = f"{RACK}-NVS{switch:02d}"
        switch_tray_id = ident("resource", "nvswitch-tray", switch)
        resources.append({
            "id": switch_tray_id,
            "resource_type_id": type_ids["nvswitch-tray"],
            "parent_id": rack_id,
            "name": switch_name,
            "domain_id": nvlink_domain_id,
            "lifecycle": "active",
            "observation": "observed",
            "part_location": {
                "service_label": f"NVS{switch:02d}",
                "location_type": "Slot",
                "location_ordinal_value": switch - 1,
            },
            "identifiers": [
                {"format": "SERIAL", "value": serial("NVS", switch), "scope": "NVIDIA"},
            ],
            "provenance": provenance,
        })

        for asic in range(NVSWITCH_ASICS_PER_TRAY):
            resources.append({
                "id": ident("resource", "nvswitch-asic", switch, asic),
                "resource_type_id": type_ids["nvswitch-asic"],
                "parent_id": switch_tray_id,
                "name": f"{switch_name}-ASIC{asic}",
                "domain_id": nvlink_domain_id,
                "lifecycle": "active",
                "observation": "observed",
                "part_location": {"location_type": "Embedded", "location_ordinal_value": asic},
                "identifiers": [{
                    "format": "NVLINK_GUID",
                    "value": f"0x{(0xb8cef60005000000 + switch * 8 + asic):016x}",
                }],
                "provenance": provenance,
            })

        # One NVLink port per compute tray this switch serves, expressed as two ports here to keep
        # the fixture reviewable. The real spine is fully connected; the fixture's job is to
        # exercise the SHAPE -- layered links over a cartridge -- not to enumerate every trace.
        for slot in range(1, 3):
            ports.append({
                "id": ident("port", "nvlink-switch", switch, slot),
                "resource_id": switch_tray_id,
                "name": f"NVLINK{slot}",
                "port_class": "nvlink",
                "media": "nvlink_cartridge",
                "index": slot,
                "observation": "observed",
                "provenance": provenance,
            })

    # ── Power shelves ────────────────────────────────────────────────────────────────────────
    for shelf in range(1, POWER_SHELVES + 1):
        resources.append({
            "id": ident("resource", "power-shelf", shelf),
            "resource_type_id": type_ids["power-shelf"],
            "parent_id": rack_id,
            "name": f"{RACK}-PS{shelf:02d}",
            "lifecycle": "active",
            "observation": "observed",
            "part_location": {
                "service_label": f"PS{shelf:02d}",
                "location_type": "Slot",
                "location_ordinal_value": shelf - 1,
            },
            "identifiers": [{"format": "SERIAL", "value": serial("PS", shelf), "scope": "NVIDIA"}],
            "provenance": provenance,
        })

    # ── NVLink cartridges, and the layered links they carry ──────────────────────────────────
    #
    # This is the part of the fixture that earns it. Each cartridge is a serialized, replaceable,
    # individually failing part, so it gets its own Resource. The physical link runs between a
    # compute tray and a switch tray; the logical NVLink is a SEPARATE link that declares the
    # physical one as its support. Without that layering, "six NVLink faults, one bad cartridge"
    # is an investigation instead of a query.
    resource_names = {record["id"]: record["name"] for record in resources}
    port_by_id = {record["id"]: record for record in ports}

    for tray in range(1, CARTRIDGES + 1):
        switch = ((tray - 1) % NVSWITCH_TRAYS) + 1
        slot = 1 if tray <= NVSWITCH_TRAYS else 2

        cartridge_id = ident("resource", "cartridge", tray)
        resources.append({
            "id": cartridge_id,
            "resource_type_id": type_ids["cartridge"],
            "parent_id": rack_id,
            "name": f"{RACK}-NVLC{tray:02d}",
            "lifecycle": "active",
            "observation": "observed",
            "identifiers": [
                {"format": "SERIAL", "value": serial("NVLC", tray), "scope": "Amphenol"},
            ],
            "provenance": provenance,
        })

        tray_port = port_by_id[ident("port", "nvlink", tray)]
        switch_port = port_by_id[ident("port", "nvlink-switch", switch, slot)]

        physical_key = identity.link_key(
            a_resource=resource_names[tray_port["resource_id"]],
            a_port=tray_port["name"],
            b_resource=resource_names[switch_port["resource_id"]],
            b_port=switch_port["name"],
        )
        physical_id = ident("link", "cartridge", tray)
        links.append({
            "id": physical_id,
            "key": physical_key,
            "a_port_id": tray_port["id"],
            "b_port_id": switch_port["id"],
            "link_class": "nvlink",
            "observation": "observed",
            "operational_state": "up",
            "cable": {
                "cable_type": "NVLink cable cartridge",
                "part_number": "NVL72-NVLC",
                "manufacturer": "Amphenol",
                "resource_id": cartridge_id,
            },
            "provenance": provenance,
        })
        links.append({
            "id": ident("link", "nvlink-logical", tray),
            "key": physical_key,
            "a_port_id": tray_port["id"],
            "b_port_id": switch_port["id"],
            "link_class": "nvlink",
            "supporting_link_id": physical_id,
            "speed_gbps": 1800,
            "observation": "observed",
            "operational_state": "up",
            "provenance": provenance,
        })

    # ── The cooling path ─────────────────────────────────────────────────────────────────────
    #
    # `cooled_resource_ids` covers every compute and switch tray, which is what makes a flow
    # deficit at the CDU into a computable blast radius rather than a phone call.
    cdu_id = ident("resource", "cdu", 1)
    resources.append({
        "id": cdu_id,
        "resource_type_id": type_ids["cdu"],
        "parent_id": None,
        "name": "CDU-01",
        "location_id": rack_location_id,
        "lifecycle": "active",
        "observation": "observed",
        "identifiers": [{"format": "SERIAL", "value": serial("CDU", 1), "scope": "Vertiv"}],
        "provenance": provenance,
    })

    cooled = [
        ident("resource", "compute-tray", tray) for tray in range(1, COMPUTE_TRAYS + 1)
    ] + [
        ident("resource", "nvswitch-tray", switch) for switch in range(1, NVSWITCH_TRAYS + 1)
    ]

    cooling_paths.append({
        "id": ident("cooling-path", "cdu-01", "a"),
        "name": "CDU-01 secondary loop A",
        "source_resource_id": cdu_id,
        "loop": "technology_secondary",
        "feed_resource_ids": [manifold_id],
        "intake_port_id": ident("port", "coolant", 1, "INLET"),
        "outflow_port_id": ident("port", "coolant", 1, "OUTLET"),
        "cooled_resource_ids": cooled,
        "coolant": "pg25",
        "design": {
            "flow_lpm": 180,
            "supply_temp_c": 32,
            "return_temp_c": 45,
            "pressure_kpa": 450,
            "delta_p_kpa": 120,
            # Sized above the summed TDP of what it cools: 18 trays at 5.4 kW plus 9 switch
            # trays at 1.5 kW is 110.7 kW, so 120 kW is the design margin.
            "heat_capacity_kw": 120,
        },
        "redundancy": "n_plus_1",
        "observation": "observed",
        "provenance": provenance,
    })

    return {
        "nrm_version": "v0.1",
        "generated_at": "2026-01-15T00:00:00Z",
        "generated_by": "bin/gen-nvl72-fixture.py 0.1",
        "observation": "observed",
        "resource_types": resource_types,
        "locations": locations,
        "domains": domains,
        "resources": resources,
        "ports": ports,
        "links": links,
        "cooling_paths": cooling_paths,
    }


def render() -> str:
    return json.dumps(build(), indent=2, sort_keys=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the committed fixture differs from what would be generated",
    )
    args = parser.parse_args()

    rendered = render()

    if args.check:
        if not OUTPUT.is_file():
            print(f"MISSING: {OUTPUT.relative_to(REPO_ROOT)}", file=sys.stderr)
            print("Run: bin/gen-nvl72-fixture.py", file=sys.stderr)
            return 1
        if OUTPUT.read_text(encoding="utf-8") != rendered:
            print(f"STALE: {OUTPUT.relative_to(REPO_ROOT)}", file=sys.stderr)
            print("Run: bin/gen-nvl72-fixture.py", file=sys.stderr)
            return 1
        print(f"up to date: {OUTPUT.relative_to(REPO_ROOT)}")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")
    document = build()
    print(
        f"wrote {OUTPUT.relative_to(REPO_ROOT)}: "
        f"{len(document['resources'])} resources, {len(document['ports'])} ports, "
        f"{len(document['links'])} links"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
