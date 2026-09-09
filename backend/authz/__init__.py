# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Default-deny authorization: an action vocabulary and a pure decision function.

Author: Rafael M. Koike & Cursor Agent ("Ada")

    from authz import action, Role

    @bp.route("/", methods=["POST"])
    @action("assessment:create")
    def create():
        ...

A route without a decorator is denied. See ``policy.py`` for why enforcement lives in the request
hook rather than in the decorator.
"""

from __future__ import annotations

from .policy import (
    ANONYMOUS,
    Decision,
    Principal,
    action,
    action_of,
    authorized_actions,
    decide,
    roles_from_groups,
)
from .resources import ACTIONS, Action, Role

__all__ = [
    "ACTIONS",
    "ANONYMOUS",
    "Action",
    "Decision",
    "Principal",
    "Role",
    "action",
    "action_of",
    "authorized_actions",
    "decide",
    "roles_from_groups",
]
