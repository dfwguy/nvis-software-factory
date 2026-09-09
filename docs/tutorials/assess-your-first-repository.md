---
diataxis: tutorial
description: Take a repository from URL to remediation plan, and learn what each part of the report means.
---

# Assess your first repository

By the end of this you will have run a full assessment, read the report, and produced a document
you can paste into a Cursor or Claude session to actually fix what it found.

This is a lesson, not a recipe. You will be told to do things whose reason is not obvious yet, and
each one is explained after you have seen what it does. Fifteen minutes, give or take how long the
reasoning passes take on the day.

:::{note}
Use a repository you did not write. The first assessment you read is much easier to think about
when you are not defending it. A small internal tool from another team is ideal.
:::

## What you need

- Access to a Software Factory deployment, and a browser signed in to it.
- A GitLab or GitHub URL for a repository the deployment can reach.
- Nothing installed locally. The clone happens server-side.

If you do not have a deployment yet, {doc}`../how-to/deploy-on-an-itss-vm` gets one running, then
come back here.

## Step 1 — Check that the deployment can reason

Open **Platform health** in the sidebar and press **Probe now** under *Reasoning endpoint*.

You want "Reachable". If it says otherwise, stop here — a run will fail, and it will fail after
cloning and scanning, which wastes several minutes. Reasoning is a required stage of every
assessment, not an enhancement on top of a scanner report.

That design choice is doing real work, and it is the first thing to understand about this tool. A
system that quietly degraded to a scanner-only report when the model was unavailable would hand
you something that *looks* like a normal assessment and is missing the half that weighs one
finding against another. You would have no way to tell from the page.

## Step 2 — Start a run

Go to **Repositories** and paste your URL into *Repository URL*.

Now expand **Add context**. It is optional and you should fill it in anyway, at least this once,
because you are about to see what it changes:

- **What is it for?** — one sentence. "Collects DCGM and NVLink health during rack bring-up and
  writes a validation report."
- **Who depends on it?** — pick honestly. This is the field with the largest effect on the report.
- **What data does it hold?** — "Serial numbers, BMC credentials, customer rack layouts", or
  whatever is true.

Press **Start assessment**.

::::{dropdown} Why the criticality answer changes the severities
:color: light

The same missing bind mount is a nuisance in an experiment and an outage in a shared service. A
tool that assigned one severity to that finding regardless would be wrong in one of those two
cases, every time.

So criticality is part of the evidence the reasoning stage sees, and it moves severities within
each pillar's ceiling. If you leave it blank the report says "not stated" rather than assuming,
which is honest but less useful to you.
::::

## Step 3 — Watch it work, and read what the stages mean

The page follows the run. You will see it move through acquiring, scanning, reasoning and
rendering. It is worth knowing what each stage is doing, because it determines what you can trust
later:

**Acquiring** — a shallow clone, no submodules, with a size cap and a time cap. Nothing from the
repository is ever executed. Not a test, not a build, not `setup.py`. The Factory reads files.

**Scanning** — deterministic scanners walk the tree and emit *facts*, each with a file path and a
line number. "This module holds state in a dict and nothing writes to a mounted path" is a
measurement, and you can go and check it.

**Reasoning** — the evidence, redacted, goes to the model in several passes: what this software
is, then per-pillar judgement, then a remediation plan, then what it still needs to ask you.

**Rendering** — the Markdown documents.

:::{important}
Redaction happens at the evidence layer, before serialization — so anything credential-shaped is
replaced by a description of its shape (`AWS-key-like, 40 chars`) before it reaches the model or
gets written to the database. The check runs on the way *out* of the scanners rather than on the
way *in* to the prompt, so there is no path that skips it.
:::

## Step 4 — Read the report from the top

The page is ordered the way it is on purpose. Read it in that order the first time.

### The headline and posture

One sentence about what this software is and whether you would trust it with anything. Read it,
then be a little sceptical of it — it is a judgement, and you are about to see what it rests on.

### Per-pillar verdicts

Eight pillars, each `pass`, `concerns`, `fail` or `undetermined`. Two things to notice:

`undetermined` is a real answer, not a failure to answer. It means the evidence did not support a
verdict — usually because the relevant code is not in this repository. That is more useful than a
guess.

Each pillar has a **severity ceiling**. A finding against the provenance pillar cannot be a
blocker no matter how strongly the model argues, because a missing README does not lose anyone's
data. The ceiling lives in the pillar definition, so changing it is a documentation edit that
shows up in review.

### Findings

Expand a few. Each carries a badge saying where it came from, and this is the most important thing
on the page:

`scanner`
: A deterministic detector found it. There is a file and a line. This is a measurement.

`model`
: The model raised it from reading the evidence, with no detector behind it. This is an argument.
  Sometimes an excellent one; still an argument.

`escalated from minor`
: A scanner measured it as minor and the model argued it is worse *in this repository's context*.
  You can see both severities, so you can judge the argument.

There is no `de-escalated` badge, and there cannot be. Deterministic findings form a one-way
ratchet: the model may raise a severity and may never lower one. If a scanner measured that the
only copy of something lives in a dict, no amount of context makes that not the case.

### Open questions

The questions the report could not answer from the code. These are the highest-value thing on the
page and the easiest to skip. Answer them and run it again — the second report is materially
better than the first, because ambiguity that the model had to guess at becomes evidence.

## Step 5 — Take the plan to an agent

Scroll to **Documents** and download `AGENT_PLAN.md`.

Open your repository in Cursor or Claude Code, paste the plan in, and let it work. The plan is
written for that: ordered by severity, each item naming the file, the criterion it fails, and the
remediation pattern to apply. Then check the diff — the plan is a brief, not an authority.

The other two documents are for different readers. `ASSESSMENT.md` is the version to send to the
team that owns the code. `EVIDENCE.md` is exactly what the model was given, and it is what to read
when you disagree with a conclusion: usually the evidence was thin rather than the reasoning being
wrong, and that is a different fix.

## Step 6 — Look at the provenance

Expand **Provenance** at the bottom of the report.

Model id, prompt version, evidence hash, token counts, and the raw response of every pass. You
will probably never need this. It is there because a conclusion you cannot trace is a conclusion
you cannot argue with, and "the tool said so" is not a position anyone can defend in a review with
the team whose code was just called unsafe.

The **baseline version** in the footer matters for the same reason: it is content-addressed from
`standards/`, so when someone edits a pillar, this report remains identifiable as having been
judged against different criteria rather than becoming silently stale.

## What you did

You ran an assessment, and you can now tell measurement from judgement in the output — which is
the skill that makes the rest of this tool useful.

## Where to go next

::::{grid} 2
:gutter: 2

:::{grid-item-card} The pillars in full
:link: ../reference/pillars/index
:link-type: doc

Every criterion, and which ones a scanner can actually measure.
:::

:::{grid-item-card} Add a check of your own
:link: ../how-to/add-an-analyzer-check
:link-type: doc

You found something the scanners missed. Make it a measurement.
:::

::::
