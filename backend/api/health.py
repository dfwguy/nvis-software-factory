# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Health, per dependency, with a status code an orchestrator can act on.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Reliability criterion R5, applied to ourselves. A health check that returns 200 unconditionally is
answering a question nobody asked -- "is the process running" is what the process manager already
knows.

THREE ENDPOINTS, THREE DIFFERENT QUESTIONS
-------------------------------------------
``/api/health/live``
    Is the process up? Nothing else. Unauthenticated, on the bypass list, because a container
    healthcheck carries no cookie and an orchestrator that cannot distinguish "unauthenticated"
    from "dead" will restart a healthy container.

``/api/health``
    Are the dependencies healthy? Checks each one and names the unhealthy ones. Returns 503 when a
    *required* dependency is down, so this is the endpoint monitoring should watch.

``/api/health/llm``
    Can we reach the reasoning endpoint? Separated because it is the only check that costs a
    network round trip to a third party, and because it is the one an SA asks about by name when
    an assessment fails.
"""

from __future__ import annotations

import logging

from authz import action
from flask import Blueprint, jsonify

from ._common import ok

_logger = logging.getLogger("nvsf.api.health")

bp = Blueprint("health", __name__)


@bp.route("/live", methods=["GET"])
# No @action: on the bypass list by design. See the module docstring.
def live():
    """Liveness. Deliberately says nothing about the data, so it cannot fail for a reason that a
    restart will not fix."""
    return jsonify({"ok": True, "status": "live"})


@bp.route("/", methods=["GET"])
@action("health:read")
def health():
    """Per-dependency health, with a 503 when a required dependency is unavailable."""
    import settings
    from store import backup, db, migrations

    checks: dict[str, dict[str, object]] = {}
    required_failures: list[str] = []

    # ── Store. Required: without it nothing can be recorded, and this app must not degrade to
    # in-memory operation, which is the exact failure it exists to catch in others.
    try:
        sound, detail = db.integrity_check()
        stats = db.stats()
        checks["store"] = {
            "ok": sound,
            "detail": detail,
            "schema_version": migrations.current_version(),
            "journal_mode": stats["journal_mode"],
            "bytes": stats["bytes"],
        }
        if not sound:
            required_failures.append("store")
    except Exception as exc:  # noqa: BLE001 - a health check must report, never raise
        checks["store"] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
        required_failures.append("store")

    # ── Pending migrations. A schema behind the code is a real problem, not a warning: the code
    # will fail on a column that does not exist, at whichever request needs it first.
    try:
        outstanding = migrations.pending()
        checks["migrations"] = {
            "ok": not outstanding,
            "pending": [f"{m.version:04d}_{m.name}" for m in outstanding],
        }
        if outstanding:
            required_failures.append("migrations")
    except Exception as exc:  # noqa: BLE001
        checks["migrations"] = {"ok": False, "detail": str(exc)}
        required_failures.append("migrations")

    # ── Backups. NOT required: a stale snapshot is a degraded state, not an outage, and taking
    # the service down over it would be a worse outcome than reporting it.
    posture = backup.health()
    checks["backups"] = {
        "ok": bool(posture["configured"]) and not posture["stale"],
        **posture,
    }

    # ── Reasoning endpoint. Configuration only here; reachability is /api/health/llm, which costs
    # a round trip and should not be paid for by every monitoring poll.
    configured = bool(settings.get("NVSF_LLM_BASE_URL") and settings.get("NVSF_LLM_MODEL"))
    checks["llm"] = {
        "ok": configured,
        "configured": configured,
        "model": settings.get_str("NVSF_LLM_MODEL") or None,
        "note": "reachability is checked by /api/health/llm",
    }
    if not configured:
        required_failures.append("llm")

    # ── Identity. Reported so a deployment can see at a glance that it is running on the mock.
    from authn import mock

    checks["identity"] = {
        "ok": True,
        "mode": "mock" if mock.enabled() else "oidc",
        "issuer": settings.get_str("NVSF_OIDC_ISSUER") or None,
    }
    if mock.enabled():
        checks["identity"]["warning"] = (
            "the mock identity provider is active; every request is a fixed development user"
        )

    body = {
        "ok": not required_failures,
        "status": "unhealthy" if required_failures else "healthy",
        "failing": required_failures,
        "checks": checks,
    }
    return jsonify(body), (503 if required_failures else 200)


@bp.route("/llm", methods=["GET"])
@action("health:read")
def llm_health():
    """Probe the reasoning endpoint.

    Returns 503 when unreachable, because that is a real statement about this deployment: no
    assessment can complete. It does not take the app down, though -- the app started fine, and a
    transient upstream outage must not become a crash loop.
    """
    from factory import llm

    result = llm.probe()
    return jsonify({"ok": result["reachable"], **result}), (200 if result["reachable"] else 503)


@bp.route("/standards", methods=["GET"])
@action("health:read")
def standards_health():
    """Which quality baseline this deployment is judging against.

    Worth an endpoint of its own: an assessment's conclusions are only meaningful next to the
    version of ``standards/`` that produced them, and this is how a reader checks.
    """
    from factory import standards

    loaded = standards.load_all()
    return ok(
        version=standards.version(),
        pillars=[
            {"id": p.id, "title": p.title, "severity_ceiling": str(p.severity_ceiling),
             "criteria": len(p.criteria), "detectors": p.detectors}
            for p in loaded
        ],
    )
