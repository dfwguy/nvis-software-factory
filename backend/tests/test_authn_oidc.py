# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The OIDC relying party, tested at the checks that decide whether a token is believed.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Every test here is about a way an attacker gets in, and each corresponds to a real published
attack rather than a hypothetical. Discovery from an issuer that names a different issuer is
mix-up. An unverified signature is forgery. A missing nonce check is replay. A missing audience
check means a token minted for another client of the same provider works here.

Signing keys are generated in-process and the JWKS is served from memory: a test that reaches the
network is a test that fails when the network does, and this is exactly the code where a skipped
test would be mistaken for a passing one.
"""

from __future__ import annotations

import json
import time

import pytest

jwt = pytest.importorskip("jwt")

from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from jwt.utils import base64url_encode  # noqa: E402

ISSUER = "https://idp.test.nvidia.com"
CLIENT_ID = "nvis-software-factory"


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def jwks(signing_key):
    """The provider's public key set, as it would be served from jwks_uri."""
    numbers = signing_key.public_key().public_numbers()

    def b64(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64url_encode(raw).decode("ascii")

    return {"keys": [{
        "kty": "RSA", "use": "sig", "alg": "RS256", "kid": "test-key-1",
        "n": b64(numbers.n), "e": b64(numbers.e),
    }]}


@pytest.fixture
def discovery_document():
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "jwks_uri": f"{ISSUER}/jwks",
        "end_session_endpoint": f"{ISSUER}/logout",
        "id_token_signing_alg_values_supported": ["RS256"],
    }


@pytest.fixture
def oidc(monkeypatch):
    from authn import oidc as module

    monkeypatch.setenv("NVSF_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("NVSF_OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("NVSF_PUBLIC_URL", "https://factory.test.nvidia.com")
    module.reset_caches()
    yield module
    module.reset_caches()


class _Response:
    """Enough of requests.Response for this module, and nothing else.

    Deliberately not a MagicMock: a mock answers every attribute, so a test keeps passing after
    the code starts calling something the real response would not have.
    """

    def __init__(self, payload, status_code=200, text=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text if text is not None else json.dumps(payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code}", response=self)

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _KeySet:
    """A PyJWKClient that resolves against a key set already in memory.

    PyJWKClient fetches jwks_uri with urllib rather than requests, so faking requests.get leaves
    it reaching the network. That mattered more than it sounds: with only requests faked, the
    "token signed by the wrong key is refused" test passed because the *fetch* failed, which is
    a test that would keep passing after signature checking was removed entirely.
    """

    def __init__(self, jwks):
        self._set = jwt.PyJWKSet.from_dict(jwks)

    def get_signing_key_from_jwt(self, token):
        kid = jwt.get_unverified_header(token)["kid"]
        for key in self._set.keys:
            if key.key_id == kid:
                return key
        raise jwt.PyJWKClientError(f"no key {kid}")


def _serve(monkeypatch, oidc, discovery_document, jwks):
    """Point discovery and key resolution at an in-memory provider."""
    def fake_get(url, **kwargs):
        if url.endswith("/.well-known/openid-configuration"):
            return _Response(discovery_document)
        if url.endswith("/jwks"):
            return _Response(jwks)
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr(oidc.requests, "get", fake_get)
    monkeypatch.setattr(oidc, "_jwks_client", lambda uri: _KeySet(jwks))


def _id_token(signing_key, **overrides):
    now = int(time.time())
    claims = {
        "iss": ISSUER, "aud": CLIENT_ID, "sub": "rkoike",
        "email": "rkoike@nvidia.com", "name": "Rafael Koike",
        "groups": ["nvis-ova"], "nonce": "the-nonce",
        "iat": now, "exp": now + 300,
    }
    claims.update(overrides)
    return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "test-key-1"})


# ── Discovery ────────────────────────────────────────────────────────────────────────────────


def test_discovery_requires_an_issuer(oidc, monkeypatch):
    monkeypatch.delenv("NVSF_OIDC_ISSUER", raising=False)
    with pytest.raises(oidc.OidcError, match="NVSF_OIDC_ISSUER"):
        oidc.discovery()


def test_discovery_rejects_a_document_naming_a_different_issuer(
    oidc, monkeypatch, discovery_document, jwks
):
    """The IdP mix-up check.

    If the document at issuer A can claim to be issuer B, an attacker who controls any URL we can
    be pointed at can serve a document naming the real issuer, and tokens get validated against
    endpoints they choose.
    """
    discovery_document["issuer"] = "https://attacker.example.com"
    _serve(monkeypatch, oidc, discovery_document, jwks)

    with pytest.raises(oidc.OidcError, match="issuer"):
        oidc.discovery()


