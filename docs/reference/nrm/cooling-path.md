---
diataxis: reference
nvsf_generated: contracts/nrm/v0.1/cooling-path.schema.json
---

# CoolingPath

:::{admonition} Generated page
:class: generated-page

This page is generated from `contracts/nrm/v0.1/cooling-path.schema.json` by `bin/gen-docs-reference.py`. Edits here are lost on the
next build, and CI fails if the two disagree — change the source.
:::

One coolant route from a source to the thing it cools, following the NetBox/Nautobot 4.7 liquid-cooling model: CoolingSource to CoolingFeed to CoolingIntake and CoolingOutflow. Adopting their shape rather than inventing one means the crosswalk is field-for-field, and it is the reason this contract needs no RDF -- the IT/OT requirement turned out to be expressible in a flat relational form.

This entity is why converged observability is possible at all. A GPU throttling at the top of a rack and a CDU running at reduced flow are the same incident, and nothing in a GPU-centric data model can connect them. The path is the connection: it names the source, the feed, and every resource downstream, so a flow deficit at the source has a computable blast radius.

Coolant *ports* are Port records with `port_class: coolant`, and the physical hoses between them are Links. This entity is the route through them, not a replacement for them.

**Schema id:** `https://schemas.nvidia.com/nvis/nrm/v0.1/cooling-path.schema.json`

## Fields

| Field | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `id` | `uuid` | yes | — |  |
| `loop` | `string` | yes | one of `facility_primary`, `technology_secondary`, `tertiary` | Which loop this path belongs to. The distinction matters because the primary and secondary loops are separated by a heat exchanger and owned by different organizations -- facilities owns one, the deployment team owns the other -- and a fault on either side presents identically at the rack. |
| `name` | `string` | yes | min length 1; max length 256 | Path name as the facility uses it, typically naming the CDU and the loop: `CDU-01 secondary loop A`. |
| `source_resource_id` | `uuid` | yes | — | Where the coolant comes from: a CDU, or a facility connection for a primary loop. NetBox's CoolingSource. |
| `attributes` | `object` | no | — |  |
| `coolant` | `string` | no | one of `water`, `pg25`, `pg30`, `dielectric`, `other` |  |
| `cooled_resource_ids` | `array` of `uuid` | no | — | Everything this path removes heat from. Denormalized on purpose, and the one place in this contract where that is the right call: it is the blast radius of a cooling fault, it is read on every alert, and deriving it means walking the feed chain and the containment tree on each read. |
| `design` | `object` | no | — | Commissioned design point. This is the `expected` side of a cooling validation, and the numbers a measured reading is compared against. |
| `external_refs` | `external_refs` | no | — |  |
| `feed_resource_ids` | `array` of `uuid` | no | — | The distribution chain in flow order, source-side first: manifolds, busbar-mounted hoses, quick disconnects. NetBox's CoolingFeed. Order matters, because an isolation valve halfway along determines what a shutdown affects. |
| `intake_port_id` | `one of` | no | — | Coolant inlet port on the cooled resource. NetBox's CoolingIntake, expressed as a Port here so intake and outflow sit in the same topology graph as every other termination point. |
| `labels` | `labels` | no | — |  |
| `observation` | `observation` | no | — |  |
| `outflow_port_id` | `one of` | no | — | Coolant return port. NetBox's CoolingOutflow. |
| `provenance` | `provenance` | no | — |  |
| `redundancy` | `string` | no | one of `none`, `n_plus_1`, `n_plus_2`, `2n` | Redundancy tier of the SOURCE serving this path. Recorded because it is the difference between a CDU pump failure being a maintenance ticket and being a rack-down event, and that is a design decision worth being able to audit after the fact. |
| `timestamps` | `timestamps` | no | — |  |

This schema is closed: a property not listed above is a validation error. Tool-specific data belongs in `attributes`.
