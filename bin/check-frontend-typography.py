#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual property and proprietary
# rights in and to this material, related documentation and any modifications thereto. Any use,
# reproduction, disclosure or distribution of this material and related documentation without an
# express license agreement from NVIDIA CORPORATION or its affiliates is strictly prohibited.
#
# check-frontend-typography.py — enforce the Kaizen type scale rules that a reviewer cannot see.
# Author: Rafael M. Koike & Cursor Agent ("Ada")
"""Guard the four typography mistakes this codebase has actually made.

The rules themselves live in ``.cursor/rules/frontend-typography.mdc``; this only enforces the
mechanical half. It cannot tell you a paragraph should have been ``lg`` instead of ``md`` -- that
needs a person, or a browser. What it can do is stop the specific regressions that took a long
time to diagnose, each of which looked like a different problem than it was.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FRONTEND = REPO / "frontend" / "src"
INDEX_CSS = FRONTEND / "index.css"

Problem = tuple[Path, int, str]


def _sources() -> list[Path]:
    return sorted(p for p in FRONTEND.rglob("*.tsx") if not p.name.endswith(".test.tsx"))


def _css_without_comments() -> str:
    """index.css with comment bodies blanked, line numbering intact.

    The comments in that file explain these very traps, and quote the offending declarations to do
    it. Scanning the raw text flags the documentation instead of the code.
    """
    if not INDEX_CSS.is_file():
        return ""
    return re.sub(
        r"/\*.*?\*/",
        lambda m: "\n" * m.group(0).count("\n"),
        INDEX_CSS.read_text(),
        flags=re.DOTALL,
    )


def no_ten_pixel_text() -> list[Problem]:
    """`xs` is 10px on every Kaizen text scale, and nothing here is allowed to be 10px.

    It is below the floor for anything a person reads. Kaizen spends it on badge chrome; this
    application had 35 call sites using it for table metadata before anyone measured.
    """
    pattern = re.compile(r'kind="(body|label|heading)/[a-z]+/xs"')
    problems: list[Problem] = []
    for path in _sources():
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if match := pattern.search(line):
                message = (
                    f"{match.group(0)} is 10px. The floor for readable text is `sm` (12px), and "
                    f"body copy should be `md` (14px) or `lg` (16px)."
                )
                problems.append((path, number, message))
    return problems


def no_dead_body_font_size() -> list[Problem]:
    """`body { font-size }` in index.css cannot take effect, so it must not be written.

    MUI's <CssBaseline> injects `body { ...typography.body1 }` at runtime, after the bundled
    stylesheet. A rule here loses on order every time. The danger is not the dead declaration --
    it is that editing it appears to do nothing, which reads as a stylesheet-order problem and
    sends the next person to reorder imports and add override files that also cannot work.
    """
    text = _css_without_comments()
    problems: list[Problem] = []
    for match in re.finditer(r"(?<![-\w])body\s*\{[^}]*?font-size\s*:", text, re.DOTALL):
        line = text[: match.start()].count("\n") + 1
        message = (
            "`body { font-size }` is overridden by MUI's CssBaseline and has no effect. Size text "
            "at the call site with a Kaizen `--text-*` step instead."
        )
        problems.append((INDEX_CSS, line, message))
    return problems


def no_root_scaling() -> list[Problem]:
    """The root font size stays at the browser default.

    Scaling it is the obvious fix for "the text is too small" and it is the wrong one: it
    multiplies the sizes that were already correct along with the ones that were not, moving the
    chrome away from Kaizen while leaving the mis-chosen step exactly where it was. It also
    overrides a reader's own accessibility setting.
    """
    text = _css_without_comments()
    problems: list[Problem] = []
    for match in re.finditer(r"(?<![-\w])(html|:root)\s*\{[^}]*?font-size\s*:", text, re.DOTALL):
        line = text[: match.start()].count("\n") + 1
        message = (
            "do not scale the root font size. If text is too small, a call site picked the wrong "
            "Kaizen step -- fix that instead."
        )
        problems.append((INDEX_CSS, line, message))
    return problems


def text_containers_size_in_rem() -> list[Problem]:
    """A width that bounds text is rem, so it grows when the text does.

    Declared in pixels, a drawer stays put while its labels grow with the reader's font size, and
    the longest one truncates inside a container with room to spare.
    """
    pattern = re.compile(r"^\s*export const (DRAWER_WIDTH_\w+)\s*=\s*([^;]+);")
    problems: list[Problem] = []
    for path in _sources():
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            match = pattern.match(line)
            if match and "rem" not in match.group(2):
                message = (
                    f"{match.group(1)} is {match.group(2).strip()}; a width that holds text must "
                    f"be a rem string so it scales with the text."
                )
                problems.append((path, number, message))
    return problems


CHECKS = (
    no_ten_pixel_text,
    no_dead_body_font_size,
    no_root_scaling,
    text_containers_size_in_rem,
)


def main() -> int:
    problems: list[Problem] = []
    for check in CHECKS:
        problems.extend(check())

    if not problems:
        print(
            f"check-frontend-typography: PASS — {len(CHECKS)} rules over "
            f"{len(_sources())} component(s)"
        )
        return 0

    print("check-frontend-typography: FAIL\n")
    for path, line, message in problems:
        print(f"  {path.relative_to(REPO)}:{line}")
        print(f"    {message}\n")
    print(f"{len(problems)} problem(s). The scale is documented in")
    print("  .cursor/rules/frontend-typography.mdc")
    return 1


if __name__ == "__main__":
    sys.exit(main())
