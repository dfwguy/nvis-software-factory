---
diataxis: explanation
description: What problem a shared data contract solves, why the alternatives fail, and why NRM is deliberately small.
---

# Why contracts, and why now

Four teams — AIC, Ethernet, IB, OVA — build tools against the same racks. Each tool is right about
what it was built for. Together they produce an environment where a simple question has four
answers.

*How many compute trays are installed in rack 3?*

The bring-up spreadsheet says 18, because that is what was shipped. The fabric discovery tool says
17, because one tray's IB links are down and it only reports what it can see. Nautobot says 18,
from the packing list. The validation tool says 16, because it excludes two that failed a check
last week and were not re-run.

None of those tools is broken. Every one is answering a slightly different question and calling it
the same thing. The cost is not the discrepancy — it is the hour someone spends every time it
surfaces, reconstructing which tool means what, on a bring-up where the schedule is measured in
days.

## Why this is getting worse

Tool count is going up, fast, because agent-assisted development made building one cheap. That is
a real gain and we do not want to reverse it.

But the cost of *n* tools is not linear in *n*. It is the pairs: every two tools that describe
overlapping reality are a potential disagreement, and someone eventually has to reconcile them by
hand. Four tools is six pairs. Ten tools is forty-five. We are heading for ten.

The integrations do get written, one at a time, ad hoc: a script that reads the IB tool's CSV and
writes the validation tool's JSON, owned by whoever needed it that week. Each is reasonable in
isolation. Collectively they are a mesh of point-to-point translations with no owner, and each one
encodes a guess about what the other side meant.

## What we chose not to do

**One tool to replace them all.** Every consolidation attempt starts here. It fails on the same
thing every time: the four teams have genuinely different jobs, different timelines, and different
notions of what a rack is. A tool general enough to serve all four is a tool that fits none of
them well, and it becomes the thing people work around.

**One database everyone writes to.** Better, and it is roughly what Nautobot is for physical
inventory. But it does not address the question above. Four teams writing to one schema still
means four teams writing 18, 17, 18 and 16 into the same column — because the disagreement is
about *meaning*, not storage. A shared database without a shared contract is a shared argument.

**Nothing; let people integrate as needed.** The status quo. It works, at a cost that grows
quadratically and is paid in hours during bring-up, which is the most expensive time to pay for
anything.

## What a contract is instead

The contract does not say what tools you may build or where you may put your data. It says: **when
you describe a rack to another team, describe it like this.**

Each team keeps its own tool, its own storage, its own opinions. What becomes shared is the wire
format and the vocabulary. Nine tools, one format, nine integrations instead of forty-five.

That is not a new idea — it is what OpenAPI did for HTTP APIs and what CycloneDX did for software
inventory. The observation worth stealing from both is that the leverage is in the *vocabulary*,
not the transport. Everyone already speaks JSON. Nobody agreed on what a tray is.

## Why NRM is deliberately small

Seven entities: `Resource`, `ResourceType`, `Location`, `Port`, `Link`, `Domain`, `CoolingPath`.
That is a suspiciously short list for something claiming to describe everything from a transceiver
to a rack, and the shortness is the design.

An expansive model is easy to write and hard to adopt. Give teams a hundred entities and each one
implements the twelve it needs, differently, and two implementations of "the same standard" do not
interoperate. Nobody is at fault and the contract has failed anyway.

So NRM covers what several teams demonstrably need to exchange, and nothing else:

**One `Resource` type, discriminated by `resource_type`.** A rack, a tray, a GPU and a transceiver
are all resources. They differ in `resource_type` and in what they carry, not in schema. A new
kind of hardware is a new enum member, not a new entity and not a schema change — which matters in
a fleet where the hardware changes faster than any standards process.

**Containment is physical only.** `parent_id` means "is inside". Logical grouping — an NVLink
domain, a tenant, a fabric — is `Domain`, separately, because a tray is in exactly one rack and
can be in several domains at once. Collapsing those is where inventory models usually go wrong,
and it is unrecoverable once data exists.

