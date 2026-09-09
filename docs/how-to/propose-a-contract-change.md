---
diataxis: how-to
description: Add an entity, field or crosswalk to NRM without breaking the teams already consuming it.
---

# How to propose a contract change

NRM needs something it does not have. This is how to get it in without breaking the tools already
reading the current version.

## First: is it a contract change?

Most "NRM is missing X" turns out not to need a contract change at all. Work down this list before
you open a merge request:

**Is it a fact about a resource that only your team cares about?** Put it in `attributes`. That
field exists for exactly this, and it costs nobody else anything.

**Is it a fact another entity already carries?** Rack elevation is `Location`, not a field on
`Resource`. Cable serial is on `Link`. Check {doc}`../reference/nrm/index` properly first — the
model is small enough to read end to end in ten minutes.

**Is it position, state or naming that changes over time?** That is not identity, no matter how
convenient it would be to match on it.

**Is it something only your system's export has?** Then it is a crosswalk gap, not a model gap.
Record it in `unmapped_nrm` and stop.

If it is still a contract change, keep going.

## Choose the smallest change that works

In descending order of preference:

1. **A new optional field** on an existing entity. Additive, backward compatible, no version bump.
2. **A new enum member** — a `resource_type`, a `lifecycle` state, a `media_type`. Additive for
   producers; consumers with exhaustive switches will need to handle it, so it is a minor bump.
3. **A new identifier format.** Additive, and see the warning below.
4. **A new entity.** A real addition to the model. Justify why it cannot be a `Resource` with a
   `resource_type`.
5. **Changing or removing anything existing.** Breaking. Needs a new NRM version and a migration
   note, and it will be slow. Exhaust the four options above first.

::::{warning}
A new identifier format is the highest-consequence additive change in the model, because
reconciliation matches on any format-and-value pair. Add a format whose values are not globally
unique — a hostname, a position label, a per-vendor part number — and you have created a rule that
merges unrelated resources across the fleet. There is no way to un-merge those records
afterwards.

Before proposing a format, be able to answer: is this value unique across every vendor and every
site, forever? If the answer involves "in practice", the answer is no.
::::

## Write the change

For a new optional field on `Resource`:

```bash
$EDITOR contracts/nrm/v0.1/resource.schema.json
```

```json
"thermal_design_watts": {
  "type": "integer",
  "minimum": 0,
  "description": "Rated thermal design power in watts. Nameplate rating from the vendor, not a measurement -- observed draw belongs in telemetry, which NRM does not carry."
}
```

Three requirements, all enforced in review:

**A `description` on every field**, saying what it means and — where it is not obvious — what it is
*not*. That description is the only thing a reader of the generated reference sees, and "the
schema is the documentation" only works if the schema is documented.

**Additive fields are optional.** Adding to `required` breaks every existing producer and is a
version bump, not a field addition.

**`additionalProperties` stays `false`.** Do not relax it to sneak a field in. Silently dropping
unknown fields in transit is a data-loss bug that surfaces weeks later in a report nobody can
explain.

## Cover it in a crosswalk

A field no system maps is a field nobody populates. For each of the six published crosswalks,
either map it or say why not:

```yaml
# contracts/crosswalk/redfish.yaml
- nrm_field: thermal_design_watts
  system_field: Chassis.PowerSubsystem.Allocation.RequestedWatts
  transform: none
  note: >-
    Requested rather than rated where the BMC reports both; a chassis that reports neither
    contributes nothing rather than a zero.
```

Or:

```yaml
unmapped_nrm:
  - field: thermal_design_watts
    reason: DCGM reports observed power draw, not the nameplate rating. Populating this from a
      measurement would make a nameplate field vary between polls.
```

`unmapped_nrm` is required on every mapping, empty list included. That is so "this system cannot
carry it" is a claim someone made rather than a section someone forgot.

## Update the fixture and the tests

`contracts/fixtures/nvl72-rack.json` is the worked example and the round-trip test subject. Add
your field there with a realistic value — the fixture is what the next person reads to see what a
populated record looks like, so an empty one teaches nothing.

Then:

```bash
cd backend && python -m pytest tests/test_contracts.py -v
```

The round-trip tests validate the fixture against every schema and run every crosswalk over it in
both directions.

## Regenerate the docs

```bash
./bin/gen-docs-reference.py
```

Review the diff. It is the published reference, and it is the artifact other teams read — a field
whose generated description reads badly here reads badly to them.

## Breaking changes: cut a version

If you must change or remove something:

```bash
cp -r contracts/nrm/v0.1 contracts/nrm/v0.2
```

Then:

- Make the change in `v0.2` only. **`v0.1` is immutable** — it is being served to running tools,
  and editing a published version is how a consumer's validation starts failing on data that
  did not change.
- Add `contracts/nrm/v0.2/MIGRATION.md` saying, per changed field, what it was, what it is, and
  what a producer must do.
- Keep v0.1 served. Both versions are available from `/api/contracts/index.json`, and consumers
  move on their own schedule.
- Update every crosswalk for v0.2, leaving the v0.1 mappings in place.

## Open the merge request

Reference the issue with `#<number>` and use a conventional commit:

```
feat(contracts): add thermal_design_watts to Resource

Adds an optional nameplate TDP field, mapped from Redfish RequestedWatts and
declared unmapped for DCGM (which reports draw, not rating).

Refs #142
```

State in the description which of the five change categories above it is, and why the smaller
options were not enough. That is the question a reviewer will ask first.

## Related

- {doc}`../reference/nrm/index` — the current model.
- {doc}`../reference/crosswalks` — the six mappings you need to touch.
- {doc}`../explanation/why-contracts-and-why-now` — what the contract is for, which is the standard
  a proposal is judged against.
