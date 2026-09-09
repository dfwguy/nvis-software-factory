---
id: scalability
title: Scalability
severity_ceiling: major
order: 4
detectors:
  - backend/factory/scanners/scalability.py
---

# Scalability

**The question:** what breaks first when this is used for real?

Scalability here does not mean web scale. It means the difference between a tool that worked on one
rack during a demo and a tool that works on 72 racks during a bring-up, where the operative limits
are SSH fan-out, head-node NFS, and how many things you can ask a BMC before it stops answering.

## Criteria

### SC1 — Mutable state is not held in process globals

*Detector: yes.*

- **Pass:** shared state lives in the store. Process memory holds caches that can be rebuilt.
- **Fail:** a module-level dict that is the only copy of something. This fails the durability
  pillar too, and it additionally pins the service to exactly one worker forever.

### SC2 — Worker-count assumptions are stated

*Detector: partial.*

Single-worker is a legitimate design. Single-worker by accident is not.

- **Pass:** if the service must run one worker, the constraint is documented and the launch
  configuration enforces it.
- **Fail:** a service that silently corrupts or duplicates work when a second worker starts,
  because nobody wrote down that it could not.

### SC3 — Work scales with the fleet, not per-item

*Detector: partial.*

- **Pass:** batched or fanned-out execution — one `pdsh` across a node list, one bulk query.
- **Fail:** a loop that opens an SSH connection per node. At 72 racks that is thousands of
  handshakes, and the failure mode is a timeout somewhere unrelated.

### SC4 — Fan-out is bounded

*Detector: yes.*

- **Pass:** a concurrency limit on parallel execution, sized deliberately.
- **Fail:** unbounded thread or process creation from a list whose length comes from the fleet.
  1,000 concurrent SSH sessions is how you take down a head node.

### SC5 — Result sets are paginated or streamed

*Detector: partial.*

- **Pass:** bounded responses, streaming for large payloads.
- **Fail:** an endpoint that loads every historical record into memory and serializes it. This is
  fine for weeks and then is not.

### SC6 — Expensive work is cached with an explicit invalidation story

*Detector: no — judgement.*

- **Pass:** a stated TTL or invalidation trigger, and a documented staleness bound.
- **Fail:** either no caching where it is plainly needed, or a cache with no invalidation, which
  turns into stale data reported as current — which is a correctness bug, not a performance one.

## What this pillar deliberately does not ask

Nothing about horizontal scaling, clustering, or load balancing. Most NVIS tooling is a single
instance serving a handful of engineers, and adding a message broker to a tool used by six people
is a cost with no benefit. The criteria above are about not falling over at fleet size, which is a
different and much more common problem.

## Remediation patterns

**Per-node SSH in a loop.** Replace with a single fan-out execution against a node list. Where the
tool genuinely needs per-node interaction, use a bounded pool and make the bound configurable.

**Unbounded `ThreadPoolExecutor`.** Give it `max_workers` from configuration with a sane default.
Sizing is a real decision: for SSH to a head node, single digits; for HTTP to BMCs, tens.

**Global dict cache with no invalidation.** Add a timestamp and a TTL, and expose the age in the
API response so a consumer can tell how stale the answer is. Surfacing staleness is usually more
valuable than eliminating it.
