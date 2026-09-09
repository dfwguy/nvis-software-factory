# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""A fake identity provider for local development, with three locks on it.

Author: Rafael M. Koike & Cursor Agent ("Ada")

This module authenticates nobody. It hands out an admin session to whoever asks. That is exactly
what you want while building a feature and exactly what must never reach a deployment, so it is
gated three independent ways -- one is not enough, because each can plausibly be satisfied by
accident:

1. ``NVSF_OIDC_MOCK`` must be on. Explicit opt-in.
2. ``NVSF_ENV`` must be ``development``. But a ``.env`` gets copied to a VM with everything in it,
   so this alone is weak.
3. ``NVSF_BIND_ADDR`` must be loopback. But a loopback bind can sit behind a reverse proxy, so
   this alone is weak too.

All three are checked here *and* at startup, where failing the check exits the process rather than
logging a warning. Duplicated deliberately: the startup check is what an operator sees, and this
one is what protects a running process if configuration is somehow reloaded.

The principal it issues is marked ``is_mock=True``, which is carried into every audit event. An
investigation must never confuse a development-shaped event with a real one.
"""

from __future__ import annotations

import ipaddress
import logging

import settings
from authz import Principal, Role

_logger = logging.getLogger("nvsf.authn.mock")

_MOCK_SUBJECT = "dev-mock-user"


def _loopback(addr: str) -> bool:
    if addr in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False


def enabled() -> bool:
    """All three locks open. Any single one closed means no."""
    if not settings.get_bool("NVSF_OIDC_MOCK", False):
        return False
    if settings.is_production():
        _logger.error(
            "authn: NVSF_OIDC_MOCK is set but NVSF_ENV=production — refusing to use the mock "
            "identity provider. Nobody can sign in until OIDC is configured."
        )
        return False
    if not _loopback(settings.get_str("NVSF_BIND_ADDR", "127.0.0.1")):
        _logger.error(
            "authn: NVSF_OIDC_MOCK is set but NVSF_BIND_ADDR=%s is not loopback — refusing. The "
            "mock provider must not be reachable from another host.",
            settings.get_str("NVSF_BIND_ADDR"),
        )
        return False
    return True


def principal() -> Principal:
    """The development principal. Admin, so every feature is reachable while building it."""
    return Principal(
        subject=_MOCK_SUBJECT,
        email="dev@localhost",
        display_name="Development User (mock identity)",
        groups=frozenset({"nvis-ova", "nvis-software-factory-admins"}),
        roles=frozenset({Role.ADMIN}),
        is_mock=True,
    )
