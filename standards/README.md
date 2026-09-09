# The NVIS quality baseline

This directory is the single definition of what good software looks like at NVIS. It has two
consumers, and that is the whole point:

- `backend/factory/prompts/` injects these files into the LLM reasoning passes, so the model judges
  a repository against the written standard rather than against its own priors.
- `bin/gen-docs-reference.py` renders the same files into the docs site.

If the guidance an agent receives and the guidance a human reads could drift, we would have two
standards and therefore none.

## The eight pillars

- [Durability and data safety](pillars/durability.md) — does the data survive a restart?
- [Data security](pillars/data-security.md) — credentials, transport, access.
- [Reliability](pillars/reliability.md) — behaviour when a dependency misbehaves.
- [Scalability](pillars/scalability.md) — what breaks when this is used for real.
- [Testability and quality gates](pillars/testability.md) — can a change be made safely?
- [Observability](pillars/observability.md) — can you tell what it did?
- [Contract conformance](pillars/contract-conformance.md) — does it speak NRM?
- [Provenance and maintainability](pillars/provenance.md) — can someone else pick this up?

## How a pillar is structured

Frontmatter is parsed, so it is contract rather than convention:

```yaml
---
id: durability
title: Durability and data safety
severity_ceiling: blocker
detectors:
  - backend/factory/scanners/durability.py
---
```

`id` is both a database value and a prompt key — renaming one is a migration. `severity_ceiling`
caps what the model may escalate a finding to, so a missing README cannot become a blocker no
matter how strongly the model feels about it.

## Writing criteria

Every criterion must be answerable yes or no about a specific repository. "Handles data
responsibly" is not a criterion. "State that must survive a restart is written to a path outside
the container's writable layer" is.

Some criteria have deterministic detectors and some genuinely need architectural judgement. Each
pillar says which are which, so the model knows when it is being asked to confirm a fact and when
it is being asked to form an opinion.

## Severity

- `blocker` — do not deploy. Data loss, exposed credentials, an unauthenticated mutating API.
- `major` — fix before another team depends on this.
- `minor` — worth doing, not urgent.
- `info` — an observation, no action implied.

## These are a floor, not a ceiling

A repository that clears all eight pillars is safe for another team to depend on. It is not
necessarily good software. The pillars deliberately say nothing about whether the design is elegant
or the abstraction is right, because those cannot be checked mechanically and a rubric that
pretends otherwise invites gaming.
