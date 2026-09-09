# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Scanner discovery and the run loop.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Adding a scanner is adding a module with ``PILLAR`` and ``scan(view)``. Discovery walks the
package, exactly as the API blueprint loader does, so there is no registry list to forget to
update.

ONE SCANNER'S CRASH IS NOT THE RUN'S CRASH
-------------------------------------------
:func:`run_all` catches per scanner. A scanner is a pile of regular expressions pointed at
arbitrary third-party code, and eventually one of them will hit a file that breaks an assumption.
Losing that pillar's evidence is bad; losing an eight-minute assessment because the observability
scanner tripped over a minified bundle is worse.

The failure is not silent. It becomes a fact of its own, tagged so the report says "this pillar
could not be evaluated" rather than quietly reading as "nothing found here" -- which is the same
distinction between absence of evidence and evidence of absence that the whole pipeline turns on.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import time
from types import ModuleType

from .base import Fact, RepoView, Scanner

__all__ = ["Fact", "RepoView", "ScanReport", "Scanner", "discover", "run_all"]

_logger = logging.getLogger("nvsf.factory.scanners")

#: Per-scanner wall-clock budget. A pathological repository -- a million-line generated file, a
#: vendored SDK -- can make a linear scan quadratic in practice. Exceeded is reported, not raised.
SCANNER_BUDGET_SECONDS = 90.0


def discover() -> dict[str, ModuleType]:
    """Every scanner module in this package, keyed by module name.

    Underscore-prefixed modules and ``base`` are skipped, so helpers can live here without being
    mistaken for scanners.
    """
    found: dict[str, ModuleType] = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_") or info.name == "base":
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        pillar = getattr(module, "PILLAR", None)
        scan = getattr(module, "scan", None)
        if not pillar or not callable(scan):
            # Loud, because a scanner that silently does not run means a pillar reports clean.
            raise RuntimeError(
                f"scanners: {info.name} defines no PILLAR/scan(); either implement both or "
                f"rename it with a leading underscore"
            )
        found[info.name] = module
    return found


class ScanReport:
    """Facts from a full scan, plus what it cost and what failed.

    Kept as an object rather than a bare list because the assessment needs the timing and the
    failure list for the run record, and callers should not have to reach into a tuple.
    """

    def __init__(self) -> None:
        self.facts: list[Fact] = []
        self.durations: dict[str, float] = {}
        self.failures: dict[str, str] = {}

    @property
    def findings(self) -> list[Fact]:
        """Facts carrying a severity. The ratchet floor."""
        return [f for f in self.facts if f.is_finding]

    @property
    def observations(self) -> list[Fact]:
        return [f for f in self.facts if not f.is_finding]

    def by_pillar(self) -> dict[str, list[Fact]]:
        grouped: dict[str, list[Fact]] = {}
        for fact in self.facts:
            grouped.setdefault(fact.pillar_id, []).append(fact)
        return grouped

    def to_json(self) -> dict[str, object]:
        return {
            "facts": [f.to_json() for f in self.facts],
            "durations_seconds": {k: round(v, 3) for k, v in self.durations.items()},
            "failures": self.failures,
            "counts": {
                "facts": len(self.facts),
                "findings": len(self.findings),
                "observations": len(self.observations),
            },
        }


def run_all(view: RepoView, only: list[str] | None = None) -> ScanReport:
    """Run every scanner against *view*.

    ``only`` restricts to named modules, which is what the tests and a future "re-run just this
    pillar" action use.
    """
    report = ScanReport()
    modules = discover()
    if only is not None:
        modules = {name: module for name, module in modules.items() if name in set(only)}

    for name, module in sorted(modules.items()):
        started = time.monotonic()
        try:
            facts = module.scan(view)
        except Exception as error:
            elapsed = time.monotonic() - started
            report.durations[name] = elapsed
            report.failures[name] = f"{type(error).__name__}: {error}"
            _logger.exception("scanners: %s failed after %.1fs", name, elapsed)
            report.facts.append(Fact(
                pillar_id=getattr(module, "PILLAR", name),
                key="scanner_failed",
                title=f"The {name} scanner failed, so this pillar was not evaluated",
                detail=(
                    f"{type(error).__name__}: {error}. Treat this pillar as unknown rather than "
                    "clean — no evidence was collected for it."
                ),
                data={"scanner": name, "error": f"{type(error).__name__}: {error}"},
            ))
            continue

        elapsed = time.monotonic() - started
        report.durations[name] = elapsed
        report.facts.extend(facts)
        if elapsed > SCANNER_BUDGET_SECONDS:
            _logger.warning("scanners: %s took %.1fs (budget %.0fs)", name, elapsed,
                            SCANNER_BUDGET_SECONDS)
            report.facts.append(Fact(
                pillar_id=getattr(module, "PILLAR", name),
                key="scanner_slow",
                title=f"The {name} scanner exceeded its time budget",
                detail=f"Took {elapsed:.0f}s against a {SCANNER_BUDGET_SECONDS:.0f}s budget. "
                       "Its results are included, but coverage may be capped by internal limits.",
                data={"scanner": name, "seconds": round(elapsed, 1)},
            ))

    _logger.info(
        "scanners: %d scanner(s), %d fact(s), %d finding(s), %d failure(s) in %.1fs",
        len(modules), len(report.facts), len(report.findings), len(report.failures),
        sum(report.durations.values()),
    )
    return report
