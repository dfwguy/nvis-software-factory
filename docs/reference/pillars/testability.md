---
diataxis: reference
nvsf_generated: standards/pillars/testability.md
---

# Testability and quality gates

:::{admonition} Generated page
:class: generated-page

This page is generated from `standards/pillars/testability.md` by `bin/gen-docs-reference.py`. Edits here are lost on the
next build, and CI fails if the two disagree — change the source.
:::

**Severity ceiling:** `major` — no finding against this pillar can exceed it, however strongly the model argues.

| Criterion | Statement | Deterministic detector |
|---|---|---|
| `T1` | There are tests, and they test behaviour | partial |
| `T2` | Tests run without the production environment | partial |
| `T3` | CI runs the suite on every change | yes |
| `T4` | A linter runs and gates, with pinned versions and declared rules | yes |
| `T5` | Coverage is measured and has a floor | yes |
| `T6` | Dependencies are reproducible | yes |

---

**The question:** can someone who did not write this change it safely?

This is the pillar that decides whether a tool can be handed over. Everything else can be fixed by
the author; this one determines whether anybody else can.

## Criteria

### T1 — There are tests, and they test behaviour

*Detector: partial — the detector counts tests and can spot trivially empty ones. Whether a test
asserts anything meaningful is judgement.*

- **Pass:** tests that would fail if the behaviour changed.
- **Fail:** no tests, or tests that only assert the code does not raise.

### T2 — Tests run without the production environment

*Detector: partial.*

- **Pass:** the suite runs on a laptop with no cluster, no BMC, and no network. External systems
  are behind an interface with a fake.
- **Fail:** tests that need a live head node. Those never run, and a test that never runs is a
  comment.

This is the single highest-leverage criterion for our tooling, because almost everything we build
talks to hardware we do not have a copy of.

### T3 — CI runs the suite on every change

*Detector: yes.*

- **Pass:** a pipeline that runs tests on merge requests, and gates on the result.
- **Fail:** no CI, or a pipeline where the test job is `allow_failure: true`. A yellow pipeline
  reads as green and a job that cannot fail is decoration.

### T4 — A linter runs and gates, with pinned versions and declared rules

*Detector: yes.*

- **Pass:** a linter with a committed config, pinned in CI, failing the build on error.
- **Fail:** no linter; or a linter with no config, so the enforced rule set is whatever that
  version happened to default to; or an unpinned linter, so a release can turn a green branch red
  for reasons the author cannot reproduce.

### T5 — Coverage is measured and has a floor

*Detector: yes.*

- **Pass:** coverage measured across the codebase with a per-file floor that gates.
- **Fail:** no measurement, or a project-wide average — which one well-tested module can hold up
  while everything around it is uncovered.

### T6 — Dependencies are reproducible

*Detector: yes.*

- **Pass:** a lockfile, or pinned versions for both runtime and test tooling.
- **Fail:** test tooling installed unpinned in CI, so "passes locally" and "passes in CI" are
  different claims about different software.

## Remediation patterns

**No tests and everything talks to hardware.** Do not start by testing the hardware paths. Extract
the pure logic — parsing, threshold comparison, report shaping — into functions that take data and
return data, and test those. That is usually most of the risk and it needs no fixtures.

**Tests exist but need a cluster.** Introduce a narrow interface at the boundary (one `run_command`
method, not a full abstraction layer) and inject a fake in tests. Capture one real output sample
per command as a fixture; those samples are valuable documentation in their own right.

**Coverage floor cannot be turned on because the codebase is already below it.** Use a floor with
an explicit, shrink-only exception list naming each file below the line. New files must meet the
floor; listed files may not get worse. This is how you switch a gate on without a red pipeline on
day one.
