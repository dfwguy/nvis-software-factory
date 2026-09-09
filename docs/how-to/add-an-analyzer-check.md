---
diataxis: how-to
description: Turn something you keep finding by hand into a deterministic scanner check.
---

# How to add an analyzer check

You reviewed a repository, found a problem the Factory missed, and want it caught automatically
from now on.

Adding a check is adding a few lines to a scanner module. There is no registry to update —
discovery walks `backend/factory/scanners/` and any module with a `PILLAR` and a `scan()` runs.

## 1. Decide whether it is a check at all

Answer this before writing code, because it determines the whole shape of what you do next:

**Can code be certain about it?**

*Yes* — write a deterministic finding with a severity. "No `volumes:` key anywhere in the compose
file" is certain.

*No, but the evidence is useful* — write an **observation** (no severity) and let the reasoning
pass judge it. "There is a module-level dict named `_cache`" is a fact; whether it holds the only
copy of something important is a judgement.

*No, and you cannot even gather evidence* — this belongs in the pillar's criteria as a
`Detector: no` criterion, so the reasoning pass is prompted to look for it. Edit
`standards/pillars/<pillar>.md` and stop here.

:::{important}
A false deterministic finding is worse than a missed one. Deterministic findings are a one-way
ratchet — the reasoning pass may escalate a severity and may never lower one — so a wrong hard
finding cannot be cleared by anything except a code change here. When in doubt, emit an
observation.
:::

## 2. Add the criterion to the pillar first

Findings cite a criterion, and the criterion is the contract. Open the pillar file — say
`standards/pillars/durability.md` — and add to `## Criteria`:

```markdown
### D5 — Snapshots are written somewhere other than the live volume

*Detector: yes.*

- **Pass:** snapshots land on a different filesystem, an object store, or a remote host.
- **Fail:** snapshots are written into the same volume as the data they protect, so losing the
  volume loses both.
```

Say what pass and fail look like in terms someone can check, and be honest in the `Detector:`
line — `yes`, `partial` or `no`. That line is published in
{doc}`../reference/pillars/index`, and a criterion claiming a detector it does not have makes a
clean pillar mean less than it should.

Editing a pillar changes the baseline hash, so existing assessments stay identifiable as having
been judged against the previous criteria. That is intended.

## 3. Write the check

Add to the pillar's scanner module. `RepoView` is read-only and never executes anything from the
repository:

```python
def _snapshot_target(view: RepoView) -> list[Fact]:
    """D5 — a snapshot written into the volume it is protecting."""
    facts: list[Fact] = []
    for relative, line_number, line in view.grep(_SNAPSHOT_WRITE_RE, view.code_files()):
        if _writes_outside_data_dir(line):
            continue
        facts.append(Fact(
            pillar_id=PILLAR,
            key="snapshot_inside_data_volume",
            title="Snapshots are written into the volume they protect",
            detail=(
                "Losing the volume loses the data and every snapshot of it in the same event, "
                "which is the failure mode a snapshot exists to survive."
            ),
            criterion="D5",
            severity=Severity.MAJOR,
            file_path=relative,
            line_start=line_number,
            excerpt=view.excerpt(relative, line_number),
            remediation=(
                "Write snapshots to a path on a different filesystem, or push them to an "
                "object store after writing."
            ),
        ))
    return facts
```

Then call it from `scan()`.

What each field is for, since a finding is read by someone deciding whether to act:

`key`
: Stable identifier for this check. It is how a finding is tracked across runs, so do not rename
  it casually.

`file_path` + `line_start`
: The citation. **Always populate these for a deterministic finding.** A hard finding with no
  location is an assertion the reader cannot check, which is precisely what the deterministic
  layer exists not to produce.

`detail`
: Why it matters *here*, not a definition of the general problem. The reader knows what a snapshot
  is.

`remediation`
: What to do. This text ends up in `AGENT_PLAN.md` and gets executed by a coding agent, so write
  it as an instruction.

`excerpt`
: Use `view.excerpt()` rather than slicing lines yourself — it redacts, and redaction at the point
  of extraction is what makes it a boundary rather than a convention.

## 4. Bound it

Scanners run against arbitrary third-party code, including vendored SDKs and generated files.

- Use `view.grep(..., limit=N)` for citations and `view.count_matches()` for "how widespread". A
  thousand citations blow the model's context and tell it nothing that ten do not.
- Scan the narrowest file set that makes sense: `view.code_files()` excludes docs and config, so a
  `print()` in a README code block is not an observability finding.
- Emit one finding with a count, not one finding per occurrence.

There is a 90-second per-scanner budget. Exceeding it does not fail the run; it adds a fact saying
coverage may be capped, which is honest and also embarrassing, so stay inside it.

## 5. Test it both ways

`backend/tests/test_scanners.py` builds a `RepoView` over a temporary directory. Write two tests
and treat the second as mandatory:

```python
def test_flags_snapshot_written_into_data_volume(tmp_path):
    view = repo_with(tmp_path, {"backup.py": 'shutil.copy(DB, DATA_DIR / "snap.db")\n'})
    findings = [f for f in durability.scan(view) if f.key == "snapshot_inside_data_volume"]
    assert findings and findings[0].criterion == "D5"
    assert findings[0].file_path == "backup.py"


def test_does_not_flag_snapshot_written_off_volume(tmp_path):
    """The false-positive case. The ratchet means a wrong hard finding cannot be argued away."""
    view = repo_with(tmp_path, {"backup.py": 'shutil.copy(DB, Path("/mnt/backups/snap.db"))\n'})
    assert not [f for f in durability.scan(view) if f.key == "snapshot_inside_data_volume"]
```

## 6. Check it against real repositories

Run an assessment against two or three repositories you know well before you merge — ideally one
you expect to fail this check and one you expect to pass.

Regular expressions over unfamiliar code fail in ways that are obvious in hindsight and invisible
in a unit test with a fixture you wrote to match your own pattern.

## 7. Regenerate the docs

```bash
./bin/gen-docs-reference.py
```

Your criterion appears in the pillar reference page. CI runs this with `--check`, so skipping it
fails the pipeline rather than shipping docs that describe a different baseline than the one being
applied.

## Adding a whole pillar

Rarely needed — the eight cover the ground. If you do: add `standards/pillars/<id>.md` with
`id`, `title`, `severity_ceiling` and `order` in the frontmatter, add
`backend/factory/scanners/<id>.py` with `PILLAR = "<id>"` and `scan()`, and regenerate. Nothing
else registers it.

Choose the `severity_ceiling` deliberately. It is the cap on what any finding in that pillar can
reach no matter how the reasoning pass argues, and it is why a missing README cannot become a
blocker.

## Related

- {doc}`../reference/pillars/index` — the current baseline.
- {doc}`../explanation/why-the-llm-is-required-but-never-authoritative` — the ratchet, argued out.
