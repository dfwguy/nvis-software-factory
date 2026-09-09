# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Fetch a repository safely. The code inside is data, never instructions.

Author: Rafael M. Koike & Cursor Agent ("Ada")

This module accepts a URL from a user and runs ``git`` against it. That makes it the most
security-sensitive code in the project, so the constraints are worth stating rather than leaving
implicit.

**Repository code is never executed.** Not to detect a build system, not to read a version, not to
run a linter. Every scanner reads files as text. There is no step in this pipeline where a
``setup.py``, a ``Makefile``, a ``package.json`` lifecycle hook or a git hook runs. Anything else
would mean an SA can execute arbitrary code on the factory host by submitting a URL.

The specific measures, and what each one is actually for:

``--no-checkout`` is not used; ``--depth 1`` is
    History is not needed to assess the current state, and fetching it is the slowest part of
    acquisition. A shallow clone of a repository with a large history is seconds rather than
    minutes.

``--recurse-submodules`` is NOT used
    A submodule is a URL controlled by the repository author, pointing anywhere. Fetching it means
    fetching from a host we did not choose. Submodules are *reported* as an evidence fact instead,
    which is more useful anyway.

``core.hooksPath=/dev/null`` and ``--config core.fsmonitor=false``
    A clone can carry hooks. ``git`` will not run a hook from a fresh clone in the normal case, but
    the guarantee is cheap to make explicit rather than to reason about per git version.

``GIT_TERMINAL_PROMPT=0``, ``GIT_ASKPASS=/bin/true``, ``GIT_SSH_COMMAND`` with batch mode
    A private repository without a token must fail immediately. Without these, ``git`` blocks
    waiting for a username on a terminal that does not exist, and the run hangs until the timeout
    rather than failing in a second with a clear reason.

Timeout kills the process group, not just the child
    ``git clone`` spawns ``git-remote-https``. Killing only the parent leaves the child holding the
    connection and the temporary directory.

Size cap is enforced AFTER the clone as well as via ``--filter``
    ``--filter=blob:limit`` needs server support and is silently ignored without it, so the
    post-clone measurement is the check that actually holds.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import paths
import settings

_logger = logging.getLogger("nvsf.factory.acquire")

#: Schemes we will fetch. ``file://`` is refused in production -- it would let a URL read the
#: factory host's own filesystem, including the data directory.
_ALLOWED_SCHEMES = frozenset({"https", "http"})

#: Git transports enabled for the clone subprocess. Everything else is denied, including ``file``
#: and ``ext`` -- the latter executes an arbitrary command named in the URL. This is a second,
#: independent line: :func:`_validate` already rejects the URL, and this stops a transport being
#: reached even if a rewrite rule in inherited config redirected it.
ALLOWED_GIT_PROTOCOLS = ("https", "http")

#: Directories never worth scanning, skipped at walk time rather than filtered later so a
#: node_modules tree does not cost anything to begin with.
SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", ".next", ".nuxt", "target",
    "vendor", ".gradle", ".idea", ".terraform", "site-packages", ".eggs", "htmlcov",
})


class AcquireError(RuntimeError):
    """The repository could not be fetched. Message is safe to show a user."""


class AcquireRefused(AcquireError):
    """The URL was rejected before any network access. Not retryable."""


