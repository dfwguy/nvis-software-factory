---
diataxis: reference
nvsf_generated: standards/pillars/observability.md
---

# Observability

:::{admonition} Generated page
:class: generated-page

This page is generated from `standards/pillars/observability.md` by `bin/gen-docs-reference.py`. Edits here are lost on the
next build, and CI fails if the two disagree — change the source.
:::

**Severity ceiling:** `major` — no finding against this pillar can exceed it, however strongly the model argues.

| Criterion | Statement | Deterministic detector |
|---|---|---|
| `O1` | Logging goes through a configured logger | yes |
| `O2` | Log records carry enough context to correlate | partial |
| `O3` | Secrets are redacted in logs | yes |
| `O4` | Operations that change state are recorded durably | partial |
| `O5` | Health and readiness are exposed | yes |
| `O6` | Errors are logged with the context needed to act | no — judgement |
| `O7` | Numeric health is exposed as metrics, not only prose | partial |

---

**The question:** six weeks from now, can you tell what this did and why?

Observability is where the OVA charter meets the code we write ourselves. We ask customers to
instrument their clusters; our own tooling should be able to answer the same kind of question.

## Criteria

### O1 — Logging goes through a configured logger

*Detector: yes.*

- **Pass:** the standard logging module, configured once at startup, with a level that is
  controllable without a code change.
- **Fail:** `print()` as the logging mechanism. It cannot be levelled, filtered, redirected or
  redacted, and under a WSGI server it lands somewhere nobody looks.

### O2 — Log records carry enough context to correlate

*Detector: partial.*

- **Pass:** a request or run identifier on every record emitted while handling it, so one
  operation's records can be pulled out of an interleaved log.
- **Fail:** messages with no correlating identifier, which are unusable the moment two things
  happen at once.

### O3 — Secrets are redacted in logs

*Detector: yes.*

Also a data-security criterion. It is here too because the redaction has to live in the logging
configuration to be reliable, and that makes it an observability design decision.

- **Pass:** a filter applied centrally to every sink.
- **Fail:** redaction attempted at individual call sites, which works until someone adds a call
  site.

### O4 — Operations that change state are recorded durably

*Detector: partial.*

- **Pass:** an audit trail — who did what, to what, when, and what the outcome was — written
  somewhere that survives log rotation.
- **Fail:** state-changing operations visible only in an ephemeral application log.

For anything that can power-cycle hardware, the absence of this is a `blocker`, not a `major`.

### O5 — Health and readiness are exposed

*Detector: yes.*

Covered in reliability (R5); repeated here because it is the endpoint monitoring actually scrapes.

### O6 — Errors are logged with the context needed to act

*Detector: no — judgement.*

- **Pass:** the exception, the operation, and the inputs that mattered — redacted.
- **Fail:** `except Exception: pass`, or `log.error("failed")` with no detail. A swallowed
  exception is an outage you will diagnose twice.

### O7 — Numeric health is exposed as metrics, not only prose

*Detector: partial.*

- **Pass:** counters and gauges for the things you would page on, in a scrapeable format.
- **Fail:** the only record of how often something failed is the log volume.

This is the criterion most tools skip, and it is what makes the difference between "the SA who
wrote it knows it is unhappy" and "the dashboard shows it is unhappy".

## Remediation patterns

**`print()` everywhere.** Add a `logging_config` module configured at startup before other imports,
then mechanically replace `print` with a module logger. Doing the configuration first matters —
otherwise early imports emit through the root logger's default handler and bypass your filters.

**No correlation id.** Generate one per request in a `before_request` hook, put it in a context
variable, and add a log filter that stamps it onto every record. No call site changes.

**No audit trail.** Append JSONL to a file on the durable volume. A hundred lines, and it answers
"who rebooted that node" without a database.
