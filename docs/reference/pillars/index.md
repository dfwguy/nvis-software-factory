---
diataxis: reference
nvsf_generated: standards/pillars/
---

# Quality pillars

:::{admonition} Generated page
:class: generated-page

This page is generated from `standards/pillars/` by `bin/gen-docs-reference.py`. Edits here are lost on the
next build, and CI fails if the two disagree — change the source.
:::

Baseline version `8p-7a0e63a60c82`. The version is content-addressed, so an assessment records which baseline judged it and an edit here makes older results identifiable as judged against different criteria rather than silently stale.

| Pillar | Severity ceiling | Criteria | Measured | Judgement |
|---|---|---|---|---|
| [Durability and data safety](durability.md) | `blocker` | 5 | 4 | 1 |
| [Data security](data-security.md) | `blocker` | 7 | 7 | 0 |
| [Reliability](reliability.md) | `major` | 7 | 5 | 2 |
| [Scalability](scalability.md) | `major` | 6 | 5 | 1 |
| [Testability and quality gates](testability.md) | `major` | 6 | 6 | 0 |
| [Observability](observability.md) | `major` | 7 | 6 | 1 |
| [Contract conformance](contract-conformance.md) | `major` | 6 | 5 | 1 |
| [Provenance and maintainability](provenance.md) | `minor` | 7 | 7 | 0 |

The **measured** column is the number of criteria a deterministic scanner checks. Those findings form a floor the reasoning stage may raise but never lower. The **judgement** column is the number that depend on the model reading the evidence, and every finding in the application says which kind it is.