**`Link` is an entity, not a field.** A cable has a serial, a type and an operational state. On
bring-up, "which cable is this and is it up" is most of the work.

**`CoolingPath` exists at all**, which is unusual in an inventory model, because in a liquid-cooled
rack the coolant loop is a dependency graph like the power feed. A CDU failure has a blast radius,
and answering "what is downstream of this CDU" requires modelling it.

**Telemetry is not in NRM.** Deliberately. NRM describes what exists and how it is connected.
Time-series belongs in Prometheus, and mixing them produces a model where every record is
simultaneously stale and enormous.

Things NRM does not model — because no exchange has needed them yet — get added when one does. The
`attributes` field is the escape hatch in the meantime, and
{doc}`../how-to/propose-a-contract-change` is how something graduates out of it.

## The identity decision

The one thing to understand about NRM: identity is an array.

```json
"identifiers": [
  { "format": "SERIAL", "value": "GB300-CT-000117" },
  { "format": "NAA", "value": "0x5000c500a1b2c3d4" }
]
```

Every resource carries every identifier anyone knows about it, and two records refer to the same
physical thing when **any** identifier matches on both format and value.

This is not over-engineering. It falls directly out of how bring-up actually works. A rack is
described weeks before it arrives, from a packing list — serials only. It is described again after
energisation, from the fabric — GUIDs, MACs, UUIDs, and maybe serials if the BMC reports them.
Those two descriptions must merge without a human matching them up, and they overlap on whichever
identifier both sources happened to have.

A single `serial_number` field cannot express that. You get a join table maintained by hand, and
it is wrong within a month.

The `format` vocabulary is Redfish's `DurableNameFormat` — `NAA`, `UUID`, `EUI`, `MACAddress`,
`iQN` — extended with the four this fleet needs and Redfish lacks: `IB_GUID`, `GPU_UUID`,
`NVLINK_GUID`, `SERIAL`. Extending a governed vocabulary rather than inventing one means every
Redfish identifier is already an NRM identifier, with no translation step to get wrong.

The consequence is that adding a format is the most consequential additive change anyone can make
to NRM. A format whose values are not globally unique creates a rule that merges unrelated
resources, permanently. {doc}`../how-to/propose-a-contract-change` says so in a warning box for
this reason.

## Why crosswalks come first

Every entity ships with mappings to six systems — Nautobot, Redfish, UFM, BCM rack-import, DCGM,
CycloneDX — and each mapping is required to declare what it *cannot* carry.

A contract with no crosswalks asks every team to do integration work before getting anything back.
That is a rational reason to defer adoption forever. A contract that ships with "here is how your
existing export maps, and here is precisely what it loses" asks for a transform, and pays for it
immediately.

The `unmapped_nrm` section is the part to read before choosing a source of truth. It is required
even when empty, so that "DCGM cannot carry cooling paths" is a claim someone made rather than a
section someone forgot. {doc}`why-nautobot-is-the-crosswalk-target` explains why the target set
looks like this.

## What this does not solve

The contract makes tools *interoperable*. It does not make them *good* — a tool can emit perfect
NRM and hold its only copy in memory, which is the
{doc}`other half <the-reboot-that-lost-the-data>` of the problem.

It also does not create agreement. If the fabric tool reports 17 trays and the packing list says
18, NRM lets both records exist, merged by identifier, each with a `lifecycle` and a provenance.
Reconciling them is still someone's judgement. What NRM removes is the hour spent working out
whether the two tools even mean the same thing by "tray" — which, on a bring-up, is the hour that
was actually being wasted.

## Related

- {doc}`../tutorials/describe-a-rack-in-nrm` — the model, by building one.
- {doc}`why-nautobot-is-the-crosswalk-target` — why we map to systems we do not own.
- {doc}`../reference/nrm/index` — every entity and field.
