# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Does it still work at 72 nodes, and at 30 racks?

Author: Rafael M. Koike & Cursor Agent ("Ada")

Scalability findings here are almost all observations rather than deterministic findings, for a
specific reason: a sequential loop over hosts is a correct, readable implementation, and calling it
a defect is only justified once you know the fan-out. Eight BMCs sequentially is fine. Seventy-two
racks of eighteen trays each, at four seconds per BMC, is ninety minutes — and that is the same
code. The scanner reports the shape and the reasoning pass supplies the arithmetic.
"""

from __future__ import annotations

import re

from store.models import Severity

from .base import Fact, RepoView

PILLAR = "scalability"

#: Sequential iteration over something host-shaped, containing a network call.
_HOST_LOOP_RE = re.compile(
    r"""(?ix)
    for \s+ \w+ \s+ in \s+
    (?: \w* (?: host | node | bmc | switch | rack | tray | gpu | device | target | server |
                ip | address | endpoint | member | port ) \w* )
    """
)

_NETWORK_IN_BODY_RE = re.compile(
    r"(?i)requests\.|httpx\.|urlopen|\.get\(|\.post\(|ssh|redfish|ipmitool|subprocess|"
    r"paramiko|socket\."
)

_PARALLEL_HINTS = (
    "ThreadPoolExecutor", "ProcessPoolExecutor", "asyncio.gather", "asyncio.as_completed",
    "multiprocessing.Pool", "joblib.Parallel", "concurrent.futures", "Promise.all",
    "errgroup", "rayon", "pdsh", "clush", "ansible", "parallel-ssh", "fabric",
)

#: Pulling a whole thing into memory at once.
_READ_ALL_RE = re.compile(
    r"""(?ix)
    (?: \.read \s* \( \s* \)
      | \.readlines \s* \( \s* \)
      | json\.load \s* \(
      | \.load \s* \( \s* (?:f|fh|fp|file|handle) \s* \)
      | pd\.read_(?:csv|json|parquet) \s* \(
      | fetchall \s* \( \s* \)
    )
    """
)

_UNBOUNDED_QUERY_RE = re.compile(
    r"(?i)(?:SELECT\s+\*\s+FROM\s+\w+\s*(?:;|\"|'|$))|\.all\(\)\s*$|objects\.all\(\)"
)

_PAGINATION_HINTS = ("limit", "offset", "page", "cursor", "LIMIT ", "per_page", "paginate",
                     "next_page", "chunk", "batch", "yield ", "iterator", "stream")


def scan(view: RepoView) -> list[Fact]:
    facts: list[Fact] = []
    code = view.code_files()
    haystack = " ".join(view.read(f) or "" for f in code)
    manifests = " ".join(view.read(f) or "" for f in view.find_names(
        "requirements.txt", "pyproject.toml", "package.json", "go.mod",
    ))

    parallel = sorted({h for h in _PARALLEL_HINTS if h in haystack or h in manifests})

    # ── C1: sequential fan-out over hosts ────────────────────────────────────────────────────
    host_loops: list[tuple[str, int, int]] = []
    for relative in code:
        lines = view.lines(relative)
        for index, line in enumerate(lines):
            if not _HOST_LOOP_RE.search(line):
                continue
            indent = len(line) - len(line.lstrip())
            body: list[str] = []
            for following in lines[index + 1:index + 40]:
                if following.strip() and len(following) - len(following.lstrip()) <= indent:
                    break
                body.append(following)
            if _NETWORK_IN_BODY_RE.search(" ".join(body)):
                host_loops.append((relative, index + 1, len(body)))

    if host_loops:
        facts.append(Fact(
            pillar_id=PILLAR, key="sequential_host_fanout",
            title=f"{len(host_loops)} sequential loop(s) over hosts containing a network call",
            detail=(
                "Wall-clock time here is nodes times per-node latency. That is fine at eight "
                "nodes and it is ninety minutes at an NVL72 fleet. "
                + (f"Parallel execution appears elsewhere in the repository ({parallel[0]}), so "
                   "some paths may already be handled."
                   if parallel else
                   "No parallel execution primitive appears anywhere in the repository.")
            ),
            criterion="C1",
            # An observation: the loop is only a defect at a fan-out the scanner cannot see.
            severity=None,
            file_path=host_loops[0][0], line_start=host_loops[0][1],
            excerpt=view.excerpt(host_loops[0][0], host_loops[0][1], context=2),
            data={
                "sites": [f"{p}:{n}" for p, n, _ in host_loops[:15]],
                "parallel_primitives": parallel,
            },
        ))
    elif parallel:
        facts.append(Fact(
            pillar_id=PILLAR, key="parallel_execution_present",
            title=f"Parallel execution primitives present: {', '.join(parallel[:5])}",
            detail="Concurrency bound and failure isolation per worker still need checking.",
            criterion="C1",
            data={"primitives": parallel},
        ))

    # Unbounded concurrency is the opposite failure and just as real: 72 simultaneous SSH
    # sessions from one host exhausts file descriptors before it exhausts patience.
    if parallel:
        bounded = view.grep(
            r"(?i)max_workers\s*=|Semaphore\s*\(|concurrency\s*=|limit\s*=|-P\s*\d+|"
            r"pool_size|batch_size",
            code, limit=10,
        )
        if not bounded:
            facts.append(Fact(
                pillar_id=PILLAR, key="unbounded_concurrency",
                title="Parallel execution with no concurrency bound found",
                detail=(
                    "No `max_workers`, semaphore, or batch size appears. Unbounded fan-out "
                    "exhausts local file descriptors and can look like a denial of service to "
                    "the BMCs or the switch management plane on the receiving end."
                ),
                criterion="C1", severity=Severity.MINOR,
                remediation=(
                    "Set an explicit worker count and derive it from the target's capacity, not "
                    "from the local core count."
                ),
            ))

    # ── C2: loading everything into memory ───────────────────────────────────────────────────
    read_all = view.grep(_READ_ALL_RE, code, limit=30)
    streaming = sorted({h for h in _PAGINATION_HINTS if h in haystack})
    if read_all:
        facts.append(Fact(
            pillar_id=PILLAR, key="whole_file_reads",
            title=f"{len(read_all)} site(s) that read an entire file or result set into memory",
            detail=(
                "Fine for a config file, a problem for a telemetry dump or a full `fetchall` on a "
                "table that grows. Whether it matters depends on what the input is, which is why "
                "this is reported rather than asserted. "
                + (f"Streaming or pagination signals present: {', '.join(streaming[:6])}."
                   if streaming else "No streaming or pagination signals found.")
            ),
            criterion="C2",
            file_path=read_all[0][0], line_start=read_all[0][1],
            data={"sites": [f"{p}:{n}" for p, n, _ in read_all[:12]],
                  "streaming_signals": streaming},
        ))

    unbounded_query = view.grep(_UNBOUNDED_QUERY_RE, code, limit=20)
    if unbounded_query:
        facts.append(Fact(
            pillar_id=PILLAR, key="unbounded_query",
            title=f"{len(unbounded_query)} query with no LIMIT or pagination",
            detail="Response size and memory use grow with the table.",
            criterion="C2",
            file_path=unbounded_query[0][0], line_start=unbounded_query[0][1],
            data={"sites": [f"{p}:{n}" for p, n, _ in unbounded_query[:10]]},
        ))

    # ── C3: N+1 queries inside loops ─────────────────────────────────────────────────────────
    n_plus_one: list[tuple[str, int]] = []
    for relative in code:
        lines = view.lines(relative)
        for index, line in enumerate(lines):
            if not re.match(r"\s*(?:for|while)\s", line):
                continue
            indent = len(line) - len(line.lstrip())
            for following in lines[index + 1:index + 25]:
                if following.strip() and len(following) - len(following.lstrip()) <= indent:
                    break
                if re.search(r"(?i)\.execute\s*\(|\.query\s*\(|\.filter\s*\(|\.get\s*\(|"
                             r"fetchone\s*\(|SELECT ", following):
                    n_plus_one.append((relative, index + 1))
                    break

    if n_plus_one:
        facts.append(Fact(
            pillar_id=PILLAR, key="query_inside_loop",
            title=f"{len(n_plus_one)} loop(s) issuing a query or lookup per iteration",
            detail=(
                "The classic N+1. Per-iteration round-trip cost is invisible on a fixture and "
                "dominant on real data."
            ),
            criterion="C3",
            file_path=n_plus_one[0][0], line_start=n_plus_one[0][1],
            excerpt=view.excerpt(n_plus_one[0][0], n_plus_one[0][1], context=2),
            remediation="Fetch the set in one query and index it in memory, or use a join.",
            data={"sites": [f"{p}:{n}" for p, n in n_plus_one[:12]]},
        ))

    # ── C4: resource limits ──────────────────────────────────────────────────────────────────
    compose = view.find_names("docker-compose.yml", "docker-compose.yaml", "compose.yml",
                              "compose.yaml")
    k8s = [f for f in view.by_suffix(".yaml", ".yml")
           if (text := view.read(f)) and re.search(r"kind:\s*(Deployment|StatefulSet)", text)]
    if compose or k8s:
        limits = view.grep(r"(?i)^\s*(?:limits|resources|mem_limit|cpus|memory):",
                           compose + k8s, limit=10)
        facts.append(Fact(
            pillar_id=PILLAR, key="resource_limits",
            title="Resource limits declared" if limits else
                  "Containerized with no CPU or memory limits",
            detail=(
                f"Found at {limits[0][0]}:{limits[0][1]}." if limits else
                "Without a memory limit, a leak or an oversized input takes the host down rather "
                "than the container. The blast radius is everything else on the VM."
            ),
            criterion="C4",
            severity=None if limits else Severity.MINOR,
            file_path=(compose + k8s)[0],
            remediation=(
                "Set memory and CPU limits. A container killed by its own limit is a contained "
                "failure; a host out of memory is not."
            ) if not limits else None,
        ))

    # ── C5: single-instance assumptions ──────────────────────────────────────────────────────
    single_instance = sorted({
        h for h in (
            "@lru_cache", "functools.cache", "global ", "SimpleCache", "local_cache",
            "threading.local", "APScheduler", "schedule.every", "BackgroundScheduler",
        )
        if h in haystack
    })
    if single_instance:
        facts.append(Fact(
            pillar_id=PILLAR, key="single_instance_assumptions",
            title=f"State or scheduling that assumes one instance: {', '.join(single_instance)}",
            detail=(
                "In-process caches and in-process schedulers mean a second replica has a "
                "different view of the world and runs the same scheduled job twice. Whether "
                "horizontal scaling is even planned needs an answer from the owner."
            ),
            criterion="C5",
            data={"signals": single_instance},
        ))

    return facts
