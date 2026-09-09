# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Per-domain API modules, discovered and registered automatically.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Adding an endpoint should not mean editing a file someone else is editing. Drop a module in this
package and it registers itself -- ``app.py`` is not edited, and neither is this file. If you find
yourself editing the composition root to add a route, something has gone wrong.

One module per DOMAIN, not per route. A domain is a set of routes that share helpers: if your new
endpoint's helpers already live in ``assessments.py``, it belongs there.

A module qualifies by exposing either of:

``bp``
    A ``flask.Blueprint``. If it declares its own ``url_prefix`` that is honoured; otherwise the
    prefix comes from the filename, so ``contract_validate.py`` serves ``/api/contract-validate``.
    ``url_prefix=""`` means "my routes already carry their full paths".

``install(app)``
    An escape hatch for what Flask routing cannot express -- WSGI middleware, for instance.

Deliberately strict in both directions:

* imports are **not** wrapped in ``try``. A module that fails to import takes startup down and
  names itself. A lazy import inside a ``try`` that swallows a missing dependency produces a
  feature that silently does nothing, which is the worst available outcome.
* a module exposing neither ``bp`` nor ``install`` is an error, not something to skip quietly.
  Shared helpers belong in an underscore-prefixed module, which the loader ignores.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flask import Flask

_logger = logging.getLogger("nvsf.api")


def module_names() -> list[str]:
    """Every registrable module in this package, in a stable order.

    Sorted so registration order does not depend on filesystem iteration order, and
    underscore-prefixed modules are skipped so the package can hold helpers of its own.
    """
    return sorted(
        info.name
        for info in pkgutil.iter_modules(__path__)
        if not info.name.startswith("_")
    )


def default_prefix(module_name: str) -> str:
    """URL prefix implied by a filename: ``contract_validate`` -> ``/api/contract-validate``."""
    return f"/api/{module_name.replace('_', '-')}"


def register(app: Flask) -> list[str]:
    """Register every API module on *app*. Returns what was registered, for logging and tests."""
    registered: list[str] = []
    for name in module_names():
        module = importlib.import_module(f"{__name__}.{name}")
        bp = getattr(module, "bp", None)
        install = getattr(module, "install", None)

        if bp is None and install is None:
            raise RuntimeError(
                f"backend/api/{name}.py exposes neither 'bp' nor 'install(app)'. "
                "Give it a Blueprint, or rename it with a leading underscore if it is a helper."
            )

        if bp is not None:
            if bp.url_prefix is None:
                app.register_blueprint(bp, url_prefix=default_prefix(name))
            else:
                app.register_blueprint(bp)
            # "" is a real answer ("my routes carry full paths"), not a missing one.
            where = (
                default_prefix(name) if bp.url_prefix is None
                else (bp.url_prefix or "full paths")
            )
            registered.append(f"{name} -> {where}")

        if install is not None:
            install(app)
            registered.append(f"{name} -> install()")

    _logger.info("api: registered %d module(s): %s", len(registered), ", ".join(registered))
    return registered
