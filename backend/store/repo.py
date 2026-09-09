# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Data access. Hand-written SQL, one function per question.

Author: Rafael M. Koike & Cursor Agent ("Ada")

No ORM. The schema is seven tables and the queries are simple enough to read, which matters more
here than the convenience would: when someone is debugging a stuck assessment against a live
database, the SQL they see in this file is the SQL that ran.

Every statement is parameterized. There is deliberately no helper that takes an interpolated WHERE
clause, because the moment one exists somebody passes a filter value through it.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from . import db
from .models import (
    Assessment,
    Finding,
    LlmCall,
    Origin,
    PassStatus,
    Repository,
    Severity,
    Status,
    new_id,
    now_iso,
)

_logger = logging.getLogger("nvsf.store.repo")


# ── Repositories ─────────────────────────────────────────────────────────────────────────────

_GIT_SUFFIX = re.compile(r"\.git/?$")


def canonicalize(url: str) -> tuple[str, str, str | None, str]:
    """``(canonical_url, forge, namespace, name)``.

    Dedup key, so three spellings of the same repository do not become three repositories. Strips
    the scheme, any embedded credentials, the port, a trailing ``.git`` and a trailing slash, then
    lowercases. SSH shorthand (``git@host:group/project.git``) is normalized to the same form as
    the https URL, because people paste both.

    Note it strips credentials rather than preserving them: a URL with a token in it must not be
    stored, and this is the chokepoint that guarantees it.
    """
    raw = url.strip()

    ssh = re.match(r"^(?:ssh://)?(?:[^@/]+@)([^:/]+)[:/](.+)$", raw)
    if ssh and "://" not in raw:
        host, path = ssh.group(1), ssh.group(2)
    else:
        parts = urlsplit(raw if "://" in raw else f"https://{raw}")
        host = parts.hostname or ""
        path = parts.path

    path = _GIT_SUFFIX.sub("", path.strip("/"))
    canonical = f"{host.lower()}/{path.lower()}"

    lowered = host.lower()
    if "gitlab" in lowered:
        forge = "gitlab"
    elif "github" in lowered:
        forge = "github"
    else:
        forge = "other"

    # Split the CANONICAL path, not the raw one, so the derived namespace and name do not depend
    # on how the URL happened to be typed. Two people pasting the same repository in different
    # case should see the same name in the list, not two that differ only in capitalization.
    segments = [s for s in canonical.split("/")[1:] if s]
    name = segments[-1] if segments else canonical
    namespace = "/".join(segments[:-1]) or None
    return canonical, forge, namespace, name


def sanitize_url(url: str) -> str:
    """The submitted URL with any embedded credentials removed, still fetchable.

    ``canonical_url`` is a dedup key and deliberately not fetchable — it has no scheme. So the
    row also keeps the original URL, and that is the one a token would survive in. Somebody
    pasting ``https://oauth2:glpat-xxx@gitlab.com/...`` must not have it persisted, appear in a
    log line, or come back out of the API.
    """
    raw = url.strip()
    if "://" not in raw or "@" not in raw:
        return raw
    parts = urlsplit(raw)
    if not (parts.username or parts.password):
        return raw
    _logger.warning("store: stripped credentials from a submitted repository URL")
    netloc = (parts.hostname or "") + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _row_to_repository(row: Any) -> Repository:
    return Repository(
        id=row["id"], url=row["url"], canonical_url=row["canonical_url"], forge=row["forge"],
        namespace=row["namespace"], name=row["name"], default_branch=row["default_branch"],
        added_at=row["added_at"], added_by=row["added_by"], notes=row["notes"],
    )


def upsert_repository(url: str, added_by: str, notes: str | None = None) -> Repository:
    """Find or create. Returns the existing row when the canonical form already exists."""
    canonical, forge, namespace, name = canonicalize(url)
    existing = db.query_one(
        "SELECT * FROM repositories WHERE canonical_url = ?", (canonical,)
    )
    if existing:
        return _row_to_repository(existing)

    record = Repository(
        id=new_id(), url=sanitize_url(url), canonical_url=canonical, forge=forge,
        namespace=namespace, name=name, added_at=now_iso(), added_by=added_by, notes=notes,
    )
    db.execute(
        "INSERT INTO repositories "
        "(id, url, canonical_url, forge, namespace, name, default_branch, added_at, added_by, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (record.id, record.url, record.canonical_url, record.forge, record.namespace,
         record.name, record.default_branch, record.added_at, record.added_by, record.notes),
    )
    _logger.info("store: registered repository %s (%s)", record.canonical_url, record.id)
    return record


def get_repository(repository_id: str) -> Repository | None:
    row = db.query_one("SELECT * FROM repositories WHERE id = ?", (repository_id,))
    return _row_to_repository(row) if row else None


