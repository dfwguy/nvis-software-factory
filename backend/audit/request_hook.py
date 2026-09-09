# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The one place a request is authenticated, authorized and audited.

Author: Rafael M. Koike & Cursor Agent ("Ada")

A single ``before_request``/``after_request`` pair rather than per-blueprint decorators, for the
reason that recurs throughout this codebase: a control that depends on every future call site
remembering it is not a control. Here that principle has teeth, because the hook can see the
*absence* of an ``@action`` declaration and deny, which a decorator on the route obviously cannot.

WHAT THE BYPASS LIST IS FOR
----------------------------
Three kinds of request cannot require a session, and each is enumerated rather than pattern-matched:

* the sign-in endpoints, which is where a session comes from;
* the liveness probe, because a container healthcheck has no cookie and an orchestrator that
  cannot tell "unauthenticated" from "dead" will restart a perfectly healthy container;
* the static shell -- the SPA's own JS and CSS -- because the browser has to load the page that
  offers the login button. It carries no data of its own.

The list is closed and tested. ``test_bypass_list_is_exhaustive`` asserts every entry still
resolves to a real endpoint, so an entry left behind after a rename cannot quietly widen it.

DENIALS ARE AUDITED, SUCCESSFUL READS ARE NOT
----------------------------------------------
Every denial is recorded, because a pattern of denials is the interesting signal. Successful
mutations are recorded. Successful reads are not: auditing every GET turns the trail into a second
access log, and a trail nobody can read is a trail nobody reads.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

import authz
import logging_config
from authz import resources

from . import sink

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flask import Flask, Response

_logger = logging.getLogger("nvsf.audit.hook")

#: Exact paths that need no session. Prefixes, so ``/api/auth/callback?code=...`` matches.
_BYPASS_PREFIXES = (
    "/api/auth/login",
    "/api/auth/callback",
    "/api/auth/logout",
    "/api/auth/me",       # answers 401 with a body the SPA can read, rather than being blocked
    "/api/health/live",   # container healthcheck; deliberately says nothing about the data
    "/static/",
    "/assets/",
)

#: Non-API paths that serve the SPA shell. These carry no application data.
_SHELL_PATHS = ("/", "/index.html", "/favicon.ico", "/manifest.webmanifest")


def _needs_session(path: str) -> bool:
    if path.startswith(_BYPASS_PREFIXES):
        return False
    if path in _SHELL_PATHS:
        return False
    # Client-side routes: the SPA is one HTML file, and every route in it resolves to the shell.
    # Requiring a session for those would mean the browser cannot load the page that logs you in.
    return path.startswith(("/api/", "/docs"))


def install(app: Flask) -> None:
    """Attach the hook pair. Called once, from the composition root."""
    from flask import g, jsonify, request

    @app.before_request
    def _authenticate_and_authorize():
        # Correlation id first, so even a rejected request's log lines are correlated. Honour an
        # inbound header when present, so a caller chaining requests can tie them together.
        incoming = request.headers.get("X-Correlation-ID", "").strip()
        cid = incoming[:64] if incoming else uuid.uuid4().hex[:12]
        g.correlation_token = logging_config.set_correlation_id(cid)
        g.correlation_id = cid

        if not _needs_session(request.path):
            return None

        # CORS preflight never carries credentials. There is no cross-origin client by design, so
        # this exists only so a stray preflight gets a clean answer rather than a 401.
        if request.method == "OPTIONS":
            return None

        from authn import session as authn_session

        principal = authn_session.current_principal()
        g.principal = principal

        view = app.view_functions.get(request.endpoint or "")

        # An /api/ path that matched nothing but the SPA catch-all does not exist. Answering 403
        # would be true in a narrow sense -- the catch-all declares no action -- and misleading in
        # every practical one: the caller reads it as a permissions problem and goes looking for a
        # role they are missing, when they have a typo, or are calling a POST-only endpoint with
        # GET. Endpoint existence is not a secret here anyway; the OpenAPI document lists them all.
        #
        # Let it through to the view, which answers with the JSON 404 it was written to give.
        if request.endpoint == "serve_spa" and request.path.startswith("/api/"):
            g.action_name = None
            g.decision = None
            return None

        action_name = authz.action_of(view)
        decision = authz.decide(principal, action_name)
        g.action_name = action_name
        g.decision = decision

        if decision.allowed:
            return None

        unauthenticated = principal is None or principal.subject == "anonymous"
        status = 401 if unauthenticated else 403

        sink.emit(sink.build_event(
            actor=principal.subject if principal else "anonymous",
            action=action_name or f"{request.method} {request.path}",
            outcome="denied",
            resource=request.path,
            detail={"reason": decision.reason, "method": request.method, "status": status},
            correlation_id=cid,
            source_ip=request.remote_addr,
            is_mock=bool(principal and principal.is_mock),
        ))

        if action_name is None:
            # A route with no declared action. Loud, because it is a bug in our code rather than a
            # user's mistake, and the message names the fix.
            _logger.error(
                "authz: %s %s (endpoint %s) declares no action and was denied. Add "
                "@action(...) from backend/authz to the view.",
                request.method, request.path, request.endpoint,
            )

        body = {"ok": False, "error": decision.reason, "reason": "unauthorized" if
                unauthenticated else "forbidden", "action": action_name}
        response = jsonify(body)
        response.status_code = status
        if status == 401:
            # Names the scheme, so a scripted client knows what to do rather than guessing.
            response.headers["WWW-Authenticate"] = 'Session realm="nvis-software-factory"'
        return response

    @app.after_request
    def _audit_success(response: Response) -> Response:
        decision = getattr(g, "decision", None)
        action_name = getattr(g, "action_name", None)
        principal = getattr(g, "principal", None)

        if decision is not None and decision.allowed and action_name:
            declared = resources.get(action_name)
            # Only mutations, and only ones that actually succeeded. A 400 on a create is a
            # validation event, not a change, and recording it as one makes the trail misleading.
            if declared and declared.mutating and 200 <= response.status_code < 400:
                sink.emit(sink.build_event(
                    actor=principal.subject if principal else "unknown",
                    action=action_name,
                    outcome="ok",
                    resource=request.path,
                    detail={"method": request.method, "status": response.status_code},
                    correlation_id=getattr(g, "correlation_id", None),
                    source_ip=request.remote_addr,
                    is_mock=bool(principal and principal.is_mock),
                ))

        response.headers.setdefault("X-Correlation-ID", getattr(g, "correlation_id", "-"))
        return response

    @app.teardown_request
    def _reset_correlation(_exc: BaseException | None) -> None:
        token = getattr(g, "correlation_token", None)
        if token is not None:
            logging_config.reset_correlation_id(token)


def bypass_prefixes() -> tuple[str, ...]:
    """Exposed so the OpenAPI generator can mark these endpoints as unauthenticated, and so the
    test that keeps the list honest has something to read."""
    return _BYPASS_PREFIXES


def needs_session(path: str) -> bool:
    """Whether *path* is subject to authentication and authorization.

    Public because the rule "a route either bypasses this hook or declares an action" is the one
    that decides whether a route is reachable at all, and a test asserting it should read the same
    function the hook uses rather than reimplementing the prefix and shell lists. When those two
    drifted apart, ``/docs`` was a 403 for every user and the test passed.
    """
    return _needs_session(path)
