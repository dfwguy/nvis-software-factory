# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Scanners against synthetic repositories with known defects.

Author: Rafael M. Koike & Cursor Agent ("Ada")

The test that matters most is :func:`test_the_incident_that_started_this_is_detected`. A team kept
their state in a container with no volume, someone restarted Docker, and the data was gone. If the
factory cannot detect that shape, it does not justify its existence, so the fixture reproduces it
literally and the assertion is on the blocker.

The second theme is false positives. A scanner that flags a clean repository is worse than one that
misses things, because the first report an SA reads decides whether they read the second. So there
is a clean fixture, and it is asserted to produce no blockers at all.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from factory.acquire import Clone
from factory.evidence import MAX_DOCUMENT_CHARS, build
from factory.scanners import RepoView, discover, run_all
from store.models import Severity


def _write(root: Path, files: dict[str, str]) -> RepoView:
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return RepoView(root)


def _clone_for(root: Path) -> Clone:
    return Clone(
        path=root,
        commit_sha="0" * 40,
        ref="main",
        bytes=sum(f.stat().st_size for f in root.rglob("*") if f.is_file()),
        file_count=sum(1 for f in root.rglob("*") if f.is_file()),
        submodules=(),
    )


def _keys(facts, pillar: str | None = None) -> set[str]:
    return {f.key for f in facts if pillar is None or f.pillar_id == pillar}


def _find(facts, key: str):
    matches = [f for f in facts if f.key == key]
    assert matches, f"expected a fact keyed {key!r}; got {sorted(_keys(facts))}"
    return matches[0]


# ── The motivating incident ──────────────────────────────────────────────────────────────────


@pytest.fixture
def in_memory_service(tmp_path: Path) -> RepoView:
    """A service holding its only copy of the data in a module-level dict, in a container.

    Written the way it actually gets written: it is not incompetent code, it is a prototype that
    worked, shipped, and was never revisited.
    """
    return _write(tmp_path / "in-memory", {
        "app.py": """
            from flask import Flask, jsonify, request

            app = Flask(__name__)

            # Validation results, keyed by rack.
            results = {}
            node_state = {}

            @app.route("/results/<rack>", methods=["POST"])
            def record(rack):
                results[rack] = request.json
                return jsonify({"stored": True})

            @app.route("/results/<rack>")
            def fetch(rack):
                return jsonify(results.get(rack, {}))

            if __name__ == "__main__":
                app.run(host="0.0.0.0", port=8080)
        """,
        "collect.py": """
            import requests

            def collect(hosts):
                for host in hosts:
                    try:
                        r = requests.get(f"https://{host}/redfish/v1/Chassis", verify=False)
                        print("collected", host)
                    except Exception:
                        pass
        """,
        "Dockerfile": """
            FROM python:3.12-slim
            COPY . /app
            WORKDIR /app
            RUN pip install flask requests
            CMD ["python", "app.py"]
        """,
        "docker-compose.yml": """
            services:
              api:
                build: .
                ports:
                  - "8080:8080"
        """,
    })


def test_the_incident_that_started_this_is_detected(in_memory_service, tmp_path):
    """Containerized, writes state, no volume anywhere: a blocker, not a suggestion."""
    report = run_all(in_memory_service)

    finding = _find(report.findings, "container_without_volume")
    assert finding.severity is Severity.BLOCKER
    assert finding.pillar_id == "durability"
    # The remediation has to name the specific fix, because it is fed to a coding agent.
    assert "bind mount" in (finding.remediation or "")

    # And the surrounding evidence the model needs to explain why it matters.
    assert "module_level_mutable_state" in _keys(report.facts, "durability")
    assert "backup_signals" in _keys(report.facts, "durability")


def test_the_incident_repository_also_trips_the_adjacent_pillars(in_memory_service):
    """The same prototype shape fails several pillars at once, which is the honest picture."""
    report = run_all(in_memory_service)
    keys = _keys(report.findings)

    assert "container_without_volume" in keys          # durability
    assert "swallowed_exceptions" in keys              # reliability: except/pass
    assert "network_call_without_timeout" in keys      # reliability: no timeout
    assert "tls_verification_disabled" in keys         # data security: verify=False
    assert "print_only_output" in keys                 # observability
    assert "no_tests" in keys                          # testability
    assert "no_ci" in keys                             # testability
    assert "no_readme" in keys                         # provenance

    # Unauthenticated mutating endpoint: a POST route and no authentication anywhere.
    unauthenticated = _find(report.findings, "mutating_endpoints_without_auth")
    assert unauthenticated.severity is Severity.BLOCKER