def list_repositories(limit: int = 50, offset: int = 0) -> list[Repository]:
    rows = db.query(
        "SELECT * FROM repositories ORDER BY added_at DESC LIMIT ? OFFSET ?", (limit, offset)
    )
    return [_row_to_repository(r) for r in rows]


def count_repositories() -> int:
    return int(db.query_one("SELECT COUNT(*) AS n FROM repositories")["n"])


def set_default_branch(repository_id: str, branch: str) -> None:
    db.execute("UPDATE repositories SET default_branch = ? WHERE id = ?", (branch, repository_id))


# ── Assessments ──────────────────────────────────────────────────────────────────────────────

def _row_to_assessment(row: Any) -> Assessment:
    return Assessment(
        id=row["id"], repository_id=row["repository_id"], status=Status(row["status"]),
        created_at=row["created_at"], created_by=row["created_by"], ref=row["ref"],
        commit_sha=row["commit_sha"], evidence_hash=row["evidence_hash"],
        standards_version=row["standards_version"],
        intake=json.loads(row["intake_json"]) if row["intake_json"] else {},
        failure_reason=row["failure_reason"], failure_detail=row["failure_detail"],
        retryable=bool(row["retryable"]), started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def create_assessment(
    repository_id: str,
    created_by: str,
    ref: str | None = None,
    intake: dict[str, Any] | None = None,
    standards_version: str | None = None,
) -> Assessment:
    record = Assessment(
        id=new_id(), repository_id=repository_id, status=Status.QUEUED, created_at=now_iso(),
        created_by=created_by, ref=ref, intake=intake or {},
        standards_version=standards_version,
    )
    db.execute(
        "INSERT INTO assessments "
        "(id, repository_id, status, ref, intake_json, standards_version, created_at, created_by, "
        " retryable) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
        (record.id, record.repository_id, str(record.status), record.ref,
         json.dumps(record.intake), record.standards_version, record.created_at,
         record.created_by),
    )
    return record


def get_assessment(assessment_id: str) -> Assessment | None:
    row = db.query_one("SELECT * FROM assessments WHERE id = ?", (assessment_id,))
    return _row_to_assessment(row) if row else None


def list_assessments(
    repository_id: str | None = None, limit: int = 50, offset: int = 0
) -> list[Assessment]:
    if repository_id:
        rows = db.query(
            "SELECT * FROM assessments WHERE repository_id = ? "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (repository_id, limit, offset),
        )
    else:
        rows = db.query(
            "SELECT * FROM assessments ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
        )
    return [_row_to_assessment(r) for r in rows]


def active_assessments() -> list[Assessment]:
    """Runs that have not reached a terminal state.

    Used at startup to reconcile: a run left 'reasoning' by a crash is not running any more, and
    leaving it in that state means the UI shows a spinner forever.
    """
    placeholders = ", ".join("?" * 5)
    # The interpolated part is a run of question marks. Every status is bound as a parameter;
    # nothing derived from input reaches the SQL text.
    rows = db.query(
        f"SELECT * FROM assessments WHERE status IN ({placeholders}) ORDER BY created_at",  # noqa: S608
        (Status.QUEUED, Status.CLONING, Status.SCANNING, Status.REASONING, Status.RENDERING),
    )
    return [_row_to_assessment(r) for r in rows]


def set_status(assessment_id: str, status: Status) -> None:
    """Advance a run's status, stamping start and finish times.

    A terminal status also stamps ``finished_at``, which is what the UI uses to stop polling.
    """
    fields = ["status = ?"]
    params: list[Any] = [str(status)]
    if status is Status.CLONING:
        fields.append("started_at = COALESCE(started_at, ?)")
        params.append(now_iso())
    if status.terminal:
        fields.append("finished_at = ?")
        params.append(now_iso())
    params.append(assessment_id)
    # `fields` is assembled from the string literals above and nothing else. The values,
    # including the status, are bound.
    db.execute(
        f"UPDATE assessments SET {', '.join(fields)} WHERE id = ?",  # noqa: S608
        tuple(params),
    )


def fail_assessment(
    assessment_id: str, reason: str, detail: str | None = None, retryable: bool = False
) -> None:
    """Mark a run failed.

    ``reason`` is mandatory. A failed run with no recorded reason is a run nobody can act on, and
    the LLM being unavailable mid-run is the case this exists for: the run must say what happened
    and whether retrying can help, rather than emitting a thinner report.
    """
    if not reason:
        raise ValueError("a failed assessment must record a reason")
    db.execute(
        "UPDATE assessments SET status = ?, failure_reason = ?, failure_detail = ?, "
        "retryable = ?, finished_at = ? WHERE id = ?",
        (str(Status.FAILED), reason, detail, 1 if retryable else 0, now_iso(), assessment_id),
    )
    _logger.warning(
        "assessment %s failed: %s (retryable=%s)", assessment_id, reason, retryable
    )


def set_commit(assessment_id: str, commit_sha: str) -> None:
    db.execute("UPDATE assessments SET commit_sha = ? WHERE id = ?", (commit_sha, assessment_id))


def set_evidence_hash(assessment_id: str, evidence_hash: str) -> None:
    db.execute(
        "UPDATE assessments SET evidence_hash = ? WHERE id = ?", (evidence_hash, assessment_id)
    )


# ── Evidence ─────────────────────────────────────────────────────────────────────────────────

def save_evidence(assessment_id: str, document: dict[str, Any], evidence_hash: str) -> None:
    """Persist the redacted evidence document.

    Stored so a run can be re-reasoned without re-cloning -- which is what makes a prompt change
    cheap to evaluate against past assessments.

    The hash is also stamped on the assessment row, in the same transaction. Two writes because
    two readers need it -- the assessment list shows it without joining, and the evidence row owns
    it -- but one call, because an assessment whose recorded hash disagrees with its own evidence
    would make the provenance claim worthless.
    """
    payload = json.dumps(document, separators=(",", ":"))
    with db.transaction() as target:
        target.execute(
            "INSERT INTO evidence (assessment_id, hash, document_json, bytes, created_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(assessment_id) DO UPDATE SET "
            "hash = excluded.hash, document_json = excluded.document_json, "
            "bytes = excluded.bytes, created_at = excluded.created_at",
            (assessment_id, evidence_hash, payload, len(payload.encode("utf-8")), now_iso()),
        )
        target.execute(
            "UPDATE assessments SET evidence_hash = ? WHERE id = ?",
            (evidence_hash, assessment_id),
        )


def get_evidence(assessment_id: str) -> dict[str, Any] | None:
    row = db.query_one(
        "SELECT document_json FROM evidence WHERE assessment_id = ?", (assessment_id,)
    )
    return json.loads(row["document_json"]) if row else None


# ── Passes ───────────────────────────────────────────────────────────────────────────────────

def start_pass(assessment_id: str, pass_name: str) -> str:
    """Mark a pass running, creating the row if it does not exist. Returns the pass id."""
    existing = db.query_one(
        "SELECT id FROM passes WHERE assessment_id = ? AND pass_name = ?",
        (assessment_id, pass_name),
    )
    if existing:
        db.execute(
            "UPDATE passes SET status = ?, started_at = ?, error = NULL WHERE id = ?",
            (str(PassStatus.RUNNING), now_iso(), existing["id"]),
        )
        return str(existing["id"])
    pass_id = new_id()
    db.execute(
        "INSERT INTO passes (id, assessment_id, pass_name, status, started_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (pass_id, assessment_id, pass_name, str(PassStatus.RUNNING), now_iso()),
    )
    return pass_id


def complete_pass(pass_id: str, output: dict[str, Any]) -> None:
    """Persist a pass's output BEFORE the next pass begins.

    This one write is what makes the pipeline resumable. Without it, an endpoint that goes away
    between pass three and pass four costs the whole run.
    """
    db.execute(
        "UPDATE passes SET status = ?, output_json = ?, finished_at = ? WHERE id = ?",
        (str(PassStatus.COMPLETE), json.dumps(output), now_iso(), pass_id),
    )


def fail_pass(pass_id: str, error: str) -> None:
    db.execute(
        "UPDATE passes SET status = ?, error = ?, finished_at = ? WHERE id = ?",
        (str(PassStatus.FAILED), error, now_iso(), pass_id),
    )


def completed_passes(assessment_id: str) -> dict[str, dict[str, Any]]:
    """``{pass_name: output}`` for passes already done. Read on resume."""
    rows = db.query(
        "SELECT pass_name, output_json FROM passes WHERE assessment_id = ? AND status = ?",
        (assessment_id, str(PassStatus.COMPLETE)),
    )
    return {
        r["pass_name"]: json.loads(r["output_json"]) if r["output_json"] else {}
        for r in rows
    }


def pass_states(assessment_id: str) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT pass_name, status, error, started_at, finished_at FROM passes "
        "WHERE assessment_id = ? ORDER BY started_at",
        (assessment_id,),
    )
    return [dict(r) for r in rows]


