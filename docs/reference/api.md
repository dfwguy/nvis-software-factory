---
diataxis: reference
nvsf_generated: backend/api/openapi.py
---

# REST API

:::{admonition} Generated page
:class: generated-page

This page is generated from `backend/api/openapi.py` by `bin/gen-docs-reference.py`. Edits here are lost on the
next build, and CI fails if the two disagree — change the source.
:::

Two surfaces in one API.

**The Factory** takes a GitLab or GitHub URL, clones it safely, gathers deterministic evidence, and puts a required LLM reasoning stage on top to produce an assessment plus agent-ready remediation documents.

**The Contract** publishes the NVIS Resource Model: a versioned data contract for every unit of resource from a transceiver to a rack, with normative crosswalks to Nautobot, Redfish, UFM, BCM rack-import, DCGM and CycloneDX.

This document is GENERATED from the live route table and the authorization registry, so it cannot describe an endpoint that does not exist or a permission that is not enforced.

The same description is served as OpenAPI 3.1 at `/api/openapi.json`, which is the form to hand to a client generator or an agent.

## assessments

Assessment runs. Each produces deterministic findings plus a required LLM reasoning stage, and renders a downloadable Markdown bundle.

| Method | Path | Permission | Summary |
|---|---|---|---|
| `GET` | `/api/assessments` | `assessment:list` | assessments.list_assessments |
| `POST` | `/api/assessments` | `assessment:create` | assessments.create_assessment |
| `GET` | `/api/assessments/{assessment_id}` | `assessment:read` | assessments.get_assessment |
| `GET` | `/api/assessments/{assessment_id}/artifacts` | `assessment:read` | assessments.list_artifacts |
| `GET` | `/api/assessments/{assessment_id}/artifacts/{name}` | `assessment:artifact` | assessments.download_artifact |
| `POST` | `/api/assessments/{assessment_id}/cancel` | `assessment:cancel` | assessments.cancel_assessment |
| `GET` | `/api/assessments/{assessment_id}/provenance` | `assessment:provenance` | assessments.get_provenance |
| `POST` | `/api/assessments/{assessment_id}/retry` | `assessment:retry` | assessments.retry_assessment |

## auth

OIDC sign-in, sign-out, and the current session.

| Method | Path | Permission | Summary |
|---|---|---|---|
| `GET` | `/api/auth/callback` | `_public_` | Complete the flow: verify state, redeem the code, validate the ID token. |
| `GET` | `/api/auth/login` | `_public_` | Begin the OIDC flow, or explain why it cannot begin. |
| `GET` | `/api/auth/logout` | `_public_` | Clear the local session, and say honestly whether the provider session also ended. |
| `POST` | `/api/auth/logout` | `_public_` | Clear the local session, and say honestly whether the provider session also ended. |
| `GET` | `/api/auth/me` | `_public_` | The current principal and what it may do. |

## contracts

The NVIS Resource Model: schemas, crosswalks, and deterministic validation. Start at /api/contracts/index.json, or fetch /api/contracts/bundle to get the whole contract in one request.

| Method | Path | Permission | Summary |
|---|---|---|---|
| `GET` | `/api/contracts` | `contract:read` | The machine-readable index: what exists, at what version, and where to fetch it. |
| `GET` | `/api/contracts/agent-pack.md` | `contract:read` | A prompt pack: the contract as instructions for a coding agent. |
| `GET` | `/api/contracts/bundle` | `contract:read` | The whole contract in one response: index, every schema, every crosswalk. |
| `GET` | `/api/contracts/crosswalk` | `contract:read` | Every crosswalk with its coverage, including which entities it does NOT map. |
| `GET` | `/api/contracts/crosswalk/{system}` | `contract:read` | One crosswalk as JSON. The file is YAML; this is the same data, parsed. |
| `GET` | `/api/contracts/entities` | `contract:read` | Entity names with titles, for a UI that needs to render a list before fetching anything. |
| `GET` | `/api/contracts/fixtures/{name}.json` | `contract:read` | A reference fixture. The worked example a team compares their own export against. |
| `GET` | `/api/contracts/index.json` | `contract:read` | The machine-readable index: what exists, at what version, and where to fetch it. |
| `POST` | `/api/contracts/map` | `contract:map` | Ask the model to propose a crosswalk for a sample export. The schema adjudicates it. |
| `GET` | `/api/contracts/nrm/{version}/{entity}.schema.json` | `contract:read` | One schema file, verbatim. |
| `POST` | `/api/contracts/validate` | `contract:validate` | Decide whether a payload conforms. Deterministic, always. |
| `GET` | `/api/openapi.json` | `contract:read` | The OpenAPI 3.1 description of this API, generated from the live routes. |

## health

Health per dependency. /live is liveness only; / returns 503 when a required dependency is down.

| Method | Path | Permission | Summary |
|---|---|---|---|
| `GET` | `/api/health` | `health:read` | Per-dependency health, with a 503 when a required dependency is unavailable. |
| `GET` | `/api/health/live` | `_public_` | Liveness. Deliberately says nothing about the data, so it cannot fail for a reason that a restart will not fix. |
| `GET` | `/api/health/llm` | `health:read` | Probe the reasoning endpoint. |
| `GET` | `/api/health/standards` | `health:read` | Which quality baseline this deployment is judging against. |

## repositories

Repositories registered for assessment. Registration is separate from assessment because the history of a repository is the interesting part.

| Method | Path | Permission | Summary |
|---|---|---|---|
| `GET` | `/api/repositories` | `repository:list` | repositories.list_repositories |
| `POST` | `/api/repositories` | `repository:add` | repositories.add_repository |
| `GET` | `/api/repositories/{repository_id}` | `repository:read` | repositories.get_repository |

## standards

The quality baseline an assessment judges against: eight pillars, their criteria, and which criteria have a deterministic detector versus being a judgement. Served from the same files the prompts are built from.

| Method | Path | Permission | Summary |
|---|---|---|---|
| `GET` | `/api/standards` | `standards:read` | The whole baseline: every pillar, every criterion. |
| `GET` | `/api/standards/{pillar_id}` | `standards:read` | One pillar including its full Markdown body. |
