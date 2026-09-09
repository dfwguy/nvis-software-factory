# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""OIDC relying party: authorization code flow with PKCE.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Authentication is OIDC-only. There is no local password store, which removes an entire category of
problem -- password hashing, reset flows, credential storage, lockout policy -- and hands identity
to the system that already owns it.

THE THREE THINGS THAT ARE EASY TO GET WRONG HERE
-------------------------------------------------
Each of these is a real, exploited class of bug, not a hypothetical:

1. **``algorithms`` must be pinned when verifying.** ``jwt.decode`` without it trusts the token's
   own ``alg`` header. That is the ``alg: none`` bypass, and the RS256-to-HS256 confusion attack
   where an attacker signs a token using the *public* key as an HMAC secret. We pass the algorithms
   the provider advertised in its discovery document, and refuse ``none`` explicitly.

2. **``state`` and ``nonce`` are not decoration.** ``state`` binds the callback to the browser that
   started the flow, without which any page can force a login as a user of its choosing (login
   CSRF). ``nonce`` binds the ID token to this authorization request, without which a token
   obtained elsewhere can be replayed. Both are compared in constant time and both are single-use.

3. **PKCE is used even with a client secret.** The code verifier means an intercepted
   authorization code cannot be redeemed by anyone who did not start the flow. Confidential clients
   are often told they do not need it; it costs four lines.

Discovery is cached, with the JWKS cached separately and re-fetched on an unknown key id -- which
is how key rotation is meant to be handled. Re-fetching on every token validation would let an
unknown ``kid`` become a request amplifier against the provider.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any

import jwt
import requests
import settings
from jwt import PyJWKClient

_logger = logging.getLogger("nvsf.authn.oidc")

#: Discovery is stable but not immutable; an hour bounds how long a rotation takes to be noticed.
_DISCOVERY_TTL_SEC = 3600

#: Explicit timeouts on every call. Reliability criterion R1: requests has no default, so a bare
#: get() here could hang a worker until the TCP stack gives up -- during sign-in, of all moments.
_HTTP_TIMEOUT = (5, 15)

_discovery_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_jwks_clients: dict[str, PyJWKClient] = {}


class OidcError(RuntimeError):
    """Something in the flow failed. Messages are safe to show a user."""


@dataclass(frozen=True)
class FlowStart:
    """What the browser needs to begin, and what the server must remember."""

    authorization_url: str
    state: str
    nonce: str
    code_verifier: str


@dataclass(frozen=True)
class Identity:
    """Verified claims from an ID token."""

    subject: str
    email: str | None
    display_name: str | None
    groups: frozenset[str]
    issued_at: int
    expires_at: int
    raw_claims: dict[str, Any]


def discovery(issuer: str | None = None) -> dict[str, Any]:
    """The provider's ``.well-known/openid-configuration``, cached."""
    target = (issuer or settings.get_str("NVSF_OIDC_ISSUER")).rstrip("/")
    if not target:
        raise OidcError("NVSF_OIDC_ISSUER is not configured")

    cached = _discovery_cache.get(target)
    if cached and time.monotonic() - cached[0] < _DISCOVERY_TTL_SEC:
        return cached[1]

    url = f"{target}/.well-known/openid-configuration"
    try:
        response = requests.get(url, timeout=_HTTP_TIMEOUT)
        response.raise_for_status()
        document = response.json()
    except requests.RequestException as exc:
        raise OidcError(f"could not fetch OIDC discovery from {url}: {exc}") from exc
    except ValueError as exc:
        raise OidcError(f"OIDC discovery at {url} is not JSON") from exc

    for required in ("authorization_endpoint", "token_endpoint", "jwks_uri", "issuer"):
        if required not in document:
            raise OidcError(f"OIDC discovery at {url} has no {required}")

    # The discovery document's own issuer must match what we asked for, or a compromised discovery
    # URL could point us at a different provider's endpoints while we validate against its issuer.
    if document["issuer"].rstrip("/") != target:
        raise OidcError(
            f"OIDC discovery issuer mismatch: configured {target}, document says "
            f"{document['issuer']}"
        )

    _discovery_cache[target] = (time.monotonic(), document)
    _logger.info("oidc: discovered %s", target)
    return document


def _jwks_client(jwks_uri: str) -> PyJWKClient:
    """Cached JWKS client.

    ``PyJWKClient`` caches keys itself and re-fetches on an unknown ``kid``, which is the correct
    behaviour for key rotation. Constructing a new client per validation would defeat that cache
    and turn every unknown key id into a request to the provider.
    """
    client = _jwks_clients.get(jwks_uri)
    if client is None:
        client = PyJWKClient(jwks_uri, cache_keys=True, lifespan=3600)
        _jwks_clients[jwks_uri] = client
    return client


def redirect_uri() -> str:
    """Callback URL. Must match what is registered with the provider, byte for byte."""
    base = settings.get_str("NVSF_PUBLIC_URL").rstrip("/")
    if not base:
        raise OidcError("NVSF_PUBLIC_URL is not configured, so the redirect URI cannot be built")
    return f"{base}/api/auth/callback"