# ── LLM provenance ───────────────────────────────────────────────────────────────────────────

def record_llm_call(call: LlmCall) -> None:
    """Persist a model call. Called for failures too -- a timeout is provenance as much as a
    success is, and it is what explains a run that took nine minutes."""
    db.execute(
        "INSERT INTO llm_calls (id, assessment_id, pass_name, model, prompt_version, temperature, "
        "evidence_hash, prompt_tokens, completion_tokens, duration_ms, status, error, "
        "raw_response, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (call.id, call.assessment_id, call.pass_name, call.model, call.prompt_version,
         call.temperature, call.evidence_hash, call.prompt_tokens, call.completion_tokens,
         call.duration_ms, call.status, call.error, call.raw_response, call.created_at),
    )


def list_llm_calls(assessment_id: str) -> list[LlmCall]:
    rows = db.query(
        "SELECT * FROM llm_calls WHERE assessment_id = ? ORDER BY created_at", (assessment_id,)
    )
    return [
        LlmCall(
            id=r["id"], assessment_id=r["assessment_id"], pass_name=r["pass_name"],
            model=r["model"], prompt_version=r["prompt_version"], temperature=r["temperature"],
            status=r["status"], created_at=r["created_at"], evidence_hash=r["evidence_hash"],
            prompt_tokens=r["prompt_tokens"], completion_tokens=r["completion_tokens"],
            duration_ms=r["duration_ms"], error=r["error"], raw_response=r["raw_response"],
        )
        for r in rows
    ]


