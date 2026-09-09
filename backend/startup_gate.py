# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Refuse to start in a configuration that cannot work correctly.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Reliability criterion R6, applied to ourselves: required configuration is validated at startup, not
at first use. Failing at boot is a deployment error somebody sees while they are still looking at
the terminal. Failing at first use is an incident at 2am, discovered by a user.

Every check reports ALL of its problems in one pass rather than the first one. Discovering
misconfiguration one restart at a time turns a five-minute task into an afternoon.

WHY THE LLM CHECK IS HERE
--------------------------
This application is AI-first: reasoning is a required pipeline stage, not an enhancement. There is
deliberately no degraded mode that emits a thinner report when the endpoint is missing, because a
report that looks like a real report but is not is worse than no report -- the reader cannot tell
the difference. So a missing endpoint is a startup failure, in the same category as a missing
database.

Note the check is *configuration*, not *reachability*. An endpoint that is configured but
temporarily down must not prevent the app from starting, or a transient upstream outage becomes a
crash loop. Reachability is a health-endpoint question, and an assessment run that cannot reach the
endpoint fails that run, retryably.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import secrets
import stat

import config_registry
import paths
import settings

_logger = logging.getLogger("nvsf.startup")

#: Written on first start so a restart does not invalidate every session.
_SESSION_SECRET_FILE = "session-secret"


class StartupRefused(RuntimeError):
    """The configuration cannot work. The message lists every problem found."""


def _is_loopback(addr: str) -> bool:
    if addr in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False


def _check_required() -> list[str]:
    problems = []
    for setting in config_registry.missing_required():
        problems.append(
            f"{setting.env} is required and unset — {setting.description.split('.')[0]}."
        )
    for setting, value in config_registry.invalid_choices():
        problems.append(
            f"{setting.env}={value!r} is not one of {', '.join(setting.choices)}."
        )
    return problems


def _check_data_dir() -> list[str]:
    """The data directory must exist and be writable, and we must say so if it does not.

    Durability criterion D1 turned on ourselves: an app that silently falls back to a path inside
    the container looks healthy right up until the restart that discards everything.
    """
    root = paths.data_dir()
    try:
        paths.ensure_runtime_dirs()
    except OSError as exc:
        return [
            (
                f"data directory {root} is not usable: {exc}. In a container this is a bind "
                "mount; check the compose volume and the host directory's ownership."
            )
        ]

    probe = root / ".write-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return [f"data directory {root} is not writable: {exc}"]
    return []


def _check_llm() -> list[str]:
    """Configuration only. Reachability belongs to the health endpoint (see module docstring)."""
    problems = []
    if not settings.get("NVSF_LLM_BASE_URL"):
        problems.append(
            "NVSF_LLM_BASE_URL is unset. Reasoning is a required stage of every assessment and "
            "there is no degraded mode by design, so the application does not start without an "
            "endpoint. Point it at an internal NIM deployment or any OpenAI-compatible service."
        )
    if not settings.get("NVSF_LLM_MODEL"):
        problems.append(
            "NVSF_LLM_MODEL is unset. The model id is recorded with every assessment so results "
            "stay reproducible; it cannot be inferred."
        )
    base_url = settings.get_str("NVSF_LLM_BASE_URL")
    if base_url and not base_url.startswith(("http://", "https://")):
        problems.append(f"NVSF_LLM_BASE_URL={base_url!r} is not an http(s) URL.")
    if base_url.startswith("http://") and settings.is_production():
        problems.append(
            "NVSF_LLM_BASE_URL is plaintext http in production. The API key would cross the "
            "network in the clear on every call."
        )
    return problems