def test_discovery_rejects_a_document_missing_endpoints(
    oidc, monkeypatch, discovery_document, jwks
):
    """Failing here names the problem. Failing later is a KeyError in a request handler."""
    del discovery_document["jwks_uri"]
    _serve(monkeypatch, oidc, discovery_document, jwks)

    with pytest.raises(oidc.OidcError):
        oidc.discovery()


def test_discovery_is_cached(oidc, monkeypatch, discovery_document, jwks):
    """One HTTP round trip per sign-in is a round trip on the critical path of every sign-in."""
    calls = []

    def counting_get(url, **kwargs):
        calls.append(url)
        return _Response(discovery_document if "openid-configuration" in url else jwks)

    monkeypatch.setattr(oidc.requests, "get", counting_get)

    oidc.discovery()
    oidc.discovery()

    assert len(calls) == 1


def test_a_provider_that_is_down_produces_a_usable_error(oidc, monkeypatch):
    import requests

    def refuse(url, **kwargs):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(oidc.requests, "get", refuse)

    with pytest.raises(oidc.OidcError):
        oidc.discovery()


# ── Authorization request ────────────────────────────────────────────────────────────────────


def test_begin_produces_a_pkce_challenge_and_unguessable_state(
    oidc, monkeypatch, discovery_document, jwks
):
    """PKCE is what makes a stolen authorization code useless without the verifier."""
    from urllib.parse import parse_qs, urlparse

    _serve(monkeypatch, oidc, discovery_document, jwks)

    flow = oidc.begin()
    query = parse_qs(urlparse(flow.authorization_url).query)

    assert query["response_type"] == ["code"]
    assert query["client_id"] == [CLIENT_ID]
    assert query["code_challenge_method"] == ["S256"], "plain would defeat the purpose"
    assert query["code_challenge"][0] != flow.code_verifier, "the challenge is a hash, not the key"
    assert query["state"] == [flow.state]
    assert query["nonce"] == [flow.nonce]
    # 128 bits of entropy, roughly. Short enough to guess is short enough to forge a callback.
    assert len(flow.state) >= 20
    assert len(flow.code_verifier) >= 43, "RFC 7636 sets the floor at 43 characters"


def test_two_flows_never_share_a_state(oidc, monkeypatch, discovery_document, jwks):
    _serve(monkeypatch, oidc, discovery_document, jwks)
    assert oidc.begin().state != oidc.begin().state


def test_the_redirect_uri_is_derived_from_the_public_url(oidc):
    assert oidc.redirect_uri() == "https://factory.test.nvidia.com/api/auth/callback"


def test_the_redirect_uri_requires_a_public_url(oidc, monkeypatch):
    """Guessing it from the request host is how an open redirect gets built by accident."""
    monkeypatch.delenv("NVSF_PUBLIC_URL", raising=False)
    with pytest.raises(oidc.OidcError, match="NVSF_PUBLIC_URL"):
        oidc.redirect_uri()


# ── Token exchange ───────────────────────────────────────────────────────────────────────────


def test_exchange_sends_the_verifier_and_returns_the_token_set(
    oidc, monkeypatch, discovery_document, jwks, signing_key
):
    _serve(monkeypatch, oidc, discovery_document, jwks)
    sent = {}

    def fake_post(url, **kwargs):
        sent.update(kwargs.get("data") or {})
        return _Response({"id_token": _id_token(signing_key), "access_token": "at"})

    monkeypatch.setattr(oidc.requests, "post", fake_post)

    result = oidc.exchange("the-code", "the-verifier")

    assert sent["grant_type"] == "authorization_code"
    assert sent["code"] == "the-code"
    assert sent["code_verifier"] == "the-verifier"
    assert "id_token" in result


def test_exchange_rejects_a_response_with_no_id_token(
    oidc, monkeypatch, discovery_document, jwks
):
    """An access token alone says nothing about who the user is."""
    _serve(monkeypatch, oidc, discovery_document, jwks)
    monkeypatch.setattr(oidc.requests, "post", lambda url, **kw: _Response({"access_token": "at"}))

    with pytest.raises(oidc.OidcError):
        oidc.exchange("code", "verifier")


def test_exchange_reports_a_rejected_code(oidc, monkeypatch, discovery_document, jwks):
    _serve(monkeypatch, oidc, discovery_document, jwks)
    monkeypatch.setattr(
        oidc.requests, "post",
        lambda url, **kw: _Response({"error": "invalid_grant"}, status_code=400),
    )

    with pytest.raises(oidc.OidcError):
        oidc.exchange("used-already", "verifier")