def token_usage(assessment_id: str) -> dict[str, int]:
    row = db.query_one(
        "SELECT COALESCE(SUM(prompt_tokens), 0) AS prompt, "
        "COALESCE(SUM(completion_tokens), 0) AS completion, COUNT(*) AS calls "
        "FROM llm_calls WHERE assessment_id = ?",
        (assessment_id,),
    )
    return {
        "prompt_tokens": int(row["prompt"]),
        "completion_tokens": int(row["completion"]),
        "calls": int(row["calls"]),
    }


# ── Findings ─────────────────────────────────────────────────────────────────────────────────

def save_findings(findings: list[Finding]) -> int:
    """Insert findings in one transaction. Returns how many were written."""
    if not findings:
        return 0
    with db.transaction() as conn:
        conn.executemany(
            "INSERT INTO findings (id, assessment_id, pillar_id, criterion, severity, title, "
            "detail, file_path, line_start, line_end, origin, escalated_from, detector, "
            "remediation, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (f.id, f.assessment_id, f.pillar_id, f.criterion, str(f.severity), f.title,
                 f.detail, f.file_path, f.line_start, f.line_end, str(f.origin),
                 str(f.escalated_from) if f.escalated_from else None, f.detector, f.remediation,
                 f.created_at)
                for f in findings
            ],
        )
    return len(findings)


def clear_findings(assessment_id: str) -> None:
    """Remove a run's findings, so a re-reason does not double them up."""
    db.execute("DELETE FROM findings WHERE assessment_id = ?", (assessment_id,))


def list_findings(assessment_id: str) -> list[Finding]:
    rows = db.query(
        "SELECT * FROM findings WHERE assessment_id = ? ORDER BY pillar_id, "
        "CASE severity WHEN 'blocker' THEN 0 WHEN 'major' THEN 1 WHEN 'minor' THEN 2 ELSE 3 END",
        (assessment_id,),
    )
    return [
        Finding(
            id=r["id"], assessment_id=r["assessment_id"], pillar_id=r["pillar_id"],
            severity=Severity(r["severity"]), title=r["title"], origin=Origin(r["origin"]),
            created_at=r["created_at"], criterion=r["criterion"], detail=r["detail"],
            file_path=r["file_path"], line_start=r["line_start"], line_end=r["line_end"],
            escalated_from=Severity(r["escalated_from"]) if r["escalated_from"] else None,
            detector=r["detector"], remediation=r["remediation"],
        )
        for r in rows
    ]


def severity_counts(assessment_id: str) -> dict[str, int]:
    rows = db.query(
        "SELECT severity, COUNT(*) AS n FROM findings WHERE assessment_id = ? GROUP BY severity",
        (assessment_id,),
    )
    counts = {str(s): 0 for s in Severity}
    for row in rows:
        counts[row["severity"]] = int(row["n"])
    return counts


# ── Artifacts ────────────────────────────────────────────────────────────────────────────────

def record_artifact(
    assessment_id: str, kind: str, filename: str, size: int, sha256: str
) -> None:
    db.execute(
        "INSERT INTO artifacts (id, assessment_id, kind, filename, bytes, sha256, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(assessment_id, kind) DO UPDATE SET "
        "filename = excluded.filename, bytes = excluded.bytes, sha256 = excluded.sha256, "
        "created_at = excluded.created_at",
        (new_id(), assessment_id, kind, filename, size, sha256, now_iso()),
    )


def list_artifacts(assessment_id: str) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT kind, filename, bytes, sha256, created_at FROM artifacts "
        "WHERE assessment_id = ? ORDER BY kind",
        (assessment_id,),
    )
    return [dict(r) for r in rows]
