# The NVIS Resource Model (NRM)

A small, versioned data contract for every unit of resource in an AI factory, from a transceiver to
a rack. This directory is the contract itself — the published artifact, not documentation about it.

```
contracts/
  nrm/v0.1/          JSON Schema 2020-12, one file per entity
  crosswalk/         mappings to the systems NVIDIA already governs, as testable data
  fixtures/          a whole GB200 NVL72 rack, generated and round-tripped in CI
```

Fetch it at `/api/contracts/index.json`, or point an agent at `/api/contracts/agent-pack.md`.

## Why this exists

Each team can build its own tools — that is not the problem and it is not going to change. The
problem is that today the same rack exists as a spreadsheet row, a Nautobot device, a UFM node and
four hostnames in four scripts, with nothing to say they are the same rack. So the data gets copied
instead of referenced, the copies disagree, and every integration is a bespoke afternoon of
matching strings.

NRM is the agreement that makes referencing possible. It is deliberately not a new database.

## What it is not

**Not a source of truth.** Nautobot is NVIDIA's source of record for asset management — the InfoSec
Asset Management Standard names it, NGC-CFA maintains the field-level population standard, and
DCEO's OpsTwin DCIM treats it as authoritative. NRM is a *profile* over it with a normative
crosswalk. Where the two disagree about an asset, Nautobot is right.

**Not a monitoring system.** No telemetry, no time series, no health. A throttling GPU is a DCGM
fact. Putting it here would make a slow inventory database get polled like Prometheus, which is how
an inventory stops being trusted.

**Not RDF.** NetBox/Nautobot 4.7 shipped a liquid-cooling model that covers the IT/OT requirement
in a flat relational shape, so the graph modelling turned out to be unnecessary. Brick and Haystack
stay documented export targets rather than dependencies.

## The seven entities

| Entity | What it answers |
|---|---|
| [`Resource`](nrm/v0.1/resource.schema.json) | one physical or logical thing, and what contains it |
| [`ResourceType`](nrm/v0.1/resource-type.schema.json) | the catalog/SKU object — where partner data lands |
| [`Location`](nrm/v0.1/location.schema.json) | site, room, row, rack, rack unit |
| [`Port`](nrm/v0.1/port.schema.json) | a termination point: network, power, coolant, console |
| [`Link`](nrm/v0.1/link.schema.json) | a connection between two ports, and what carries it |
| [`Domain`](nrm/v0.1/domain.schema.json) | a logical grouping that cuts across racks |
| [`CoolingPath`](nrm/v0.1/cooling-path.schema.json) | one coolant route, and its blast radius |

Plus [`common.schema.json`](nrm/v0.1/common.schema.json) for shared definitions and
[`bundle.schema.json`](nrm/v0.1/bundle.schema.json) for the interchange container.

Each schema carries its own reasoning in `description`. Read the schema, not a summary of it.

## The four decisions worth knowing

**Identity is a surrogate key plus reconciliation aliases.** The primary key is a minted UUIDv7 —
opaque, so a resource can be renamed, re-serialized, moved or replaced under warranty and keep its
key. Real-world identity lives in `identifiers[]`, an array reusing Redfish's `DurableNameFormat`
enum extended with `IB_GUID`, `GPU_UUID`, `NVLINK_GUID` and `SERIAL`. Reconciliation matches on any
member, so a record built from a packing list merges with the same unit discovered over the fabric.

Note that `urn:nvis:` is *not* a registered RFC 8141 namespace, so identifiers are plain strings
rather than URNs that only look official.

