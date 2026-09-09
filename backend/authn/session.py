# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Session state: a signed, HttpOnly cookie holding claims, not tokens.

Author: Rafael M. Koike & Cursor Agent ("Ada")

WHAT IS IN THE COOKIE, AND WHAT IS DELIBERATELY NOT
----------------------------------------------------
In: the subject, email, display name, resolved groups, and an expiry. Out: the access token, the
refresh token, and the ID token itself.

The reason is blast radius. Flask's session cookie is *signed*, not encrypted -- anyone holding the
cookie can read its contents, they simply cannot alter them. So the cookie may hold claims, which
the user already knows about themselves, and must not hold a bearer credential, which would be
usable against the provider and every other service that trusts it.

The tokens are used once, at the callback, to establish who the user is, and then discarded. This
application never calls the provider's API on the user's behalf, so it has no reason to keep them.

Roles are recomputed from groups on **every request** rather than stored. That means a group
mapping change takes effect immediately, and it means a stale cookie cannot carry a role that
configuration no longer grants.

FLOW STATE
----------
``state``, ``nonce`` and the PKCE verifier live in the same session between ``/login`` and
``/callback``, and are deleted the moment they are read. Single-use: replaying a callback URL
finds nothing to compare against and fails, rather than succeeding a second time.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import TYPE_CHECKING, Any

import settings
from authz import Principal, roles_from_groups

from . import mock, oidc

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flask import Flask

_logger = logging.getLogger("nvsf.authn.session")

_USER_KEY = "user"
_FLOW_KEY = "flow"
_RETURN_KEY = "return_to"


def install(app: Flask) -> None:
    """Nothing to attach today.

    Kept as the seam the composition root already calls, so adding session behaviour later does
    not mean editing ``app.py``. Cookie configuration itself lives in ``app.config``, because
    Flask reads it from there.
    """
    _logger.debug("authn: session cookie %s configured", app.config["SESSION_COOKIE_NAME"])


# ── Flow state ───────────────────────────────────────────────────────────────────────────────

def stash_flow(state: str, nonce: str, code_verifier: str, return_to: str | None) -> None:
    from flask import session

    session[_FLOW_KEY] = {"state": state, "nonce": nonce, "code_verifier": code_verifier}
    # Path-only, and validated on the way out. Never a full URL, so the callback cannot be turned
    # into an open redirect.
    if return_to and return_to.startswith("/") and not return_to.startswith("//"):
        session[_RETURN_KEY] = return_to[:512]


def take_flow(presented_state: str) -> dict[str, str]:
    """Consume the stashed flow state, verifying ``state`` matches.

    Deletes before comparing, so a failed comparison also invalidates the attempt. Otherwise a
    wrong guess would leave the state in place to be guessed again.
    """
    from flask import session

    stored = session.pop(_FLOW_KEY, None)
    if not stored:
        raise oidc.OidcError(
            "no sign-in attempt is in progress for this browser. This usually means the callback "
            "was opened directly, the cookie was cleared, or the attempt expired. Start again."
        )
    if not secrets.compare_digest(str(stored.get("state", "")), presented_state or ""):
        raise oidc.OidcError("sign-in state does not match; the attempt was rejected")
    return stored


def take_return_to() -> str:
    from flask import session

    return session.pop(_RETURN_KEY, "/") or "/"


# ── Established session ──────────────────────────────────────────────────────────────────────

def establish(identity: oidc.Identity) -> Principal:
    """Turn verified claims into a session. Returns the resulting principal."""
    from flask import session

    session.clear()  # drop the flow state and anything from a previous user
    session.permanent = True
    # Our own expiry, recorded server-side in the signed cookie, so it is enforced independently
    # of the browser honouring the cookie's Max-Age. The ID token's `exp` is deliberately NOT used
    # for this: it is often minutes long, because it is meant to bound the assertion's freshness at
    # exchange time, not the length of a working session.
    session[_USER_KEY] = {
        "subject": identity.subject,
        "email": identity.email,
        "display_name": identity.display_name,
        "groups": sorted(identity.groups),
        "authenticated_at": int(time.time()),
        "expires_at": int(time.time()) + settings.get_int("NVSF_SESSION_TTL_HOURS", 12) * 3600,
    }
    principal = _principal_from(session[_USER_KEY])
    _logger.info(
        "authn: signed in %s (groups=%s roles=%s)",
        principal.subject, ",".join(sorted(principal.groups)) or "none",
        ",".join(sorted(str(r) for r in principal.roles)),
    )
    return principal


def clear() -> None:
    from flask import session

    session.clear()


def _principal_from(stored: dict[str, Any]) -> Principal:
    """Build a principal from stored claims, recomputing roles from current configuration."""
    groups = frozenset(stored.get("groups") or [])
    roles = roles_from_groups(
        set(groups),
        set(settings.get_list("NVSF_OIDC_ADMIN_GROUPS")),
        settings.get_mapping("NVSF_OIDC_ROLE_MAP"),
    )
    return Principal(
        subject=str(stored["subject"]),
        email=stored.get("email"),
        display_name=stored.get("display_name"),
        groups=groups,
        roles=roles,
    )


def current_principal() -> Principal | None:
    """Who is making this request, or None.

    Order matters: the mock provider is consulted first, but only when all three of its locks are
    open, so a development session needs no sign-in round trip. In any real deployment
    ``mock.enabled()`` is False and this reduces to reading the cookie.
    """
    if mock.enabled():
        return mock.principal()

    from flask import session

    stored = session.get(_USER_KEY)
    if not stored or "subject" not in stored:
        return None

    # Enforced server-side rather than relying on the cookie's Max-Age, which is a request to the
    # browser and not a guarantee. A session with no recorded expiry is from an older cookie
    # format and is rejected rather than treated as immortal.
    expires_at = stored.get("expires_at")
    if not expires_at or time.time() > float(expires_at):
        session.clear()
        return None

    return _principal_from(stored)
