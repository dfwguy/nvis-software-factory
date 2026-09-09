# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Authorization fails closed, in every direction.

Author: Rafael M. Koike & Cursor Agent ("Ada")

The design claim is that forgetting something produces a denial rather than an opening. These
tests are what make that a claim rather than an aspiration -- including
``test_every_route_declares_an_action``, which walks the real app and fails if any endpoint was
added without a policy.
"""

from __future__ import annotations

import pytest
from authz import ANONYMOUS, Principal, Role, decide, roles_from_groups
from authz.policy import action


def _principal(*roles: Role, groups: set[str] | None = None) -> Principal:
    return Principal(
        subject="user@nvidia.com", roles=frozenset(roles),
        groups=frozenset(groups or set()),
    )


def test_no_declared_action_is_denied():
    """A route that forgot its decorator is denied, and the reason names the fix."""
    decision = decide(_principal(Role.ADMIN), None)
    assert not decision
    assert "declares no action" in decision.reason


def test_undeclared_action_name_is_denied():
    decision = decide(_principal(Role.ADMIN), "assessment:sudo")
    assert not decision
    assert "not a declared action" in decision.reason


def test_anonymous_is_denied_even_a_read():
    decision = decide(ANONYMOUS, "assessment:list")
    assert not decision
    assert decision.reason == "not authenticated"


def test_none_principal_is_denied():
    assert not decide(None, "assessment:list")


def test_viewer_can_read_but_not_create():
    viewer = _principal(Role.VIEWER)
    assert decide(viewer, "assessment:list")
    assert decide(viewer, "contract:read")
    assert not decide(viewer, "assessment:create")
    assert not decide(viewer, "repository:add")


def test_member_can_assess_but_not_administer():
    member = _principal(Role.MEMBER)
    assert decide(member, "assessment:create")
    assert decide(member, "repository:add")
    assert not decide(member, "repository:delete")
    assert not decide(member, "diagnostics:read")


def test_admin_inherits_everything():
    admin = _principal(Role.ADMIN)
    from authz import resources

    for name in resources.names():
        assert decide(admin, name), f"admin was denied {name}"


def test_raw_provenance_is_a_narrower_grant_than_reading_an_assessment():
    """The raw model response can contain excerpts of the assessed repository, so reading it is a
    broader grant than reading the conclusions."""
    member = _principal(Role.MEMBER)
    assert decide(member, "assessment:read")
    assert not decide(member, "assessment:provenance")
    assert decide(_principal(Role.OVA), "assessment:provenance")


def test_denial_explains_why_it_was_denied():
    """'Denied' is not actionable. Naming the group that maps to nothing is."""
    unmapped = Principal(subject="new@nvidia.com", groups=frozenset({"nvis-brand-new"}))
    decision = decide(unmapped, "assessment:create")
    assert not decision
    assert "nvis-brand-new" in decision.reason


def test_unmapped_group_grants_viewer_and_nothing_more():
    """A new group appearing in the IdP must not confer access until someone maps it."""
    roles = roles_from_groups({"nvis-unknown-team"}, admin_groups=set(), role_map={})
    assert roles == frozenset({Role.VIEWER})


def test_admin_group_grants_admin():
    roles = roles_from_groups(
        {"sf-admins"}, admin_groups={"sf-admins"}, role_map={},
    )
    assert Role.ADMIN in roles


def test_typo_in_role_map_grants_nothing(caplog):
    """A configuration typo must not lock everyone out, and must not grant anything either."""
    roles = roles_from_groups(
        {"nvis-ova"}, admin_groups=set(), role_map={"nvis-ova": "superuser"},
    )
    assert roles == frozenset({Role.VIEWER})
    assert "unknown role" in caplog.text


def test_role_map_is_applied():
    roles = roles_from_groups(
        {"nvis-ova", "nvis-aic"}, admin_groups=set(),
        role_map={"nvis-ova": "ova", "nvis-aic": "member"},
    )
    assert roles == frozenset({Role.OVA, Role.MEMBER})


def test_decorator_rejects_an_undeclared_action_at_import_time():
    """Fails when the module is imported, so a typo cannot become a permanently dead endpoint that
    somebody later 'fixes' by loosening the policy."""
    with pytest.raises(RuntimeError, match="not a declared action"):
        action("assessment:nonexistent")


def test_decorator_records_the_action_on_the_view():
    from authz import action_of

    @action("assessment:read")
    def view():
        return "ok"

    assert action_of(view) == "assessment:read"
    assert view() == "ok", "the decorator must not change the view's behaviour"


def test_every_route_declares_an_action(app_client):
    """The gate that keeps the whole design honest.

    Walks every registered route in the real application and asserts the one invariant that
    decides whether a route is reachable at all: it either bypasses the authorization hook, or it
    declares an action. A route doing neither is denied to everybody, admins included.

    Asked via ``request_hook.needs_session`` rather than against a hand-kept exemption set. The
    previous version of this test listed ``serve_docs`` as a static fallback that legitimately had
    no action -- but ``/docs`` is not on the bypass list, so it went through the hook and 403'd for
    every user, and this test passed the whole time. An exemption list is a second copy of the
    rule, and the copy is what goes stale.
    """
    import authz
    from audit import request_hook

    app = app_client.application
    undeclared: list[str] = []

    for rule in app.url_map.iter_rules():
        path = str(rule.rule)
        if not request_hook.needs_session(path):
            continue
        if authz.action_of(app.view_functions.get(rule.endpoint)):
            continue
        undeclared.append(f"{rule.endpoint} ({path})")

    assert not undeclared, (
        "these routes are subject to authorization but declare no @action, so they are denied "
        "to everyone:\n  " + "\n  ".join(undeclared)
    )


def test_the_documentation_is_reachable_by_a_viewer(app_client):
    """A regression test for a specific 403.

    Named for the symptom rather than the mechanism, because the mechanism is not what anyone
    reports: they report that the docs link in the sidebar is broken.
    """
    import authz
    from authz import Principal, Role

    app = app_client.application
    view = app.view_functions["serve_docs"]

    assert authz.action_of(view) == "docs:read"
    assert authz.decide(Principal(subject="someone", roles={Role.VIEWER}), "docs:read").allowed


def test_bypass_list_entries_all_resolve(app_client):
    """An entry left behind after a rename would quietly widen the unauthenticated surface."""
    from audit import request_hook

    app = app_client.application
    routes = [str(r.rule) for r in app.url_map.iter_rules()]

    for prefix in request_hook.bypass_prefixes():
        if prefix.startswith(("/static", "/assets")):
            continue
        assert any(r.startswith(prefix) for r in routes), (
            f"bypass prefix {prefix} matches no route; remove it or fix the route"
        )


def test_mutating_actions_are_declared_deliberately():
    """The audit trail records mutations only, so the mutating flag decides what is auditable.
    Anything named create/add/delete/retry/cancel that is not flagged is a mistake."""
    from authz import resources

    verbs = ("create", "add", "delete", "retry", "cancel", "map")
    for name, act in resources.ACTIONS.items():
        looks_mutating = any(name.endswith(f":{v}") for v in verbs)
        assert looks_mutating == act.mutating, (
            f"{name}: mutating={act.mutating} but the verb suggests otherwise"
        )
