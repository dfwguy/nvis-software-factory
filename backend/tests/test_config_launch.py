# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Loading factory.toml, and the two refusals that make it safe to have at all.

Author: Rafael M. Koike & Cursor Agent ("Ada")

A config file is a convenience with two sharp edges. It gets committed, so a secret in one ends up
in git history -- which is why a secret-flagged setting in the file is refused rather than warned
about. And a typo in a key is silent by nature: the setting keeps its default and the deployment
behaves in a way nobody configured, so an unknown key is refused too.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def loader():
    import config_launch

    return config_launch


def _write(tmp_path, text):
    path = tmp_path / "factory.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_missing_file_is_not_an_error(loader, tmp_path):
    """Every setting has an environment variable, so running without the file is a supported way
    to deploy -- the container image does exactly that."""
    assert loader.load(tmp_path / "nope.toml") == []


def test_values_reach_the_environment_under_their_declared_names(loader, tmp_path, monkeypatch):
    monkeypatch.delenv("NVSF_LOG_LEVEL", raising=False)
    path = _write(tmp_path, '[logging]\nlevel = "DEBUG"\n')

    applied = loader.load(path)

    assert "NVSF_LOG_LEVEL" in applied
    assert os.environ["NVSF_LOG_LEVEL"] == "DEBUG"


def test_the_environment_wins_over_the_file(loader, tmp_path, monkeypatch):
    """setdefault, not assignment. The file is the site's baseline; the environment is what the
    operator passed to this specific run, usually to debug the thing the file is doing."""
    monkeypatch.setenv("NVSF_LOG_LEVEL", "ERROR")
    path = _write(tmp_path, '[logging]\nlevel = "DEBUG"\n')

    loader.load(path)

    assert os.environ["NVSF_LOG_LEVEL"] == "ERROR"


def test_booleans_and_numbers_survive_the_trip(loader, tmp_path, monkeypatch):
    """TOML has real types and the environment has only strings, so something has to convert. A
    bool arriving as "True" would be truthy under every parser that expects "true"."""
    monkeypatch.delenv("NVSF_LOG_JSON", raising=False)
    monkeypatch.delenv("NVSF_WEB_WORKERS", raising=False)
    path = _write(tmp_path, "[logging]\njson = true\n\n[runtime]\nweb_workers = 4\n")

    loader.load(path)

    assert os.environ["NVSF_LOG_JSON"] == "true"
    assert os.environ["NVSF_WEB_WORKERS"] == "4"


def test_a_secret_in_the_file_is_refused(loader, tmp_path):
    """The whole reason `secret` exists in the registry.

    Refused, not warned about: a warning scrolls past during a deployment, and by the time anyone
    reads it the credential is committed. The failure has to be at boot, and it has to be loud.
    """
    path = _write(tmp_path, '[llm]\napi_key = "nvapi-not-a-real-key"\n')

    with pytest.raises(loader.ConfigError, match="secret"):
        loader.load(path)


def test_the_refusal_does_not_quote_the_secret_back(loader, tmp_path):
    """An error message ends up in CI logs, terminals and screenshots."""
    path = _write(tmp_path, '[llm]\napi_key = "nvapi-not-a-real-key"\n')

    with pytest.raises(loader.ConfigError) as caught:
        loader.load(path)

    assert "nvapi-not-a-real-key" not in str(caught.value)


def test_an_unknown_key_is_refused(loader, tmp_path):
    """A typo'd setting is worse than a missing one: the default applies and the deployment runs
    with a configuration nobody chose, looking exactly like a working one."""
    path = _write(tmp_path, '[logging]\nlevl = "DEBUG"\n')

    with pytest.raises(loader.ConfigError, match="unknown"):
        loader.load(path)


def test_malformed_toml_names_the_file(loader, tmp_path):
    path = _write(tmp_path, "[logging\nlevel =\n")

    with pytest.raises(loader.ConfigError) as caught:
        loader.load(path)

    assert "factory.toml" in str(caught.value)


def test_load_or_exit_exits_78_rather_than_raising(loader, tmp_path, capsys):
    """EX_CONFIG. A configuration problem is not a crash, and the exit code says so to whatever
    supervises the process -- which is the difference between "restart it" and "fix it"."""
    path = _write(tmp_path, '[llm]\napi_key = "nvapi-not-a-real-key"\n')

    with pytest.raises(SystemExit) as caught:
        loader.load_or_exit(path)

    assert caught.value.code == 78
    assert "secret" in capsys.readouterr().err
