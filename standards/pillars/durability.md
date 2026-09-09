---
id: durability
title: Durability and data safety
severity_ceiling: blocker
order: 1
detectors:
  - backend/factory/scanners/durability.py
---

# Durability and data safety

**The question:** if this process dies right now, what is gone?

This pillar exists because of a specific incident. A team built a service that kept all of its
state in memory inside a container. Someone unrelated restarted the Docker daemon on that host. The
data was not in a volume, not in a database, not reconstructable from logs, and not backed up. It
was simply gone, and the work that produced it had to be redone.

Nothing about that failure was exotic. It is the default outcome for a service that was never asked
this question.

## Criteria

### D1 — State that must survive a restart is written outside the container's writable layer

*Detector: yes.*

A container's filesystem is scratch space. Anything written to it disappears on `docker rm`, on an
image update, and on most orchestrator reschedules.

- **Pass:** durable state is written to a bind mount or a named volume declared in the compose file
  or manifest.
- **Fail:** the only copy lives in a process variable, a module-level dict, an unmounted path
  inside the container, or `/tmp`.

Note that a named volume is better than nothing and worse than a bind mount, because
`docker volume prune` removes unused named volumes without asking about their contents.

### D2 — The durable store survives an unclean shutdown

*Detector: partial.*

Being on disk is not the same as being intact. A JSON file rewritten with `open(path, "w")` is
empty for the duration of the write, and a crash in that window leaves a truncated file where the
data used to be.

- **Pass:** an embedded or external database with write-ahead logging, or file writes that go
  through a temporary file plus an atomic `os.replace`.
- **Fail:** in-place rewrites of a file that holds the only copy of something.

### D3 — There is a backup, and its restore path has been exercised

*Detector: partial — the detector can see a backup mechanism, not whether it works.*

An unverified backup is a belief, not a control.

- **Pass:** scheduled snapshots to a location that is not the same disk, a documented retention
  window, and a documented restore procedure.
- **Fail:** no backup, or a backup written next to the live data so that losing the volume loses
  both.

### D4 — Schema changes are migrations, not manual steps

*Detector: yes.*

- **Pass:** versioned migrations applied automatically at startup, or an explicit documented
  migration command.
- **Fail:** schema drift handled by hand, by `DROP TABLE`, or by "delete the file and let it
  recreate".

### D5 — Data loss is loud

*Detector: no — judgement.*

When the store is unavailable, the service should fail visibly rather than silently continue with
an empty in-memory substitute. Falling back to a dict on a database error converts an outage into
data loss, and does it quietly.

## What good looks like

For a small internal tool, this is genuinely not a big lift:

- SQLite in WAL mode on a bind-mounted host directory.
- Numbered SQL migrations applied at startup.
- A periodic `VACUUM INTO` snapshot with a retention window.
- Startup fails loudly if the data directory is missing or not writable, rather than quietly using
  a path inside the container.

That is roughly a hundred lines and it removes this entire failure class. The Software Factory
itself is built this way, deliberately — a tool that audits durability cannot fail its own check.

## Remediation patterns

**In-memory dict as the source of truth.** Introduce a store module with the same interface the
dict had (`get`, `put`, `list`), back it with SQLite, and change the construction site. The call
sites do not need to change, which is what makes this a contained change rather than a rewrite.

**JSON file rewritten in place.** Write to `path.tmp`, `flush()`, `os.fsync()`, then
`os.replace(tmp, path)`. `os.replace` is atomic on POSIX and Windows, so a crash leaves either the
old file or the new one.

**No volume in compose.** Add a bind mount to a host path, and make the application refuse to start
if that path is not writable. The refusal is the important half: without it, a mount typo silently
degrades to container-local storage and looks fine until the restart.
