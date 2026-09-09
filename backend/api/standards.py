# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The quality baseline: /api/standards

Author: Rafael M. Koike & Cursor Agent ("Ada")

The golden path, served from the same ``standards/`` files the prompts are built from. There is no
second copy of "what good looks like" for the website to render, because a second copy is how an
assessment ends up citing a criterion the published baseline does not contain.

Readable by anyone with a session, including roles that cannot start an assessment: an SA who wants
to know what will be checked before submitting their repository should not need permission to find
out.
"""

from __future__ import annotations

import logging

from authz import action
from factory import standards
from flask import Blueprint

from ._common import fail, ok

bp = Blueprint("standards", __name__)

_logger = logging.getLogger("nvsf.api.standards")


def _pillar_json(pillar: standards.Pillar, include_body: bool = False) -> dict:
    payload = {
        "id": pillar.id,
        "title": pillar.title,
        "order": pillar.order,
        "severity_ceiling": str(pillar.severity_ceiling),
        "detectors": list(pillar.detectors),
        "criteria": [
            {
                "id": criterion.id,
                "title": criterion.title,
                "detector": criterion.detector,
                # A criterion with no detector is a judgement, and the UI labels it as one. A
                # reader who cannot tell which conclusions were measured and which were reasoned
                # has no way to calibrate how much to trust any of them.
                "judgement_only": criterion.judgement_only,
                "body": criterion.body,
            }
            for criterion in pillar.criteria
        ],
    }
    if include_body:
        payload["body"] = pillar.body
    return payload


@bp.route("/", methods=["GET"])
@action("standards:read")
def list_standards():
    """The whole baseline: every pillar, every criterion.

    One response rather than a pillar at a time. The golden path is read as a whole -- an SA is
    deciding what to fix first, which is a comparison across pillars -- and eight round trips to
    render one page is a worse trade than a single larger payload.
    """
    loaded = standards.load()
    return ok(
        version=loaded.version,
        overview=loaded.overview,
        pillars=[_pillar_json(pillar) for pillar in loaded.pillars],
    )


@bp.route("/<pillar_id>", methods=["GET"])
@action("standards:read")
def get_pillar(pillar_id: str):
    """One pillar including its full Markdown body.

    The body carries the remediation patterns and the reasoning, which is the part an SA actually
    acts on. It is served separately because it is long and the index does not need it.
    """
    loaded = standards.load()
    pillar = loaded.by_id(pillar_id)
    if pillar is None:
        return fail(
            f"No such pillar. This deployment publishes: {', '.join(loaded.ids)}",
            status=404, reason="not-found",
        )
    return ok(version=loaded.version, pillar=_pillar_json(pillar, include_body=True))
