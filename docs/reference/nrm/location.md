---
diataxis: reference
nvsf_generated: contracts/nrm/v0.1/location.schema.json
---

# Location

:::{admonition} Generated page
:class: generated-page

This page is generated from `contracts/nrm/v0.1/location.schema.json` by `bin/gen-docs-reference.py`. Edits here are lost on the
next build, and CI fails if the two disagree — change the source.
:::

A place in a data centre, addressed the way an operator addresses it: site, room, row, rack, rack unit. Kept as its own entity rather than fields on Resource because many resources share one location, and because a location exists before anything is installed in it -- a rack position in a floor plan is a real thing to plan against.

Addressing INSIDE a chassis is not here. That is Redfish PartLocation on the Resource, because it is relative to a parent rather than to the building.

**Schema id:** `https://schemas.nvidia.com/nvis/nrm/v0.1/location.schema.json`

## Fields

| Field | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `id` | `uuid` | yes | — |  |
| `site` | `string` | yes | min length 1; max length 128 | Site code as the business uses it, not a street address. This is the field that appears in a ticket subject line. |
| `cooling_zone` | `string` | no | max length 128 | Facility cooling zone, typically the CDU or manifold group serving this position. |
| `coordinates` | `object` | no | — | Position within the room, for floor plans and cooling models. Room-relative metres rather than lat/long, because building-relative is what every facility drawing uses. |
| `external_refs` | `external_refs` | no | — |  |
| `grid_reference` | `string` | no | max length 64 | Floor tile or grid square, where the facility uses one. This is what a crane plan and a cooling survey are drawn against. |
| `labels` | `labels` | no | — |  |
| `observation` | `observation` | no | — |  |
| `power_zone` | `string` | no | max length 128 | Facility power zone or feed identifier. Present because 'which racks lose power together' is a question about the building, not about the racks, and it cannot be derived from anything else here. |
| `provenance` | `provenance` | no | — |  |
| `rack` | `string` | no | max length 128 | Rack label as printed on the rack. For an NVL72 this is the unit an entire validation campaign is scoped to, which is why it is a first-class field rather than a label. |
| `rack_face` | `string` | no | one of `front`, `rear` | Which side the resource is mounted on. Two resources may share a rack unit if they are on opposite faces, and a validation that ignores face will report a phantom collision. |
| `rack_unit` | `number` | no | min 0; max 60 | Lowest rack unit occupied, counting from the bottom, matching how racks are physically numbered and how NetBox stores position. Fractional for half-U placements. |
| `room` | `string` | no | max length 128 |  |
| `row` | `string` | no | max length 64 | Row label as painted on the floor or containment. |
| `timestamps` | `timestamps` | no | — |  |

This schema is closed: a property not listed above is a validation error. Tool-specific data belongs in `attributes`.
