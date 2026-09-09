# AGENTS.md — instructions for AI coding agents

**Single source of truth:** this project's rules and conventions live in **`.cursor/rules/*.mdc`**.
Those files are authoritative for *every* agent working in this repo — Cursor, Claude Code, and
Codex alike. This file exists only to point non-Cursor agents at them, so there is one place to
maintain. **Do not duplicate rule content here** — edit the `.mdc` files instead.

> `CLAUDE.md` is a symlink to this file, so Claude Code and Codex read the exact same thing.

## What this repository is

The NVIS Software Factory. Two fronts, one codebase:

1. **The Factory** — clones an SA's repository, gathers deterministic evidence, and puts a
   *required* LLM reasoning stage on top to produce an assessment and agent-ready remediation
   documents.
2. **The Contract** — the NVIS Resource Model (NRM), a versioned data contract for datacenter
   resources, published as JSON Schema and crosswalked to Nautobot, Redfish, UFM and BCM.

There is an irony worth holding onto: this is a tool that judges software quality, written largely
by agents. It has to pass its own gates. If you would flag it in someone else's repo, do not write
it here.

## Read these first (always apply)

- @.cursor/rules/nvis-software-factory.mdc — architecture, key files, the two fronts, SPDX headers
- @.cursor/rules/ai-first-boundaries.mdc — **read before touching anything in `backend/factory/`.**
  Where the LLM has authority and where it must not. The one-way ratchet, fail-closed startup, the
  redaction boundary, provenance capture
- @.cursor/rules/quality-baseline.mdc — the eight pillars in `standards/` are the single definition
  of "good", consumed by both prompts and docs. How to change one without splitting the source

## Read when relevant (task-scoped)

- @.cursor/rules/backend-api.mdc — Flask `/api/*` conventions; new endpoints go in `backend/api/`
- @.cursor/rules/docs-diataxis.mdc — the Diátaxis compass as an authoring test, per page
- @.cursor/rules/contracts-nrm.mdc — editing NRM schemas and crosswalks without breaking consumers
- @.cursor/rules/frontend.mdc — React 19 / Kaizen-first frontend conventions

## Notes

- Each `.mdc` carries YAML frontmatter (`description`, `globs`, `alwaysApply`) — honor it.
- Every new source file carries the NVIDIA SPDX header; scripts additionally carry
  `Author: Rafael M. Koike & Cursor Agent ("Ada")`.
- To change guidance, edit the `.mdc` source of truth — never this pointer or the `CLAUDE.md`
  symlink.
