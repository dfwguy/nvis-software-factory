# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Composition root.

Author: Rafael M. Koike & Cursor Agent ("Ada")

This file wires the application together and holds no domain logic. It keeps three routes, all of
them static-asset fallbacks. **Endpoints go in ``backend/api/``**, which registers itself -- if you
are editing this file to add a route, something has gone wrong.

ORDER IS LOad-BEARING
----------------------
1. ``config_launch`` materializes ``factory.toml`` into the environment. This must happen before
   the first import of any module that reads configuration, because a module that snapshots
   ``os.environ`` at import time would otherwise capture the state from before the file applied.
2. ``logging_config`` installs handlers and the redaction filter, before anything can log a
   credential through the root logger's default handler.
3. ``startup_gate`` refuses to continue in a configuration that cannot work.
4. Everything else imports normally.

Steps 1 and 2 are why the imports below are not all at the top of the file, and why ruff's E402 is
disabled for this file in ruff.toml.
"""

from __future__ import annotations

import sys
from pathlib import Path

# backend/ is a flat module namespace: modules import each other as top-level names. Under gunicorn
# the working directory is not guaranteed, so put this directory on the path explicitly rather than
# relying on how the process was launched.
_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import config_launch

_applied_from_file = config_launch.load_or_exit()

import logging_config

logging_config.configure()

import logging

_logger = logging.getLogger("nvsf.app")
if _applied_from_file:
    _logger.info("config: applied %d setting(s) from factory.toml", len(_applied_from_file))

import startup_gate

try:
    startup_gate.prepare()
except startup_gate.StartupRefused as exc:
    # No traceback: nothing has started, so the stack says nothing the operator needs. The message
    # lists every problem at once.
    print(f"\nnvis-software-factory: {exc}\n", file=sys.stderr)
    raise SystemExit(78) from exc  # EX_CONFIG

import atexit

import api
import paths
import security_headers
import settings
from audit import request_hook
from authn import session as authn_session
from authz import action
from factory import runner
from flask import Flask, Response, jsonify, send_from_directory
from flask_compress import Compress
from store import migrations

app = Flask(
    __name__,
    static_folder=str(paths.REPO_ROOT / "static"),
    static_url_path="/static",
)

# The assessment bundle and the contract bundle are both large JSON payloads, frequently fetched
# over an SSH tunnel. Compression is a real win here rather than a micro-optimization.
Compress(app)

# A collection route is declared as "/" inside its blueprint, so its rule is "/api/assessments/".
# With strict slashes, "/api/assessments" is a 308 redirect -- and a redirect has no endpoint, so
# the authorization hook sees a view declaring no action and denies it. The caller gets a 403 for
# a URL that exists.
#
# That URL is not hypothetical: it is what the published OpenAPI document advertises, and
# therefore what every generated client requests. Serving both spellings is the fix; making the
# contract describe the trailing slash would be documenting a quirk instead of removing it.
app.url_map.strict_slashes = False

app.config.update(
    SECRET_KEY=settings.get_str("NVSF_SESSION_SECRET"),
    SESSION_COOKIE_NAME="nvsf_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Secure in production; a Secure cookie over plaintext http is simply never stored, which
    # presents as "sign-in silently does nothing".
    SESSION_COOKIE_SECURE=settings.is_production(),
    PERMANENT_SESSION_LIFETIME=settings.get_int("NVSF_SESSION_TTL_HOURS", 12) * 3600,
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
    JSON_SORT_KEYS=False,
)

# Schema is applied at startup, not by hand. Durability criterion D4: a migration that an operator
# has to remember to run is a migration that gets skipped.
migrations.apply()

security_headers.install(app)
request_hook.install(app)
authn_session.install(app)

_registered = api.register(app)

# ── Background work ──────────────────────────────────────────────────────────────────────────
#
# Assessments run in a small thread pool rather than the request thread. Orphan recovery must
# happen after the schema is applied and before the first request is served: a container that
# stopped mid-run left an assessment in a non-terminal state with no thread behind it, and left
# alone it shows as running forever, which is the worst of the available outcomes.

runner.start()
_recovered = runner.recover_orphans()
if _recovered:
    _logger.warning(
        "startup: re-queued %d assessment(s) left running by a previous process", len(_recovered),
    )

atexit.register(runner.shutdown)


# ── Static fallbacks ─────────────────────────────────────────────────────────────────────────
#
# The only routes this file owns. Everything else is a blueprint.


@app.route("/docs/", defaults={"filename": "index.html"})
@app.route("/docs/<path:filename>")
@action("docs:read")
def serve_docs(filename: str) -> Response:
    """Sphinx HTML, built by CI and copied into the image.

    Served by the app rather than published separately so the documentation a deployment shows is
    always the documentation that matches the code running there.

    Carries an action like any other route: the authorization hook denies anything that declares
    none, so without this the docs are a 403 for everybody, admins included.
    """
    target = paths.DOCS_DIR
    if not (target / filename).is_file():
        if (target / filename / "index.html").is_file():
            return send_from_directory(target, f"{filename}/index.html")
        if not target.is_dir():
            return Response(
                "Documentation is not built into this image. Run:\n"
                "  sphinx-build -b html docs static/docs\n",
                status=503, mimetype="text/plain",
            )
    return send_from_directory(target, filename)


@app.route("/assets/<path:filename>")
def serve_spa_asset(filename: str) -> Response:
    """Vite's hashed bundle output.

    An explicit 404 rather than the SPA fallback below: a missing hashed asset means a stale
    index.html is referencing a bundle that no longer exists, and answering with HTML turns that
    into an inscrutable JavaScript syntax error instead of a clear 404 in the network tab.
    """
    return send_from_directory(paths.SPA_DIR / "assets", filename)


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_spa(path: str) -> Response:
    """SPA entry point, and the catch-all for client-side routes.

    Guarded so an unmatched ``/api/`` path answers JSON. Without this, a typo'd endpoint returns
    the SPA's index.html with a 200, and the client reports 'unexpected token <' instead of 404.
    """
    if path.startswith("api/"):
        return jsonify({"ok": False, "error": f"no such endpoint: /{path}", "reason": "not_found"}), 404

    candidate = paths.SPA_DIR / path
    if path and candidate.is_file():
        return send_from_directory(paths.SPA_DIR, path)

    index = paths.SPA_DIR / "index.html"
    if not index.is_file():
        return Response(
            "The frontend is not built. From the repository root:\n"
            "  cd frontend && npm ci && npm run build\n",
            status=503, mimetype="text/plain",
        )
    return send_from_directory(paths.SPA_DIR, "index.html")


_logger.info(
    "nvis-software-factory ready — %d api module(s), env=%s, data=%s",
    len(_registered), settings.get_str("NVSF_ENV"), paths.data_dir(),
)