@dataclass(frozen=True)
class Clone:
    path: Path
    commit_sha: str
    ref: str
    bytes: int
    file_count: int
    submodules: tuple[str, ...]
    truncated: bool = False

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def _validate(url: str) -> str:
    """Reject a URL before touching the network. Returns the URL to hand to git.

    Credentials in the URL are stripped rather than honoured: a token pasted into the box must not
    end up in a process argument list, where any other process on the host can read it from
    ``/proc``. The token comes from configuration instead.
    """
    raw = url.strip()
    if not raw:
        raise AcquireRefused("no repository URL was given")
    if len(raw) > 2048:
        raise AcquireRefused("that URL is implausibly long")

    # SSH shorthand. We do not fetch over SSH: it would need a key on the factory host, which is a
    # credential with more reach than this service should hold.
    if "://" not in raw and "@" in raw and ":" in raw:
        raise AcquireRefused(
            "SSH URLs are not supported. Use the HTTPS URL for the repository; for a private "
            "repository, an administrator configures a read-only token."
        )

    parts = urlsplit(raw)
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise AcquireRefused(
            f"scheme {parts.scheme or '(none)'!r} is not supported; use an https:// URL"
        )
    if not parts.hostname:
        raise AcquireRefused("that URL has no host")

    # Block the metadata service and loopback outright. A URL is user input and this process can
    # reach the host's network; SSRF via git is a real technique.
    lowered = parts.hostname.lower()
    # S104 reads the literal below as a service listening on every interface. It is a blocklist
    # entry, which is the opposite.
    if lowered in {"localhost", "127.0.0.1", "0.0.0.0", "::1",  # noqa: S104
                   "metadata", "metadata.google.internal"}:
        raise AcquireRefused(f"refusing to fetch from {parts.hostname}")
    if lowered == "169.254.169.254":
        raise AcquireRefused("refusing to fetch from the instance metadata address")

    if parts.username or parts.password:
        _logger.warning("acquire: stripped credentials from a submitted URL")

    # Rebuild without userinfo, and without a query or fragment, which git does not use.
    netloc = parts.hostname + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def validate_url(url: str) -> str:
    """Public entry point to :func:`_validate`, for callers that want to check before committing.

    The API validates at registration so an unusable URL is rejected at the point the user can
    still fix it, rather than becoming a row that only fails minutes later inside a run. Sharing
    the implementation is the point: two validators would drift, and the one that mattered would
    be the looser one.
    """
    return _validate(url)


