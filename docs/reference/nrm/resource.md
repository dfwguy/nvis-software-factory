---
diataxis: reference
nvsf_generated: contracts/nrm/v0.1/resource.schema.json
---

# Resource

:::{admonition} Generated page
:class: generated-page

This page is generated from `contracts/nrm/v0.1/resource.schema.json` by `bin/gen-docs-reference.py`. Edits here are lost on the
next build, and CI fails if the two disagree — change the source.
:::

One physical or logical thing, from a transceiver to a rack. Deliberately ONE polymorphic entity rather than a table per kind: the alternative is thirty near-identical schemas whose shared fields drift, and a query that cannot ask 'what is in this rack' without a union across all of them.

Containment is the primary relationship (`parent_id`), following OpenConfig's insight that a physical inventory is a tree before it is anything else. A transceiver's parent is a cage, whose parent is a switch, whose parent is a rack. Every other relation -- ports, links, cooling paths -- hangs off that tree.

What a resource IS lives on its ResourceType. What makes it THIS one lives in `identifiers[]`.

**Schema id:** `https://schemas.nvidia.com/nvis/nrm/v0.1/resource.schema.json`

## Fields

| Field | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `id` | `uuid` | yes | — |  |
| `name` | `string` | yes | min length 1; max length 256 | The name operators use. For a compute node this is the hostname, because that is what appears in every log, every Slurm queue and every escalation. Not unique by itself -- two sites may both have `gpu-001`. |
| `resource_type_id` | `uuid` | yes | — | The catalog entry this is an instance of. Required: a resource whose type is unknown cannot be power-budgeted, cooled, cabled or validated, so admitting one would only defer the problem. |
| `attributes` | `object` | no | — | Instance facts the model does not cover: a firmware version, a BIOS setting, a measured coolant flow. Type-level facts belong on ResourceType instead -- putting them here copies them onto every unit and guarantees they disagree. |
| `domain_id` | `one of` | no | — | The logical grouping this participates in: a compute domain, an IB fabric, an NVLink domain, a power zone. |
| `external_refs` | `external_refs` | no | — |  |
| `identifiers` | `array` of `identifier` | no | — | Every known real-world name for this resource. Reconciliation matches on ANY member, which is what lets a record built from a packing list (SERIAL) merge with the same unit discovered over the fabric (IB_GUID) once one system reports both.  Empty is legal but weak: a resource with no identifiers can never be reconciled with a discovered one, so an inventory built entirely without them will duplicate itself on first discovery. |
| `labels` | `labels` | no | — |  |
| `lifecycle` | `lifecycle` | no | — |  |
| `location_id` | `one of` | no | — | Where it is. Usually set only on rack-level and above, with everything inside inheriting through `parent_id` -- storing a full location on every transceiver is denormalization that goes stale the first time a tray moves. |
| `observation` | `observation` | no | — |  |
| `parent_id` | `one of` | no | — | The resource physically containing this one. Null only for a top-level resource, in practice a site. A cycle here is invalid; the schema cannot express that, so `backend/contracts/validate.py` checks it. |
| `part_location` | `part_location` | no | — | Position within the parent. This plus `parent_id` is the full physical address, so no path syntax needs inventing. |
| `provenance` | `provenance` | no | — |  |
| `quantity` | `integer` | no | min 1; default `1` | For consumables tracked in bulk rather than individually -- a bag of quick-disconnect gaskets. Anything with a serial should be its own record instead; a quantity above one means identity was given up, and it cannot be recovered later. |
| `timestamps` | `timestamps` | no | — |  |

This schema is closed: a property not listed above is a validation error. Tool-specific data belongs in `attributes`.
