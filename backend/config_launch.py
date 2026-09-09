# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Materialize ``factory.toml`` into the environment, before anything else reads it.

Author: Rafael M. Koike & Cursor Agent ("Ada")

The file is a **baseline**: anything already in the environment at launch wins. That ordering is
what makes a container deployment work -- compose passes real values as environment variables, and
the file supplies whatever compose did not mention, without either one having to know about the
other.

TIMING MATTERS AND IS EASY TO GET WRONG
----------------------------------------
``load()`` must run before the first import of any module that reads configuration at import time.
``app.py`` calls it as its first statement for exactly this reason. A module that snapshots
``os.environ`` into a module-level constant during import will otherwise capture the state from
before the file was applied, and the symptom -- a setting that works from the shell and not from
the config file -- is genuinely unpleasant to track down.

SECRETS ARE REFUSED, NOT WARNED ABOUT
--------------------------------------
A setting declared ``secret=True`` in the registry is rejected if it appears in the file, and the
process exits. Config files get committed; that is not a hypothetical, it is the single most common
way a credential enters a repository. A warning would be logged at startup and read by nobody.
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path
from typing import Any

import config_registry

#: Default location, overridable so an operator can keep configuration outside the checkout.
DEFAULT_PATH_ENV = "NVSF_CONFIG"
DEFAULT_FILENAME = "factory.toml"


class ConfigError(RuntimeError):
    """The configuration file exists but cannot be honoured."""


def _config_path() -> Path:
    override = os.environ.get(DEFAULT_PATH_ENV)
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent.parent / DEFAULT_FILENAME


def _flatten(doc: dict[str, Any]) -> dict[tuple[str, str], Any]:
    """``{"llm": {"model": "x"}}`` -> ``{("llm", "model"): "x"}``.

    Only two levels are supported, deliberately. A deeper tree would need a nesting convention in
    environment variable names, and the flat ``NVSF_SECTION_KEY`` shape is the thing that makes the
    file and the environment interchangeable.
    """
    flat: dict[tuple[str, str], Any] = {}
    for section, body in doc.items():
        if not isinstance(body, dict):
            raise ConfigError(
                f"top-level key '{section}' must be a table, e.g. [{section}]. "
                "Bare top-level values have no environment variable to map onto."
            )
        for key, value in body.items():
            if isinstance(value, dict):
                raise ConfigError(f"[{section}.{key}] is nested too deeply; use a flat table")
            flat[(section, key)] = value
    return flat


def _stringify(value: Any) -> str:
    """TOML is typed; the environment is not. Booleans must round-trip through the same spelling
    the registry's bool parser accepts."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def load(path: Path | None = None) -> list[str]:
    """Apply the configuration file. Returns the environment names it set, for logging.

    Absent file is not an error: a deployment configured entirely through environment variables is
    a legitimate and common setup.
    """
    target = path or _config_path()
    if not target.is_file():
        return []

    try:
        with target.open("rb") as handle:
            doc = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{target} is not valid TOML: {exc}") from exc

    flat = _flatten(doc)

    # Build the reverse index once: (section, key) -> Setting.
    by_location = {(s.section, s.key): s for s in config_registry.all_settings()}

    secrets_in_file: list[str] = []
    unknown: list[str] = []
    applied: list[str] = []

    for location, value in sorted(flat.items()):
        setting = by_location.get(location)
        if setting is None:
            unknown.append(f"[{location[0]}] {location[1]}")
            continue
        if setting.secret:
            secrets_in_file.append(f"[{location[0]}] {location[1]} -> {setting.env}")
            continue
        # setdefault semantics: the environment wins.
        if os.environ.get(setting.env) is None:
            os.environ[setting.env] = _stringify(value)
            applied.append(setting.env)

    if secrets_in_file:
        raise ConfigError(
            f"{target} contains secret settings, which are refused from a config file because "
            "config files get committed:\n  "
            + "\n  ".join(secrets_in_file)
            + "\n\nSupply these as environment variables or through a mounted secret file. If any "
            "of these values has been committed, treat it as compromised and rotate it."
        )

    if unknown:
        raise ConfigError(
            f"{target} declares settings that do not exist:\n  "
            + "\n  ".join(unknown)
            + "\n\nA typo here would otherwise be silent -- the value would sit in the file doing "
            "nothing while the default stayed in force. Check the spelling against "
            "factory.toml.example, which is generated from the registry."
        )

    return applied


def load_or_exit(path: Path | None = None) -> list[str]:
    """``load()`` for the composition root: a configuration error exits rather than raising.

    A traceback at this point is noise -- nothing has started yet and there is no useful stack. The
    operator needs the message.
    """
    try:
        return load(path)
    except ConfigError as exc:
        print(f"configuration: {exc}", file=sys.stderr)
        raise SystemExit(78) from exc  # EX_CONFIG
