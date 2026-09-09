# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Shared fixtures.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Every test runs against a temporary data directory. No test touches ``var/``, and the suite runs
with no cluster, no BMC and no network -- testability criterion T2, applied to ourselves. If a test
here needs a live anything, that is a design problem in the code under test, not a missing fixture.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A throwaway data directory, with the store's thread-local connection reset around it.

    Resetting matters: the connection is cached per thread, so a test that changed
    ``NVSF_DATA_DIR`` without clearing it would keep writing to the previous test's database and
    the failure would land in whichever test ran next.
    """
    from store import db

    db.close_connection()
    monkeypatch.setenv("NVSF_DATA_DIR", str(tmp_path))
    yield tmp_path
    db.close_connection()


@pytest.fixture
def migrated(data_dir):
    """A migrated, empty database."""
    from store import migrations

    migrations.apply()
    return data_dir


@pytest.fixture(scope="session")
def _app_module(tmp_path_factory):
    """The real application, imported once.

    ``app.py`` is a composition root: importing it runs the startup gate, applies migrations and
    registers blueprints. That is the point -- these tests exercise the app as it actually starts,
    not a stripped-down factory that could diverge from it.

    Session-scoped because module-level side effects cannot be undone by reimporting, and
    deliberately so: a test that needed a differently-configured app would be testing a
    configuration this app never runs in.
    """
    import os

    root = tmp_path_factory.mktemp("app-data")
    os.environ.update({
        "NVSF_ENV": "development",
        "NVSF_DATA_DIR": str(root),
        "NVSF_BIND_ADDR": "127.0.0.1",
        "NVSF_PUBLIC_URL": "http://127.0.0.1:8000",
        # Configured but pointed at a closed port. The startup gate checks configuration, not
        # reachability, so this is exactly the state a real deployment is in when its endpoint is
        # briefly down -- and the app must still start.
        "NVSF_LLM_BASE_URL": "http://127.0.0.1:1/v1",
        "NVSF_LLM_MODEL": "test-model",
        "NVSF_OIDC_MOCK": "true",
        "NVSF_LOG_LEVEL": "WARNING",
    })
    import app as app_module

    return app_module


@pytest.fixture
def app_client(_app_module):
    """A test client authenticated as the mock development admin."""
    return _app_module.app.test_client()


@pytest.fixture
def anonymous_client(_app_module, monkeypatch):
    """A test client with no session.

    Turning the mock provider off is what makes this anonymous: with it on, every request is the
    development admin, which would make an authorization test pass for the wrong reason.
    """
    monkeypatch.setenv("NVSF_OIDC_MOCK", "false")
    return _app_module.app.test_client()


@pytest.fixture
def llm_env(monkeypatch):
    """Minimum configuration for the startup gate to pass in development."""
    monkeypatch.setenv("NVSF_ENV", "development")
    monkeypatch.setenv("NVSF_PUBLIC_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("NVSF_LLM_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("NVSF_LLM_MODEL", "test-model")
    monkeypatch.setenv("NVSF_OIDC_MOCK", "true")
    monkeypatch.setenv("NVSF_BIND_ADDR", "127.0.0.1")
