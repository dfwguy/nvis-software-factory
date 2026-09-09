# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The action vocabulary and the roles that may perform each one.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Actions are declared here, in one place, so the answer to "what can this application do, and who
can do it" is a file somebody can read rather than a survey of decorators.

An action a route names but that is not declared here is a **deny**, not an allow, and the test
suite fails on it. That is the whole design: forgetting to declare an action produces a loud
failure during development, never a quietly open endpoint.

ROLES
-----
Coarse on purpose. Fine-grained per-object permissions are a real need in a product with tenants;
this is an internal tool used by a handful of teams, and an authorization model nobody can hold in
their head gets worked around.

``admin``   configuration, deletion, other people's runs.
``ova``     the OVA team: full use of the factory, may edit the contract.
``member``  any other mapped team (aic, ethernet, ib): may assess and read, may not edit contracts.
``viewer``  authenticated but unmapped: read-only. This is what an unrecognized group gets, so a
            new group appearing in the IdP grants nothing until someone maps it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    OVA = "ova"
    MEMBER = "member"
    VIEWER = "viewer"


#: Roles that always inherit another's permissions. Kept explicit rather than as a numeric level,
#: because a level implies a total order that stops being true the moment a role is added for a
#: different axis.
_IMPLIES: dict[Role, frozenset[Role]] = {
    Role.ADMIN: frozenset({Role.ADMIN, Role.OVA, Role.MEMBER, Role.VIEWER}),
    Role.OVA: frozenset({Role.OVA, Role.MEMBER, Role.VIEWER}),
    Role.MEMBER: frozenset({Role.MEMBER, Role.VIEWER}),
    Role.VIEWER: frozenset({Role.VIEWER}),
}


def effective_roles(roles: set[Role]) -> frozenset[Role]:
    """Expand held roles through the implication table."""
    result: set[Role] = set()
    for role in roles:
        result |= _IMPLIES.get(role, frozenset({role}))
    return frozenset(result)


@dataclass(frozen=True)
class Action:
    name: str
    allowed: frozenset[Role]
    description: str
    #: Whether this action changes state. Mutating actions are always audited; reads are not, or
    #: the audit trail becomes a second access log and stops being readable.
    mutating: bool = False


def _action(
    name: str, allowed: set[Role], description: str, mutating: bool = False
) -> Action:
    return Action(name=name, allowed=frozenset(allowed), description=description,
                  mutating=mutating)


_ALL = [
    # ── Repositories and assessments ────────────────────────────────────────────────────────
    _action("repository:list", {Role.VIEWER}, "List registered repositories"),
    _action("repository:read", {Role.VIEWER}, "Read one repository"),
    _action("repository:add", {Role.MEMBER}, "Register a repository for assessment",
            mutating=True),
    _action("repository:delete", {Role.ADMIN},
            "Remove a repository and every assessment of it", mutating=True),

    _action("assessment:list", {Role.VIEWER}, "List assessments"),
    _action("assessment:read", {Role.VIEWER}, "Read an assessment and its findings"),
    _action("assessment:create", {Role.MEMBER}, "Start an assessment run", mutating=True),
    _action("assessment:retry", {Role.MEMBER}, "Retry a failed run from its last complete pass",
            mutating=True),
    _action("assessment:cancel", {Role.MEMBER}, "Cancel a run in flight", mutating=True),
    _action("assessment:delete", {Role.ADMIN}, "Delete an assessment", mutating=True),
    # Separated from assessment:read deliberately. The raw model response can contain excerpts of
    # the assessed repository, so reading it is a broader grant than reading the conclusions.
    _action("assessment:provenance", {Role.OVA},
            "Read the raw model responses and full provenance record for a run"),
    _action("assessment:artifact", {Role.VIEWER}, "Download a rendered assessment document"),

    # ── Contracts ───────────────────────────────────────────────────────────────────────────
    # Contract reads are the product. Any authenticated user gets them, because the entire point
    # is that another team can point an agent at the schema.
    _action("contract:read", {Role.VIEWER}, "Read NRM schemas, crosswalks and the agent pack"),
    _action("contract:validate", {Role.VIEWER}, "Validate a payload against NRM"),
    _action("contract:map", {Role.MEMBER},
            "Ask the model to propose a crosswalk for a sample export", mutating=True),

    # ── Operations ──────────────────────────────────────────────────────────────────────────
    _action("health:read", {Role.VIEWER}, "Read health and dependency status"),
    _action("diagnostics:read", {Role.ADMIN},
            "Read resolved configuration and store diagnostics"),
    _action("backup:create", {Role.ADMIN}, "Take a database snapshot on demand", mutating=True),
    _action("audit:read", {Role.ADMIN}, "Read the audit trail"),
]

ACTIONS: dict[str, Action] = {a.name: a for a in _ALL}


def get(name: str) -> Action | None:
    return ACTIONS.get(name)


def names() -> list[str]:
    return sorted(ACTIONS)


def mutating_names() -> list[str]:
    return sorted(name for name, action in ACTIONS.items() if action.mutating)