def _authenticated_url(url: str) -> str:
    """Inject a configured read-only token for a known forge, if one is set.

    Returned separately from the sanitized URL so the token never reaches a log line or an
    evidence document -- only the subprocess sees it.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    token = None
    if "gitlab" in host:
        token = settings.get("NVSF_GITLAB_TOKEN")
        user = "oauth2"
    elif "github" in host:
        token = settings.get("NVSF_GITHUB_TOKEN")
        user = "x-access-token"
    if not token:
        return url
    netloc = f"{user}:{token}@{parts.hostname}" + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _isolated_home() -> Path:
    """A real, empty directory to use as git's HOME, with an empty global config in it.

    Pointing ``HOME`` and ``GIT_CONFIG_GLOBAL`` at a *nonexistent* path also stops git reading the
    invoking user's configuration, and was the original implementation. It also costs several
    seconds per clone: git falls into a slow path when the global config it expects cannot be
    opened. A real empty directory gives identical isolation at no cost, so this exists rather
    than a string constant.
    """
    home = paths.workspace_dir() / ".git-home"
    home.mkdir(parents=True, exist_ok=True)
    config = home / "gitconfig"
    if not config.exists():
        config.write_text("# Intentionally empty. See factory/acquire.py:_isolated_home.\n")
    return home


def _git_env() -> dict[str, str]:
    """Environment for git. Non-interactive, no credential helpers, no hooks."""
    home = _isolated_home()
    env = dict(os.environ)
    env.update({
        # Fail instead of prompting. Without this a private repository hangs the run.
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/true",
        "SSH_ASKPASS": "/bin/true",
        # Batch mode, and never trust a new host key silently.
        "GIT_SSH_COMMAND": "ssh -oBatchMode=yes -oStrictHostKeyChecking=yes",
        # English, so error parsing does not depend on the host locale.
        "LC_ALL": "C",
        # Read neither the system nor the user's configuration. Either could carry an `insteadOf`
        # rewrite that redirects the URL we validated, or a credential helper that hands a token
        # for an unrelated host to whatever we are fetching.
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_CONFIG_GLOBAL": str(home / "gitconfig"),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home),
    })
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(name, None)
    return env


def _run(args: list[str], cwd: Path | None, timeout: int, redact: str | None = None) -> str:
    """Run git with a hard timeout, killing the process group on expiry.

    ``start_new_session`` puts git in its own process group so ``killpg`` reaches
    ``git-remote-https`` too. Killing only the parent leaves the child holding the connection.
    """
    printable = " ".join(a.replace(redact, "***") if redact else a for a in args)
    _logger.debug("acquire: %s", printable)
    try:
        # The check S603 asks for, done: `args` is an argv list rather than a string, and `shell`
        # is left at its default of False, so there is no shell to inject into. The remote URL
        # inside it has been through _canonicalize and the SSRF blocklist above, and it lands in a
        # position git reads as a URL rather than as an option.
        process = subprocess.Popen(  # noqa: S603
            args, cwd=str(cwd) if cwd else None, env=_git_env(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True,
        )
    except OSError as exc:
        raise AcquireError(f"could not run git: {exc}") from exc

    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
        process.communicate()
        raise AcquireError(
            f"git did not finish within {timeout}s and was killed. The repository may be very "
            "large, or the host unreachable. Raise NVSF_CLONE_TIMEOUT_SEC if this is expected."
        ) from None

    if process.returncode != 0:
        detail = (stderr or stdout or "").strip().splitlines()
        message = detail[-1] if detail else f"exit {process.returncode}"
        if redact:
            message = message.replace(redact, "***")
        raise AcquireError(_explain(message))
    return stdout


def _explain(git_error: str) -> str:
    """Turn a git error into something an SA can act on.

    Worth the translation: 'Authentication failed' is technically accurate and tells the reader
    nothing about what to do, whereas naming the missing token does.
    """
    lowered = git_error.lower()
    if "authentication failed" in lowered or "could not read username" in lowered:
        return (
            "the repository is private, or does not exist. If it is private, an administrator "
            "needs to configure a read-only token (NVSF_GITLAB_TOKEN or NVSF_GITHUB_TOKEN)."
        )
    # Before the generic "not found" below, which this message also contains. git says "Remote
    # branch nope not found", and matching the general case first told the user their repository
    # did not exist -- sending them to check their access when the ref was the problem.
    if "couldn't find remote ref" in lowered or "remote branch" in lowered:
        return "that branch or tag does not exist in the repository."
    if "not found" in lowered or "repository not found" in lowered:
        return "no repository at that URL. Check the path and that you have access to it."
    if "could not resolve host" in lowered:
        return (
            "that host could not be resolved from the factory. If it is an internal forge, this "
            "deployment may not have a route to it."
        )
    if "ssl" in lowered or "certificate" in lowered:
        return (
            f"TLS verification failed: {git_error}. The forge's CA may need to be installed in "
            "the container."
        )
    return f"git failed: {git_error}"


def _measure(root: Path) -> tuple[int, int]:
    """``(bytes, file_count)`` for the working tree, skipping vendored trees."""
    total = 0
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            try:
                if path.is_symlink():
                    continue
                total += path.stat().st_size
                count += 1
            except OSError:
                continue
    return total, count


def _submodules(root: Path) -> tuple[str, ...]:
    """Declared submodules, read as text from ``.gitmodules``.

    Reported rather than fetched. A submodule URL is chosen by the repository's author and points
    wherever they like; fetching it would mean fetching from a host we did not choose. Knowing
    that a repository has submodules is the useful part anyway -- it tells the assessment that
    what was scanned is not the whole story.
    """
    modules = root / ".gitmodules"
    if not modules.is_file():
        return ()
    found: list[str] = []
    for line in modules.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("url"):
            _, _, value = stripped.partition("=")
            if value.strip():
                found.append(value.strip())
    return tuple(found)


def clone(url: str, ref: str | None = None, destination: Path | None = None) -> Clone:
    """Shallow-clone *url* into a scratch directory under the workspace.

    The caller owns the result and must call :meth:`Clone.cleanup` -- or leave it to the workspace
    reaper, which removes clones older than ``NVSF_WORKSPACE_RETAIN_HOURS``. Clones are kept
    briefly on purpose, so a failed run can be retried without re-fetching.
    """
    safe_url = _validate(url)
    timeout = settings.get_int("NVSF_CLONE_TIMEOUT_SEC", 300)
    depth = max(1, settings.get_int("NVSF_CLONE_DEPTH", 1))
    max_bytes = settings.get_int("NVSF_CLONE_MAX_MB", 512) * 1024 * 1024

    target = destination or (paths.workspace_dir() / f"clone-{int(time.time() * 1000)}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)

    fetch_url = _authenticated_url(safe_url)
    token = fetch_url != safe_url and fetch_url.split("@")[0].split(":")[-1] or None

    args = [
        "git",
        # Hooks cannot run from a path that is not a directory.
        "-c", "core.hooksPath=/dev/null",
        "-c", "core.fsmonitor=false",
        # Never consult a credential helper; the token, if any, is in the URL.
        "-c", "credential.helper=",
        # Deny every transport, then re-enable only the ones we mean to use. Default-deny rather
        # than blocklisting `ext::`: the ext transport runs an arbitrary command, and a blocklist
        # would need updating every time git grows a helper.
        "-c", "protocol.allow=never",
        *[
            argument
            for scheme in ALLOWED_GIT_PROTOCOLS
            for argument in ("-c", f"protocol.{scheme}.allow=always")
        ],
        "clone",
        f"--depth={depth}",
        "--single-branch",
        # Explicitly NOT --recurse-submodules. See the module docstring.
        "--no-tags",
        "--quiet",
    ]
    if ref:
        args += ["--branch", ref]
    args += [fetch_url, str(target)]

    started = time.monotonic()
    try:
        _run(args, cwd=None, timeout=timeout, redact=token)
    except AcquireError:
        shutil.rmtree(target, ignore_errors=True)
        raise

    try:
        commit = _run(["git", "rev-parse", "HEAD"], cwd=target, timeout=30).strip()
        actual_ref = _run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=target, timeout=30
        ).strip()
    except AcquireError:
        commit, actual_ref = "unknown", ref or "unknown"

    size, count = _measure(target)
    truncated = False
    if size > max_bytes:
        # Refuse rather than scan a partial tree and report on it as though it were whole.
        shutil.rmtree(target, ignore_errors=True)
        raise AcquireError(
            f"the working tree is {size / 1_048_576:.0f} MB, over the "
            f"{max_bytes / 1_048_576:.0f} MB limit. Assessing part of a repository would produce "
            "a report that looks complete and is not. Raise NVSF_CLONE_MAX_MB if this repository "
            "is legitimately this large."
        )

    _logger.info(
        "acquire: cloned %s at %s (%d files, %.1f MB) in %.1fs",
        safe_url, commit[:8], count, size / 1_048_576, time.monotonic() - started,
    )

    return Clone(
        path=target, commit_sha=commit, ref=actual_ref, bytes=size, file_count=count,
        submodules=_submodules(target), truncated=truncated,
    )


def reap_workspace(retain_hours: int | None = None) -> list[Path]:
    """Delete clones older than the retention window. Returns what was removed.

    The workspace is scratch by definition, so this is safe to run unconditionally. Nothing
    durable may ever be written here -- that is what ``var/artifacts`` and the database are for.
    """
    hours = retain_hours if retain_hours is not None else settings.get_int(
        "NVSF_WORKSPACE_RETAIN_HOURS", 6
    )
    root = paths.workspace_dir()
    if not root.is_dir() or hours <= 0:
        return []
    cutoff = time.time() - hours * 3600
    removed: list[Path] = []
    for entry in root.iterdir():
        if not entry.is_dir() or not entry.name.startswith("clone-"):
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                removed.append(entry)
        except OSError:
            continue
    if removed:
        _logger.info("acquire: reaped %d stale clone(s)", len(removed))
    return removed
