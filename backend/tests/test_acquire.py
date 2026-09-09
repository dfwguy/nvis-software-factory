# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The clone sandbox: fetching a stranger's repository without running any of it.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Cloning is the one place this application executes another program against input a user supplied,
and git is far more programmable than it looks. A repository can ask for its own hooks to run, can
declare submodules pointing at hosts nobody chose, and -- through the ``ext::`` transport -- can
name a shell command for git to execute. None of those need a bug in this code to happen; they are
git working as designed.

So the argv this module builds is a security control, and the tests below read it as one. They
assert the flags rather than the outcome because the outcome, if a flag were dropped, would be
arbitrary code execution that no assertion about the returned tree would notice.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest


@pytest.fixture
def acquire(data_dir):
    from factory import acquire as module

    return module


@pytest.fixture
def captured_git(acquire, monkeypatch):
    """Record the argv git would have been run with, and fake a successful clone."""
    calls: list[list[str]] = []

    def fake_run(args, cwd, timeout, redact=None):
        calls.append(list(args))
        if args[:2] == ["git", "rev-parse"]:
            return "abc123def456\n" if "HEAD" == args[-1] else "main\n"
        # The clone itself: create the destination so the code after it has a tree to measure.
        Path(args[-1]).mkdir(parents=True, exist_ok=True)
        (Path(args[-1]) / "README.md").write_text("hello", encoding="utf-8")
        return ""

    monkeypatch.setattr(acquire, "_run", fake_run)
    return calls


# ── The argv, read as a security control ─────────────────────────────────────────────────────


def test_transports_are_default_deny(acquire, captured_git):
    """`ext::` runs an arbitrary command as the user git runs as.

    A blocklist would need a new entry every time git grows a helper, and the entry would be added
    after the technique was published. Denying everything and re-enabling http(s) inverts that:
    a new transport is unusable until somebody decides otherwise.
    """
    acquire.clone("https://gitlab.example.com/nvis/example.git")

    argv = captured_git[0]
    assert "protocol.allow=never" in argv, "transports are not default-deny"

    allowed = {a.split(".")[1] for a in argv if a.startswith("protocol.") and a.endswith("=always")}
    assert allowed == {"https", "http"}, f"unexpected transports enabled: {allowed}"


def test_hooks_cannot_run(acquire, captured_git):
    """A repository ships its own hooks, and a clone can be made to run one."""
    acquire.clone("https://gitlab.example.com/nvis/example.git")

    assert "core.hooksPath=/dev/null" in captured_git[0]


def test_no_credential_helper_is_consulted(acquire, captured_git):
    """Otherwise a clone can pick up the host's git credentials, and the sandbox is fetching with
    permissions the requesting user does not have."""
    acquire.clone("https://gitlab.example.com/nvis/example.git")

    assert "credential.helper=" in captured_git[0]


def test_submodules_are_not_fetched(acquire, captured_git):
    """A submodule URL is chosen by the repository's author. Recursing means making outbound
    connections to hosts this deployment never approved."""
    acquire.clone("https://gitlab.example.com/nvis/example.git")

    argv = captured_git[0]
    assert "--recurse-submodules" not in argv
    assert not any(a.startswith("--recurse") for a in argv)


def test_the_clone_is_shallow_and_single_branch(acquire, captured_git):
    """History is not what is being assessed, and a deep clone of a large repository is the
    difference between a run that takes a minute and one that times out."""
    acquire.clone("https://gitlab.example.com/nvis/example.git")

    argv = captured_git[0]
    assert any(a.startswith("--depth=") for a in argv)
    assert "--single-branch" in argv
    assert "--no-tags" in argv


def test_a_ref_is_passed_as_a_branch_rather_than_interpolated(acquire, captured_git):
    """`--branch` `<value>` as two argv entries: a ref is user input, and anything that lets it
    start with a dash lets it be read as an option."""
    acquire.clone("https://gitlab.example.com/nvis/example.git", ref="release/2.1")

    argv = captured_git[0]
    assert argv[argv.index("--branch") + 1] == "release/2.1"


def test_the_url_is_canonicalized_before_it_reaches_git(acquire, captured_git):
    acquire.clone("https://gitlab.example.com/nvis/example/")

    assert captured_git[0][-2].startswith("https://gitlab.example.com/nvis/example")


# ── Refusals ─────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("url", [
    "ext::sh -c 'touch /tmp/pwned'",
    "file:///etc/passwd",
    "git://example.com/x.git",
    "ssh://git@example.com/x.git",
    "https://127.0.0.1/x.git",
    "https://169.254.169.254/x.git",
    "https://localhost/x.git",
    "not a url",
    "",
])
def test_a_dangerous_url_never_reaches_git(acquire, captured_git, url):
    """Refused during validation, so the process is never started at all."""
    with pytest.raises(acquire.AcquireRefused):
        acquire.clone(url)

    assert captured_git == [], f"{url!r} reached git"


