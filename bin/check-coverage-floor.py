#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Every file reaches the coverage floor, or is on a shrinking list of known exceptions.

Author: Rafael M. Koike & Cursor Agent ("Ada")

This project starts with the gate on and the exception list EMPTY, which is the whole advantage of
a greenfield repo: there is no pre-existing debt to grandfather in, so the list can only ever grow
by someone deciding to add to it in a merge request.

The gate enforces two things:

  1. Any file NOT on the list must meet the floor. A new file therefore cannot merge below it.
  2. A file ON the list must not get worse than its recorded value (plus a small tolerance).

Usage:
    python -m pytest backend/tests --cov --cov-config=.coveragerc --cov-report=json:coverage.json
    bin/check-coverage-floor.py coverage.json

Exits non-zero on a violation so it can gate a CI job.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

FLOOR = 60.0

#: Allowed slippage on an exception file before the gate complains. Coverage moves by fractions of
#: a percent when unrelated code is added, and a gate that fails on noise gets switched off.
TOLERANCE = 1.5

#: Files below the floor. THIS LIST MAY ONLY SHRINK, and it starts empty on purpose.
#:
#: Measure from a tracked-files-only tree, not your working tree -- an untracked fixture lying
#: around locally can move a file by several points and CI will reject numbers seeded from it:
#:
#:   git ls-tree --name-only HEAD | grep -v -e '^\.' -e '^frontend$' \
#:     | xargs git archive HEAD -- | tar -x -C <dir>
EXCEPTIONS: dict[str, float] = {}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check-coverage-floor.py <coverage-json>", file=sys.stderr)
        return 64

    path = Path(argv[1])
    if not path.is_file():
        print(f"coverage-floor: no such report: {path}", file=sys.stderr)
        return 64
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        files = report["files"]
    except (ValueError, KeyError) as exc:
        print(f"coverage-floor: {path} is not a coverage json report ({exc})", file=sys.stderr)
        return 64

    new_violations: list[str] = []
    regressions: list[str] = []
    improved: list[str] = []

    for name, data in sorted(files.items()):
        if int(data["summary"]["num_statements"]) == 0:
            continue
        pct = float(data["summary"]["percent_covered"])
        baseline = EXCEPTIONS.get(name)
        if baseline is None:
            if pct < FLOOR:
                new_violations.append(f"{name}: {pct:.1f}% is below the {FLOOR:.0f}% floor")
        elif pct >= FLOOR:
            improved.append(f"{name}: {pct:.1f}% — above the floor in THIS run")
        elif pct < baseline - TOLERANCE:
            regressions.append(
                f"{name}: {pct:.1f}%, was {baseline:.1f}% when listed — the list may only shrink"
            )

    stale = [n for n in EXCEPTIONS if n not in files]

    if improved:
        print("coverage-floor: listed files that cleared the floor in this run:")
        for line in improved:
            print(f"  {line}")
        print("  Confirm in a tracked-files-only tree before removing an entry.")
    if stale:
        print("coverage-floor: listed files that no longer exist (delete these entries):")
        for name in stale:
            print(f"  {name}")

    if new_violations or regressions:
        print()
        if new_violations:
            print(f"coverage-floor: FAIL — {len(new_violations)} file(s) below the floor and not "
                  "on the exception list:")
            for line in new_violations:
                print(f"  {line}")
            print("  Cover the file, or -- if it is genuinely untestable -- add it to EXCEPTIONS in")
            print("  this script with a reason, which makes the debt a reviewed decision.")
        if regressions:
            print(f"coverage-floor: FAIL — {len(regressions)} listed file(s) got worse:")
            for line in regressions:
                print(f"  {line}")
        return 1

    total = float(report["totals"]["percent_covered"])
    print(f"coverage-floor: PASS — {len(files)} files, total {total:.1f}%, "
          f"{len(EXCEPTIONS) - len(stale)} known exception(s) remaining")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
