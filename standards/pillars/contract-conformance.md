---
id: contract-conformance
title: Contract conformance
severity_ceiling: major
order: 7
detectors:
  - backend/factory/scanners/contracts.py
---

# Contract conformance

**The question:** can another team's tool consume this one's output without a bespoke adapter?

This is the pillar that connects the Factory to the other half of the project. Every team models
racks, nodes, switches and transceivers, and every team models them slightly differently, so every
integration is a one-off translation that rots.

## Criteria

### C1 — Exported resource data validates against NRM

*Detector: yes.*

- **Pass:** data describing physical or logical resources validates against the NVIS Resource Model
  schemas, or is accompanied by a crosswalk that transforms it.
- **Fail:** a bespoke JSON or CSV shape with no published schema and no mapping.

A tool is not required to *store* NRM internally. It is required to be able to *emit* it.

### C2 — Resources carry stable identifiers

*Detector: partial.*

- **Pass:** every exported resource carries at least one durable identifier — serial number, MAC,
  GPU UUID, IB GUID — in the `identifiers[]` shape, so two tools' exports can be reconciled.
- **Fail:** resources keyed only by a display name, a row index, or a local database id.

This is what makes merging two teams' data possible at all. A hostname is not an identifier: it
changes, and the same hostname means different hardware at different sites.

### C3 — The HTTP API has a machine-readable description

*Detector: yes.*

- **Pass:** an OpenAPI document, served by the app so it cannot drift from the routes.
- **Fail:** no description, or a hand-maintained one that no longer matches the code.

### C4 — Schema versions are explicit

*Detector: yes.*

- **Pass:** exported documents state which contract version they conform to.
- **Fail:** unversioned payloads, which make every consumer guess and make every change breaking.

### C5 — The tool does not become a competing source of truth

*Detector: no — judgement.*

- **Pass:** asset data is read from, or reconciled back to, the system of record. Nautobot is
  NVIDIA's source of record for asset management.
- **Fail:** a private inventory database that diverges from Nautobot, with no crosswalk and no
  reconciliation.

This is the criterion that most directly addresses the duplicated-data problem. The fix is rarely
"stop keeping local data" — caching and enrichment are legitimate. It is "record where the truth
came from, and be able to point back at it".

### C6 — Telemetry carries a foreign key into inventory

*Detector: partial.*

- **Pass:** exported metrics carry a label identifying the resource in inventory terms, so a
  dashboard can join telemetry to assets.
- **Fail:** metrics labelled only with a hostname or an index, duplicating inventory attributes
  into the metric labels instead of referencing them.

## Remediation patterns

**Bespoke export shape.** Do not rewrite the internal model. Add an export function that maps it to
NRM and a test that validates the output against the schema. One function, one test, and the tool
becomes consumable.

**No stable identifiers.** Find what the tool already collects — it usually has serials or MACs
somewhere — and surface them in `identifiers[]`. If it genuinely collects none, that is a data
collection gap worth naming, because it means its output cannot be joined to anything.

**Private inventory diverging from Nautobot.** Add the `resource_id` custom field to the Nautobot
records this tool cares about and store the Nautobot id alongside local records. Reconciliation
becomes possible later even if it is not implemented now.
