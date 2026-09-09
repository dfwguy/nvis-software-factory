# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""What the deployment artifacts promise, checked against the application.

Author: Rafael M. Koike & Cursor Agent ("Ada")

A Dockerfile, a compose file and a published API document are all claims about how this software
runs. Nothing keeps a claim true on its own: the healthcheck names an endpoint, the OpenAPI
document names paths, the compose file names a data directory, and each of those can be quietly
falsified by a change somewhere else in the tree.

These tests are cheap and they catch failures that are otherwise found by an operator, at
deployment time, with the service already down.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCKERFILE = REPO_ROOT / "Dockerfile"
COMPOSE = REPO_ROOT / "docker-compose.yml"


def _healthcheck_paths() -> list[tuple[str, str]]:
    """Every URL path a container healthcheck will request, with where it was found."""
    found = []
    for source in (DOCKERFILE, COMPOSE):
        text = source.read_text(encoding="utf-8")
        for match in re.finditer(r"curl -fsS[^\n]*?(/api/[^\s\"'|]+)", text):
            found.append((source.name, match.group(1)))
    return found


def test_the_healthcheck_calls_an_endpoint_that_answers_without_a_session():
    """The failure this catches is a container that is fine and reports itself dying.

    The deep health endpoint is the more useful one and it is behind authorization, so a
    healthcheck pointed at it gets 403, `curl -f` returns non-zero, and Docker restarts a healthy
    container on a thirty-second cycle forever. The only endpoint that is correct here is one on
    the authentication bypass list.
    """
    from audit import request_hook

    paths = _healthcheck_paths()
    assert paths, "no healthcheck found in the Dockerfile or compose file"

    wrong = [
        f"{source}: {path}"
        for source, path in paths
        if request_hook.needs_session(path)
    ]
    assert not wrong, (
        "these healthchecks call endpoints that require a session, so they will always fail:\n  "
        + "\n  ".join(wrong)
        + "\nUse /api/health/live, which is on the bypass list for exactly this caller."
    )


def test_the_healthcheck_endpoint_exists_and_returns_200(app_client):
    """Named correctly and still wrong, if the route was renamed."""
    for _, path in _healthcheck_paths():
        assert app_client.get(path).status_code == 200, f"{path} is not a working endpoint"


def test_published_api_paths_resolve(app_client):
    """Every path in the OpenAPI document must route.

    A generated client requests exactly what the document says. Flask declares a collection route
    as ``/`` inside its blueprint, which makes ``/api/assessments`` -- the spelling the document
    publishes -- a redirect; and a redirect carries no endpoint, so the authorization hook sees a
    view declaring no action and denies it. The caller gets a 403 for a URL that exists, which
    reads as a permissions problem and is not one.
    """
    document = app_client.get("/api/openapi.json").get_json()
    assert document["paths"], "the OpenAPI document publishes no paths"

    adapter = app_client.application.url_map.bind("localhost")
    unroutable = []

    for path, operations in document["paths"].items():
        for method in operations:
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            # Matched against the URL map rather than requested. A POST to a real endpoint has
            # side effects, and what is in question is whether the path routes at all -- not what
            # the handler does with it. Path templates match fine here, which a request cannot do.
            try:
                adapter.match(path, method=method.upper())
            except Exception as exc:  # noqa: BLE001 - werkzeug raises several routing types
                unroutable.append(f"{method.upper()} {path} -> {type(exc).__name__}")

    assert not unroutable, (
        "the OpenAPI document advertises paths that do not route:\n  "
        + "\n  ".join(unroutable)
        + "\nA generated client requests exactly these."
    )


def test_a_nonexistent_api_path_reports_not_found_rather_than_forbidden(app_client):
    """403 for a URL that does not exist sends the caller looking for a missing role.

    The SPA catch-all is what an unmatched path lands on, and it declares no action -- so without
    an explicit carve-out the authorization hook denies it before the view can answer. The symptom
    is that every typo, and every GET against a POST-only endpoint, looks like a permissions
    problem.
    """
    response = app_client.get("/api/no-such-endpoint")
    assert response.status_code == 404, (
        f"expected 404, got {response.status_code}: a missing endpoint is not a policy decision"
    )
    assert response.get_json()["reason"] == "not_found"


def test_collection_endpoints_answer_with_and_without_a_trailing_slash(app_client):
    """Both spellings, because both are in use: the document publishes one and the SPA the other."""
    for path in ("/api/assessments", "/api/repositories", "/api/contracts"):
        bare = app_client.get(path).status_code
        slashed = app_client.get(path + "/").status_code
        assert bare == slashed, (
            f"{path} answers {bare} but {path}/ answers {slashed}; one of them is a redirect the "
            f"authorization hook will deny"
        )


@pytest.mark.parametrize(
    ("claim", "why"),
    [
        ("USER ", "a container running as root turns a code-execution bug into host access"),
        ("HEALTHCHECK ", "without one, a wedged container reports itself as running"),
    ],
)
def test_dockerfile_keeps_its_hardening(claim, why):
    """Directives that are easy to lose in a rewrite and expensive to notice missing."""
    assert claim in DOCKERFILE.read_text(encoding="utf-8"), f"Dockerfile has no {claim!r}: {why}"


def test_the_data_directory_is_a_host_path_not_a_named_volume():
    """The failure that started this project, in the file that would cause it here.

    ``docker volume prune`` deletes a named volume that no running container references, and it is
    the command people reach for when a disk fills up. A host path survives it.
    """
    compose = COMPOSE.read_text(encoding="utf-8")
    mount = re.search(r"^\s*-\s*(\$\{NVSF_HOST_DATA_DIR[^\n]*)", compose, re.MULTILINE)
    assert mount, "no data mount found in docker-compose.yml"
    assert ":" in mount.group(1), "the data mount is not a bind mount"
