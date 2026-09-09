# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Default-deny authorization.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Data-security criterion S3. Three ways to be denied, and all three are the default:

* a route with no ``@action`` decorator -- ``authorized_actions`` returns nothing for it, and the
  request hook rejects it;
* an action name not declared in ``resources.py``;
* a principal whose roles do not include one the action allows.

The decision function is pure: principal in, decision out, no Flask, no globals. That is what
makes the policy exhaustively testable, and there is a test that walks every registered route and
asserts it names a declared action -- so an endpoint added without one fails the suite instead of
shipping open.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, TypeVar

from . import resources
from .resources import Action, Role, effective_roles

_logger = logging.getLogger("nvsf.authz")

F = TypeVar("F", bound=Callable[..., Any])

#: Attribute the decorator writes onto a view function, and the request hook reads back.
ACTION_ATTR = "_nvsf_action"


@dataclass(frozen=True)
class Principal:
    """Who is making a request.

    ``groups`` is kept alongside ``roles`` so a denial can say *why* -- "you are in nvis-xyz, which
    maps to no role" is actionable, and "denied" is not.
    """

    subject: str
    email: str | None = None
    display_name: str | None = None
    groups: frozenset[str] = field(default_factory=frozenset)
    roles: frozenset[Role] = field(default_factory=frozenset)
    #: True for the loopback-only development principal. Recorded in the audit trail so a
    #: development-shaped event is never mistaken for a real one.
    is_mock: bool = False

    @property
    def effective(self) -> frozenset[Role]:
        return effective_roles(set(self.roles))

    def to_json(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "email": self.email,
            "display_name": self.display_name,
            "groups": sorted(self.groups),
            "roles": sorted(str(r) for r in self.roles),
            "effective_roles": sorted(str(r) for r in self.effective),
            "is_mock": self.is_mock,
        }


@dataclass(frozen=True)
class Decision:
    allowed: bool
    action: str
    reason: str

    def __bool__(self) -> bool:
        return self.allowed


#: The one anonymous principal. Holds no roles, so it is denied everything by the same code path
#: an authenticated-but-unauthorized user takes -- there is no separate anonymous branch to get
#: wrong.
ANONYMOUS = Principal(subject="anonymous")


def decide(principal: Principal | None, action_name: str | None) -> Decision:
    """The whole policy. Pure function, no Flask."""
    if not action_name:
        return Decision(
            False, "<none>",
            "the endpoint declares no action, so it is denied. Add @action(...) to the view.",
        )

    action: Action | None = resources.get(action_name)
    if action is None:
        return Decision(
            False, action_name,
            f"'{action_name}' is not a declared action. Add it to authz/resources.py.",
        )

    if principal is None or principal is ANONYMOUS or not principal.subject or \
            principal.subject == "anonymous":
        return Decision(False, action_name, "not authenticated")

    held = principal.effective
    if held & action.allowed:
        return Decision(True, action_name, "allowed")

    if not principal.roles:
        return Decision(
            False, action_name,
            f"no role. Your groups ({', '.join(sorted(principal.groups)) or 'none'}) map to no "
            "role in this deployment; ask an administrator to add a mapping.",
        )
    return Decision(
        False, action_name,
        f"role(s) {', '.join(sorted(str(r) for r in principal.roles))} cannot perform "
        f"'{action_name}', which requires one of "
        f"{', '.join(sorted(str(r) for r in action.allowed))}",
    )


def action(name: str) -> Callable[[F], F]:
    """Declare what a view does. Enforcement happens in the request hook.

    The decorator only records the name; it does not check anything itself. That is deliberate:
    a decorator that enforced would be bypassed by any route that forgot it, whereas a hook that
    reads the attribute sees the absence and denies.
    """
    if name not in resources.ACTIONS:
        # Fails at import, so a typo cannot become a permanently denied endpoint that somebody
        # "fixes" later by loosening the policy.
        raise RuntimeError(
            f"@action('{name}') is not a declared action. Add it to authz/resources.py first — "
            f"known actions: {', '.join(resources.names())}"
        )

    def decorator(view: F) -> F:
        @wraps(view)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return view(*args, **kwargs)

        setattr(wrapper, ACTION_ATTR, name)
        return wrapper  # type: ignore[return-value]

    return decorator


def action_of(view: Callable[..., Any] | None) -> str | None:
    """The action a view declares, or None."""
    return getattr(view, ACTION_ATTR, None) if view else None


def authorized_actions(principal: Principal) -> list[str]:
    """Every action this principal may perform. Sent to the frontend so the UI can hide controls
    the user cannot use -- which is a usability measure, not a security one. The server decides."""
    return sorted(
        name for name, act in resources.ACTIONS.items()
        if principal.effective & act.allowed
    )


def roles_from_groups(
    groups: set[str], admin_groups: set[str], role_map: dict[str, str]
) -> frozenset[Role]:
    """Map IdP group membership onto roles.

    An unmapped group grants ``viewer`` and nothing more, so a new group appearing in the identity
    provider cannot silently confer access. An unknown role *name* in the mapping is ignored with a
    warning rather than crashing: a typo in configuration should not lock everyone out, but it must
    not grant anything either.
    """
    roles: set[Role] = set()
    for group in groups:
        if group in admin_groups:
            roles.add(Role.ADMIN)
            continue
        mapped = role_map.get(group)
        if mapped is None:
            continue
        try:
            roles.add(Role(mapped))
        except ValueError:
            _logger.warning(
                "authz: NVSF_OIDC_ROLE_MAP maps group %r to unknown role %r; ignoring. "
                "Valid roles: %s",
                group, mapped, ", ".join(str(r) for r in Role),
            )
    if not roles:
        roles.add(Role.VIEWER)
    return frozenset(roles)