# ── Token verification: the checks that decide who you are ───────────────────────────────────


def test_a_valid_token_yields_the_identity(oidc, monkeypatch, discovery_document, jwks, signing_key):
    _serve(monkeypatch, oidc, discovery_document, jwks)

    identity = oidc.verify_id_token(_id_token(signing_key), nonce="the-nonce")

    assert identity.subject == "rkoike"
    assert identity.email == "rkoike@nvidia.com"
    assert "nvis-ova" in identity.groups


def test_a_token_signed_by_the_wrong_key_is_refused(
    oidc, monkeypatch, discovery_document, jwks
):
    """Signature verification, which is the whole basis for believing any of the claims."""
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _serve(monkeypatch, oidc, discovery_document, jwks)

    with pytest.raises(oidc.OidcError):
        oidc.verify_id_token(_id_token(other), nonce="the-nonce")


def test_an_expired_token_is_refused(oidc, monkeypatch, discovery_document, jwks, signing_key):
    now = int(time.time())
    _serve(monkeypatch, oidc, discovery_document, jwks)

    with pytest.raises(oidc.OidcError):
        oidc.verify_id_token(
            _id_token(signing_key, exp=now - 60, iat=now - 3600), nonce="the-nonce"
        )


def test_a_token_for_another_client_is_refused(
    oidc, monkeypatch, discovery_document, jwks, signing_key
):
    """Same provider, different application. Without the audience check, any other client of the
    same IdP can mint a token that signs its users into this one."""
    _serve(monkeypatch, oidc, discovery_document, jwks)

    with pytest.raises(oidc.OidcError):
        oidc.verify_id_token(_id_token(signing_key, aud="some-other-app"), nonce="the-nonce")


def test_a_replayed_token_is_refused(oidc, monkeypatch, discovery_document, jwks, signing_key):
    """The nonce binds a token to the sign-in that asked for it. Without this check a token
    captured once is reusable until it expires."""
    _serve(monkeypatch, oidc, discovery_document, jwks)

    with pytest.raises(oidc.OidcError, match="nonce"):
        oidc.verify_id_token(_id_token(signing_key, nonce="a-different-nonce"), nonce="the-nonce")


def test_a_token_with_no_nonce_is_refused(
    oidc, monkeypatch, discovery_document, jwks, signing_key
):
    """A provider that drops the claim must not silently downgrade us to no replay protection."""
    _serve(monkeypatch, oidc, discovery_document, jwks)
    token = _id_token(signing_key)
    stripped = jwt.encode(
        {k: v for k, v in jwt.decode(token, options={"verify_signature": False}).items()
         if k != "nonce"},
        signing_key, algorithm="RS256", headers={"kid": "test-key-1"},
    )

    with pytest.raises(oidc.OidcError):
        oidc.verify_id_token(stripped, nonce="the-nonce")


def test_the_groups_claim_name_is_configurable(
    oidc, monkeypatch, discovery_document, jwks, signing_key
):
    """Providers disagree about this one, and it decides what roles a user gets."""
    monkeypatch.setenv("NVSF_OIDC_GROUPS_CLAIM", "memberOf")
    _serve(monkeypatch, oidc, discovery_document, jwks)

    identity = oidc.verify_id_token(
        _id_token(signing_key, memberOf=["nvis-aic"]), nonce="the-nonce"
    )

    assert "nvis-aic" in identity.groups


# ── Sign-out ─────────────────────────────────────────────────────────────────────────────────


def test_end_session_url_is_built_from_discovery(oidc, monkeypatch, discovery_document, jwks):
    _serve(monkeypatch, oidc, discovery_document, jwks)
    assert oidc.end_session_url("a-token").startswith(f"{ISSUER}/logout")


def test_end_session_url_is_none_when_the_provider_does_not_offer_one(
    oidc, monkeypatch, discovery_document, jwks
):
    """Sign-out must still clear our own session. Returning None lets the caller say so honestly
    rather than claiming the provider session ended when it did not."""
    del discovery_document["end_session_endpoint"]
    _serve(monkeypatch, oidc, discovery_document, jwks)

    assert oidc.end_session_url("a-token") is None


def test_end_session_url_is_none_when_the_provider_is_unreachable(oidc, monkeypatch):
    """Sign-out is the one operation that must never fail: a user trying to sign out of a broken
    deployment is exactly who most needs it to work."""
    import requests

    def refuse(url, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(oidc.requests, "get", refuse)

    assert oidc.end_session_url("a-token") is None
