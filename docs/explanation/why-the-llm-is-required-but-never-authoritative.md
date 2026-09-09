---
diataxis: explanation
description: Why reasoning is a mandatory pipeline stage with no degraded mode, and why it can never lower a severity a scanner measured.
---

# Why the LLM is required, but never authoritative

Two decisions about this system look contradictory until you see what each one is for:

1. If the reasoning endpoint is unreachable, an assessment **fails**. There is no scanner-only
   mode.
2. The reasoning stage may **never** lower a severity a scanner established.

The first says the model is essential. The second says it cannot be trusted. Both are right,
because they are about different failure modes.

## Why required

The obvious design is a scanner suite with optional AI enhancement. Scanners produce the report;
if a model is available, it adds commentary. It degrades gracefully.

We rejected that, and the reason is worth being precise about, because "AI-first" as a slogan is
not an argument.

**Most of what matters here cannot be measured.** Look at the detector status in
{doc}`../reference/pillars/index`: roughly a third of criteria are `yes`, a third `partial`, a
third `no`. That distribution is not a gap in our scanner engineering. It is the nature of the
questions:

- *Is this the only copy of something important?* A scanner sees a module-level dict. Whether it
  is a cache or the system of record depends on what else in the codebase reads it, what the tool
  is for, and who depends on it. That is reading comprehension.
- *Is this error handling, or is it silence?* A bare `except: pass` around a health check is a
  reliability failure. The same three lines around a best-effort metrics push is correct. The
  syntax is identical.
- *Does the architecture match the claim?* "Scales horizontally" plus in-process scheduler state
  is a contradiction a reader spots and a regular expression cannot.

A scanner-only report answers the third of the baseline that happens to be mechanically checkable,
which is not the third that lost that team their data.

**And a degraded report is worse than no report.** This is the sharper half. Suppose the endpoint
is down and we emit scanner findings only. That report has: a severity distribution, per-pillar
sections, citations, a professional appearance — and no judgement of anything that required
reading the code. A reader cannot tell. They see few findings and conclude the software is in
decent shape.

An assessment that fails loudly costs someone five minutes. An assessment that quietly answers a
third of the question costs someone their confidence in a tool that deserved scrutiny. So the
pipeline fails closed: the startup gate refuses to boot without a reachable endpoint, and a run
that loses it mid-flight is marked failed rather than partial.

## Why never authoritative

The other half. Language models are fluent, and fluency is uncorrelated with correctness. A model
given a repository will produce a confident, well-organised, plausible assessment whether or not
it understood the code — and the failure mode is not gibberish, it is a specific claim about a
specific file that is subtly wrong.

That is dangerous in a report that gets sent to another team as an argument that their software is
unsafe. So three mechanisms constrain what the model's output can be.

### The ratchet

Deterministic findings set a floor. The model may escalate a severity, with a reason. It may never
lower one.

The asymmetry is the point. Consider what each direction means:

**Escalation** is the model saying "a scanner measured this as minor; given what this tool is for
and who depends on it, it is worse than that." That is exactly the contextual reasoning we brought
it in for, and the report shows both severities so a reader can judge the argument.

**De-escalation** would be the model saying "a scanner measured this and I am overruling the
measurement." But the scanner did not have an opinion. It found no `volumes:` key in the compose
file. There is no context under which container-local writes survive `docker rm`. A model that
appears to argue otherwise has not found an exception; it has produced fluent text that happens
to disagree with a fact.

This constrains what a scanner author may assert, too, and the constraint is load-bearing: set a
severity only when the check cannot be wrong. A false hard finding is worse than a missed one,
because the ratchet means nothing clears it except a code change. Everything less certain is an
observation with no severity, which the model is free to judge in either direction.

### Severity ceilings

Each pillar caps how bad any finding in it can be, in the pillar file. Provenance findings cannot
be blockers, because a missing README does not lose anyone's data — no matter how strongly the
model argues on a day when it has been reading about documentation debt.

The ceiling lives in the frontmatter, so changing one is a documentation edit that appears in a
diff and gets reviewed. It is not a constant buried in a prompt.

### Provenance on everything

Every run records the model identifier, the prompt template version, a hash of the evidence, token
counts, and the raw response of every pass. Every finding is labelled `scanner`, `model`, or
`escalated from <severity>`.

This is not for auditors. It is for the conversation where another team disagrees with a
conclusion about their code, and the honest answer has to be better than "the tool said so." With
provenance, you can show what the model was given and what it said. Often the evidence was thin
rather than the reasoning wrong — a different problem, with a different fix, and one you can only
diagnose if you kept the inputs.

The baseline version is content-addressed from `standards/` for the same reason: when someone
edits a pillar, old assessments remain identifiable as having been judged against different
criteria, rather than becoming silently stale.

## What the model is actually for

Given all those constraints, what is left? The parts of the work that are genuinely reading and
writing:

**Understanding what the software is.** Before any judgement, one pass establishes what this
repository does. Everything downstream depends on it, because "no retry logic" means different
things in a report generator and a telemetry collector.

**Weighing evidence against criteria.** A pillar verdict is a judgement over facts, including the
judgement that the facts are insufficient — `undetermined` is a real verdict, and a scanner cannot
produce it.

**Writing the remediation plan.** `AGENT_PLAN.md` is the deliverable. It has to be specific enough
for a coding agent to act on, ordered so the sequence makes sense, and written in the idiom of
*this* codebase. That is a writing task, and it is the thing the model does best.

**Asking the questions the code cannot answer.** The open questions section — "is this the system
of record for rack layouts, or a cache of Nautobot?" — is often the most valuable output. Answer
them, re-run, and the second report is materially better, because ambiguity the model had to guess
at has become evidence.

## Redaction, and why it is at the evidence layer

The model runs on an internal endpoint, and it still gets redacted input. Anything
credential-shaped is replaced with a description of its shape — `AWS-key-like, 40 chars` — before
serialization.

The placement matters more than the fact. Redaction happens on the way *out* of the scanners, not
on the way *in* to the prompt. Put it at the prompt and it is a convention that the next code path
to serialize evidence — an export, a debug log, a database write — silently bypasses. Put it at
extraction and there is no path that skips it.

`view.excerpt()` redacts. Reading lines and slicing them yourself does not. That is why the helper
exists and why scanners are expected to use it.

## Related

- {doc}`the-reboot-that-lost-the-data` — what the baseline is for.
- {doc}`../reference/pillars/index` — detector status per criterion.
- {doc}`../how-to/add-an-analyzer-check` — where the certain/uncertain line falls in practice.