**Containment is the primary relationship.** A physical inventory is a tree before it is anything
else (OpenConfig's insight). Transceiver → cage → switch → rack. Everything else hangs off it.

**`expected` versus `observed` is on every entity.** No surveyed standard carries this distinction,
and it is the whole validation product: a cabling file says `expected`, `ibnetdiscover` says
`observed`, and the difference is the defect list. Nautobot cannot express it, which is the specific
reason NRM is a profile rather than just a Nautobot view.

**Link keys are content-addressable.** A link's `key` is derived from its endpoints as
`<resource>_<port>:<resource>_<port>` (UFM's convention), with the two terms sorted. That is what
makes plan-versus-reality a set difference instead of a matching heuristic — a cabling file lists a
link switch-first and a sweep reports it node-first, and without the sort every link in the rack
reads as both missing and unexpected.

Generate keys with `contracts.identity.link_key`. Never by hand; CI rejects a key that disagrees
with its endpoints.

## Crosswalks

Mappings live in [`crosswalk/`](crosswalk/) as versioned YAML, not as prose in a wiki page. That
distinction is load-bearing: prose cannot be tested, so it drifts from the contract silently and
gets discovered wrong by the team that trusted it. CI checks every mapping against
[`crosswalk.schema.json`](crosswalk/crosswalk.schema.json) and checks that every NRM field it names
still exists.

| System | Role | Direction |
|---|---|---|
| [`nautobot`](crosswalk/nautobot.yaml) | source of record | both |
| [`ufm`](crosswalk/ufm.yaml) | IB discovery — the `observed` side | import |
| [`bcm-netautogen`](crosswalk/bcm-netautogen.yaml) | rack inventory + P2P cabling — the `expected` side | both |
| [`redfish`](crosswalk/redfish.yaml) | in-chassis discovery | import |
| [`dcgm`](crosswalk/dcgm.yaml) | telemetry join keys only | export |
| [`cyclonedx`](crosswalk/cyclonedx.yaml) | hardware BOM | export only |

Every entity mapping must declare `unmapped_nrm`. A crosswalk that lists only what it maps looks
complete; what an integrating team needs is what it *cannot* carry, and each gap states a reason so
it reads as a decision rather than an oversight.

The upstream inputs that matter most are NVIDIA's own files, not a standard — the factory rack
inventory sheet, the P2P cabling file, and `bcm-netautogen` JSON. Those exist weeks before any
hardware can be reached, and every `expected` record originates there.

## Validating

Adjudication is deterministic, always. `backend/contracts/validate.py` is the only thing that
decides conformance. The Software Factory's mapping assistant will have an LLM *propose* a crosswalk
for your export, but the schema decides whether the proposal is right — a probabilistic answer to a
decidable question is strictly worse than a deterministic one.

```bash
curl -X POST https://<factory>/api/contracts/validate \
     -H 'Content-Type: application/json' --data @my-export.json
```

Beyond schema conformance, three invariants are checked that JSON Schema structurally cannot
express, because publishing an unchecked invariant is publishing a suggestion:

- every reference resolves within the bundle — a dangling reference is the failure mode of every
  hand-built rack import;
- containment has no cycles — a cycle makes every consumer's tree walk run forever;
- no duplicate IDs, and link classes and keys agree with their endpoints.

## The reference rack

[`fixtures/nvl72-rack.json`](fixtures/nvl72-rack.json) is a complete GB200 NVL72: 18 compute trays,
72 GPUs, 36 Grace CPUs, 9 NVLink switch trays, the compute-fabric ports, 18 cable cartridges with
their layered NVLinks, and the cooling path serving the rack.

It is generated by [`bin/gen-nvl72-fixture.py`](../bin/gen-nvl72-fixture.py) and checked in CI,
because a hand-written fixture of this size is wrong in ways nobody notices — 72 GPUs means 72
UUIDs and 72 parent references, and a transposed digit produces a fixture that validates but does
not describe a real rack.

It is a whole rack rather than a toy on purpose. A three-record example would exercise none of what
actually breaks: deep containment, breakout ports, links layered over a physical cartridge, and a
cooling path with a real blast radius.

## Versioning

The contract is versioned as a whole — `nrm/v0.1/` — rather than per entity, and a bundle declares
`nrm_version` exactly. There is no "latest": a consumer that silently follows latest gets a
breaking change on our release schedule instead of theirs.

While v0.x, additive changes land in place. Anything that removes a field, narrows an enum, or
changes a field's meaning gets a new version directory with the old one kept served.
