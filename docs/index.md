---
description: The NVIS Software Factory — assess an SA repository against a shared quality baseline, and publish the NVIS Resource Model data contract.
keywords: nvis, software factory, nvidia, nrm, resource model, code quality, diataxis
# No `diataxis:` key, deliberately. The landing page is a hub -- it routes readers to the four
# modes rather than being one of them, and badging it as an explanation would be a claim that
# reading it teaches you something, which is not its job.
---

# NVIS Software Factory

Two things live here, and they solve halves of the same problem.

**The Factory** takes a GitLab or GitHub URL, clones it safely, gathers deterministic evidence
about it, and reasons over that evidence to produce an assessment plus remediation documents you
can hand straight to a coding agent.

**The Contract** publishes the NVIS Resource Model: a small, versioned data model for every unit
of resource from a transceiver to a rack, so that two teams' tools can describe the same rack the
same way.

:::{tip}
Never used this before? {doc}`tutorials/assess-your-first-repository` takes you from a URL to a
remediation plan in about fifteen minutes, and explains what you are looking at along the way.
:::

## Why this exists

Every SA on this team can build software, and increasingly does, with an agent's help. That gets
results, and it has also produced an environment where the same fact lives in four tools that
disagree, and where a service can hold its only copy of something in a Python dict.

That last one is not hypothetical. A team lost everything they had collected because someone
restarted the Docker daemon on the host — the state was in memory, not in a volume, not in a
database, not reconstructable from logs. The work had to be redone. {doc}`explanation/the-reboot-that-lost-the-data`
writes up what happened and what it changed.

The response is not a review board. It is a baseline that is written down, machine-readable, and
applied the same way every time — plus a data contract so that "the same rack" means the same
thing in the AIC, Ethernet, IB and OVA toolchains.

## Start here

::::{grid} 2
:gutter: 3

:::{grid-item-card} Assess your first repository
:link: tutorials/assess-your-first-repository
:link-type: doc
:class-card: sd-border-primary

**Tutorial.** URL in, remediation plan out. Start here if you have not used the Factory.
:::

:::{grid-item-card} What good looks like
:link: reference/pillars/index
:link-type: doc

**Reference.** The {{ pillar_count }} pillars every assessment judges against, with the criteria and
which of them a scanner can actually measure.
:::

:::{grid-item-card} The NVIS Resource Model
:link: reference/nrm/index
:link-type: doc

**Reference.** NRM {{ nrm_version }} as JSON Schema: seven entities, and the identifier scheme that
lets two systems agree they are talking about one GPU.
:::

:::{grid-item-card} How to map your export
:link: how-to/map-your-export-to-the-nvis-resource-model
:link-type: doc

**How-to.** You have a tool that emits inventory. Get it speaking NRM without rewriting it.
:::

::::

## How the Factory reaches a conclusion

```{mermaid}
flowchart LR
    A[Repository URL] --> B[Shallow clone<br/>read-only, never executed]
    B --> C[Deterministic scanners<br/>facts with file:line]
    C --> D[Redaction<br/>before anything leaves]
    D --> E[Reasoning passes<br/>required, never optional]
    E --> F[Ratchet<br/>measured severity is a floor]
    F --> G[Assessment + AGENT_PLAN.md]
```

Two properties of that pipeline are worth stating up front, because they determine how much of a
report you should trust:

**The scanners measure; the model judges, and the report says which is which.** A scanner finding
carries a file and a line number you can go and check. A model finding is an argument from
evidence. Both are useful and they are not the same kind of claim, so every finding is labelled.

**Reasoning is required, not an enhancement.** If the reasoning endpoint is unreachable, a run
fails and says so. It does not fall back to a scanner-only report, because a thinner report that
looks like a normal one is worse than no report —
{doc}`explanation/why-the-llm-is-required-but-never-authoritative` argues that out.

## The contract, in one paragraph

NRM is deliberately small: `Resource`, `ResourceType`, `Location`, `Port`, `Link`, `Domain`,
`CoolingPath`. Identity is the interesting part — every resource carries an `identifiers[]` array
using Redfish's `DurableNameFormat` vocabulary extended with the formats this fleet actually needs
(`IB_GUID`, `GPU_UUID`, `NVLINK_GUID`, `SERIAL`), and reconciliation matches on *any* member. That
is what lets a record built from a packing list merge with the same unit discovered over the
fabric. {doc}`explanation/why-nautobot-is-the-crosswalk-target` explains why NRM crosswalks to
systems NVIDIA already governs rather than competing with them.

## Everything else

::::{grid} 3
:gutter: 2

:::{grid-item-card} How-to guides
:link: how-to/map-your-export-to-the-nvis-resource-model
:link-type: doc

Map an export, add a scanner check, deploy on an ITSS VM.
:::

:::{grid-item-card} Reference
:link: reference/index
:link-type: doc

Schemas, crosswalks, pillars, REST API, configuration. Generated from the code.
:::

:::{grid-item-card} Explanation
:link: explanation/why-contracts-and-why-now
:link-type: doc

Why contracts, why Nautobot, why the model is required, and the incident behind all of it.
:::

::::

---

Reading NRM `{{ nrm_version }}`, build `{{ release }}`. The reference section is generated from the
same files the application reads, so it cannot describe a contract the API does not serve.
