# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Response security headers, applied centrally.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Applied in one ``after_request`` hook rather than per blueprint, for the same reason redaction is a
log filter: a control that depends on every future call site remembering it is not a control.

The CSP is deliberately tight. The SPA is served same-origin from this app and talks only to this
app, so there is no legitimate cross-origin fetch to allow. ``'unsafe-inline'`` appears once, for
styles, because MUI's emotion runtime injects style tags -- scripts do not get it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flask import Flask, Response

_CSP = "; ".join((  # noqa: FLY002 - one directive per line, each with its own rationale
    "default-src 'self'",
    "script-src 'self'",
    # emotion/MUI injects <style> at runtime; there is no nonce path that survives their runtime.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    # Same-origin only. The SPA has no third-party endpoint to reach, so anything else is either a
    # mistake or an exfiltration attempt.
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
))

_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    # The app has no need for any of these, and denying them means a compromised dependency cannot
    # quietly ask for them either.
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "X-Frame-Options": "DENY",
}


def install(app: Flask) -> None:
    """Attach the header hook. Called once from the composition root."""

    @app.after_request
    def _apply(response: Response) -> Response:
        for name, value in _HEADERS.items():
            response.headers.setdefault(name, value)

        # HSTS only over TLS. Sending it on a plaintext development response would pin localhost
        # to https in the browser for a year, which is a genuinely annoying thing to undo.
        from flask import request
        if request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )

        # API responses must not be cached. An assessment result changes as the run progresses, and
        # a cached 'queued' is indistinguishable from a stuck run.
        if request.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")

        return response