# ── False positives ──────────────────────────────────────────────────────────────────────────


@pytest.fixture
def well_built_service(tmp_path: Path) -> RepoView:
    """A repository that does the things the standard asks for."""
    return _write(tmp_path / "well-built", {
        "README.md": """
            # rack-collector

            Collects Redfish inventory from BMCs and writes it to SQLite.

            Owner: OVA team (ova-team@nvidia.com)

            ## Usage

            ```bash
            docker compose up -d
            ```

            ## Backup and restore

            A snapshot is written nightly with `VACUUM INTO`; restore by copying it back.

            ## Deploy

            `docker compose pull && docker compose up -d`.

            ## Troubleshooting

            Check `/api/health` first.
        """,
        "collector/store.py": """
            import logging
            import os
            import sqlite3

            logger = logging.getLogger(__name__)

            def connect(path):
                conn = sqlite3.connect(path)
                conn.execute("PRAGMA journal_mode = WAL")
                return conn

            def save(conn, node_id, payload):
                conn.execute(
                    "INSERT OR REPLACE INTO inventory (node_id, payload) VALUES (?, ?)",
                    (node_id, payload),
                )
                conn.commit()
                logger.info("saved inventory", extra={"node_id": node_id})

            def snapshot(conn, destination):
                tmp = f"{destination}.tmp"
                conn.execute("VACUUM INTO ?", (tmp,))
                os.replace(tmp, destination)
        """,
        "collector/fetch.py": """
            import logging

            import requests
            from tenacity import retry, stop_after_attempt, wait_exponential

            logger = logging.getLogger(__name__)

            TIMEOUT = (5, 30)

            @retry(stop=stop_after_attempt(4), wait=wait_exponential(max=30))
            def fetch(session, host, ca_bundle):
                try:
                    response = session.get(
                        f"https://{host}/redfish/v1/Chassis",
                        timeout=TIMEOUT,
                        verify=ca_bundle,
                    )
                    response.raise_for_status()
                except requests.RequestException:
                    logger.exception("redfish fetch failed for host %s", host)
                    raise
                return response.json()
        """,
        "collector/api.py": """
            import logging

            from flask import Blueprint, jsonify, request

            from .auth import login_required

            logger = logging.getLogger(__name__)
            bp = Blueprint("api", __name__)

            @bp.route("/api/v1/inventory", methods=["POST"])
            @login_required
            def upsert():
                logger.info("upsert requested", extra={"correlation_id": request.headers.get(
                    "X-Correlation-Id")})
                return jsonify({"ok": True})

            @bp.route("/api/v1/health")
            def health():
                return jsonify({"ok": True})
        """,
        "collector/auth.py": """
            import functools

            from flask import abort, session

            def login_required(view):
                @functools.wraps(view)
                def wrapped(*args, **kwargs):
                    if not session.get("sub"):
                        abort(401)
                    return view(*args, **kwargs)
                return wrapped
        """,
        "tests/test_store.py": """
            from collector import store

            def test_save_survives_reconnect(tmp_path):
                path = tmp_path / "x.db"
                conn = store.connect(path)
                conn.execute("CREATE TABLE inventory (node_id TEXT PRIMARY KEY, payload TEXT)")
                store.save(conn, "n1", "{}")
                conn.close()
                assert store.connect(path).execute(
                    "SELECT payload FROM inventory").fetchone() is not None
        """,
        "docker-compose.yml": """
            services:
              collector:
                build: .
                volumes:
                  - ./data:/data
                environment:
                  - COLLECTOR_DB=/data/inventory.db
                deploy:
                  resources:
                    limits:
                      memory: 512M
                      cpus: "1.0"
        """,
        "Dockerfile": "FROM python:3.12-slim\nCOPY . /app\n",
        ".gitlab-ci.yml": """
            stages: [lint, test]
            lint:
              stage: lint
              script:
                - ruff check .
            test:
              stage: test
              script:
                - pytest --cov=collector
        """,
        "ruff.toml": 'line-length = 100\n',
        ".coveragerc": "[run]\nsource = collector\n",
        ".gitignore": ".env\n*.pem\n__pycache__/\n",
        "requirements.txt": "flask==3.0.3\nrequests==2.32.3\ntenacity==8.5.0\n",
        "CODEOWNERS": "* @nvis-ova\n",
        "LICENSE": "Proprietary.\n",
        "migrations/0001_initial.sql": "CREATE TABLE inventory (node_id TEXT PRIMARY KEY);\n",
    })


