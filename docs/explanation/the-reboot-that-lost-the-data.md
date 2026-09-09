---
diataxis: explanation
description: The incident that started this project, and what it says about the difference between working software and durable software.
---

# The reboot that lost the data

A team built a tool. It worked. Someone restarted the Docker service on the host it ran on, and
everything the tool had collected was gone.

Not corrupted, not partially recoverable. Gone. It was not in a volume, not in a database, not
reconstructable from logs, and not backed up. The state lived in Python data structures inside a
process, and the process ended.

The work had to be redone.

## Nothing about this was exotic

That is the important part. There was no bug, no race condition, no clever failure. Every
component behaved exactly as documented. `docker restart` creates a new container from the image.
A container's writable layer is scratch space. A Python dict lives in a process. All three
statements are in the first page of their respective documentation.

The tool worked correctly for as long as nothing restarted, which — on a developer's laptop, over
the days it took to write — is indistinguishable from working.

It is worth being precise about what the team did wrong, because the honest answer is: nothing
that anyone asked them not to do. They were not careless. They asked "does it work?", got a yes,
and shipped it. Nobody asked "where does the state live?" — and that question has to be asked
before the code exists, because afterwards the answer is expensive to change.

## Why agent-assisted development makes this more likely, not less

Most of us on this team now build tools with an agent's help, and it is genuinely good at this
kind of work. Ask for a service that collects rack telemetry and exposes it over HTTP and you get
one, quickly, and it works.

It works because the agent produced the most conventional possible implementation of what you
asked for. You asked for collection and an endpoint; you got collection and an endpoint. You did
not ask where the state lives, so the state lives in the most convenient place, which is memory.

This is not a flaw in the agent. It is a property of the interaction: **the agent optimises for
the request, and durability is almost never in the request.** It is one of a set of properties
experienced engineers supply from habit rather than from thought — the things you do without being
asked because you have been on the wrong end of not doing them.

We have a team of Solutions Architects, most of whom do not have that particular scar tissue,
producing software faster than ever. The result is predictable: more tools, quicker, with a
consistent gap in exactly the properties nobody thinks to request.

## What we chose not to do about it

**A review board.** Someone senior reviews every tool before it is used. This works and does not
scale — it makes one person the bottleneck for the whole team's velocity, and the velocity is the
thing we actually gained.

**A checklist in a wiki.** Costs nothing and changes nothing. It is read once, by the people who
already knew, and never again. Nothing detects that it was skipped.

**A blessed framework everyone must use.** Every tool is built from an approved template. This
fails on the diversity of what these tools are: a bring-up validation script, a telemetry
collector and a rack inventory service have almost nothing structurally in common, and a framework
general enough for all three constrains nothing.

## What we did instead

Write down what good looks like, in a form both a machine and a person can read, and apply it the
same way every time.

That is the whole idea. Three properties follow from it, and each one is a response to a specific
failure of the alternatives:

**The baseline is a file, not a person's judgement.** `standards/pillars/` holds eight pillars with
explicit pass and fail criteria. Both the reasoning prompts and the published reference are
generated from those files, so what the tool enforces and what the docs claim cannot drift. When
we disagree about whether something is acceptable, we argue about a file and the argument leaves a
diff.

**Deterministic where possible, judged where not.** "No `volumes:` key in the compose file" is a
measurement — a scanner finds it, cites a line, and the finding cannot be argued away. "This
module-level dict is the only copy of something important" is a judgement, because a cache is also
a module-level dict, and it needs a reader who can weigh context. The report labels which is
which, and the machinery treats them differently:
{doc}`why-the-llm-is-required-but-never-authoritative`.

**The output is a plan, not a grade.** A score tells you that you failed and leaves you to work out
what to do. The Factory emits `AGENT_PLAN.md` — ordered by severity, each item naming the file,
the criterion and the remediation pattern — because the people producing these tools with an agent
can fix things with an agent, if someone hands them a specific enough brief. Turning "your
software has durability problems" into "here is the diff" is most of the value.

## The pillar this became

Durability is the first pillar, its criteria are written from this incident, and its severity
ceiling is `blocker`:

> **D1** — State that must survive a restart is written outside the container's writable layer.
>
> **Fail:** the only copy lives in a process variable, a module-level dict, an unmounted path
> inside the container, or `/tmp`.

There is a deliberate symmetry here. The Factory's own state is in SQLite with write-ahead
logging, on a bind mount rather than a named volume, snapshotted with `VACUUM INTO` on a retention
schedule, with numbered migrations applied at startup. It is a reference implementation of the
pillar it enforces, and if it ever fails its own D1, that is a more serious bug than any assessment
it gets wrong.

The bind mount specifically, rather than a named volume, because `docker volume prune` removes
unused named volumes without asking what is in them. That is the same class of mistake as the
original incident: a routine operation on infrastructure, taken by someone who was not thinking
about your data, with no warning that data was involved.

## What this does not fix

Plenty. A tool can pass all eight pillars and be the wrong tool. It can be durable, secure,
observable and duplicate another team's work entirely — which is the problem the
{doc}`contract <why-contracts-and-why-now>` addresses, and it is a different problem.

The Factory also cannot tell you whether a backup restores. It can see that a backup mechanism
exists; it cannot see that anyone has ever exercised the restore path. Criterion D3 says so
explicitly, and its detector status is `partial`, because a check that claims more certainty than
it has is worse than one that admits the gap.

## Related

- {doc}`../reference/pillars/durability` — the criteria this incident produced.
- {doc}`why-the-llm-is-required-but-never-authoritative` — measurement versus judgement.
- {doc}`why-contracts-and-why-now` — the other half of the problem.
