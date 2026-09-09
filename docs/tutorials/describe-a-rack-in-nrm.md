---
diataxis: tutorial
description: Build up an NVL72 rack in the NVIS Resource Model one entity at a time, and learn why identity works the way it does.
---

# Describe a rack in NRM

You are going to build a valid NRM description of an NVL72 rack from nothing, one entity at a
time, validating as you go. By the end you will understand why identity in NRM is an array rather
than a field — which is the one design decision in the model that surprises everyone and matters
most.

Twenty minutes. You need a Software Factory deployment and a browser; the **Validate** page is the
only tool involved.

:::{note}
You will be told to submit payloads that fail validation. Those are the interesting steps. The
error you get back is the lesson.
:::

## Step 1 — One rack

Open **Validate** in the sidebar, choose entity `Resource`, and paste this:

```json
{
  "id": "01JBQ8Z3K4MN5P6R7S8T9V0WXY",
  "nrm_version": "v0.1",
  "resource_type": "rack",
  "identifiers": [
    { "format": "SERIAL", "value": "NVL72-PT-0001" }
  ],
  "name": "pt-dc1-r03",
  "lifecycle": "installed"
}
```

Press **Validate**. It passes.

Six fields for a rack, and every one is doing something:

`id`
: A ULID, opaque and assigned by whoever created the record. It carries no meaning — not a
  position, not a serial. Meaning in an identifier is a trap: rack `r03` gets moved to another
  row, and now every system holding `r03` is wrong in a way nothing detects.

`nrm_version`
: On every entity. When two systems exchange records for years, the version has to travel with
  the record rather than with the API call that happened to carry it.

`identifiers`
: The array. This is the interesting one, and the next step is about it.

`lifecycle`
: `planned`, `ordered`, `installed`, `active`, `maintenance`, `decommissioned`, `disposed`. A rack
  on a packing list and a rack passing traffic are both real, and a model that can only describe
  the second one cannot help with bring-up — which is when we need it most.

## Step 2 — Why identity is an array

Try replacing `identifiers` with something simpler:

```json
"serial_number": "NVL72-PT-0001"
```

It fails: `additionalProperties` is false on every NRM entity, so unknown fields are rejected
rather than ignored. That strictness is deliberate — a field silently dropped in transit is a
data-loss bug that surfaces weeks later in a report nobody can explain.

But the real reason `serial_number` does not exist is not strictness. Put the array back and add a
second identifier:

```json
"identifiers": [
  { "format": "SERIAL", "value": "NVL72-PT-0001" },
  { "format": "NAA", "value": "0x5000c500a1b2c3d4" }
]
```

Both are the same rack. Neither is more true than the other. They came from different places — one
off a label, one from the fabric — and *which one you have depends on which system you are*.

::::{dropdown} The reconciliation rule this enables
:color: primary
:open:

Two records refer to the same physical thing when **any** identifier matches on **both format and
value**.

That single rule is what lets a record created from a packing list weeks before delivery merge
with the unit discovered over the fabric after energisation, without a human matching them up. The
packing-list record has `SERIAL`. The discovered record has `NAA` and `SERIAL`. They share
`SERIAL`, so they are one resource, and the merged record now carries both.

A single `serial_number` field cannot express that. You would need a join table maintained by
hand, and it would be wrong within a month.

The `format` values come from Redfish's `DurableNameFormat` — `NAA`, `UUID`, `EUI`, `MACAddress`
and the rest — extended with the four this fleet needs and Redfish lacks: `IB_GUID`, `GPU_UUID`,
`NVLINK_GUID`, `SERIAL`. Extending a governed vocabulary rather than inventing one means a Redfish
identifier is already an NRM identifier, no translation.
::::

## Step 3 — Put a compute tray in it

Now a resource inside the rack:

```json
{
  "id": "01JBQ8Z3K4MN5P6R7S8T9V0WXZ",
  "nrm_version": "v0.1",
  "resource_type": "compute_tray",
  "identifiers": [
    { "format": "SERIAL", "value": "GB300-CT-000117" }
  ],
  "parent_id": "01JBQ8Z3K4MN5P6R7S8T9V0WXY",
  "lifecycle": "installed"
}
```

