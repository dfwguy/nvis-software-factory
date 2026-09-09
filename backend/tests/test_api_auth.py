# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The sign-in endpoints, which are the only ones reachable without a session.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Everything else in the API is behind the authorization hook. These four routes are on the bypass
list because they have to be -- you cannot present a session to the endpoint that issues one --
which makes them the entire unauthenticated attack surface of the application, and worth testing
in proportion to that rather than in proportion to their size.

The callback is where an attacker-supplied value first reaches server-side logic, so most of what
follows is about what it refuses.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def oidc_configured(monkeypatch):
    """Turn the mock provider off and point at an OIDC provider that is not reachable.

    Unreachable on purpose for most of these: what is under test is the endpoint's behaviour, and
    a test that needs a real IdP is a test that does not run.
    """
    monkeypatch.setenv("NVSF_OIDC_MOCK", "false")
    monkeypatch.setenv("NVSF_OIDC_ISSUER", "https://idp.invalid.nvidia.com")
    monkeypatch.setenv("NVSF_OIDC_CLIENT_ID", "nvis-software-factory")

    from authn import oidc

    oidc.reset_caches()
    yield
    oidc.reset_caches()


# ── /api/auth/me ─────────────────────────────────────────────────────────────────────────────


def test_me_tells_an_anonymous_caller_where_to_sign_in(anonymous_client):
    """A 401 with no instructions makes every client invent its own sign-in URL."""
    response = anonymous_client.get("/api/auth/me")

    assert response.status_code == 401
    body = response.get_json()
    assert body["reason"] == "unauthenticated"
    assert body["login_url"] == "/api/auth/login"


def test_me_returns_the_user_and_what_they_may_do(app_client):
    """Permissions come from the server. A UI that decides for itself which buttons a role gets
    will disagree with the server the first time the policy changes."""
    body = app_client.get("/api/auth/me").get_json()

    assert body["user"]["subject"]
    assert isinstance(body["permissions"], list)
    assert body["permissions"], "an authenticated user with no permissions cannot do anything"


def test_me_marks_a_mock_session_as_mock(app_client):
    """So the UI can display the banner. A developer who forgets which mode they are in files
    bugs about permissions that were never real."""
    assert app_client.get("/api/auth/me").get_json()["user"]["is_mock"] is True


def test_me_does_not_return_tokens(app_client):
    """The ID token is not needed by the browser and is a bearer credential for the provider."""
    body = app_client.get("/api/auth/me").get_data(as_text=True)

    for leak in ("id_token", "access_token", "refresh_token", "code_verifier"):
        assert leak not in body, f"{leak} was returned to the browser"


# ── /api/auth/login ──────────────────────────────────────────────────────────────────────────


def test_login_redirects_straight_through_when_the_mock_is_on(app_client):
    """There is no provider to visit. Redirecting to the app is what makes the mock usable."""
    response = app_client.get("/api/auth/login")

    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_login_reports_an_unreachable_provider_as_503(anonymous_client, oidc_configured):
    """Not a 500. The application is fine; the thing it depends on is not, and the distinction
    decides who gets paged."""
    response = anonymous_client.get("/api/auth/login")

    assert response.status_code == 503
    body = response.get_json()
    assert body["reason"] == "oidc_unavailable"
    assert body.get("hint"), "a sign-in failure with no hint is unactionable"


# ── /api/auth/callback ───────────────────────────────────────────────────────────────────────


def test_a_callback_with_no_code_is_a_400(anonymous_client, oidc_configured):
    assert anonymous_client.get("/api/auth/callback").status_code == 400


def test_a_callback_reporting_a_provider_error_is_a_401(anonymous_client, oidc_configured):
    """access_denied is the normal shape of "the user pressed cancel", and it must not look like
    a bug in this application."""
    response = anonymous_client.get(
        "/api/auth/callback?error=access_denied&error_description=User+declined"
    )

    assert response.status_code == 401
    assert response.get_json()["reason"] == "provider_error"


def test_a_callback_with_no_matching_flow_is_refused(anonymous_client, oidc_configured):
    """The CSRF check. A code and state arriving in a browser that never started a sign-in is
    someone else's flow being completed in this user's session."""
    response = anonymous_client.get("/api/auth/callback?code=abc&state=never-issued")

    assert response.status_code == 401
    assert response.get_json()["reason"] == "sign_in_failed"


def test_a_failed_callback_does_not_echo_the_provider_message_verbatim(
    anonymous_client, oidc_configured
):
    """error_description is attacker-controllable: the URL is one an attacker can send someone.
    Reflecting it unchanged makes this endpoint a way to put chosen text on a trusted origin."""
    response = anonymous_client.get(
        "/api/auth/callback?error=access_denied"
        "&error_description=<script>alert(document.domain)</script>"
    )

    assert b"<script>" not in response.get_data(), "the provider message was reflected as HTML"


def test_a_failed_callback_establishes_no_session(anonymous_client, oidc_configured):
    anonymous_client.get("/api/auth/callback?code=abc&state=never-issued")

    assert anonymous_client.get("/api/auth/me").status_code == 401


# ── /api/auth/logout ─────────────────────────────────────────────────────────────────────────


def test_logout_reports_whether_the_provider_session_ended(app_client):
    """Signing out here and staying signed in at the IdP means the next sign-in is silent, which
    surprises people on shared machines. Saying so is the honest minimum."""
    body = app_client.post("/api/auth/logout").get_json()

    assert body["signed_out"] is True
    assert "provider_session_ended" in body


def test_logout_works_for_a_caller_with_no_session(anonymous_client):
    """Idempotent. Someone whose session already expired is exactly who is most likely to press
    sign out, and an error there is confusing and pointless."""
    assert anonymous_client.post("/api/auth/logout").status_code == 200


def test_logout_survives_an_unreachable_provider(anonymous_client, oidc_configured):
    """Sign-out is the one operation that must never depend on something else being up."""
    response = anonymous_client.post("/api/auth/logout")

    assert response.status_code == 200
    assert response.get_json()["provider_session_ended"] is False