def _check_identity() -> list[str]:
    """OIDC-only. The mock provider is the one thing that must never reach a deployment."""
    problems: list[str] = []
    mock = settings.get_bool("NVSF_OIDC_MOCK", False)
    bind = settings.get_str("NVSF_BIND_ADDR", "127.0.0.1")

    if mock:
        # Two independent conditions, both required. Either alone is too easy to satisfy by
        # accident: NVSF_ENV can be copied from a dev .env, and a loopback bind can be fronted by
        # a reverse proxy.
        if settings.is_production():
            problems.append(
                "NVSF_OIDC_MOCK is on but NVSF_ENV=production. The mock provider logs in a fixed "
                "user without authenticating anyone; it exists for local development only."
            )
        if not _is_loopback(bind):
            problems.append(
                f"NVSF_OIDC_MOCK is on but NVSF_BIND_ADDR={bind} is not loopback. The mock "
                "provider must never be reachable from another host."
            )
        if not problems:
            _logger.warning(
                "identity: MOCK provider active — every request is authenticated as a fixed "
                "development user. This is refused outside loopback development."
            )
        return problems

    for env in ("NVSF_OIDC_ISSUER", "NVSF_OIDC_CLIENT_ID"):
        if not settings.get(env):
            problems.append(
                f"{env} is unset and the mock provider is off. Authentication is OIDC-only, so "
                "nobody can sign in until a client is registered with the identity provider. For "
                "local work set NVSF_ENV=development and NVSF_OIDC_MOCK=true."
            )

    public = settings.get_str("NVSF_PUBLIC_URL")
    if public.endswith("/"):
        problems.append(
            f"NVSF_PUBLIC_URL={public!r} has a trailing slash. The redirect URI is built from it "
            "and must match what is registered with the provider exactly."
        )
    if public.startswith("http://") and settings.is_production():
        problems.append(
            "NVSF_PUBLIC_URL is plaintext http in production. Session cookies are marked Secure, "
            "so sign-in would silently never complete."
        )

    if not settings.get_list("NVSF_OIDC_ADMIN_GROUPS"):
        # Not fatal. A deployment with no admins is safe, just not yet useful.
        _logger.warning(
            "identity: NVSF_OIDC_ADMIN_GROUPS is empty, so no user will hold the admin role. "
            "Set it to the group that should administer this deployment."
        )
    return problems


def _check_transport() -> list[str]:
    if not settings.is_production():
        return []
    cert = settings.get_path("NVSF_TLS_CERT")
    key = settings.get_path("NVSF_TLS_KEY")
    if not cert or not key:
        return [
            (
                "NVSF_TLS_CERT and NVSF_TLS_KEY are required in production. Session cookies are "
                "issued Secure and an OIDC redirect will not complete over plaintext. Set "
                "NVSF_ENV=development for local work, or terminate TLS at a proxy and set "
                "NVSF_TRUST_PROXY_TLS if that is your topology."
            )
        ]
    problems = []
    for label, item in (("NVSF_TLS_CERT", cert), ("NVSF_TLS_KEY", key)):
        if not item.is_file():
            problems.append(f"{label}={item} does not exist.")
    return problems


def ensure_session_secret() -> str:
    """Return the cookie signing key, generating and persisting one on first start.

    Persisted rather than regenerated per boot, because a fresh key invalidates every session and
    a service that logs everyone out when it restarts trains people to distrust it.
    """
    configured = settings.get("NVSF_SESSION_SECRET")
    if configured:
        return configured

    path = paths.data_dir() / _SESSION_SECRET_FILE
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()

    value = secrets.token_urlsafe(48)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    _logger.info("identity: generated a session signing key at %s", path)
    return value


def _check_contracts() -> list[str]:
    """The published contract must compile, resolve, and actually enforce its format assertions.

    A malformed schema, a dangling ``$ref``, or a missing format validator is a deployment defect,
    not a runtime condition. Left to surface on first use, the first two are a 500 for whichever
    team validates against us first, and the third is worse -- it is a silent pass, so the team
    ships an integration we told them was conformant when we had not checked.

    The crosswalks are checked too, because a crosswalk that names a field the contract no longer
    has is indistinguishable from a working one until an import quietly drops the value.
    """
    from contracts import crosswalk, loader

    problems = [f"contract: {problem}" for problem in loader.self_check()]
    problems += [f"crosswalk: {problem}" for problem in crosswalk.check_all()]
    return problems


def prepare() -> None:
    """Run every check. Raises :class:`StartupRefused` listing all problems found."""
    problems: list[str] = []
    problems += _check_required()
    problems += _check_data_dir()
    problems += _check_llm()
    problems += _check_identity()
    problems += _check_transport()
    problems += _check_contracts()

    if problems:
        numbered = "\n".join(f"  {i}. {p}" for i, p in enumerate(problems, 1))
        raise StartupRefused(
            f"refusing to start — {len(problems)} configuration problem(s):\n{numbered}\n\n"
            "Every setting is documented in factory.toml.example, which is generated from "
            "backend/config_registry.py."
        )

    os.environ.setdefault("NVSF_SESSION_SECRET", ensure_session_secret())
    _logger.info(
        "startup: checks passed — env=%s data_dir=%s llm=%s",
        settings.get_str("NVSF_ENV"), paths.data_dir(), settings.get_str("NVSF_LLM_MODEL"),
    )
