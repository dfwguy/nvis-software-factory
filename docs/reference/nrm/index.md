---
diataxis: reference
nvsf_generated: contracts/nrm/v0.1/
---

# NVIS Resource Model v0.1

:::{admonition} Generated page
:class: generated-page

This page is generated from `contracts/nrm/v0.1/` by `bin/gen-docs-reference.py`. Edits here are lost on the
next build, and CI fails if the two disagree — change the source.
:::

The 7 entities of NRM v0.1, as JSON Schema 2020-12.

| Entity | What it is | Schema |
|---|---|---|
| [ResourceType](resource-type.md) | The catalog object: a kind of thing, not a thing. One GB200 NVL72 compute tray SKU is one ResourceType; the seventy-two of them in a rack are seventy-two Resources pointing at it. | `resource-type.schema.json` |
| [Location](location.md) | A place in a data centre, addressed the way an operator addresses it: site, room, row, rack, rack unit. Kept as its own entity rather than fields on Resource because many resources share one location, and because a location exists before anything is installed in it -- a rack position in a floor plan is a real thing to plan against. | `location.schema.json` |
| [Domain](domain.md) | A logical grouping that cuts across the containment tree. Racks are physical; an InfiniBand fabric, an NVLink domain, a Slurm partition and a power zone are not, and none of them nest neatly inside a rack. | `domain.schema.json` |
| [Resource](resource.md) | One physical or logical thing, from a transceiver to a rack. Deliberately ONE polymorphic entity rather than a table per kind: the alternative is thirty near-identical schemas whose shared fields drift, and a query that cannot ask 'what is in this rack' without a union across all of them. | `resource.schema.json` |
| [Port](port.md) | A termination point on a resource, in the RFC 8345 sense: the thing a Link attaches to. Ports are modelled separately from Links so that an uncabled port is still a fact -- 'this switch has sixteen OSFP cages and four are empty' is exactly what a bring-up needs to know, and a link-only model cannot say it. | `port.schema.json` |
| [Link](link.md) | A connection between two ports: RFC 8345's link, carrying Redfish Cable's physical attributes. | `link.schema.json` |
| [CoolingPath](cooling-path.md) | One coolant route from a source to the thing it cools, following the NetBox/Nautobot 4.7 liquid-cooling model: CoolingSource to CoolingFeed to CoolingIntake and CoolingOutflow. Adopting their shape rather than inventing one means the crosswalk is field-for-field, and it is the reason this contract needs no RDF -- the IT/OT requirement turned out to be expressible in a flat relational form. | `cooling-path.schema.json` |

Each schema is fetchable from the running application at `/api/contracts/nrm/v0.1/<entity>.schema.json`, and all of them at once from `/api/contracts/bundle`.
