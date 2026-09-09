---
diataxis: reference
nvsf_generated: contracts/nrm/v0.1/port.schema.json
---

# Port

:::{admonition} Generated page
:class: generated-page

This page is generated from `contracts/nrm/v0.1/port.schema.json` by `bin/gen-docs-reference.py`. Edits here are lost on the
next build, and CI fails if the two disagree — change the source.
:::

A termination point on a resource, in the RFC 8345 sense: the thing a Link attaches to. Ports are modelled separately from Links so that an uncabled port is still a fact -- 'this switch has sixteen OSFP cages and four are empty' is exactly what a bring-up needs to know, and a link-only model cannot say it.

`port_class` spans network, PCIe, power, coolant and console on purpose. A coolant inlet and an OSFP cage have nothing physically in common, but they play the identical role in the topology graph, and one termination-point entity means reachability, expected-versus-observed and cable tracing work the same way for both. This is the IT/OT convergence, expressed in the data model rather than in a dashboard.

**Schema id:** `https://schemas.nvidia.com/nvis/nrm/v0.1/port.schema.json`

## Fields

| Field | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `id` | `uuid` | yes | — |  |
| `name` | `string` | yes | min length 1; max length 128 | Port name as the device reports it and as the label reads: `OSFP1`, `eth0`, `mlx5_0`, `INLET_A`. Unique within its resource. |
| `port_class` | `string` | yes | one of `ethernet`, `infiniband`, `nvlink`, `pcie`, `power`, `coolant`, `console`, `management`, `usb`, `other` | What kind of connection terminates here. Closed list, because the class determines which validations apply and an unrecognized class would silently skip all of them. |
| `resource_id` | `uuid` | yes | — | The resource this port is on. |
| `admin_state` | `string` | no | one of `enabled`, `disabled` | Intended state. Separate from operational state, which is telemetry: a port that is administratively down is correct, and a monitoring system that conflates the two pages someone at 3am for a deliberate configuration. |
| `attributes` | `object` | no | — |  |
| `breakout_of` | `one of` | no | — | The physical parent port, when this is one channel of a breakout. A 4x split OSFP is one physical cage and four logical ports, and both views have to exist: the cage is what gets cabled, the channels are what come up. |
| `external_refs` | `external_refs` | no | — |  |
| `identifiers` | `array` of `identifier` | no | — | Port-level identity. IB_GUID and MACAddress are the common cases, and they are what discovery output joins on. |
| `index` | `integer` | no | min 0 | Ordinal position, for ports whose name does not sort usefully. `OSFP10` sorts before `OSFP2` as a string, and a cabling report in that order is unusable. |
| `labels` | `labels` | no | — |  |
| `lanes` | `integer` | no | min 1; max 32 | Lane count, for split or breakout ports. |
| `media` | `string` | no | one of `osfp`, `qsfp112`, `qsfp56`, `qsfp28`, `sfp112`, `sfp56`, `sfp28`, `rj45`, `dac`, `aoc`, `mpo`, `lc`, `backplane`, `nvlink_cartridge`, `busbar`, `c13`, `c19`, `quick_disconnect`, `hose_barb`, `other` | Physical medium or connector. Needed because a cabling plan that matches port names but mismatches media is a plan that fails at install time. |
| `observation` | `observation` | no | — |  |
| `part_location` | `part_location` | no | — | Where the cage or connector physically sits, for a port on a large chassis where the name alone does not locate it. |
| `provenance` | `provenance` | no | — |  |
| `speed_gbps` | `number` | no | min 0 | Configured or negotiated speed. On an `expected` record this is the design speed; on an `observed` record it is what the link actually came up at, and the difference is one of the most common real defects. |
| `timestamps` | `timestamps` | no | — |  |

This schema is closed: a property not listed above is a validation error. Tool-specific data belongs in `attributes`.
