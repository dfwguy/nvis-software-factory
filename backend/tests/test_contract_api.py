# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Tests for the contract delivery surface: /api/contracts and /api/openapi.json

Author: Rafael M. Koike & Cursor Agent ("Ada")

The contract is only useful if a team can actually fetch and use it, so what is tested here is the
delivery promises rather than the HTTP plumbing: that a schema arrives as a schema rather than
wrapped in an envelope, that one fetch really does get the whole contract, that validation is
deterministic with no model in the path, and that the OpenAPI document cannot describe a permission
it does not enforce.
"""

from __future__ import annotations

import copy
import json

import paths
import pytest


@pytest.fixture(scope="module")
def nvl72() -> dict:
    return json.loads(
        (paths.CONTRACTS_DIR / "fixtures" / "nvl72-rack.json").read_text(encoding="utf-8")
    )


# ── Discovery ────────────────────────────────────────────────────────────────────────────────


def test_the_index_names_everything_needed_to_go_further(app_client):
    """One URL worth remembering, and everything else discoverable from it."""
    response = app_client.get("/api/contracts/index.json")
    assert response.status_code == 200

    published = response.get_json()
    assert published["nrm_version"] == "v0.1"
    assert len(published["entities"]) == 7
    for key in ("bundle", "agent_pack", "crosswalks", "validate", "openapi", "schema_base"):
        assert published["links"][key], f"the index does not point to {key}"


def test_a_schema_arrives_as_a_schema_not_as_an_envelope(app_client):
    """A `$ref` resolver fetching this must get the schema, not the schema under a key.

    Wrapping it in the API's `{ok: true, ...}` envelope would make every standard JSON Schema tool
    fail here, and the team hitting that would write a custom fetcher instead -- which is the
    outcome publishing a schema is meant to avoid.
    """
    response = app_client.get("/api/contracts/nrm/v0.1/resource.schema.json")
    assert response.status_code == 200

    document = response.get_json()
    assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert document["title"] == "Resource"
    assert "ok" not in document


def test_a_schema_is_cached_hard_because_a_version_is_immutable(app_client):
    response = app_client.get("/api/contracts/nrm/v0.1/resource.schema.json")
    assert "immutable" in response.headers["Cache-Control"]


def test_an_unknown_entity_is_a_404_that_says_what_exists(app_client):
    response = app_client.get("/api/contracts/nrm/v0.1/nonsense.schema.json")
    assert response.status_code == 404
    body = response.get_json()
    assert body["reason"] == "unknown-entity"
    assert "resource" in body["error"], "the error should list what is available"


def test_an_unpublished_version_is_refused(app_client):
    response = app_client.get("/api/contracts/nrm/v9.9/resource.schema.json")
    assert response.status_code == 404
    assert response.get_json()["reason"] == "unknown-version"


def test_a_traversal_attempt_never_returns_a_file(app_client):
    """`entity`, `version` and `system` come from the URL, which makes these traversal surfaces.

    The assertion is that no file comes back, not that the status is 404. Two layers refuse these
    and they answer differently: a decoded `../` no longer matches the schema route at all, so it
    falls through to the SPA catch-all and default-deny returns 403. Pinning an exact status would
    make this test fail if routing changed while the endpoint stayed just as safe.
    """
    for url in (
        "/api/contracts/nrm/v0.1/..%2f..%2f..%2fetc%2fpasswd.schema.json",
        "/api/contracts/nrm/v0.1/../../../etc/passwd.schema.json",
        "/api/contracts/crosswalk/..%2f..%2ffactory.toml",
        "/api/contracts/crosswalk/../../factory.toml",
        "/api/contracts/fixtures/..%2f..%2fetc%2fpasswd.json",
    ):
        response = app_client.get(url)
        assert response.status_code != 200, f"{url} returned something"
        assert b"root:" not in response.data
        assert b"NVSF_" not in response.data, "a config file leaked"


# ── Crosswalks ───────────────────────────────────────────────────────────────────────────────


def test_the_crosswalk_list_shows_gaps_not_just_coverage(app_client):
    """What a team needs before integrating is what a mapping CANNOT carry."""
    response = app_client.get("/api/contracts/crosswalk")
    assert response.status_code == 200

    body = response.get_json()
    assert body["systems"]["nautobot"]["role"] == "source_of_record"
    assert "link" in body["systems"]["dcgm"]["missing_entities"]


def test_a_crosswalk_is_served_as_parsed_data(app_client):
    """YAML on disk, JSON on the wire. A consumer should not need a YAML parser to read it."""
    response = app_client.get("/api/contracts/crosswalk/nautobot")
    assert response.status_code == 200

    document = response.get_json()
    assert document["system"] == "nautobot"
    assert document["join"]["system_field"] == "custom_fields.resource_id"
    assert any(m["nrm_entity"] == "cooling-path" for m in document["entities"])


# ── Single-fetch delivery ────────────────────────────────────────────────────────────────────


def test_one_fetch_gets_the_whole_contract(app_client):
    """The endpoint that exists because of how agents behave.

    An agent told to conform, given a base URL, fetches two or three things and infers the rest --
    and inferred schema is indistinguishable from real schema to whoever consumes the output. One
    fetch removes the incentive, so it has to genuinely contain everything.
    """
    response = app_client.get("/api/contracts/bundle")
    assert response.status_code == 200

    bundle = response.get_json()
    from contracts import crosswalk, loader

    for entity in loader.entity_names():
        assert f"{entity}.schema.json" in bundle["schemas"], f"{entity} missing from the bundle"
    assert "common.schema.json" in bundle["schemas"], "shared $defs are needed to resolve refs"
    assert "bundle.schema.json" in bundle["schemas"]
    assert set(bundle["crosswalks"]) == set(crosswalk.systems())

    # And it states the two rules an agent gets wrong without being told.
    assert "jsonschema decides" in bundle["notes"]["adjudication"]
    assert "sort" in bundle["notes"]["link_keys"]


def test_the_bundle_is_self_sufficient_for_validation(app_client):
    """Every `$ref` in the bundled schemas resolves within the bundle.

    If it does not, a consumer that fetched only this still has to make more requests -- which
    defeats the endpoint's purpose in exactly the way that is hard to notice.
    """
    bundle = app_client.get("/api/contracts/bundle").get_json()
    available = set(bundle["schemas"])

    def refs(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref" and isinstance(value, str):
                    yield value
                else:
                    yield from refs(value)
        elif isinstance(node, list):
            for item in node:
                yield from refs(item)

    for filename, schema in bundle["schemas"].items():
        for reference in refs(schema):
            target = reference.split("#", maxsplit=1)[0]
            if not target or target.startswith("https://json-schema.org"):
                continue
            resolved = target.rsplit("/", maxsplit=1)[-1]
            assert resolved in available, f"{filename} refs {reference}, absent from the bundle"


def test_the_agent_pack_carries_the_reasoning_not_just_the_fields(app_client):
    """Raw schema alone reliably produces a plausible integration with the diff quietly broken.

    So the pack has to state the non-obvious rules. These assertions are on the rules being
    present, because each one corresponds to a specific mistake seen in practice.
    """
    response = app_client.get("/api/contracts/agent-pack.md")
    assert response.status_code == 200
    assert response.mimetype == "text/markdown"

    text = response.get_data(as_text=True)
    assert "opaque" in text, "must say primary keys are not derived"
    assert "verbatim" in text, "must say identifier values are not normalized"
    assert "sort" in text, "must explain the link-key sort"
    assert "expected" in text and "observed" in text
    assert "Nautobot is" in text, "must say NRM is not the asset source of truth"
    assert "/api/contracts/validate" in text, "must point at the adjudicator"

    # Built from the schemas, so every entity appears.
    from contracts import loader
    for entity in loader.entity_names():
        assert entity in text


def test_the_reference_fixture_is_fetchable(app_client):
    """The worked example a team compares their own export against."""
    response = app_client.get("/api/contracts/fixtures/nvl72-rack.json")
    assert response.status_code == 200

    document = response.get_json()
    assert document["nrm_version"] == "v0.1"
    assert len(document["resources"]) > 200


# ── Adjudication ─────────────────────────────────────────────────────────────────────────────


def test_the_reference_rack_validates_through_the_endpoint(app_client, nvl72):
    """The fixture and the endpoint must agree, or one of them is lying to somebody."""
    response = app_client.post("/api/contracts/validate", json=nvl72)
    assert response.status_code == 200

    body = response.get_json()
    assert body["valid"] is True
    assert body["mode"] == "bundle"
    assert body["counts"]["resources"] > 200


def test_validation_reports_a_pointer_to_the_offending_field(app_client, nvl72):
    """A pointer is what lets a UI highlight the line and an agent patch the right field.

    "Invalid resource" sends someone scrolling through a 40,000-line export.
    """
    broken = copy.deepcopy(nvl72)
    broken["ports"][0]["resource_id"] = "018f4b1a-dead-7000-8000-000000000000"

    body = app_client.post("/api/contracts/validate", json=broken).get_json()
    assert body["valid"] is False
    problem = next(p for p in body["problems"] if p["rule"] == "reference.ports.resource_id")
    assert problem["pointer"] == "/ports/0/resource_id"


def test_a_single_record_can_be_checked_and_says_what_it_could_not_check(app_client):
    """A team integrating incrementally has one Resource, not a bundle.

    The response has to be honest that reference and cycle checks did not run, or the team reads a
    partial pass as a full one.
    """
    body = app_client.post("/api/contracts/validate", json={
        "entity": "location",
        "record": {"id": "018f4b1a-0000-7000-8000-000000000001", "site": "NSCALE-PT1"},
    }).get_json()

    assert body["valid"] is True
    assert body["mode"] == "record"
    assert "cannot be checked" in body["note"]


def test_a_non_json_body_is_refused_with_a_usable_message(app_client):
    response = app_client.post(
        "/api/contracts/validate", data="not json", content_type="application/json",
    )
    assert response.status_code == 400
    assert response.get_json()["reason"] == "not-json"


def test_an_oversized_payload_is_refused_before_it_is_parsed(app_client, monkeypatch, nvl72):
    """Validation walks the whole document in a request thread, so the body has to be bounded.

    The limit is lowered rather than a 16 MB body being sent: the point under test is that the
    guard trips on `Content-Length` before the body is parsed, and sending a genuinely oversized
    body to prove it would spend the memory the limit exists to protect. A faked header does not
    work either, because the test client recomputes it from the actual body.
    """
    from api import contracts

    monkeypatch.setattr(contracts, "MAX_VALIDATE_BYTES", 128)

    response = app_client.post("/api/contracts/validate", json=nvl72)
    assert response.status_code == 413

    body = response.get_json()
    assert body["reason"] == "payload-too-large"
    assert "Split it" in body["error"], "the error should say what to do about it"


def test_there_is_no_model_in_the_validation_path(app_client, nvl72, monkeypatch):
    """Conformance is decidable, so nothing here may consult the LLM.

    Enforced behaviourally rather than by reading the source: any call into the model client
    raises, and validation still returns a verdict. If someone later adds a "when unsure, ask the
    model" branch, this fails.
    """
    from factory import llm

    def refuse(*args, **kwargs):
        raise AssertionError("validation consulted the language model")

    monkeypatch.setattr(llm, "complete", refuse)
    monkeypatch.setattr(llm, "complete_json", refuse)

    body = app_client.post("/api/contracts/validate", json=nvl72).get_json()
    assert body["valid"] is True


def test_the_mapping_assistant_fails_closed_when_the_model_is_down(app_client):
    """No degraded mode here either.

    A mapping assistant that fell back to keyword matching would emit a plausible crosswalk with
    no reasoning behind it, and the user has no way to tell that apart from a real one. The test
    environment points at a closed port, so this is the real failure path.
    """
    response = app_client.post("/api/contracts/map", json={
        "system": "some-tool",
        "sample": {"hostname": "gpu-001", "serial": "ABC123"},
    })
    assert response.status_code == 503
    assert response.get_json()["reason"] == "llm-unavailable"


def test_the_mapping_assistant_needs_a_sample(app_client):
    response = app_client.post("/api/contracts/map", json={"system": "some-tool"})
    assert response.status_code == 400
    assert response.get_json()["reason"] == "missing-sample"


def test_the_mapping_prompt_matches_the_schema_it_maps_to():
    """The prompt and the contract are two places describing one thing, so they can drift.

    They already did once: the template named `durable_name_format` after the schema settled on
    `format`. A model given the stale name emits records that fail validation for a reason the
    user cannot act on, so this checks the identifier vocabulary still agrees.
    """
    from factory import prompts

    from contracts import loader

    template = prompts.get("contract_mapping")
    text = f"{template.system}\n{template.user}"

    common = loader.load_schema("common")
    formats = {
        entry["const"]
        for entry in common["$defs"]["identifier_format"]["oneOf"]
    }
    for name in formats:
        assert name in text, f"the prompt does not mention identifier format {name}"

    identifier_fields = set(common["$defs"]["identifier"]["properties"])
    assert identifier_fields == {"format", "value", "scope", "source"}, (
        "the identifier shape changed; the mapping prompt has to be updated with it"
    )
    assert "durable_name_format" not in text, "stale field name from before the schema settled"


# ── OpenAPI ──────────────────────────────────────────────────────────────────────────────────


def test_the_openapi_document_is_generated_from_the_live_routes(app_client):
    """Not hand-written, so it cannot describe an endpoint that does not exist."""
    response = app_client.get("/api/openapi.json")
    assert response.status_code == 200

    document = response.get_json()
    assert document["openapi"] == "3.1.0"

    described = set(document["paths"])
    from app import app as flask_app

    live = {
        str(rule.rule).rstrip("/") or "/"
        for rule in flask_app.url_map.iter_rules()
        if str(rule.rule).startswith("/api/") and "<" not in str(rule.rule)
    }
    missing = live - described
    assert not missing, f"live endpoints absent from the description: {sorted(missing)}"


def test_every_described_operation_states_the_permission_it_enforces(app_client):
    """The document and the enforcement read the same attribute, so they cannot disagree.

    An OpenAPI file that documents a permission the server does not enforce is worse than one that
    documents none: a reviewer checks the document and concludes the endpoint is protected.
    """
    from audit import request_hook
    from authz import resources

    document = app_client.get("/api/openapi.json").get_json()

    for path, entry in document["paths"].items():
        for method, operation in entry.items():
            if method == "parameters":
                continue

            if operation.get("x-nvsf-public"):
                # Marked public only if the hook actually bypasses it, read from the hook's own
                # list -- so this cannot be claimed for an endpoint that is in fact guarded.
                assert path.startswith(request_hook.bypass_prefixes()), (
                    f"{method.upper()} {path} claims to be public but the hook guards it"
                )
                assert "security" not in operation
                continue

            declared = operation.get("x-nvsf-action")
            assert declared, f"{method.upper()} {path} documents no action and is not public"
            assert declared in resources.ACTIONS, f"{declared} is not a real action"
            assert operation["security"] == [{"sessionCookie": []}]
            assert operation["x-nvsf-roles-allowed"]


def test_the_only_public_endpoints_are_sign_in_and_liveness(app_client):
    """Anything else unauthenticated would be a real finding, so it is asserted rather than trusted.

    Sign-in has to be public because it is where a session comes from, and liveness because a
    container healthcheck carries no cookie. Adding a third has to be a deliberate edit here.
    """
    document = app_client.get("/api/openapi.json").get_json()
    public = {
        path for path, entry in document["paths"].items()
        if any(
            isinstance(operation, dict) and operation.get("x-nvsf-public")
            for method, operation in entry.items() if method != "parameters"
        )
    }
    assert public == {
        "/api/auth/login", "/api/auth/callback", "/api/auth/logout", "/api/auth/me",
        "/api/health/live",
    }


def test_mutating_operations_are_marked_as_such(app_client):
    """A reader deciding what to grant needs to see which calls change state."""
    document = app_client.get("/api/openapi.json").get_json()

    create = document["paths"]["/api/assessments"]["post"]
    assert create["x-nvsf-mutating"] is True

    read = document["paths"]["/api/contracts/index.json"]["get"]
    assert read["x-nvsf-mutating"] is False


def test_path_parameters_are_declared(app_client):
    """Templated paths must carry their parameters, or a generated client cannot call them."""
    document = app_client.get("/api/openapi.json").get_json()

    entry = document["paths"]["/api/contracts/nrm/{version}/{entity}.schema.json"]
    names = {parameter["name"] for parameter in entry["parameters"]}
    assert names == {"version", "entity"}
    assert all(parameter["required"] for parameter in entry["parameters"])


def test_the_api_version_tracks_the_contract_not_the_build(app_client):
    """What a caller cares about is which contract they get. A build number says nothing to them."""
    from contracts import loader

    document = app_client.get("/api/openapi.json").get_json()
    assert document["info"]["version"] == loader.DEFAULT_VERSION.lstrip("v")


def test_every_operation_is_tagged_and_every_tag_is_described(app_client):
    """An untagged operation lands in an unexplained bucket in every OpenAPI renderer."""
    document = app_client.get("/api/openapi.json").get_json()
    described = {tag["name"] for tag in document["tags"]}

    for path, entry in document["paths"].items():
        for method, operation in entry.items():
            if method == "parameters":
                continue
            tags = operation.get("tags") or []
            assert tags, f"{method.upper()} {path} is untagged"
            assert set(tags) <= described, f"{method.upper()} {path} uses an undescribed tag"


def test_the_document_declares_no_bearer_token_scheme(app_client):
    """Deliberate: a long-lived token for this API would have more reach than any endpoint needs.

    Asserted so adding one is a visible decision rather than a convenience someone slips in.
    """
    document = app_client.get("/api/openapi.json").get_json()
    schemes = document["components"]["securitySchemes"]
    assert set(schemes) == {"sessionCookie"}
    assert schemes["sessionCookie"]["type"] == "apiKey"


# ── Authorization ────────────────────────────────────────────────────────────────────────────


def test_contract_reads_require_a_session(anonymous_client):
    """The contract is the product, but it is still internal.

    Any authenticated user gets it -- the whole point is that another team can point an agent at
    the schema -- and an unauthenticated one does not.
    """
    for url in (
        "/api/contracts/index.json",
        "/api/contracts/bundle",
        "/api/contracts/agent-pack.md",
        "/api/openapi.json",
    ):
        response = anonymous_client.get(url)
        assert response.status_code in (401, 403), url