`parent_id` is physical containment and nothing else: the tray is *in* the rack. A GPU is in the
tray, a transceiver is in a port. It follows one thing you can point at while standing in a data
hall, so the tree cannot become ambiguous.

Logical grouping — an NVLink domain, a compute fabric, a tenant — is not containment. It is the
`Domain` entity, and it is separate because a tray belongs to exactly one rack and can be in
several domains at once. Collapsing those two into one field is where inventory models usually go
wrong.

## Step 4 — Break it deliberately

Change `parent_id` to point at the tray's own `id`. Validate.

It fails, and notice *how*: the error is not a JSON Schema error. It is a **semantic invariant**
violation, reported separately — `parent_id must not equal id`.

Some rules cannot be expressed in JSON Schema at all. "No cycles in the containment tree" needs to
see every record together. So validation has two layers, and the response tells you which one
rejected you:

**Schema conformance** — shape, types, required fields, enums. Per record, from the published
schema.

**Semantic invariants** — cycle-freedom, referential integrity of `parent_id`, port endpoints
existing, cooling paths reaching a source. Across the whole payload.

A payload that passes only the first is well-formed nonsense. Both layers are the same code that
runs behind `POST /api/contracts/validate`, so your CI and this page agree by construction.

## Step 5 — Link two ports

Ports and the link between them:

```json
{
  "nrm_version": "v0.1",
  "resources": [],
  "ports": [
    {
      "id": "01JBQ8Z3K4MN5P6R7S8T9V0X01",
      "nrm_version": "v0.1",
      "resource_id": "01JBQ8Z3K4MN5P6R7S8T9V0WXZ",
      "name": "ibp0s1",
      "media_type": "osfp",
      "role": "compute_fabric",
      "identifiers": [{ "format": "IB_GUID", "value": "0x0002c90300a1b2c4" }]
    },
    {
      "id": "01JBQ8Z3K4MN5P6R7S8T9V0X02",
      "nrm_version": "v0.1",
      "resource_id": "01JBQ8Z3K4MN5P6R7S8T9V0WXZ",
      "name": "ibp0s2",
      "media_type": "osfp",
      "role": "compute_fabric",
      "identifiers": [{ "format": "IB_GUID", "value": "0x0002c90300a1b2c5" }]
    }
  ],
  "links": [
    {
      "id": "01JBQ8Z3K4MN5P6R7S8T9V0X03",
      "nrm_version": "v0.1",
      "a_port_id": "01JBQ8Z3K4MN5P6R7S8T9V0X01",
      "b_port_id": "01JBQ8Z3K4MN5P6R7S8T9V0X02",
      "link_type": "infiniband",
      "operational_state": "up"
    }
  ]
}
```

Choose entity `bundle` this time, so both layers run.

A `Link` is a first-class entity rather than a `connected_to` field on `Port`, because a link has
its own attributes — a type, an operational state, a cable with its own serial. During bring-up
"which cable is this and is it up" is most of the work, and it needs somewhere to live.

Now try pointing `b_port_id` at a ULID that appears nowhere. The invariant layer catches it: a
link to a port that does not exist is exactly the kind of dangling reference that makes a fabric
inventory untrustworthy.

## Step 6 — Ask the crosswalk what you would lose

Your tools do not emit NRM today. Open **Crosswalks** and pick a system you use.

Read past the field mappings to **Unmapped NRM fields**. Every crosswalk is required to have that
section, even when empty, so that "this system cannot carry cooling paths" is a claim someone
made rather than a section someone forgot to write.

That is the section to read before you decide which system is your source of truth for a given
kind of fact. {doc}`../explanation/why-nautobot-is-the-crosswalk-target` explains why the answer
for physical inventory is usually Nautobot.

## What you did

You built a rack, a tray, two ports and a link; you broke each of them in the way people actually
break them; and you saw which layer caught it. Most importantly you know why identity is an array
— which is the thing to explain to the next person on your team who asks where `serial_number`
went.

## Where to go next

::::{grid} 2
:gutter: 2

:::{grid-item-card} Map your export
:link: ../how-to/map-your-export-to-the-nvis-resource-model
:link-type: doc

Get a tool you already run emitting NRM.
:::

:::{grid-item-card} Every field
:link: ../reference/nrm/index
:link-type: doc

The full schemas, generated from the contract.
:::

::::
