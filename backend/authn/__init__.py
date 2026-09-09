# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Authentication. OIDC only -- there is no local password store.

Author: Rafael M. Koike & Cursor Agent ("Ada")

* ``oidc`` -- the relying party: discovery, PKCE, token exchange, ID token validation.
* ``session`` -- what is kept in the signed cookie, and what is deliberately not.
* ``mock`` -- a loopback-only development provider with three independent locks on it.

Authentication answers *who*; ``authz`` answers *may they*. Keeping them apart means the policy is
testable without a token and the token handling is testable without a policy.
"""

from __future__ import annotations

from . import mock, oidc, session

__all__ = ["mock", "oidc", "session"]
