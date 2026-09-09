---
diataxis: reference
nvsf_generated: contracts/nrm/v0.1/domain.schema.json
---

# Domain

:::{admonition} Generated page
:class: generated-page

This page is generated from `contracts/nrm/v0.1/domain.schema.json` by `bin/gen-docs-reference.py`. Edits here are lost on the
next build, and CI fails if the two disagree — change the source.
:::

A logical grouping that cuts across the containment tree. Racks are physical; an InfiniBand fabric, an NVLink domain, a Slurm partition and a power zone are not, and none of them nest neatly inside a rack.

This is the entity each team scopes its own view with. The IB team cares about `ib_fabric` domains, the Ethernet team about `ethernet_fabric`, OVA about `compute` and `cooling`, and facilities about `power`. One domain entity with a class discriminator means a team can filter to its own concern without every team needing its own entity -- which is precisely the duplication the contract exists to stop.

**Schema id:** `https://schemas.nvidia.com/nvis/nrm/v0.1/domain.schema.json`

## Fields

| Field | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `domain_class` | `string` | yes | one of `compute`, `storage`, `management`, `nvlink`, `ib_fabric`, `ethernet_fabric`, `power`, `cooling`, `tenant`, `other` |  |
| `id` | `uuid` | yes | — |  |
| `name` | `string` | yes | min length 1; max length 256 | Name as the owning team uses it. For an NVLink domain on a GB200 NVL72 this is typically the rack, because the domain and the rack are coextensive there. |
| `attributes` | `object` | no | — |  |
| `external_refs` | `external_refs` | no | — |  |
| `labels` | `labels` | no | — |  |
| `member_resource_ids` | `array` of `uuid` | no | — | Explicit membership. Present for domains whose membership is a decision rather than a consequence -- a Slurm partition, a tenant allocation. Omit it where membership follows from the topology, because a stored list that duplicates a derivable one will disagree with it. |
| `observation` | `observation` | no | — |  |
| `owner` | `string` | no | max length 256 | Team or person accountable for this domain. Named because 'who do I call about this fabric' is the first question of every escalation, and an inventory that cannot answer it sends people to Slack to guess. |
| `parent_id` | `one of` | no | — | Enclosing domain, for the cases that genuinely nest: an IB subnet inside a fabric, a partition inside a cluster. Not a general-purpose hierarchy -- a domain whose parent is of an unrelated class is a modelling mistake. |
| `provenance` | `provenance` | no | — |  |
| `scope` | `string` | no | max length 256 | Free-text bound on the domain's extent: a site, a hall, a cluster name. Advisory. |
| `timestamps` | `timestamps` | no | — |  |

This schema is closed: a property not listed above is a validation error. Tool-specific data belongs in `attributes`.
