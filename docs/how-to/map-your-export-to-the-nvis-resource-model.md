---
diataxis: how-to
description: Get a tool you already run emitting NRM, without rewriting its internals.
---

# How to map your export to the NVIS Resource Model

You have a tool that produces inventory in its own shape — a CSV from a bring-up script, JSON from
a discovery job, a Nautobot GraphQL response. You need it to emit NRM so other teams can consume
it. You do not want to rewrite the tool.

This guide gets you from a sample export to a tested transform. It assumes you have read
{doc}`../tutorials/describe-a-rack-in-nrm`, or at least that you know why identity is an array.

## Before you start

Have one **real** sample export on hand, with real values in it. A hand-written idealised sample
will produce a mapping that works only on hand-written idealised samples; the fields that will
cost you time are the ones that are inconsistently populated in practice.

If the export contains serial numbers or customer site names, that is fine and expected — you are
sending it to a deployment inside the NVIDIA network. Do not paste credentials.

## 1. Check whether the work is already done

Six systems already have published crosswalks: Nautobot, Redfish, UFM, BCM rack-import, DCGM and
CycloneDX. Look at {doc}`../reference/crosswalks` first.

If your tool reads from one of those, map from *that* system rather than from your tool's output.
You will inherit a mapping that is reviewed, tested and maintained, and you will not own a second
one.

## 2. Get a first-draft mapping

Open **Mapping assistant**, paste your sample export, and say in one line what the records are
("one row per compute tray from our bring-up spreadsheet").

You get back a proposed field-by-field mapping. Two things to know about it:

- The model proposes; it does not decide. Every proposal is immediately checked against the
  published schema, and you will see the adjudication next to each field.
- Fields it could not place are listed as unmapped rather than forced into an approximate home.
  That list is the useful part of the output.

::::{warning}
Read the mapping before you use it. The model is working from your sample's field *names* and a
handful of values, so a plausible-looking name mapped to the wrong NRM field is exactly the
mistake it is positioned to make — `location` meaning "rack elevation" versus "data hall" is the
classic one.
::::

## 3. Fix identity by hand

Whatever the assistant proposed for `identifiers`, review it yourself. This is the part of a
mapping that is worth ten minutes of care, because it determines whether your records merge with
anyone else's or sit alongside them as duplicates.

Work through your export's columns and ask, for each one that identifies something:

| Your column looks like | Use this format |
| --- | --- |
| A manufacturer serial off a label or packing list | `SERIAL` |
| `0x...`, 16 hex digits, from an IB tool | `IB_GUID` |
| `GPU-` followed by a UUID | `GPU_UUID` |
| A 6-byte MAC | `MACAddress` |
| An NAA WWN from storage or Redfish | `NAA` |
| A UUID from a BMC or Redfish | `UUID` |

Emit **every** identifier you have, not the one you consider primary. Reconciliation matches on
any format-and-value pair, so an extra identifier is an extra chance to merge correctly, and
holding one back guarantees a duplicate for any consumer who only has that one.

Two rules that are easy to get wrong:

**Do not synthesise identifiers.** `"format": "SERIAL", "value": "unknown-tray-17"` will match
another tool's `unknown-tray-17` and merge two unrelated resources. Omit what you do not have.

**Do not put position in identity.** Rack elevation, port number and hostname belong in
`Location`, `Port.name` and `Resource.name`. They change without the hardware changing, and an
identifier that changes is not an identifier.

## 4. Validate against the real validator

Transform a sample and submit it:

```bash
curl -sS -X POST https://<deployment>/api/contracts/validate \
  -H 'Content-Type: application/json' \
  -H "Cookie: $NVSF_SESSION" \
  --data @sample-nrm.json
```

Or paste it into the **Validate** page, which runs the same code.

Fix what comes back, in this order:

1. **Schema errors** — shape and types. Mostly mechanical.
2. **`additionalProperties` errors** — a field you invented. Either it maps to a real NRM field or
   it goes in `attributes`, which is the escape hatch for facts NRM does not model. Do not put
   something in `attributes` that has a real home; consumers will not look for it there.
3. **Semantic invariant errors** — references and cycles. These usually mean the transform emitted
   records in an order that broke `parent_id`, or that it minted a fresh ULID for a resource it had
   already emitted.

## 5. Make the ULIDs stable

The single most common defect in a first transform: re-running it produces new `id` values for the
same hardware, so every consumer sees a fleet replacement.

`id` must be derived deterministically from something that does not change, or looked up from a
record you already emitted. A hash of the strongest identifier you hold is the usual answer:

```python
#!/usr/bin/env python3
# Author: Rafael M. Koike & Cursor Agent ("Ada")
"""Stable NRM identifiers from a durable natural key."""

import hashlib
import ulid


def nrm_id(namespace: str, natural_key: str) -> str:
    """A ULID that is the same every run for the same hardware.

    Derived rather than random, because a transform that mints fresh identifiers on each run
    presents an unchanged rack as a fully replaced one to every consumer downstream.
    """
    digest = hashlib.sha256(f"{namespace}:{natural_key}".encode()).digest()
    return str(ulid.ULID.from_bytes(digest[:16]))
```

Namespace it (`"tray-serial"`, `"port-ib-guid"`) so that a serial and a GUID with coincidentally
equal string values cannot collide.

## 6. Write down what you cannot carry

Add an `unmapped_nrm` list to your notes for every NRM field your system has no source for, with
the reason. That is a required section in every published crosswalk, and it is required because
"we have no cooling data" and "we forgot cooling" look identical to a consumer otherwise.

## 7. Pin the version and test the round trip

Your transform emits `nrm_version` on every entity. Pin it explicitly to the version you tested
against rather than reading "latest" at runtime — a contract that changes underneath a running
transform is a contract that breaks it silently.

Then add a test that goes export → NRM → validate, using a committed fixture of the real sample
from step 1. `contracts/fixtures/nvl72-rack.json` is the shape to copy. When NRM moves to v0.2 that
test is what tells you, in CI, exactly which of your fields moved.

## If you want it published

A crosswalk in `contracts/crosswalk/` gets served by the API and appears in the reference docs, so
the next team to integrate your system does none of this work. That path is
{doc}`propose-a-contract-change`.

## Related

- {doc}`../reference/nrm/index` — every field, generated from the schemas.
- {doc}`../reference/crosswalks` — the six existing mappings.
- {doc}`../explanation/why-nautobot-is-the-crosswalk-target` — why to prefer mapping from a
  governed system.
