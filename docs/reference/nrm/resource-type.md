---
diataxis: reference
nvsf_generated: contracts/nrm/v0.1/resource-type.schema.json
---

# ResourceType

:::{admonition} Generated page
:class: generated-page

This page is generated from `contracts/nrm/v0.1/resource-type.schema.json` by `bin/gen-docs-reference.py`. Edits here are lost on the
next build, and CI fails if the two disagree — change the source.
:::

The catalog object: a kind of thing, not a thing. One GB200 NVL72 compute tray SKU is one ResourceType; the seventy-two of them in a rack are seventy-two Resources pointing at it.

This split is where partner data lands. Dell, Supermicro and ASUS supply almost entirely type data -- dimensions, power draw, port layout, coolant requirements -- and almost no instance data beyond serials. Without the split, every partner datasheet fact would be copied onto every unit, and correcting a published power figure would mean an UPDATE across thousands of rows instead of one.

**Schema id:** `https://schemas.nvidia.com/nvis/nrm/v0.1/resource-type.schema.json`

## Fields

| Field | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `id` | `uuid` | yes | — |  |
| `manufacturer` | `string` | yes | min length 1; max length 128 | Who made it, as the name appears in contracts and on invoices: NVIDIA, Dell, Supermicro, ASUS, Vertiv, Amphenol. Not the reseller and not the integrator. |
| `model` | `string` | yes | min length 1; max length 256 | The manufacturer's model designation, verbatim. `GB200 NVL72` is a model; `gb200-nvl72-rack-v2-final` is a filename. |
| `resource_class` | `string` | yes | one of `site`, `room`, `row`, `rack`, `chassis`, `tray`, `node`, `board`, `gpu`, `cpu`, `dpu`, `nic`, `switch`, `switch_asic`, `nvlink_switch`, `transceiver`, `cable`, `cable_cartridge`, `power_shelf`, `power_supply`, `busbar`, `pdu`, `cdu`, `manifold`, `cold_plate`, `quick_disconnect`, `hose`, `fan`, `storage_device`, `bmc`, `other` | What kind of thing this is, coarsely. Deliberately a closed list: an open vocabulary here is how you end up with `switch`, `Switch`, `network-switch` and `tor` as four classes meaning one thing. Anything genuinely new is a contract change, which is a conversation worth having. |
| `attributes` | `object` | no | — | Type facts the model does not cover. Unlike labels, these are expected to be meaningful -- GPU count, memory capacity, NVLink generation -- and are the queue for the next contract version. |
| `cooling` | `object` | no | — | How this type must be cooled. Present on the type because it is a property of the design, and it is what determines whether a rack can be placed in a given room at all. |
| `datasheet_url` | `string` | no | format `uri`; max length 2048 |  |
| `external_refs` | `external_refs` | no | — |  |
| `identifiers` | `array` of `identifier` | no | — | Type-level identity. Rare but real: a cable SKU with an EUI range, a GPU SKU with a PCI device ID. Instance identity belongs on Resource. |
| `is_full_depth` | `boolean` | no | — |  |
| `labels` | `labels` | no | — |  |
| `lifecycle` | `string` | no | one of `proposed`, `qualified`, `shipping`, `end_of_sale`, `end_of_life` | Where the SKU is in ITS life, which is a different question from where any instance is. |
| `name` | `string` | no | max length 256 | Display name. Defaults to manufacturer plus model when absent; present so a site can carry the name its operators already use. |
| `part_number` | `string` | no | max length 128 | Orderable part number. This is the field procurement and the packing list agree on, which makes it the practical join between a delivery and an inventory record. |
| `partner` | `string` | no | max length 128 | The partner whose catalog this entry came from, when it is not the manufacturer -- an OEM rack integrator, for instance. Kept separate so partner-supplied data can be re-imported wholesale without touching NVIDIA-authored entries. |
| `port_templates` | `array` of `object` | no | — | The ports every instance of this type has. A tray SKU with four OSFP cages produces four Port records per instance, and generating them from the type is what makes a cabling plan checkable before any hardware arrives. |
| `power` | `object` | no | — | Nameplate figures from the datasheet, which are design limits rather than observed draw. Observed power is telemetry and does not belong in a catalog. |
| `provenance` | `provenance` | no | — |  |
| `timestamps` | `timestamps` | no | — |  |
| `u_height` | `number` | no | min 0; max 60 | Rack units consumed. Fractional is allowed and necessary: a 1U-per-two-node sled is 0.5. |
| `weight_kg` | `number` | no | min 0 |  |

This schema is closed: a property not listed above is a validation error. Tool-specific data belongs in `attributes`.
