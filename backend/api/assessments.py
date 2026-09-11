# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Assessment runs: /api/assessments

Author: Rafael M. Koike & Cursor Agent ("Ada")

Enqueue-and-poll. ``POST`` returns 202 with a run id; the client polls the detail endpoint, which
reports a stage name rather than a percentage. A percentage would have to be invented, and an
invented one that sits at 80% for four minutes is worse than "judging Scalability".
"""

from __future__ import annotations

import logging

from authz import action
from factory import llm, pipeline, report, runner
from flask import Blueprint, g, send_file
from store import repo
from store.models import Status

from ._common import body, fail, ok, paginate

bp = Blueprint("assessments", __name__)

_logger = logging.getLogger("nvsf.api.assessments")


@bp.route("/", methods=["GET"])
@action("assessment:list")
def list_assessments():
    limit, offset = paginate()
    from flask import request

    assessments = repo.list_assessments(
        repository_id=request.args.get("repository_id"),
        limit=limit,
        offset=offset,
    )
    return ok(
        # Every assessment that has not reached a terminal state, not the ones this process
        # happens to hold. `runner.in_flight()` reads a dict owned by one gunicorn worker, so with
        # more than one worker the list view was told a run had stopped whenever the poll landed
        # elsewhere -- and the view uses this to decide whether to keep polling.
        in_flight=[a.id for a in repo.active_assessments()],
        assessments=[a.to_json() for a in assessments],
        limit=limit,
        offset=offset,
    )


@bp.route("/", methods=["POST"])
@action("assessment:create")
def create_assessment():
    data = body()
    repository_id = data.get("repository_id")
    url = data.get("url")

    if not repository_id and not url:
        return fail(
            "Give either a repository_id for an already-registered repository, or a url to "
            "register and assess in one step.",
            reason="missing-target",
        )

    if repository_id:
        repository = repo.get_repository(str(repository_id))
        if repository is None:
            return fail("No such repository", status=404, reason="not-found")
    else:
        from factory.acquire import AcquireRefused, validate_url
        try:
            validate_url(str(url))
        except AcquireRefused as error:
            return fail(str(error), status=422, reason="url-refused")
        repository = repo.upsert_repository(url=str(url), added_by=g.principal.subject)

    # One run at a time per repository. Two concurrent assessments of the same tree would produce
    # two reports that differ only by model non-determinism, which is confusing rather than
    # informative, and they would compete for the same LLM budget.
    active = [a for a in repo.active_assessments() if a.repository_id == repository.id]
    if active:
        return fail(
            "An assessment of this repository is already running.",
            status=409, reason="already-running", assessment_id=active[0].id,
        )

    # Fail before enqueueing rather than after. An assessment that sits in the queue for a minute
    # and then fails on an unreachable endpoint wastes the user's attention; the pre-flight makes
    # the 503 immediate and actionable.
    probe = llm.probe()
    if not probe.get("reachable"):
        return fail(
            "The reasoning model endpoint is unreachable, and every assessment requires it. "
            f"{probe.get('detail', '')}".strip(),
            status=503, reason="llm-unavailable", probe=probe,
        )

    intake = {
        key: data[key]
        for key in ("purpose", "audience", "criticality", "data_handled", "notes")
        if data.get(key)
    }
    assessment = repo.create_assessment(
        repository_id=repository.id,
        created_by=g.principal.subject,
        ref=str(data["ref"]) if data.get("ref") else None,
        intake=intake,
    )
    runner.submit(assessment.id)

    return ok(assessment=assessment.to_json(), repository=repository.to_json()), 202


@bp.route("/<assessment_id>", methods=["GET"])
@action("assessment:read")
def get_assessment(assessment_id: str):
    summary = pipeline.summarize_for_api(assessment_id)
    if not summary:
        return fail("No such assessment", status=404, reason="not-found")
    # The raw model responses are a wider grant than the conclusions, so they are stripped here
    # and served from the provenance endpoint under its own action.
    summary.pop("llm_calls", None)
    return ok(**summary)


@bp.route("/<assessment_id>/provenance", methods=["GET"])
@action("assessment:provenance")
def get_provenance(assessment_id: str):
    assessment = repo.get_assessment(assessment_id)
    if assessment is None:
        return fail("No such assessment", status=404, reason="not-found")
    return ok(
        assessment=assessment.to_json(),
        llm_calls=[c.to_json(include_raw=True) for c in repo.list_llm_calls(assessment_id)],
        token_usage=repo.token_usage(assessment_id),
        pass_states=repo.pass_states(assessment_id),
        evidence=repo.get_evidence(assessment_id),
    )


@bp.route("/<assessment_id>/retry", methods=["POST"])
@action("assessment:retry")
def retry_assessment(assessment_id: str):
    assessment = repo.get_assessment(assessment_id)
    if assessment is None:
        return fail("No such assessment", status=404, reason="not-found")
    if assessment.status is not Status.FAILED:
        return fail(
            f"This assessment is {assessment.status}, not failed.",
            status=409, reason="not-failed",
        )
    if not assessment.retryable:
        return fail(
            "This failure is not retryable — retrying would fail the same way. "
            f"{assessment.failure_detail or ''}".strip(),
            status=409, reason="not-retryable",
        )

    completed = repo.completed_passes(assessment_id)
    repo.set_status(assessment_id, Status.QUEUED)
    runner.submit(assessment_id)
    return ok(
        assessment=repo.get_assessment(assessment_id).to_json(),
        resuming_from=sorted(completed),
        note=(
            f"{len(completed)} completed reasoning pass(es) will be reused; only the passes that "
            "did not finish will run again."
        ),
    ), 202


@bp.route("/<assessment_id>/cancel", methods=["POST"])
@action("assessment:cancel")
def cancel_assessment(assessment_id: str):
    assessment = repo.get_assessment(assessment_id)
    if assessment is None:
        return fail("No such assessment", status=404, reason="not-found")
    if assessment.status.terminal:
        return fail(
            f"This assessment already finished ({assessment.status}).",
            status=409, reason="already-terminal",
        )

    if pipeline.request_cancel(assessment_id):
        return ok(
            note="Cancellation requested. The run stops at its next checkpoint, which is at most "
                 "one model call away.",
        )
    # Queued but not started: no thread to signal, so cancel it directly.
    repo.set_status(assessment_id, Status.CANCELLED)
    return ok(note="Cancelled before it started.")


@bp.route("/<assessment_id>/artifacts", methods=["GET"])
@action("assessment:read")
def list_artifacts(assessment_id: str):
    if repo.get_assessment(assessment_id) is None:
        return fail("No such assessment", status=404, reason="not-found")
    return ok(artifacts=repo.list_artifacts(assessment_id))


@bp.route("/<assessment_id>/artifacts/<name>", methods=["GET"])
@action("assessment:artifact")
def download_artifact(assessment_id: str, name: str):
    if repo.get_assessment(assessment_id) is None:
        return fail("No such assessment", status=404, reason="not-found")

    path = report.artifact_path(assessment_id, name)
    if path is None:
        return fail("No such artifact", status=404, reason="not-found")

    # as_attachment: these are documents to save and hand to an agent, not pages to view. It also
    # means a Markdown file cannot be rendered inline, which removes a stored-XSS surface --
    # the content includes excerpts from an arbitrary third-party repository.
    return send_file(path, as_attachment=True, download_name=name)
