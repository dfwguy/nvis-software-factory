# NVIS Software Factory

Two problems, one repository.

**Software quality.** Every SA builds their own tooling, runs it wherever they like, and
increasingly writes it with an AI agent. That gets results, and it also produces duplicated data,
several competing sources of truth, and software that has never been asked whether it survives a
restart. One team lost everything they had when someone restarted the Docker service, because their
state was in memory in a container — not recoverable from logs, not backed up, gone. Vibe coding is
excellent for a prototype and insufficient for something another team depends on.

**Interchange.** AIC, Ethernet, InfiniBand and OVA each model the same racks, nodes, switches and
transceivers differently, so nothing exports cleanly into anything else.

The Software Factory addresses both. Point it at a GitLab or GitHub repository and it clones the
code, gathers deterministic evidence about it, reasons over that evidence with an LLM, and produces
documents an SA can feed straight back into their own agent to fix what it found. Alongside that it
publishes the **NVIS Resource Model** — a small, versioned data contract covering every unit of
resource from a transceiver to a rack, machine-readable, and crosswalked to the systems NVIDIA
already governs.

## AI-first, but the model is never the authority on facts

The LLM is a required stage. The app will not start without one, and there is no degraded mode that
quietly emits a weaker report when the endpoint is down — a run fails and is retried instead.

That makes the separation of duties the important part of the design:

- **Scanners own facts.** Deterministic checks produce findings with `file:line` citations.
- **The model owns judgement and narrative.** It weighs findings in context, spots what the
  scanners cannot see, and writes the remediation plan.
- **The ratchet only turns one way.** The model may escalate a deterministic finding or add its
  own. It may not downgrade, waive, or explain away a finding a scanner produced, and it never
  decides schema conformance — `jsonschema` does.

Without that, a tool built to catch unchecked AI output would itself be unchecked AI output.

Every run records the model id, prompt template version, evidence hash and token usage, so any
assessment can be reproduced and any two can be diffed.

## The contract

The NVIS Resource Model is a **profile with a crosswalk**, not a new source of truth. Nautobot is
already NVIDIA's source of record for asset management, so NRM maps onto it through the
`resource_id` custom field rather than competing with it.

Seven entities, one JSON Schema 2020-12 file each, the whole contract versioned together:
`Resource`, `ResourceType`, `Location`, `Port`, `Link`, `Domain`, `CoolingPath`. Identity is an
opaque UUIDv7 plus an `identifiers[]` array of Redfish-style durable names, which is how a Redfish
walk, an `ibnetdiscover` dump and `nvidia-smi` output reconcile onto the same object. Crosswalks
ship as tested YAML for Nautobot, Redfish, UFM, `bcm-netautogen` and DCGM.

Teams consume it over HTTP — `/api/contracts/bundle` for everything in one fetch,
`/api/contracts/agent-pack.md` as a prompt pack — or through the MCP server.

## Getting started

```bash
git clone https://gitlab-master.nvidia.com/nvis-ova/nvis-software-factory.git
cd nvis-software-factory

cp .env.example .env                      # compose settings
cp factory.toml.example factory.toml      # app configuration
$EDITOR factory.toml                      # set the LLM endpoint; the app will not start without it

docker compose up --build
```

Then open `https://localhost:8443`. The full walk-through, including what to do before you have an
OIDC client registered, is in the docs.

## Documentation

Built with Sphinx and served by the container at `/docs`. Organized by
[Diátaxis](https://diataxis.fr/):

- **Tutorials** — learning by doing. Start with "Assess your first repository".
- **How-to guides** — recipes for a specific goal, for readers already at work.
- **Reference** — austere and factual. The NRM schema reference, the REST API, the pillar catalog
  and the configuration reference are all generated from source, so they cannot drift.
- **Explanation** — the why. Including why Nautobot is the crosswalk target and not a rival model,
  and a write-up of the reboot that lost the data.

Build locally:

```bash
pip install -r docs/requirements.txt
sphinx-build -W -b html docs docs/_build/html
```

## Repository layout

- `backend/` — Flask application. `factory/` is the assessment engine, `contracts/` serves the NRM,
  `store/` is SQLite persistence, `authn/` `authz/` `audit/` are the security surfaces.
- `contracts/` — the deliverable: NRM schemas, crosswalks, fixtures.
- `standards/` — the eight quality pillars. Read by both the LLM prompts and the docs site, so
  there is exactly one definition of the baseline.
- `frontend/` — React 19 SPA.
- `docs/` — Sphinx source.
- `var/` — runtime state, bind-mounted, never committed.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt -r backend/requirements-dev.txt

pytest backend/tests --cov --cov-config=.coveragerc --cov-report=json:coverage.json
python bin/check-coverage-floor.py coverage.json
ruff check backend/ && pylint --recursive=y backend
bash scripts/check_no_secrets_in_git.sh

cd frontend && npm ci && npm run dev
```

To run the whole application locally, on loopback with the mock identity provider:

```bash
cp .env.example .env      # then set NVSF_LLM_API_KEY
./bin/run-local.sh
```

The script probes the reasoning endpoint after startup and prints whether it answers. That is the
point of it: reasoning is only exercised when an assessment runs, so an instance configured with a
dead key serves pages perfectly and fails the first real request — which is how a placeholder key
once survived a day of local development.

The coverage floor starts at 60% per file with an empty exception list. That is only possible in a
greenfield repo, and it is worth protecting: adding to the list requires editing
`bin/check-coverage-floor.py` in a merge request, which makes new debt a visible decision rather
than a drift.

## Contributing

Conventional commits (`feat`, `fix`, `chore`, `docs`, `refactor`, `test`). Reference issues as
`#<number>`. Small, focused merge requests.

If you are an AI agent working in this repository, read [AGENTS.md](AGENTS.md) first — the
authoritative conventions live in `.cursor/rules/*.mdc`.
