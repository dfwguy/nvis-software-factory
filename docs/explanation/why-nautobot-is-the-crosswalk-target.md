---
diataxis: explanation
description: Why NRM maps onto systems NVIDIA already runs instead of asking to become the system of record.
---

# Why Nautobot is the crosswalk target

NRM is not a database and does not want to be your system of record. It is a wire format, and the
crosswalks are what make that claim credible.

The six targets — Nautobot, Redfish, UFM, BCM rack-import, DCGM, CycloneDX — are not an arbitrary
list. Each is there because it already owns a kind of truth that NRM should not try to own.

## The failure mode being avoided

The standard way a data model dies: it is defined, it is good, and it arrives asking to be the new
system of record.

Now every team has a migration project. Nautobot already holds physical inventory, with automation
built on it and people who maintain it. UFM already knows the InfiniBand fabric, authoritatively,
because it runs the fabric. Asking teams to move that into a new model means asking them to give
up working tooling for a promise, and they will reasonably decline. The model ends up with three
adopters and a wiki page.

A wire format asks for much less: keep your system, add a transform. That is a day of work with a
result you can see, and it does not require anyone to trust the new thing with their data before
they have used it.

## What each target owns

`Nautobot`
: Physical inventory: racks, devices, positions, cable plant, site hierarchy. NVIDIA already runs
  it, it already has a documented data model, and it is already the answer for "what is installed
  where". NRM's `Resource`, `Location` and `Port` map onto it closely, which is not a coincidence —
  the containment-tree design was chosen partly *because* it maps cleanly onto a system this fleet
  already governs.

`Redfish`
: The hardware's own account of itself, over the BMC. Its `DurableNameFormat` vocabulary is where
  NRM's identifier formats come from, so a Redfish identifier is already an NRM identifier.

`UFM`
: InfiniBand topology and link state, authoritatively, because it manages the fabric. NRM's `Link`
  and `Port` for IB map from UFM, and nothing else should be believed over it for link state.

`BCM rack-import`
: The bring-up on-ramp. This is the format a rack is described in *before* it exists as
  discoverable hardware, which is exactly the case a model built only around discovery cannot
  serve — and bring-up is when the model is most useful.

`DCGM`
: GPU identity and health. Contributes `GPU_UUID`, which is the identifier that ties a GPU in an
  inventory record to a GPU in a telemetry series.

`CycloneDX`
: Software inventory. Included because a rack's firmware and driver versions are as much a part of
  "what is installed here" as the trays, and there is no reason to invent a format for it when a
  governed one exists.

## Open standards where they exist, small extensions where they do not

The rule applied throughout: reuse a vocabulary someone else governs, extend it where the fleet
needs something it lacks, invent only what has no precedent.

**Reused:** JSON Schema 2020-12 for the schemas. OpenAPI 3.1 for the API. Redfish
`DurableNameFormat` for identifier formats. CycloneDX for software inventory. ULID for opaque
identifiers.

**Extended:** four identifier formats Redfish does not have and this fleet cannot work without —
`IB_GUID`, `GPU_UUID`, `NVLINK_GUID`, `SERIAL`. They sit in the same `format` enum as the Redfish
values rather than in a separate namespace, so a consumer handles them uniformly.

**Invented:** `CoolingPath`, and the specific `lifecycle` state machine. Liquid-cooling dependency
graphs have no standard we could find, and the lifecycle states are shaped by how NVIS actually
receives and energises hardware.

That last category is short, deliberately. Every invented concept is one more thing to explain to
every team, forever.

## Why the gaps are published

Every crosswalk must declare `unmapped_nrm` — the NRM fields that system cannot carry, with a
reason — even when the list is empty.

This is the section most likely to be skipped and the most useful one in the file. "DCGM does not
carry cooling paths" and "whoever wrote this crosswalk did not get to cooling paths" are
indistinguishable without it, and they have opposite implications for anyone deciding which system
to trust for a given kind of fact.

Requiring an empty list rather than allowing omission is a small thing that changes the meaning: it
makes completeness an assertion someone made, which review can then examine.

## What this means for you

If your tool reads from one of the six, **map from that system, not from your tool's output**. You
inherit a reviewed, tested, maintained mapping and you do not own a second one that will drift.

If your tool is the origin of some fact — it discovers something nothing else knows — then it needs
its own transform, and possibly its own crosswalk if others will integrate with it.
{doc}`../how-to/map-your-export-to-the-nvis-resource-model` covers the first case;
{doc}`../how-to/propose-a-contract-change` covers publishing the second.

And if you are choosing a system of truth for a new kind of data: prefer one of these six. The
crosswalk exists, the semantics are governed by someone whose job it is, and you do not become the
maintainer of a format.

## Related

- {doc}`../reference/crosswalks` — the six mappings, generated from the YAML.
- {doc}`why-contracts-and-why-now` — what the contract is for.
- {doc}`../how-to/propose-a-contract-change` — adding a target.