def test_a_well_built_repository_produces_no_blockers(well_built_service):
    """The credibility test. One false blocker and nobody reads the second report."""
    report = run_all(well_built_service)
    blockers = [f for f in report.findings if f.severity is Severity.BLOCKER]
    assert blockers == [], (
        "false positive blockers: "
        + "; ".join(f"{f.key} ({f.pillar_id}) {f.title}" for f in blockers)
    )


def test_a_well_built_repository_is_credited_for_what_it_does(well_built_service):
    """Positive facts matter: a report that only lists faults reads as noise."""
    report = run_all(well_built_service)
    keys = _keys(report.facts)

    assert "volumes_declared" in keys
    assert "persistence_inventory" in keys
    assert "ci_posture" in keys
    assert "owner_declared" in keys
    assert "environment_manifest" in keys
    assert _find(report.facts, "persistence_inventory").severity is None


def test_no_false_positive_on_placeholder_credentials(tmp_path):
    """Documentation examples and obvious placeholders must not become findings."""
    view = _write(tmp_path / "placeholders", {
        "README.md": """
            Set these before running:

            ```bash
            export API_TOKEN=your-token-here
            export PASSWORD=changeme
            ```
        """,
        ".env.example": 'API_TOKEN=xxxxxxxx\nDB_PASSWORD=<your-password>\n',
        "config.py": """
            import os

            API_TOKEN = os.environ["API_TOKEN"]
            PASSWORD = os.environ.get("PASSWORD", "")
        """,
    })
    report = run_all(view, only=["secrets"])
    assert "hardcoded_credentials" not in _keys(report.findings)
    assert "no_hardcoded_credentials" in _keys(report.facts)


def test_a_real_looking_token_is_a_blocker(tmp_path):
    """A recognised credential prefix is certain enough for a blocker."""
    view = _write(tmp_path / "leaked", {
        "settings.py": 'GITLAB_TOKEN = "glpat-AbCdEfGhIjKlMnOpQrSt"\n',
    })
    report = run_all(view, only=["secrets"])
    finding = _find(report.findings, "hardcoded_credentials")
    assert finding.severity is Severity.BLOCKER
    assert "Rotate" in (finding.remediation or "")


def test_a_tracked_private_key_is_a_blocker(tmp_path):
    view = _write(tmp_path / "keys", {
        "deploy/id_rsa": "-----BEGIN OPENSSH PRIVATE KEY-----\nnot-a-real-key\n",
    })
    report = run_all(view, only=["secrets"])
    finding = _find(report.findings, "credential_paths_tracked")
    assert finding.severity is Severity.BLOCKER


# ── The redaction boundary ───────────────────────────────────────────────────────────────────


def test_no_secret_value_reaches_the_evidence_document(tmp_path):
    """The property that must hold no matter which scanner found it.

    Asserted on the rendered document rather than on the redaction function, because the
    guarantee that matters is about the artifact that leaves the process.
    """
    secret = "glpat-ZyXwVuTsRqPoNmLkJiHg"
    aws = "AKIAIOSFODNN7EXAMPLE"
    root = tmp_path / "secretive"
    view = _write(root, {
        "settings.py": f'GITLAB_TOKEN = "{secret}"\nAWS_ACCESS_KEY_ID = "{aws}"\n',
        "deploy.sh": f'#!/bin/bash\ncurl -H "PRIVATE-TOKEN: {secret}" https://gitlab/api\n',
    })
    report = run_all(view)
    evidence = build(view, _clone_for(root), report, "https://example.invalid/x.git")

    rendered = evidence.to_markdown()
    assert secret not in rendered
    assert aws not in rendered
    # The shape survives, which is what makes the finding actionable.
    assert "GitLab" in rendered or "redacted" in rendered

    import json as _json
    assert secret not in _json.dumps(evidence.to_json(), default=str)


