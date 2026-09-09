# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Sign in, sign out, and who am I.

Author: Rafael M. Koike & Cursor Agent ("Ada")

These four routes are on the request hook's bypass list, because they are where a session comes
from. That makes them the one place in the app where "no ``@action`` decorator" is correct rather
than a bug, so each says so explicitly -- an undecorated route should always prompt the question.
"""

from __future__ import annotations

import logging

import audit
import authz
from authn import mock, oidc
from authn import session as authn_session
from flask import Blueprint, redirect, request

from ._common import fail, ok

_logger = logging.getLogger("nvsf.api.auth")

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET"])
# No @action: this is how a session is obtained. On the bypass list.
def login():
    """Begin the OIDC flow, or explain why it cannot begin."""
    if mock.enabled():
        return redirect("/")

    try:
        flow = oidc.begin()
    except oidc.OidcError as exc:
        # A configuration problem, and the message says which. Returning a 503 rather than
        # redirecting to a broken URL means the operator sees the cause, not a provider error page.
        _logger.error("auth: cannot begin sign-in: %s", exc)
        return fail(
            f"Sign-in is not available: {exc}", 503, reason="oidc_unavailable",
            hint="An administrator needs to register an OIDC client and set NVSF_OIDC_ISSUER, "
                 "NVSF_OIDC_CLIENT_ID and NVSF_PUBLIC_URL.",
        )

    authn_session.stash_flow(
        flow.state, flow.nonce, flow.code_verifier, request.args.get("return_to"),
    )
    return redirect(flow.authorization_url)


@bp.route("/callback", methods=["GET"])
# No @action: completing the flow is what produces the principal an action would be checked
# against. On the bypass list.
def callback():
    """Complete the flow: verify state, redeem the code, validate the ID token."""
    error = request.args.get("error")
    if error:
        description = request.args.get("error_description", "")
        _logger.warning("auth: provider returned %s: %s", error, description)
        audit.record(
            actor="anonymous", action="auth:login", outcome="denied",
            detail={"provider_error": error}, source_ip=request.remote_addr,
        )
        return fail(f"The identity provider rejected the sign-in: {error}", 401,
                    reason="provider_error")

    code = request.args.get("code")
    if not code:
        return fail("The callback carried no authorization code.", 400, reason="missing_code")

    try:
        flow = authn_session.take_flow(request.args.get("state", ""))
        tokens = oidc.exchange(code, flow["code_verifier"])
        identity = oidc.verify_id_token(tokens["id_token"], flow["nonce"])
    except oidc.OidcError as exc:
        audit.record(
            actor="anonymous", action="auth:login", outcome="denied",
            detail={"reason": str(exc)}, source_ip=request.remote_addr,
        )
        return fail(str(exc), 401, reason="sign_in_failed")

    principal = authn_session.establish(identity)
    audit.record(
        actor=principal.subject, action="auth:login", outcome="ok",
        detail={"groups": sorted(principal.groups),
                "roles": sorted(str(r) for r in principal.roles)},
        source_ip=request.remote_addr,
    )
    return redirect(authn_session.take_return_to())


@bp.route("/logout", methods=["POST", "GET"])
# No @action: signing out must work regardless of what the session can do, including when it has
# expired. On the bypass list.
def logout():
    """Clear the local session, and say honestly whether the provider session also ended."""
    principal = authn_session.current_principal()
    if principal:
        audit.record(
            actor=principal.subject, action="auth:logout", outcome="ok",
            source_ip=request.remote_addr, is_mock=principal.is_mock,
        )
    authn_session.clear()

    provider_url = oidc.end_session_url()
    return ok(
        signed_out=True,
        # The distinction matters on a shared workstation: if the provider does not support
        # RP-initiated logout, the user is still signed in *there*, and telling them otherwise
        # would be a security-relevant lie.
        provider_session_ended=bool(provider_url),
        provider_logout_url=provider_url,
    )


@bp.route("/me", methods=["GET"])
# No @action: this is the endpoint the SPA uses to discover whether it has a session at all, so it
# must be able to answer 401 with a readable body rather than being blocked by the hook.
def me():
    """The current principal and what it may do.

    ``permissions`` lets the UI hide controls the user cannot use. That is a usability measure,
    not a security one -- the server decides, every time, in the request hook.
    """
    principal = authn_session.current_principal()
    if principal is None:
        return fail(
            "Not signed in.", 401, reason="unauthenticated",
            login_url="/api/auth/login",
        )
    return ok(
        user=principal.to_json(),
        permissions=authz.authorized_actions(principal),
    )
