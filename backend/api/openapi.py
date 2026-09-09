# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""OpenAPI 3.1 description of this API: /api/openapi.json

Author: Rafael M. Koike & Cursor Agent ("Ada")

Generated from Flask's live route table and the authz action registry, not hand-written. A
hand-written OpenAPI file is a second source of truth for the API surface, and the one that drifts
is always the document -- so a client generated from it fails against endpoints that changed months
ago, and the failure looks like a bug in the client.

Because it is generated from the routes, the description cannot claim an endpoint that does not
exist or omit one that does. It also cannot invent a permission: the required role on each
operation comes from the same ``@action`` decorator the authorization check reads, so the document
and the enforcement are the same fact.

OpenAPI 3.1 specifically, because it aligns with JSON Schema 2020-12 -- which is what the NRM
contract is written in. That lets the request body of ``/api/contracts/validate`` reference the
real bundle schema instead of a paraphrase of it.
"""

from __future__ import annotations

import json
import logging
import re

from authz import action, action_of, resources
from flask import Blueprint, Response, current_app

bp = Blueprint("openapi", __name__, url_prefix="")

_logger = logging.getLogger("nvsf.api.openapi")

#: Flask converters to OpenAPI schema. Anything unlisted becomes a string, which is correct for
#: this API -- every path parameter here is an opaque ID or a name.
_CONVERTERS = {
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "path": {"type": "string"},
    "uuid": {"type": "string", "format": "uuid"},
}

_PARAM = re.compile(r"<(?:(?P<conv>[a-z]+)(?::))?(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)>")


def _is_public(path: str) -> bool:
    """Whether a path is deliberately unauthenticated.

    Read from the request hook's own bypass list rather than restated here. A second copy would
    eventually disagree, and the failure is silent in the worst direction: the document would
    describe an endpoint as protected while the hook waves it through.

    The genuinely public routes are the sign-in flow -- ``/api/auth/callback`` is where a session
    comes FROM, so requiring one would be circular -- and the container liveness probe.
    """
    from audit import request_hook

    return path.startswith(request_hook.bypass_prefixes())


#: Description text per path prefix, longest-prefix-wins. Grouping is by prefix rather than by
#: blueprint because that is what a reader of the document sees -- and /api/openapi.json belongs
#: with the contract for the same reason it shares contract:read: a team pointing an agent at the
#: schemas wants the API description in the same place.
_TAGS: tuple[tuple[str, str, str], ...] = (
    ("/api/openapi", "contracts", ""),
    ("/api/contracts", "contracts", (
        "The NVIS Resource Model: schemas, crosswalks, and deterministic validation. Start at "
        "/api/contracts/index.json, or fetch /api/contracts/bundle to get the whole contract in "
        "one request."
    )),
    ("/api/repositories", "repositories", (
        "Repositories registered for assessment. Registration is separate from assessment "
        "because the history of a repository is the interesting part."
    )),
    ("/api/assessments", "assessments", (
        "Assessment runs. Each produces deterministic findings plus a required LLM reasoning "
        "stage, and renders a downloadable Markdown bundle."
    )),
    ("/api/standards", "standards", (
        "The quality baseline an assessment judges against: eight pillars, their criteria, and "
        "which criteria have a deterministic detector versus being a judgement. Served from the "
        "same files the prompts are built from."
    )),
    ("/api/health", "health", (
        "Health per dependency. /live is liveness only; / returns 503 when a required dependency "
        "is down."
    )),
    ("/api/auth", "auth", "OIDC sign-in, sign-out, and the current session."),
)


def _tag_for(path: str) -> str:
    for prefix, tag, _ in _TAGS:
        if path.startswith(prefix):
            return tag
    return "other"


def _path_template(rule: str) -> tuple[str, list[dict]]:
    """Convert a Flask rule to an OpenAPI path template plus its parameter objects."""
    parameters = []
    for match in _PARAM.finditer(rule):
        name = match.group("name")
        parameters.append({
            "name": name,
            "in": "path",
            "required": True,
            "schema": _CONVERTERS.get(match.group("conv") or "", {"type": "string"}),
        })
    return _PARAM.sub(lambda m: "{" + m.group("name") + "}", rule), parameters


def _summary(view) -> tuple[str, str]:
    """``(summary, description)`` from the view's docstring.

    The docstrings are already written for a reader -- they explain why an endpoint exists, not
    just what it does. Reusing them means the API document says the same thing as the code, and
    there is no second place to update.
    """
    text = (view.__doc__ or "").strip()
    if not text:
        return "", ""
    parts = text.split("\n\n", maxsplit=1)
    summary = " ".join(parts[0].split())
    detail = " ".join(parts[1].split()) if len(parts) > 1 else ""
    return summary, detail


def _security_for(path: str, endpoint_action: str | None) -> tuple[list, dict]:
    """Security requirement and the role note for one operation."""
    if _is_public(path):
        return [], {"x-nvsf-public": True}
    if endpoint_action is None:
        # Not on the bypass list and carrying no action: the hook denies this by default, so the
        # document should say so rather than implying a permission nobody declared.
        return [{"sessionCookie": []}], {"x-nvsf-action": None, "x-nvsf-default-deny": True}

    declared = resources.get(endpoint_action)
    if declared is None:
        return [{"sessionCookie": []}], {}

    # `allowed` holds the least-privileged roles that satisfy the action; the policy engine
    # expands a principal's roles through the implication table before intersecting. So a caller
    # reading this sees "viewer or above", which is the useful statement.
    return [{"sessionCookie": []}], {
        "x-nvsf-action": endpoint_action,
        "x-nvsf-roles-allowed": sorted(str(role) for role in declared.allowed),
        "x-nvsf-mutating": bool(declared.mutating),
    }


def build() -> dict:
    """Assemble the document from the live route table."""
    import settings

    public_url = settings.get_str("NVSF_PUBLIC_URL") or "http://localhost:8000"

    paths: dict[str, dict] = {}
    for rule in sorted(current_app.url_map.iter_rules(), key=lambda r: str(r.rule)):
        path = str(rule.rule)
        if not path.startswith("/api/"):
            continue
        # Flask registers a trailing-slash variant; describing both would double the document with
        # entries a reader has to mentally deduplicate.
        if path.endswith("/") and len(path) > 5:
            path = path.rstrip("/")

        view = current_app.view_functions.get(rule.endpoint)
        if view is None:
            continue

        template, parameters = _path_template(path)
        entry = paths.setdefault(template, {})
        if parameters:
            entry["parameters"] = parameters

        summary, detail = _summary(view)
        # Read through the same accessor the request hook uses, so the document and the
        # enforcement cannot disagree about which action guards a route.
        endpoint_action = action_of(view)
        security, extensions = _security_for(path, endpoint_action)

        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            operation: dict = {
                "operationId": f"{method.lower()}_{rule.endpoint.replace('.', '_')}",
                "tags": [_tag_for(path)],
                "summary": summary or rule.endpoint,
                "responses": {
                    "200": {"description": "Success."},
                    "401": {"description": "No valid session."},
                    "403": {"description": "Authenticated, but the role does not permit this."},
                },
                **extensions,
            }
            if detail:
                operation["description"] = detail
            if security:
                operation["security"] = security
            entry[method.lower()] = operation

    document = {
        "openapi": "3.1.0",
        "info": {
            "title": "NVIS Software Factory API",
            "version": _api_version(),
            "summary": "Software quality assessment and the NVIS Resource Model data contract.",
            "description": (
                "Two surfaces in one API.\n\n"
                "**The Factory** takes a GitLab or GitHub URL, clones it safely, gathers "
                "deterministic evidence, and puts a required LLM reasoning stage on top to produce "
                "an assessment plus agent-ready remediation documents.\n\n"
                "**The Contract** publishes the NVIS Resource Model: a versioned data contract for "
                "every unit of resource from a transceiver to a rack, with normative crosswalks to "
                "Nautobot, Redfish, UFM, BCM rack-import, DCGM and CycloneDX.\n\n"
                "This document is GENERATED from the live route table and the authorization "
                "registry, so it cannot describe an endpoint that does not exist or a permission "
                "that is not enforced."
            ),
        },
        "servers": [{"url": public_url}],
        # Deduplicated, since more than one prefix can share a tag; the entry carrying the
        # description wins and the alias contributes nothing but its grouping.
        "tags": [
            {"name": tag, "description": description}
            for _, tag, description in _TAGS
            if description
        ],
        "components": {
            "securitySchemes": {
                "sessionCookie": {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": "nvsf_session",
                    "description": (
                        "Set by the OIDC authorization-code flow at /api/auth/login. There is no "
                        "API token scheme: a long-lived bearer token for this API would be a "
                        "credential with more reach than any of these endpoints needs."
                    ),
                },
            },
        },
        "paths": paths,
    }
    return document


def _api_version() -> str:
    """Version of the API surface, tied to the contract version it serves.

    Deliberately not a build number. What a client cares about is which contract it will get, and
    a build number changes on every commit without any of them meaning anything to a caller.
    """
    from contracts import loader

    return loader.DEFAULT_VERSION.lstrip("v")


@bp.route("/api/openapi.json", methods=["GET"])
@action("contract:read")
def openapi_document():
    """The OpenAPI 3.1 description of this API, generated from the live routes.

    Served under contract:read rather than its own action because it is part of the same
    deliverable: a team pointing an agent at the contract wants the API description alongside the
    schemas, and splitting the permission would mean granting two things to accomplish one.
    """
    response = Response(json.dumps(build(), indent=2) + "\n", mimetype="application/json")
    # Short cache, not immutable: unlike the contract, this changes when routes change, and a
    # stale copy would describe endpoints a deployment no longer has.
    response.headers["Cache-Control"] = "public, max-age=300"
    return response