def test_a_tree_over_the_size_limit_is_refused_rather_than_truncated(
    acquire, monkeypatch, captured_git
):
    """Scanning part of a repository and reporting on it as though it were whole is the failure
    mode this whole project exists to prevent: an answer that looks complete and is not."""
    monkeypatch.setenv("NVSF_CLONE_MAX_MB", "1")
    monkeypatch.setattr(acquire, "_measure", lambda root: (50 * 1024 * 1024, 10))

    with pytest.raises(acquire.AcquireError, match="over the"):
        acquire.clone("https://gitlab.example.com/nvis/huge.git")


def test_an_oversized_clone_is_deleted(acquire, monkeypatch, captured_git):
    """Otherwise a refusal still costs the disk space it refused to use."""
    monkeypatch.setenv("NVSF_CLONE_MAX_MB", "1")
    monkeypatch.setattr(acquire, "_measure", lambda root: (50 * 1024 * 1024, 10))

    with pytest.raises(acquire.AcquireError):
        acquire.clone("https://gitlab.example.com/nvis/huge.git")

    import paths

    assert not list(paths.workspace_dir().glob("clone-*")), "the refused clone was left on disk"


def test_a_failed_clone_leaves_nothing_behind(acquire, monkeypatch):
    def fail(args, cwd, timeout, redact=None):
        Path(args[-1]).mkdir(parents=True, exist_ok=True)
        raise acquire.AcquireError("git failed: repository not found")

    monkeypatch.setattr(acquire, "_run", fail)

    with pytest.raises(acquire.AcquireError):
        acquire.clone("https://gitlab.example.com/nvis/missing.git")

    import paths

    assert not list(paths.workspace_dir().glob("clone-*"))


# ── Error translation ────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("git_says", "should_mention"), [
    ("fatal: Authentication failed for 'https://...'", "token"),
    ("remote: Repository not found.", "access"),
    ("fatal: unable to access '...': Could not resolve host: forge.internal", "route"),
    ("fatal: unable to access '...': SSL certificate problem", "CA"),
    ("fatal: Remote branch nope not found: couldn't find remote ref", "branch"),
])
def test_a_git_error_is_translated_into_something_actionable(
    acquire, git_says, should_mention
):
    """'Authentication failed' is accurate and tells an SA nothing about what to do next."""
    assert should_mention.lower() in acquire._explain(git_says).lower()


def test_an_unrecognized_git_error_is_passed_through(acquire):
    """Better a raw message than a confident wrong translation."""
    assert "something new" in acquire._explain("something new went wrong")


# ── Measuring and inspecting the tree ────────────────────────────────────────────────────────


def test_measure_skips_vendored_trees(acquire, tmp_path):
    """node_modules is not the SA's code, and including it makes every JavaScript repository look
    like it is over the size limit."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x" * 100, encoding="utf-8")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("y" * 100_000, encoding="utf-8")

    size, count = acquire._measure(tmp_path)

    assert count == 1, "a vendored file was counted"
    assert size == 100


def test_measure_does_not_follow_symlinks(acquire, tmp_path):
    """A repository can contain a symlink to anywhere. Following it would measure -- and later
    read -- files outside the clone."""
    (tmp_path / "real.txt").write_text("x" * 10, encoding="utf-8")
    (tmp_path / "escape").symlink_to("/etc/passwd")

    size, count = acquire._measure(tmp_path)

    assert count == 1
    assert size == 10


def test_submodules_are_reported_not_fetched(acquire, tmp_path):
    """Knowing a repository has submodules is the useful part: it tells the assessment that what
    was scanned is not the whole story."""
    (tmp_path / ".gitmodules").write_text(
        '[submodule "vendor/lib"]\n'
        "\tpath = vendor/lib\n"
        "\turl = https://github.com/someone/lib.git\n",
        encoding="utf-8",
    )

    assert acquire._submodules(tmp_path) == ("https://github.com/someone/lib.git",)


def test_no_gitmodules_means_no_submodules(acquire, tmp_path):
    assert acquire._submodules(tmp_path) == ()


# ── The workspace reaper ─────────────────────────────────────────────────────────────────────


def test_the_reaper_removes_stale_clones(acquire, tmp_path, monkeypatch):
    """The workspace is scratch. Left alone it fills the same disk the database lives on."""
    import paths

    workspace = paths.workspace_dir()
    workspace.mkdir(parents=True, exist_ok=True)

    stale = workspace / "clone-1"
    stale.mkdir()
    old = time.time() - 48 * 3600
    import os

    os.utime(stale, (old, old))

    fresh = workspace / "clone-2"
    fresh.mkdir()

    removed = acquire.reap_workspace(retain_hours=6)

    assert stale in removed
    assert not stale.exists()
    assert fresh.exists(), "the reaper deleted a clone still inside the retention window"


def test_the_reaper_ignores_anything_that_is_not_a_clone(acquire):
    """It runs unconditionally at startup, so it must not be able to delete something else."""
    import paths

    workspace = paths.workspace_dir()
    workspace.mkdir(parents=True, exist_ok=True)
    keep = workspace / "important"
    keep.mkdir()
    import os

    old = time.time() - 48 * 3600
    os.utime(keep, (old, old))

    acquire.reap_workspace(retain_hours=1)

    assert keep.exists()


def test_a_retention_of_zero_disables_the_reaper(acquire):
    assert acquire.reap_workspace(retain_hours=0) == []
