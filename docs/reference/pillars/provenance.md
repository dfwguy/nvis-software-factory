---
diataxis: reference
nvsf_generated: standards/pillars/provenance.md
---

# Provenance and maintainability

:::{admonition} Generated page
:class: generated-page

This page is generated from `standards/pillars/provenance.md` by `bin/gen-docs-reference.py`. Edits here are lost on the
next build, and CI fails if the two disagree — change the source.
:::

**Severity ceiling:** `minor` — no finding against this pillar can exceed it, however strongly the model argues.

| Criterion | Statement | Deterministic detector |
|---|---|---|
| `P1` | A README that answers what, why, and how to run it | yes |
| `P2` | Configuration is documented and discoverable | yes |
| `P3` | Runtime requirements are stated | partial |
| `P4` | It is obvious how to build and deploy | yes |
| `P5` | Dependencies are declared with versions | yes |
| `P6` | Source files carry the required headers | yes |
| `P7` | Operational knowledge is written down where it will be found | partial |

---

**The question:** if the author moved to another team tomorrow, could someone else run this?

The lowest-severity pillar and often the highest-value one, because it is the difference between a
tool that outlives one engagement and a tool that is rewritten from scratch by the next SA who
needs it.

## Criteria

### P1 — A README that answers what, why, and how to run it

*Detector: yes.*

- **Pass:** what the tool does, what it is for, how to run it, and what it needs to run.
- **Fail:** no README, or the template one the forge generated.

The "why" matters more than it looks. A tool whose purpose is not written down gets reimplemented
because the next person cannot tell whether it already does what they need.

### P2 — Configuration is documented and discoverable

*Detector: yes.*

- **Pass:** every setting listed somewhere — a `.env.example`, a config example file, or a
  reference page — with meaning and default.
- **Fail:** settings discoverable only by grepping for `os.environ`.

Best when generated from the code that reads it, so the two cannot drift.

### P3 — Runtime requirements are stated

*Detector: partial.*

- **Pass:** language version, external tools, and the access it needs (which hosts, which
  credentials, which network paths).
- **Fail:** requirements discovered by running it and reading the traceback.

### P4 — It is obvious how to build and deploy

*Detector: yes.*

- **Pass:** a Dockerfile, a compose file, or a documented deployment procedure that someone else
  has followed at least once.
- **Fail:** deployment that exists only as commands in one person's shell history.

### P5 — Dependencies are declared with versions

*Detector: yes.*

Also a security criterion. Here it is about reproducibility: unpinned dependencies mean the thing
that worked last month and the thing that fails today are different software.

### P6 — Source files carry the required headers

*Detector: yes.*

- **Pass:** the NVIDIA SPDX header on source files.
- **Fail:** missing headers, which is a licensing problem before it is a style one.

### P7 — Operational knowledge is written down where it will be found

*Detector: partial.*

- **Pass:** the gotchas, the site-specific quirks, and the "if you see X it means Y" knowledge live
  in the repository — in docs, or in agent rule files.
- **Fail:** that knowledge exists only in Slack threads and the author's memory.

For our team specifically this is the highest-leverage item in the whole rubric. Most of what makes
a bring-up fast is knowledge, and knowledge that is not in a repository does not survive a
reorganization.

## Remediation patterns

**Template README.** Answer four questions in four short sections: what it does, why it exists, how
to run it, what it needs. Fifteen minutes, and it is the difference between reuse and rewrite.

**Undocumented settings.** Declare settings in one registry with type, default and description, and
generate the example file from it. Add a CI check that the committed example matches, so it cannot
go stale silently.

**Knowledge in Slack.** Start an `.cursor/rules/*.mdc` file or a docs page and paste the thread in.
Unpolished and committed beats well-written and unwritten — and once it is in the repository, the
next agent working in that codebase reads it automatically.
