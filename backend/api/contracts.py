# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Serve the NVIS Resource Model: /api/contracts

Author: Rafael M. Koike & Cursor Agent ("Ada")

The delivery surface for the contract front. Two audiences, and they want different shapes.

A **human** browsing the Contract Explorer wants one entity at a time with its reasoning attached.
A **coding agent** wants everything in one fetch, because an agent that has to make eleven requests
to learn the contract will make three and then start guessing -- and a guessed schema is worse than
no schema, since the team that receives its output believes it conforms. That is what
``/bundle`` and ``/agent-pack.md`` are for.

Everything served here is a file on disk under ``contracts/``. Nothing is assembled from Python
literals, so what a team validates against and what we publish cannot drift.
"""

from __future__ import annotations

import json
import logging

from authz import action
from flask import Blueprint, Response, request
from paths import CONTRACTS_DIR

from contracts import crosswalk as crosswalk_module
from contracts import loader, validate

from ._common import body, fail, ok

bp = Blueprint("contracts", __name__)

_logger = logging.getLogger("nvsf.api.contracts")

#: The contract is immutable per version and ships in the image, so it is safe to cache hard.
#: An agent fetching the bundle on every run should not re-download it, and a browser rendering
#: the explorer should not re-fetch a schema per navigation.
_IMMUTABLE = "public, max-age=3600, immutable"

#: Cap on a submitted payload. A bundle for a full data hall is legitimately large, but this runs
#: in a request thread and jsonschema walks the whole document -- an unbounded body is a way to
#: occupy every worker. Reliability criterion R4 applied to ourselves.
MAX_VALIDATE_BYTES = 16 * 1024 * 1024

#: Truncation point for a sample export sent to the mapping assistant. A representative record is
#: what the model needs; a whole export just spends context on repetition of the same shape.
MAX_SAMPLE_CHARS = 20_000


def _json_file(payload: object, *, download: str | None = None) -> Response:
    """A JSON response that is a document rather than an API envelope.

    Deliberately NOT wrapped in ``ok(...)``. These endpoints serve the schema itself, and an agent
    or a ``$ref`` resolver that fetches ``resource.schema.json`` must receive the schema, not the
    schema nested under a key it has to know about.
    """
    response = Response(
        json.dumps(payload, indent=2) + "\n",
        mimetype="application/schema+json" if download else "application/json",
    )
    response.headers["Cache-Control"] = _IMMUTABLE
    if download:
        response.headers["Content-Disposition"] = f'inline; filename="{download}"'
    return response


def _version() -> str | None:
    """Requested contract version, or None for the default.

    Not defaulted to "latest" anywhere. A caller that silently follows latest takes a breaking
    change on our release schedule instead of its own, which is the thing versioning exists to
    prevent.
    """
    requested = request.args.get("version")
    return requested or None


# ── Discovery ────────────────────────────────────────────────────────────────────────────────


@bp.route("/index.json", methods=["GET"])
@bp.route("/", methods=["GET"])
@action("contract:read")
def contract_index():
    """The machine-readable index: what exists, at what version, and where to fetch it.

    This is the one URL worth remembering. Everything else is discoverable from it.
    """
    try:
        published = loader.index(_version())
    except loader.ContractError as error:
        return fail(str(error), status=404, reason="unknown-version")

    published["links"] = {
        "bundle": "/api/contracts/bundle",
        "agent_pack": "/api/contracts/agent-pack.md",
        "crosswalks": "/api/contracts/crosswalk",
        "validate": "/api/contracts/validate",
        "openapi": "/api/openapi.json",
        "schema_base": f"/api/contracts/nrm/{published['nrm_version']}/",
    }
    return _json_file(published)


@bp.route("/nrm/<version>/<entity>.schema.json", methods=["GET"])
@action("contract:read")
def entity_schema(version: str, entity: str):
    """One schema file, verbatim.

    The path mirrors the repository layout so a ``$ref`` in a schema resolves against this server
    the same way it resolves on disk. That is what lets a team point a standard JSON Schema tool
    at us rather than writing a fetcher.
    """
    try:
        path = loader.schema_path(entity, version)
    except loader.UnknownVersion as error:
        return fail(str(error), status=404, reason="unknown-version")
    except loader.UnknownEntity as error:
        return fail(str(error), status=404, reason="unknown-entity")

    return _json_file(
        json.loads(path.read_text(encoding="utf-8")), download=f"{entity}.schema.json",
    )


@bp.route("/entities", methods=["GET"])
@action("contract:read")
def list_entities():
    """Entity names with titles, for a UI that needs to render a list before fetching anything."""
    try:
        published = loader.index(_version())
    except loader.ContractError as error:
        return fail(str(error), status=404, reason="unknown-version")
    return ok(
        nrm_version=published["nrm_version"],
        entities=[
            {"name": e["name"], "title": e["title"], "required": e["required"]}
            for e in published["entities"]
        ],
    )


# ── Crosswalks ───────────────────────────────────────────────────────────────────────────────


@bp.route("/crosswalk", methods=["GET"])
@action("contract:read")
def list_crosswalks():
    """Every crosswalk with its coverage, including which entities it does NOT map.

    The gaps are the useful part. A team deciding whether to integrate needs to know what a
    mapping cannot carry before they build on it, not after.
    """
    try:
        report = crosswalk_module.coverage(_version())
    except loader.ContractError as error:
        return fail(str(error), status=404, reason="unknown-version")
    # Defined in the payload, not only in the documentation. This endpoint and the agent pack are
    # where a new integrator or an agent meets the word "crosswalk" for the first time, and it is
    # a term of art -- readers reasonably assume it means the model itself, which is the one
    # confusion that makes the coverage numbers below unreadable.
    return ok(
        what_a_crosswalk_is=(
            "A translation table between NRM and one external system: which NRM field "
            "corresponds to which of that system's fields, which direction a value may travel, "
            "what the system cannot carry, and which side is authoritative when they disagree. "
            "NRM itself -- the seven-entity model these map onto -- is at /api/contracts/"
            "index.json."
        ),
        **report,
    )


@bp.route("/crosswalk/<system>", methods=["GET"])
@action("contract:read")
def get_crosswalk(system: str):
    """One crosswalk as JSON. The file is YAML; this is the same data, parsed."""
    try:
        document = crosswalk_module.load(system)
    except crosswalk_module.CrosswalkError as error:
        return fail(str(error), status=404, reason="unknown-crosswalk")
    return _json_file(document)


# ── Single-fetch delivery for agents ─────────────────────────────────────────────────────────


@bp.route("/bundle", methods=["GET"])
@action("contract:read")
def contract_bundle():
    """The whole contract in one response: index, every schema, every crosswalk.

    Exists because of how agents actually behave. Told to "conform to the NRM contract" with a
    base URL, an agent will fetch two or three things and infer the rest -- and inferred schema is
    indistinguishable from real schema to whoever consumes the output. One fetch removes the
    incentive.

    Compressed in transit by flask-compress, which matters here: this is a few hundred kilobytes
    of highly repetitive JSON and it is fetched over a tunnel.
    """
    version = _version()
    try:
        published = loader.index(version)
    except loader.ContractError as error:
        return fail(str(error), status=404, reason="unknown-version")

    resolved = published["nrm_version"]
    schemas = {}
    for name in (*loader.entity_names(resolved), *loader.SUPPORTING):
        try:
            schemas[f"{name}.schema.json"] = loader.load_schema(name, resolved)
        except loader.UnknownEntity:
            continue

    crosswalks = {}
    for system in crosswalk_module.systems():
        try:
            crosswalks[system] = crosswalk_module.load(system)
        except crosswalk_module.CrosswalkError:
            continue

    return _json_file({
        "nrm_version": resolved,
        "index": published,
        "schemas": schemas,
        "crosswalks": crosswalks,
        "coverage": crosswalk_module.coverage(resolved),
        "notes": {
            "adjudication": (
                "POST a payload to /api/contracts/validate. jsonschema decides conformance, never "
                "a language model -- a probabilistic answer to a decidable question is strictly "
                "worse than a deterministic one."
            ),
            "link_keys": (
                "Link.key is derived from its endpoints, not minted. Generate it the way "
                "contracts/identity.py does: normalize each side to <resource>_<port>, sort the "
                "two terms lexically, join with ':'. A hand-written key breaks the "
                "expected-versus-observed diff and is rejected on validation."
            ),
            "identity": (
                "Primary keys are minted UUIDv7 and opaque. Real-world identity goes in "
                "identifiers[], and reconciliation matches on any member."
            ),
        },
    })


@bp.route("/agent-pack.md", methods=["GET"])
@action("contract:read")
def agent_pack():
    """A prompt pack: the contract as instructions for a coding agent.

    Distinct from ``/bundle``, which is the data. This is the framing an agent needs around the
    data -- what to do, what not to do, and which mistakes are common. Reasoning belongs in the
    prompt; raw schema alone reliably produces a plausible integration with the plan-versus-reality
    diff quietly broken.

    Assembled from the same schema files everything else serves, so it cannot describe a contract
    we are not publishing.
    """
    version = _version()
    try:
        published = loader.index(version)
    except loader.ContractError as error:
        return fail(str(error), status=404, reason="unknown-version")

    resolved = published["nrm_version"]
    lines: list[str] = [
        f"# NVIS Resource Model {resolved} — agent pack",
        "",
        (
            "You are integrating a tool with the NVIS Resource Model (NRM), the data contract for "
            "physical and logical inventory in an NVIDIA AI factory. Read all of this before "
            "writing code."
        ),
        "",
        "## Fetch the machine-readable contract first",
        "",
        "```",
        "GET /api/contracts/bundle      # index + every schema + every crosswalk, one response",
        f"GET /api/contracts/nrm/{resolved}/<entity>.schema.json",
        "POST /api/contracts/validate   # the only thing that decides conformance",
        "```",
        "",
        (
            "Do not infer a field from an example. Every schema carries its reasoning in its "
            "`description`; if a field's purpose is unclear, the description says it."
        ),
        "",
        "## The entities",
        "",
    ]

    for entry in published["entities"]:
        schema = loader.load_schema(entry["name"], resolved)
        summary = (entry["description"] or "").strip().split("\n\n")[0]
        lines += [
            f"### `{entry['title']}` — `{entry['name']}.schema.json`",
            "",
            summary,
            "",
            f"Required: {', '.join(f'`{r}`' for r in schema.get('required', [])) or 'none'}",
            "",
        ]

    lines += [
        "## Five rules that are not obvious from the schemas",
        "",
        (
            "1. **Primary keys are opaque.** Mint a UUIDv7 and never derive it from a serial, a "
            "hostname or a GUID. Hardware gets renamed, re-serialized and replaced under "
            "warranty; a derived key changes when it should not."
        ),
        "",
        (
            "2. **Real-world identity goes in `identifiers[]`, verbatim.** Do not normalize case, "
            "strip the `GPU-` prefix, or reformat separators. The value's only job is to match a "
            "source system exactly, and every normalization is a chance to stop matching."
        ),
        "",
        (
            "3. **`Link.key` is derived, not minted.** Normalize each endpoint to "
            "`<resource>_<port>`, sort the two terms lexically, join with `:`. The sort is the "
            "important part: a cabling file lists a link switch-first and a discovery sweep "
            "reports it node-first, and without sorting every link reads as both a missing cable "
            "and an unexpected one. Validation rejects a key that disagrees with its endpoints."
        ),
        "",
        (
            "4. **Set `observation` on everything.** `expected` for anything from a plan, a "
            "cabling file or an order; `observed` for anything measured or discovered. The "
            "difference between the two IS the validation report. Defaulting everything to "
            "`observed` makes a planning import look like a completed deployment."
        ),
        "",
        (
            "5. **Type facts belong on `ResourceType`, instance facts on `Resource`.** Rack "
            "units, TDP and coolant requirements are properties of a SKU. Copying them onto every "
            "unit guarantees the copies disagree, and a corrected power figure then needs an "
            "UPDATE across thousands of rows instead of one."
        ),
        "",
        "## What NRM is not",
        "",
        (
            "- **Not a source of truth for assets.** Nautobot is, per the InfoSec Asset "
            "Management Standard. NRM is a profile with a crosswalk; where they disagree, "
            "Nautobot is right."
        ),
        (
            "- **Not a monitoring system.** No telemetry, no time series, no health fields. A "
            "throttling GPU is a DCGM fact. Writing telemetry into `lifecycle` makes the "
            "inventory flap with load."
        ),
        "",
        "## Crosswalks",
        "",
        "If your tool already speaks one of these, map through it rather than inventing a mapping:",
        "",
    ]

    report = crosswalk_module.coverage(resolved)
    for system, info in report["systems"].items():
        mapped = ", ".join(sorted(info["entities"])) or "none"
        lines.append(
            f"- **`{system}`** ({info['role']}) — maps {mapped}. "
            f"Fetch: `/api/contracts/crosswalk/{system}`"
        )

    lines += [
        "",
        (
            "Each crosswalk declares `unmapped_nrm`: the fields that system cannot carry, with a "
            "reason. Read that section before you rely on a mapping."
        ),
        "",
        "## Before you claim conformance",
        "",
        (
            "POST your output to `/api/contracts/validate`. It checks the schema, then three "
            "invariants JSON Schema cannot express: every reference resolves inside the bundle, "
            "containment has no cycles, and link classes and keys agree with their endpoints. A "
            "payload that passes the schema and fails these is the normal outcome of a first "
            "attempt."
        ),
        "",
        (
            "Reference example: a complete GB200 NVL72 rack is at "
            "`/api/contracts/fixtures/nvl72-rack.json` — 18 compute trays, 72 GPUs, layered "
            "NVLinks over cable cartridges, and a cooling path. Validate your output against the "
            "same endpoint that one passes."
        ),
        "",
    ]

    response = Response("\n".join(lines), mimetype="text/markdown; charset=utf-8")
    response.headers["Cache-Control"] = _IMMUTABLE
    return response


@bp.route("/fixtures/<name>.json", methods=["GET"])
@action("contract:read")
def get_fixture(name: str):
    """A reference fixture. The worked example a team compares their own export against."""
    directory = CONTRACTS_DIR / "fixtures"
    available = sorted(path.stem for path in directory.glob("*.json"))
    if name not in available:
        return fail(
            f"no fixture {name!r} (have: {', '.join(available) or 'none'})",
            status=404,
            reason="unknown-fixture",
        )

    return _json_file(
        json.loads((directory / f"{name}.json").read_text(encoding="utf-8")),
        download=f"{name}.json",
    )


# ── Adjudication ─────────────────────────────────────────────────────────────────────────────


@bp.route("/validate", methods=["POST"])
@action("contract:validate")
def validate_payload():
    """Decide whether a payload conforms. Deterministic, always.

    This endpoint is the reason the contract is worth anything: a team can find out they are wrong
    before another team depends on their output. There is no model in this path, and there will not
    be one -- conformance is decidable, and a probabilistic answer to a decidable question is
    strictly worse than a deterministic one.
    """
    length = request.content_length or 0
    if length > MAX_VALIDATE_BYTES:
        return fail(
            f"payload is {length} bytes; the limit is {MAX_VALIDATE_BYTES}. Split it by rack or "
            f"by entity -- validation walks the whole document in a request thread.",
            status=413,
            reason="payload-too-large",
        )

    payload = request.get_json(silent=True)
    if payload is None:
        return fail(
            "the body must be JSON: either an NRM bundle, or an object with `entity` and `record`",
            status=400,
            reason="not-json",
        )

    version = _version()

    # A single record, for a team integrating incrementally who has one Resource rather than a
    # bundle. Reference checks are impossible in this mode and the result says so.
    if isinstance(payload, dict) and "entity" in payload and "record" in payload:
        result = validate.validate_record(
            str(payload["entity"]), payload["record"], version,
        )
        return ok(
            **result.to_json(),
            mode="record",
            note=(
                "A single record cannot be checked for dangling references or containment cycles, "
                "because there is nothing to resolve against. Submit a bundle for those."
            ),
        )

    result = validate.validate_bundle(payload, version)
    return ok(**result.to_json(), mode="bundle")


@bp.route("/map", methods=["POST"])
@action("contract:map")
def propose_mapping():
    """Ask the model to propose a crosswalk for a sample export. The schema adjudicates it.

    The AI-first principle applied to the contract front, and the division of labour is the exact
    inverse of the factory's. In ``factory/``, the model reasons and deterministic scanners
    constrain it. Here the model only ever GUESSES which of the team's fields means which NRM
    field -- a genuinely hard matching problem that a model is good at and a rule set is not -- and
    then the proposal is run through ``validate`` before anyone sees it.

    So the response carries both the proposal and the verdict on it. A mapping the model was
    confident about and that produced an invalid record is reported as invalid, with the problems
    attached. The model proposes; the schema decides.
    """
    data = body()
    sample = data.get("sample")
    if not sample:
        return fail(
            "provide `sample`: one representative record from your tool's export",
            status=400,
            reason="missing-sample",
        )

    entity = str(data.get("entity") or "resource")
    if entity not in loader.entity_names():
        return fail(
            f"unknown entity {entity!r} (have: {', '.join(loader.entity_names())})",
            status=422,
            reason="unknown-entity",
        )

    from factory import llm, prompts

    version = loader.DEFAULT_VERSION
    published = loader.index(version)

    # Only the requested entity's schema plus the shared definitions, not the whole contract. The
    # model reasons better about one target than about seven, and the excerpt is what keeps this
    # request inside a sane token budget.
    excerpts = {
        f"{entity}.schema.json": loader.load_schema(entity, version),
        "common.schema.json": loader.load_schema("common", version),
    }

    try:
        template = prompts.get("contract_mapping")
        system_prompt, user_prompt = template.render(
            tool_name=str(data.get("system") or "an unnamed tool"),
            description=str(data.get("description") or "not stated by the submitter"),
            entities="\n".join(
                f"- {e['name']}: {e['title']}" for e in published["entities"]
            ),
            schema_excerpts=json.dumps(excerpts, indent=2),
            sample=json.dumps(sample, indent=2)[:MAX_SAMPLE_CHARS],
        )
        proposal, completion = llm.complete_json(
            system_prompt,
            user_prompt,
            prompt_version=template.version,
            pass_name="contract_mapping",
        )
    except prompts.PromptError as error:
        return fail(str(error), status=500, reason="prompt-error")
    except llm.LlmUnavailable as error:
        # Fail closed, as everywhere else. A mapping assistant that degrades to a keyword match
        # would produce a plausible-looking crosswalk with no reasoning behind it, and the user
        # has no way to tell the difference.
        return fail(
            f"the reasoning model is unavailable, so no mapping can be proposed: {error}",
            status=503,
            reason="llm-unavailable",
        )
    except llm.LlmBadResponse as error:
        return fail(
            f"the model did not return a usable mapping: {error}",
            status=502,
            reason="llm-bad-response",
        )

    # Adjudicate. The model's stated confidence has no bearing on whether the record is valid, and
    # the two disagreeing is the most useful thing this endpoint can report: a "high confidence"
    # proposal that fails validation is exactly the output a reviewer needs to see flagged.
    target = str(proposal.get("target_entity") or entity)
    if target not in loader.entity_names(version):
        target = entity

    candidate = proposal.get("sample_output")
    if isinstance(candidate, str):
        # The prompt asks for an object, but a model asked for "one record as a JSON object"
        # sometimes returns it as a string. Recovering here is cheaper than a correction round trip.
        try:
            candidate = json.loads(candidate)
        except ValueError:
            candidate = None

    verdict = (
        validate.validate_record(target, candidate, version).to_json()
        if isinstance(candidate, dict)
        else {
            "valid": False,
            "problem_count": 1,
            "problems": [{
                "pointer": "",
                "rule": "proposal.missing_record",
                "message": (
                    "the model did not produce a worked example record, so its mapping could not "
                    "be adjudicated. The mapping below is unverified."
                ),
            }],
        }
    )

    _logger.info(
        "contract-mapping: proposed %s for %r, model confidence=%s, adjudicated valid=%s",
        target, str(data.get("system") or "unknown"),
        proposal.get("confidence"), verdict.get("valid"),
    )

    return ok(
        entity=target,
        nrm_version=version,
        field_map=proposal.get("field_map") or [],
        identifiers=proposal.get("identifiers") or [],
        record=candidate,
        unmapped_source_fields=proposal.get("unmapped_source_fields") or [],
        unfilled_required_fields=proposal.get("unfilled_required_fields") or [],
        model_confidence=proposal.get("confidence"),
        model_confidence_reason=proposal.get("confidence_reason"),
        adjudication=verdict,
        provenance={
            "model": completion.model,
            "prompt_version": completion.prompt_version,
            "temperature": completion.temperature,
        },
        note=(
            "The model proposed this mapping; jsonschema decided whether the resulting record is "
            "valid. `model_confidence` is the model's own opinion and carries no weight -- read "
            "`adjudication`. Treat the mapping as a starting point for review, and if a crosswalk "
            "already exists for this system, that one is reviewed and this one is not."
        ),
    )