def test_excerpts_are_redacted_at_extraction(tmp_path):
    view = _write(tmp_path / "excerpt", {
        "conf.py": 'PASSWORD = "s3cr3t-p4ssw0rd-value-here"\n',
    })
    excerpt = view.excerpt("conf.py", 1)
    assert excerpt is not None
    assert "s3cr3t-p4ssw0rd-value-here" not in excerpt
    assert "PASSWORD" in excerpt


# ── The read-only, non-executing view ────────────────────────────────────────────────────────


def test_the_view_refuses_to_read_outside_the_clone(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("host filesystem content", encoding="utf-8")
    root = tmp_path / "repo"
    view = _write(root, {"a.py": "x = 1\n"})

    assert view.read("../outside.txt") is None
    assert view.read("/etc/passwd") is None
    assert not view.exists("../outside.txt")


def test_symlinks_are_not_followed(tmp_path):
    root = tmp_path / "repo"
    _write(root, {"a.py": "x = 1\n"})
    target = tmp_path / "secret-outside.txt"
    target.write_text("nope", encoding="utf-8")
    (root / "link.txt").symlink_to(target)

    # Re-create the view so the listing is recomputed after the symlink exists.
    fresh = RepoView(root)
    assert "link.txt" not in fresh.files()


def test_binary_and_oversized_files_are_skipped(tmp_path):
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    (root / "blob.py").write_bytes(b"import x\n\x00\x01\x02binary")
    view = RepoView(root)
    assert view.read("blob.py") is None


# ── Scanner infrastructure ───────────────────────────────────────────────────────────────────


def test_every_scanner_targets_a_real_pillar():
    """Drift check: a typo'd PILLAR would silently orphan a scanner's facts."""
    from factory import standards

    valid = {p.id for p in standards.load().pillars}
    for name, module in discover().items():
        assert module.PILLAR in valid, f"{name} targets unknown pillar {module.PILLAR!r}"


def test_every_pillar_has_at_least_one_scanner():
    from factory import standards

    covered = {module.PILLAR for module in discover().values()}
    for pillar in standards.load().pillars:
        assert pillar.id in covered, f"no scanner covers pillar {pillar.id}"


def test_one_scanner_failing_does_not_lose_the_run(tmp_path, monkeypatch):
    """A crash becomes a fact saying the pillar is unknown, and the rest still runs."""
    from factory.scanners import durability

    def explode(view):
        raise ValueError("regex met something unexpected")

    monkeypatch.setattr(durability, "scan", explode)
    view = _write(tmp_path / "repo", {"a.py": "print('x')\n"})
    report = run_all(view)

    assert "durability" in report.failures
    failure_fact = _find(report.facts, "scanner_failed")
    assert failure_fact.pillar_id == "durability"
    # "unknown, not clean" -- the distinction the whole pipeline turns on.
    assert "not evaluated" in failure_fact.title
    # Other scanners still produced facts.
    assert len([f for f in report.facts if f.pillar_id != "durability"]) > 0


def test_scanners_do_not_execute_repository_code(tmp_path):
    """A repository whose import would have a side effect must not have it."""
    root = tmp_path / "repo"
    canary = tmp_path / "canary.txt"
    view = _write(root, {
        "evil.py": f"""
            from pathlib import Path
            Path({str(canary)!r}).write_text("executed")
        """,
        "setup.py": f"""
            from pathlib import Path
            Path({str(canary)!r}).write_text("executed")
        """,
    })
    run_all(view)
    assert not canary.exists(), "a scanner executed repository code"


# ── The evidence document ────────────────────────────────────────────────────────────────────


def test_evidence_names_every_pillar_even_when_silent(well_built_service, tmp_path):
    """A pillar with no facts must appear as explicitly empty, not be absent."""
    from factory import standards

    report = run_all(well_built_service)
    evidence = build(well_built_service, _clone_for(well_built_service.root), report,
                     "https://example.invalid/well.git")

    for pillar in standards.load().pillars:
        assert pillar.id in evidence.pillars

    rendered = evidence.to_markdown()
    assert "absence of evidence" in rendered or "Deterministic findings" in rendered


def test_evidence_states_its_own_limits(in_memory_service, tmp_path):
    """The model must be told what it cannot see, or it will over-claim."""
    report = run_all(in_memory_service)
    evidence = build(in_memory_service, _clone_for(in_memory_service.root), report,
                     "https://example.invalid/x.git")
    joined = " ".join(evidence.limits)

    assert "history was not scanned" in joined
    assert "was executed" in joined
    assert "What this evidence does not cover" in evidence.to_markdown()


def test_evidence_hash_is_stable_for_identical_input(well_built_service, tmp_path):
    """Provenance depends on this: the hash must address content, not the moment of the run."""
    clone = _clone_for(well_built_service.root)
    first = build(well_built_service, clone, run_all(well_built_service), "https://x.invalid/a")
    second = build(RepoView(well_built_service.root), clone,
                   run_all(RepoView(well_built_service.root)), "https://x.invalid/a")
    assert first.hash() == second.hash()


def test_a_large_repository_still_fits_the_context_budget(tmp_path):
    root = tmp_path / "big"
    files = {
        f"module_{i}/handler.py": f"""
            import requests

            def go_{i}(hosts):
                for host in hosts:
                    try:
                        requests.get("http://{{host}}/x")
                    except Exception:
                        pass
                    print("done", host)
        """
        for i in range(120)
    }
    files["Dockerfile"] = "FROM python:3.12\n"
    view = _write(root, files)

    evidence = build(view, _clone_for(root), run_all(view), "https://x.invalid/big")
    assert len(evidence.to_markdown()) <= MAX_DOCUMENT_CHARS


def test_scanners_report_a_count_rather_than_a_citation_per_site(tmp_path):
    """Bounding starts in the scanners: 120 identical defects are one fact and a count.

    This is what keeps the evidence document small enough that reduction rarely has to drop
    anything, and it is also the more useful shape — the eleventh citation of the same missing
    timeout adds nothing a judgement can use.
    """
    root = tmp_path / "repetitive"
    view = _write(root, {
        f"mod_{i}.py": f"import requests\n\ndef go_{i}(h):\n    requests.get(h)\n"
        for i in range(120)
    })
    report = run_all(view, only=["reliability"])
    timeouts = [f for f in report.facts if f.key == "network_call_without_timeout"]

    assert len(timeouts) == 1
    assert timeouts[0].data["count"] >= 100          # the real scale is stated
    assert len(timeouts[0].data["sites"]) <= 20      # the citations are capped


def test_dropping_facts_is_always_announced(tmp_path, monkeypatch):
    """Reduction must be visible, or a truncated pillar reads to the model as a quiet one."""
    from factory.scanners import Fact, ScanReport

    root = tmp_path / "synthetic"
    view = _write(root, {"a.py": "x = 1\n"})

    report = ScanReport()
    report.facts = [
        Fact(
            pillar_id="durability", key=f"synthetic_{i}", title=f"Synthetic finding {i}",
            detail="x" * 200, severity=Severity.MINOR,
        )
        for i in range(25)
    ]

    evidence = build(view, _clone_for(root), report, "https://x.invalid/s")
    block = evidence.pillars["durability"]

    assert len(block["facts"]) == 10
    assert block["counts"]["facts"] == 25          # the true total survives
    assert block["truncated"] is not None
    assert "15 further fact" in block["truncated"]
    assert "15 further fact" in evidence.to_markdown()


def test_shrinking_gives_up_excerpts_before_it_gives_up_facts(tmp_path):
    """A citation without its excerpt is still actionable; a dropped fact is invisible."""
    from factory.scanners import Fact, ScanReport

    root = tmp_path / "verbose"
    view = _write(root, {"a.py": "x = 1\n"})

    report = ScanReport()
    report.facts = [
        Fact(
            pillar_id="reliability", key=f"verbose_{i}", title=f"Verbose finding {i}",
            detail="d" * 1000, severity=Severity.MAJOR,
            file_path="a.py", line_start=1, excerpt="e" * 40_000,
        )
        for i in range(8)
    ]

    evidence = build(view, _clone_for(root), report, "https://x.invalid/v")

    assert len(evidence.to_markdown()) <= MAX_DOCUMENT_CHARS
    assert len(evidence.pillars["reliability"]["facts"]) == 8
    assert all("excerpt" not in f for f in evidence.pillars["reliability"]["facts"])
    assert any("excerpt" in limit.lower() for limit in evidence.limits)