def _pkce_pair() -> tuple[str, str]:
    """``(verifier, challenge)`` for S256.

    The challenge is base64url of the SHA-256 of the verifier, with padding stripped -- RFC 7636
    is explicit that the ``=`` padding must not be sent, and a provider will reject the request
    with an unhelpful error if it is.
    """
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def begin() -> FlowStart:
    """Build the authorization URL and the values the server must remember for the callback.

    Note there is no ``return_to`` parameter. Where to land after sign-in is kept in our own
    session, never round-tripped through the provider, because a URL parameter that the callback
    redirects to is an open redirect waiting to be found.
    """
    document = discovery()
    client_id = settings.get_str("NVSF_OIDC_CLIENT_ID")
    if not client_id:
        raise OidcError("NVSF_OIDC_CLIENT_ID is not configured")

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()

    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
        "scope": settings.get_str("NVSF_OIDC_SCOPES", "openid profile email groups"),
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return FlowStart(
        authorization_url=f"{document['authorization_endpoint']}?{urlencode(params)}",
        state=state,
        nonce=nonce,
        code_verifier=verifier,
    )


def exchange(code: str, code_verifier: str) -> dict[str, Any]:
    """Redeem the authorization code for tokens."""
    document = discovery()
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(),
        "client_id": settings.get_str("NVSF_OIDC_CLIENT_ID"),
        "code_verifier": code_verifier,
    }
    secret = settings.get("NVSF_OIDC_CLIENT_SECRET")
    if secret:
        payload["client_secret"] = secret

    try:
        response = requests.post(
            document["token_endpoint"], data=payload, timeout=_HTTP_TIMEOUT,
            headers={"Accept": "application/json"},
        )
    except requests.RequestException as exc:
        raise OidcError(f"token endpoint unreachable: {exc}") from exc

    if response.status_code != 200:
        # The provider's error body can echo the request. Log the code and description only,
        # never the whole body, so a client secret cannot land in the log.
        try:
            detail = response.json()
            summary = f"{detail.get('error')}: {detail.get('error_description')}"
        except ValueError:
            summary = f"HTTP {response.status_code}"
        raise OidcError(f"token exchange rejected ({summary})")

    try:
        tokens = response.json()
    except ValueError as exc:
        raise OidcError("token endpoint did not return JSON") from exc

    if "id_token" not in tokens:
        raise OidcError(
            "token response has no id_token. Check that the 'openid' scope is requested and "
            "granted to this client."
        )
    return tokens


def verify_id_token(id_token: str, nonce: str) -> Identity:
    """Validate the ID token and extract claims.

    See the module docstring for why ``algorithms`` is pinned rather than inferred.
    """
    document = discovery()
    algorithms = [
        alg for alg in document.get("id_token_signing_alg_values_supported", ["RS256"])
        # 'none' would mean an unsigned token is acceptable. Never.
        if alg.lower() != "none"
    ]
    if not algorithms:
        raise OidcError("provider advertises no usable ID token signing algorithm")

    try:
        signing_key = _jwks_client(document["jwks_uri"]).get_signing_key_from_jwt(id_token)
    except Exception as exc:  # PyJWKClient raises several unrelated types
        raise OidcError(f"could not resolve the token's signing key: {exc}") from exc

    try:
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=algorithms,
            audience=settings.get_str("NVSF_OIDC_CLIENT_ID"),
            issuer=document["issuer"],
            options={
                "require": ["exp", "iat", "iss", "aud", "sub"],
                "verify_exp": True,
                "verify_iat": True,
                "verify_aud": True,
                "verify_iss": True,
                "verify_signature": True,
            },
            leeway=30,  # tolerate modest clock skew, not an expired token
        )
    except jwt.ExpiredSignatureError as exc:
        raise OidcError("the ID token has expired; try signing in again") from exc
    except jwt.InvalidTokenError as exc:
        raise OidcError(f"the ID token is not valid: {exc}") from exc

    # Nonce binds this token to the authorization request this browser started. Constant-time
    # compare because it is a secret comparison, even though a timing attack here is far-fetched.
    presented = str(claims.get("nonce", ""))
    if not presented or not secrets.compare_digest(presented, nonce):
        raise OidcError("ID token nonce does not match this sign-in attempt")

    groups_claim = settings.get_str("NVSF_OIDC_GROUPS_CLAIM", "groups")
    raw_groups = claims.get(groups_claim) or []
    if isinstance(raw_groups, str):
        # Some providers send a space- or comma-separated string rather than an array.
        raw_groups = [g for g in raw_groups.replace(",", " ").split() if g]

    return Identity(
        subject=str(claims["sub"]),
        email=claims.get("email"),
        display_name=claims.get("name") or claims.get("preferred_username"),
        groups=frozenset(str(g) for g in raw_groups),
        issued_at=int(claims["iat"]),
        expires_at=int(claims["exp"]),
        raw_claims=claims,
    )


def end_session_url(id_token_hint: str | None = None) -> str | None:
    """Provider's RP-initiated logout URL, if it advertises one.

    Returns None when it does not, and the caller clears the local session and says so rather than
    implying the provider session has ended too. Telling a user they are signed out when their IdP
    session is still live is a security-relevant lie on a shared workstation.
    """
    from urllib.parse import urlencode

    try:
        document = discovery()
    except OidcError:
        return None
    endpoint = document.get("end_session_endpoint")
    if not endpoint:
        return None
    params: dict[str, str] = {
        "post_logout_redirect_uri": settings.get_str("NVSF_PUBLIC_URL").rstrip("/") + "/",
    }
    if id_token_hint:
        params["id_token_hint"] = id_token_hint
    return f"{endpoint}?{urlencode(params)}"


def reset_caches() -> None:
    """Clear discovery and JWKS caches. For tests, and for an admin-triggered refresh."""
    _discovery_cache.clear()
    _jwks_clients.clear()
