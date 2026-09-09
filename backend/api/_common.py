# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Helpers shared by API modules.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Underscore-prefixed so the blueprint loader skips it -- this is a helper module, not a route
surface.
"""

from __future__ import annotations

from typing import Any

from flask import Response, jsonify, request


def ok(**payload: Any) -> Response:
    """Success response. Always carries ``ok: true`` so a client has one thing to branch on."""
    return jsonify({"ok": True, **payload})


def fail(error: str, status: int = 400, reason: str | None = None, **extra: Any) -> tuple[Response, int]:
    """Error response.

    ``error`` is for a human, ``reason`` is a stable token for a client to branch on. Keeping them
    separate means the message can be improved without breaking a caller.
    """
    body: dict[str, Any] = {"ok": False, "error": error}
    if reason:
        body["reason"] = reason
    body.update(extra)
    return jsonify(body), status


def body() -> dict[str, Any]:
    """Parsed JSON body, or an empty dict.

    ``silent=True`` because a malformed body should produce our validation error, naming the field
    that is wrong, rather than Flask's generic 400 HTML page.
    """
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def required(data: dict[str, Any], *names: str) -> list[str]:
    """Names that are absent or empty. Returns all of them, so one round trip fixes the request."""
    return [n for n in names if not data.get(n)]


def paginate(default_limit: int = 50, max_limit: int = 200) -> tuple[int, int]:
    """``(limit, offset)`` from the query string, clamped.

    Clamped rather than validated: a client asking for 10,000 rows gets 200 and a working response.
    Scalability criterion SC5 -- an endpoint that will happily serialize the whole table is fine
    for weeks and then is not.
    """
    try:
        limit = int(request.args.get("limit", default_limit))
    except ValueError:
        limit = default_limit
    try:
        offset = int(request.args.get("offset", 0))
    except ValueError:
        offset = 0
    return max(1, min(limit, max_limit)), max(0, offset)
