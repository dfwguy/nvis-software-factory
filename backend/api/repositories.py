# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Registered repositories: /api/repositories

Author: Rafael M. Koike & Cursor Agent ("Ada")

Registration is separate from assessment because a repository is assessed repeatedly and the
history is the interesting part. "Is it better than last quarter" is a question about a repository,
not about a run.
"""

from __future__ import annotations

import logging

from authz import action
from factory.acquire import AcquireRefused, validate_url
from flask import Blueprint, g
from store import repo

from ._common import body, fail, ok, paginate, required

bp = Blueprint("repositories", __name__)

_logger = logging.getLogger("nvsf.api.repositories")


@bp.route("/", methods=["GET"])
@action("repository:list")
def list_repositories():
    limit, offset = paginate()
    repositories = repo.list_repositories(limit=limit, offset=offset)
    return ok(
        repositories=[r.to_json() for r in repositories],
        total=repo.count_repositories(),
        limit=limit,
        offset=offset,
    )


@bp.route("/", methods=["POST"])
@action("repository:add")
def add_repository():
    data = body()
    missing = required(data, "url")
    if missing:
        return fail(f"Missing required field(s): {', '.join(missing)}", reason="missing-fields")

    try:
        # Validated here, before anything is written, so an unusable URL never becomes a row that
        # only fails at clone time. The same validator the clone uses, so the two cannot disagree.
        validate_url(str(data["url"]))
    except AcquireRefused as error:
        return fail(str(error), status=422, reason="url-refused")

    try:
        repository = repo.upsert_repository(
            url=str(data["url"]),
            added_by=g.principal.subject,
            notes=str(data["notes"]) if data.get("notes") else None,
        )
    except ValueError as error:
        return fail(str(error), status=422, reason="url-invalid")

    return ok(repository=repository.to_json())


@bp.route("/<repository_id>", methods=["GET"])
@action("repository:read")
def get_repository(repository_id: str):
    repository = repo.get_repository(repository_id)
    if repository is None:
        return fail("No such repository", status=404, reason="not-found")
    assessments = repo.list_assessments(repository_id=repository_id, limit=25)
    return ok(
        repository=repository.to_json(),
        assessments=[a.to_json() for a in assessments],
    )
