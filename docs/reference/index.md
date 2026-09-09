---
diataxis: reference
---

# Reference

Descriptions of the machinery: what exists, what shape it has, what each field means. No
instruction and no argument — those live in {doc}`../how-to/map-your-export-to-the-nvis-resource-model`
and the {doc}`explanation <../explanation/why-contracts-and-why-now>` section.

Almost everything below is generated from the source it describes, by
`bin/gen-docs-reference.py`. That is not a labour-saving measure: a hand-written schema table is a
second implementation of the schema, and the two diverge the first busy week. CI regenerates and
diffs, so a contract change without a docs rebuild fails the pipeline instead of shipping a
reference that lies.

::::{grid} 2
:gutter: 3

:::{grid-item-card} NVIS Resource Model
:link: nrm/index
:link-type: doc

Every entity, every field, every constraint, generated from `contracts/nrm/`.
:::

:::{grid-item-card} Crosswalks
:link: crosswalks
:link-type: doc

How Nautobot, Redfish, UFM, BCM, DCGM and CycloneDX map onto NRM — including what each one
cannot carry.
:::

:::{grid-item-card} Quality pillars
:link: pillars/index
:link-type: doc

The baseline, with each criterion's detector status, generated from `standards/`.
:::

:::{grid-item-card} REST API
:link: api
:link-type: doc

Every endpoint with the permission it enforces, generated from the live route table.
:::

:::{grid-item-card} Configuration
:link: configuration
:link-type: doc

Every setting, its type, default and whether it is required, generated from
`config_registry.py`.
:::

::::

## Machine-readable equivalents

The pages above are for people. An agent or a client generator should read these instead, from a
running deployment:

`GET /api/contracts/index.json`
: What exists, at what version, and where to fetch it. The entry point.

`GET /api/contracts/nrm/{version}/{entity}.schema.json`
: One schema file, verbatim.

`GET /api/contracts/bundle`
: Index, every schema and every crosswalk in a single response.

`GET /api/contracts/agent-pack.md`
: The contract written as instructions for a coding agent, including the handful of rules that
  are not inferable from the schemas.

`GET /api/openapi.json`
: OpenAPI 3.1 for this API, generated from the live routes.

`POST /api/contracts/validate`
: Decides whether a payload conforms. Deterministic, and the only thing that decides.
