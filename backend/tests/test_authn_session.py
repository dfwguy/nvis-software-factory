# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The session: what a signed-in user carries between requests, and for how long.

Author: Rafael M. Koike & Cursor Agent ("Ada")

The sign-in flow's state parameter is CSRF protection for the callback, and it only works if the
comparison is exact and single-use. The expiry check matters for a different reason: a session
cookie is a bearer token, and one that outlives its own claim to be valid is a credential with no
revocation story.

The return_to handling gets its own tests because it is the classic open-redirect hole -- a
sign-in link that sends the user to an attacker's page after a genuine authentication is more
convincing than any phishing page, because the authentication really happened.
"""

from __future__ import annotations

import time

import pytest
from flask import Flask


@pytest.fixture
def flask_app():
    """A minimal app, not the real one: this is about session mechanics, not routing."""
    app = Flask(__name__)
    app.config.update(SECRET_KEY="test-secret-not-a-real-one", TESTING=True)
    return app


@pytest.fixture
def session_module(monkeypatch):
    from authn import session as module

    # The mock provider short-circuits current_principal, which would make every test here pass
    # regardless of what the session contains.
    monkeypatch.setenv("NVSF_OIDC_MOCK", "false")
    return module


def _identity(subject="rkoike", groups=("nvis-ova",)):
    from authn.oidc import Identity

    now = int(time.time())
    return Identity(
        subject=subject, email=f"{subject}@nvidia.com", display_name="Rafael Koike",
        groups=frozenset(groups), issued_at=now, expires_at=now + 3600, raw_claims={},
    )


# ── The sign-in flow ─────────────────────────────────────────────────────────────────────────


def test_a_flow_round_trips(flask_app, session_module):
    with flask_app.test_request_context("/"):
        session_module.stash_flow("state-1", "nonce-1", "verifier-1", return_to=None)
        flow = session_module.take_flow("state-1")

    assert flow["nonce"] == "nonce-1"
    assert flow["code_verifier"] == "verifier-1"


def test_a_mismatched_state_is_refused(flask_app, session_module):
    """CSRF on the callback: without this, an attacker completes their own sign-in in the
    victim's browser and the victim is silently operating as the attacker's user."""
    from authn import oidc

    with flask_app.test_request_context("/"), pytest.raises(oidc.OidcError):
        session_module.stash_flow("state-1", "nonce-1", "verifier-1", return_to=None)
        session_module.take_flow("state-2")


def test_a_callback_with_no_flow_in_the_session_is_refused(flask_app, session_module):
    from authn import oidc

    with flask_app.test_request_context("/"), pytest.raises(oidc.OidcError):
        session_module.take_flow("state-1")


def test_a_flow_cannot_be_used_twice(flask_app, session_module):
    """Single-use, and popped before the comparison so a wrong guess burns it too. Otherwise the
    state is an oracle an attacker can retry against."""
    from authn import oidc

    with flask_app.test_request_context("/"):
        session_module.stash_flow("state-1", "nonce-1", "verifier-1", return_to=None)
        session_module.take_flow("state-1")

        with pytest.raises(oidc.OidcError):
            session_module.take_flow("state-1")


# ── return_to, and the open redirect it would otherwise be ───────────────────────────────────


@pytest.mark.parametrize("hostile", [
    "https://attacker.example.com/phish",
    "//attacker.example.com/phish",
    "http://attacker.example.com",
])
def test_an_offsite_return_to_is_discarded(flask_app, session_module, hostile):
    """A real sign-in that ends on someone else's page is a better phish than a fake one."""
    with flask_app.test_request_context("/"):
        session_module.stash_flow("s", "n", "v", return_to=hostile)
        assert session_module.take_return_to() == "/"


def test_a_path_return_to_is_kept(flask_app, session_module):
    """The feature is worth having: a deep link should survive being bounced through sign-in."""
    with flask_app.test_request_context("/"):
        session_module.stash_flow("s", "n", "v", return_to="/assessments/abc123")
        assert session_module.take_return_to() == "/assessments/abc123"


def test_return_to_defaults_to_the_root(flask_app, session_module):
    with flask_app.test_request_context("/"):
        assert session_module.take_return_to() == "/"


# ── Establishing and reading a session ───────────────────────────────────────────────────────


def test_establish_maps_groups_to_roles(flask_app, session_module):
    """The group claim is the only thing standing between a viewer and an admin."""
    with flask_app.test_request_context("/"):
        principal = session_module.establish(_identity(groups=("nvis-ova",)))

    assert principal.subject == "rkoike"
    assert principal.roles, "a known group produced no roles"


def test_establish_clears_whatever_was_there_before(flask_app, session_module):
    """Session fixation: signing in must not inherit state an attacker planted in the cookie."""
    from flask import session as flask_session

    with flask_app.test_request_context("/"):
        flask_session["planted"] = "value"
        session_module.establish(_identity())
        assert "planted" not in flask_session


def test_a_current_principal_is_readable_after_establish(flask_app, session_module):
    with flask_app.test_request_context("/"):
        session_module.establish(_identity())
        principal = session_module.current_principal()

    assert principal is not None
    assert principal.subject == "rkoike"
    assert principal.is_mock is False


def test_no_session_means_no_principal(flask_app, session_module):
    with flask_app.test_request_context("/"):
        assert session_module.current_principal() is None


def test_an_expired_session_is_not_honoured(flask_app, session_module, monkeypatch):
    """A cookie is a bearer token. One that outlives its own expiry claim is a credential nobody
    can revoke."""
    thirty_days_from_now = time.time() + 60 * 60 * 24 * 30

    with flask_app.test_request_context("/"):
        session_module.establish(_identity())
        monkeypatch.setattr(time, "time", lambda: thirty_days_from_now)

        assert session_module.current_principal() is None


def test_an_expired_session_is_cleared_rather_than_left_to_be_retried(
    flask_app, session_module, monkeypatch
):
    from flask import session as flask_session

    thirty_days_from_now = time.time() + 60 * 60 * 24 * 30

    with flask_app.test_request_context("/"):
        session_module.establish(_identity())
        monkeypatch.setattr(time, "time", lambda: thirty_days_from_now)
        session_module.current_principal()

        assert not flask_session.get("user")


def test_clear_signs_the_user_out(flask_app, session_module):
    with flask_app.test_request_context("/"):
        session_module.establish(_identity())
        session_module.clear()

        assert session_module.current_principal() is None


def test_the_mock_provider_overrides_the_session(flask_app, monkeypatch):
    """Stated as a test because it is the behaviour that makes the mock dangerous outside
    development, and the two containments below are what make it safe to ship at all."""
    from authn import session as module

    monkeypatch.setenv("NVSF_OIDC_MOCK", "true")
    monkeypatch.setenv("NVSF_ENV", "development")

    with flask_app.test_request_context("/"):
        principal = module.current_principal()

    assert principal is not None
    assert principal.is_mock is True


def test_the_mock_provider_is_refused_in_production(flask_app, monkeypatch, caplog):
    """The second containment, after the startup gate's loopback check.

    Defence in depth on purpose. The gate catches the configuration at boot; this catches the case
    where the environment changes under a running process, or where something imported this module
    without going through the gate at all. Refusing outright -- nobody can sign in -- rather than
    falling back to the mock, because a fixed admin user is the worst possible degraded mode.
    """
    from authn import session as module

    monkeypatch.setenv("NVSF_OIDC_MOCK", "true")
    monkeypatch.setenv("NVSF_ENV", "production")

    with flask_app.test_request_context("/"):
        assert module.current_principal() is None
