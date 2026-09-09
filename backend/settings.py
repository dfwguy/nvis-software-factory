# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Typed reads of declared settings.

Author: Rafael M. Koike & Cursor Agent ("Ada")

``config_registry`` declares what exists; this reads it. Values are resolved from the environment
on every call rather than cached, so a test can change one with ``monkeypatch.setenv`` and the
change is visible without reimporting anything.

Reading an undeclared name raises. That is the point of having a registry -- a typo in an
environment variable name would otherwise silently return the default forever.
"""

from __future__ import annotations

import os
from pathlib import Path

import config_registry

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}


class UnknownSetting(KeyError):
    """A name that is not in the registry. Almost always a typo."""


def _raw(env_name: str) -> str | None:
    setting = config_registry.get(env_name)
    if setting is None:
        raise UnknownSetting(
            f"{env_name} is not a declared setting. Add it to config_registry.py -- that is what "
            "generates the example file and the configuration reference."
        )
    value = os.environ.get(env_name)
    if value is None or value == "":
        return setting.default
    return value


def get(env_name: str, fallback: str | None = None) -> str | None:
    value = _raw(env_name)
    return fallback if value is None else value


def get_str(env_name: str, fallback: str = "") -> str:
    value = _raw(env_name)
    return fallback if value is None else value


def get_int(env_name: str, fallback: int = 0) -> int:
    value = _raw(env_name)
    if value is None:
        return fallback
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{env_name}={value!r} is not an integer") from exc


def get_float(env_name: str, fallback: float = 0.0) -> float:
    value = _raw(env_name)
    if value is None:
        return fallback
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{env_name}={value!r} is not a number") from exc


def get_bool(env_name: str, fallback: bool = False) -> bool:
    value = _raw(env_name)
    if value is None:
        return fallback
    lowered = value.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    # Deliberately strict. Silently treating "maybe" as False is how a security control ends up
    # off in production while the config file says it is on.
    raise ValueError(
        f"{env_name}={value!r} is not a boolean; use one of {sorted(_TRUE | _FALSE - {''})}"
    )


def get_path(env_name: str, fallback: Path | None = None) -> Path | None:
    value = _raw(env_name)
    if value is None:
        return fallback
    return Path(value).expanduser()


def get_list(env_name: str, separator: str = ",") -> list[str]:
    """Comma-separated setting as a list, empty entries dropped."""
    value = _raw(env_name)
    if not value:
        return []
    return [item.strip() for item in value.split(separator) if item.strip()]


def get_mapping(env_name: str) -> dict[str, str]:
    """``'a=1,b=2'`` -> ``{'a': '1', 'b': '2'}``. Used for the OIDC group-to-role map."""
    result: dict[str, str] = {}
    for pair in get_list(env_name):
        key, _, value = pair.partition("=")
        if not _:
            raise ValueError(f"{env_name} entry {pair!r} is not in key=value form")
        result[key.strip()] = value.strip()
    return result


def is_production() -> bool:
    return get_str("NVSF_ENV", "production").lower() == "production"


def is_development() -> bool:
    return not is_production()
