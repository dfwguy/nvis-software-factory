# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""What a scanner is, and the read-only view of a repository it gets.

Author: Rafael M. Koike & Cursor Agent ("Ada")

FACTS VERSUS FINDINGS
---------------------
A scanner emits :class:`Fact` objects, and the ``severity`` field decides which kind each one is:

* ``severity is None`` -- an **observation**. Neutral, goes into the evidence document for the
  model to weigh. "There is a Dockerfile", "requests is a dependency", "no volume is declared".
* ``severity is set`` -- a **deterministic finding**. A fact established by code, which becomes a
  floor in the ratchet: the model may escalate it, never lower it.

The distinction is load-bearing, so it is one field rather than two classes. A scanner author
deciding to set a severity is deciding "I am certain enough about this that a language model should
not be allowed to talk me out of it", and that decision should be visible at the call site.

**Set a severity only when the check cannot be wrong.** "No `volumes:` key in the compose file" is
certain. "This looks like it might lose data" is not -- emit that as an observation and let the
reasoning pass judge it. A false deterministic finding is worse than a missed one, because the
ratchet means nothing can clear it except a code change here.

THE VIEW IS READ-ONLY AND NEVER EXECUTES
-----------------------------------------
:class:`RepoView` reads files as text. There is no method that runs anything, imports anything,
or resolves a dependency graph by invoking a package manager. A scanner that wants to know the
Python version reads ``pyproject.toml``; it does not run ``python -V`` in the tree.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from store.models import Severity

_logger = logging.getLogger("nvsf.factory.scanners")

#: Extensions worth reading as text. A scanner asking for something outside this set gets nothing,
#: which is deliberate: reading a 200 MB binary to grep it for "password" costs real time and
#: finds nothing useful.
TEXT_SUFFIXES = frozenset({
    ".py", ".pyi", ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte",
    ".go", ".rs", ".java", ".kt", ".rb", ".php", ".pl", ".lua", ".c", ".h", ".cpp",
    ".hpp", ".cc", ".cs", ".swift", ".scala", ".r", ".jl", ".cu", ".cuh",
    ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".conf", ".properties",
    ".env", ".tf", ".tfvars", ".hcl", ".tftpl",
    ".md", ".rst", ".txt", ".adoc",
    ".sql", ".graphql", ".proto", ".thrift",
    ".html", ".css", ".scss", ".less",
    ".dockerfile", ".containerfile", ".service", ".timer", ".sbatch", ".slurm",
    ".gitignore", ".gitattributes", ".dockerignore", ".editorconfig",
})

#: Files with no extension that are still text and still interesting.
TEXT_NAMES = frozenset({
    "Dockerfile", "Containerfile", "Makefile", "makefile", "GNUmakefile", "Jenkinsfile",
    "Procfile", "Vagrantfile", "Rakefile", "Gemfile", "Pipfile", "LICENSE", "LICENCE",
    "NOTICE", "AUTHORS", "CODEOWNERS", "requirements.txt", "constraints.txt",
})

#: Cap on a single file read. A 20 MB generated JSON has nothing a scanner needs and reading it
#: costs a second.
MAX_FILE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Fact:
    """One thing a scanner observed, with a citation.

    See the module docstring on ``severity``. Everything else here exists so a reader of the final
    report can check the claim: ``file_path`` plus ``line_start`` is what makes a finding
    actionable rather than an opinion about software in general.
    """

    pillar_id: str
    key: str
    title: str
    detail: str = ""
    criterion: str | None = None
    severity: Severity | None = None
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    #: Redacted, bounded snippet. Populated only where seeing the line helps.
    excerpt: str | None = None
    remediation: str | None = None
    #: Extra structured data for the evidence document (counts, lists, versions).
    data: dict[str, object] = field(default_factory=dict)

    @property
    def is_finding(self) -> bool:
        return self.severity is not None

    @property
    def citation(self) -> str | None:
        if not self.file_path:
            return None
        if self.line_start and self.line_end and self.line_end != self.line_start:
            return f"{self.file_path}:{self.line_start}-{self.line_end}"
        if self.line_start:
            return f"{self.file_path}:{self.line_start}"
        return self.file_path

    def to_json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "key": self.key,
            "pillar": self.pillar_id,
            "title": self.title,
        }
        if self.criterion:
            payload["criterion"] = self.criterion
        if self.detail:
            payload["detail"] = self.detail
        if self.severity:
            payload["severity"] = str(self.severity)
        if self.citation:
            payload["at"] = self.citation
        if self.excerpt:
            payload["excerpt"] = self.excerpt
        if self.remediation:
            payload["remediation"] = self.remediation
        if self.data:
            payload["data"] = self.data
        return payload


class RepoView:
    """Read-only access to a cloned working tree.

    Every path returned or accepted is **relative** to the clone root, and every read is checked
    against it. A repository can contain a symlink pointing at ``/etc/shadow`` or a path with
    ``..`` in it; without the containment check, a scanner following one would read the factory
    host's own filesystem and put the contents in an evidence document.
    """

    def __init__(self, root: Path):
        self.root = root.resolve()
        self._text_cache: dict[str, str | None] = {}
        self._listing: tuple[str, ...] | None = None

    # ── Inventory ────────────────────────────────────────────────────────────────────────────

    def files(self) -> tuple[str, ...]:
        """Every scannable file, as relative POSIX paths. Computed once."""
        if self._listing is not None:
            return self._listing

        from ..acquire import SKIP_DIRS

        found: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                absolute = Path(dirpath) / name
                if absolute.is_symlink():
                    # Not followed. A symlink out of the tree is the containment problem above,
                    # and a symlink inside it is a duplicate read.
                    continue
                try:
                    relative = absolute.relative_to(self.root).as_posix()
                except ValueError:
                    continue
                found.append(relative)
        self._listing = tuple(sorted(found))
        return self._listing

    def exists(self, relative: str) -> bool:
        return self._safe(relative) is not None

    def glob(self, pattern: str) -> list[str]:
        """Files matching a glob, over the cached listing.

        Matching over the listing rather than the filesystem keeps the skip rules in one place:
        ``glob("**/*.py")`` cannot accidentally reach into ``node_modules``.
        """
        import fnmatch

        # fnmatch has no notion of path segments, so '*' would cross directories. Normalize the
        # common '**/' prefix into "anywhere".
        if pattern.startswith("**/"):
            tail = pattern[3:]
            return [f for f in self.files() if fnmatch.fnmatch(f.rsplit("/", 1)[-1], tail)
                    or fnmatch.fnmatch(f, pattern[3:])]
        return [f for f in self.files() if fnmatch.fnmatch(f, pattern)]

    def find_names(self, *names: str) -> list[str]:
        """Files whose basename matches any of *names*, case-insensitively."""
        wanted = {n.lower() for n in names}
        return [f for f in self.files() if f.rsplit("/", 1)[-1].lower() in wanted]

    def by_suffix(self, *suffixes: str) -> list[str]:
        wanted = {s.lower() if s.startswith(".") else f".{s.lower()}" for s in suffixes}
        return [f for f in self.files() if Path(f).suffix.lower() in wanted]

    # ── Reading ──────────────────────────────────────────────────────────────────────────────

    def _safe(self, relative: str) -> Path | None:
        """Resolve a relative path, or None if it escapes the tree or does not exist."""
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            _logger.warning("scanners: refused a path outside the clone: %s", relative)
            return None
        return candidate if candidate.is_file() else None

    def read(self, relative: str) -> str | None:
        """File contents as text, or None if it is missing, binary, or too large.

        Cached, because several scanners read the same handful of files -- the Dockerfile, the
        compose file, ``requirements.txt`` -- and re-reading them is pure waste.
        """
        if relative in self._text_cache:
            return self._text_cache[relative]

        result: str | None = None
        path = self._safe(relative)
        if path is not None and self._is_textual(relative):
            try:
                if path.stat().st_size <= MAX_FILE_BYTES:
                    raw = path.read_bytes()
                    # A NUL byte in the first block is the reliable binary signal; extension
                    # lists get it wrong for generated files.
                    if b"\x00" not in raw[:8192]:
                        result = raw.decode("utf-8", errors="replace")
            except OSError:
                result = None

        self._text_cache[relative] = result
        return result

    @staticmethod
    def _is_textual(relative: str) -> bool:
        name = relative.rsplit("/", 1)[-1]
        if name in TEXT_NAMES:
            return True
        suffix = Path(name).suffix.lower()
        if suffix in TEXT_SUFFIXES:
            return True
        # Dotfiles and Dockerfile.foo variants
        if name.startswith(".") and "." not in name[1:]:
            return True
        return name.lower().startswith(("dockerfile", "containerfile", "makefile"))

    def lines(self, relative: str) -> list[str]:
        text = self.read(relative)
        return text.splitlines() if text else []

    def excerpt(self, relative: str, line: int, context: int = 1) -> str | None:
        """A redacted snippet around *line*, 1-indexed.

        Redacted here, at the point of extraction, rather than by the caller. That is the
        difference between a boundary and a convention.
        """
        from ..redact import redact_excerpt

        all_lines = self.lines(relative)
        if not all_lines or line < 1 or line > len(all_lines):
            return None
        start = max(0, line - 1 - context)
        end = min(len(all_lines), line + context)
        return redact_excerpt("\n".join(all_lines[start:end]))

    # ── Searching ────────────────────────────────────────────────────────────────────────────

    def grep(
        self,
        pattern: str | re.Pattern[str],
        paths: list[str] | None = None,
        limit: int = 200,
    ) -> list[tuple[str, int, str]]:
        """``(path, line_number, line)`` for each match, bounded.

        ``limit`` is not a performance guard, it is an evidence-size guard. A repository with a
        thousand ``print()`` calls should contribute one finding and a count, not a thousand
        citations that blow the model's context and tell it nothing more than ten would.
        """
        compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
        targets = paths if paths is not None else list(self.files())
        results: list[tuple[str, int, str]] = []
        for relative in targets:
            for number, line in enumerate(self.lines(relative), start=1):
                if compiled.search(line):
                    results.append((relative, number, line.rstrip()))
                    if len(results) >= limit:
                        return results
        return results

    def count_matches(self, pattern: str | re.Pattern[str], paths: list[str] | None = None) -> int:
        """Total matches with no citation cap. For "how widespread is this" questions."""
        compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
        targets = paths if paths is not None else list(self.files())
        return sum(
            1
            for relative in targets
            for line in self.lines(relative)
            if compiled.search(line)
        )

    # ── Shape of the repository ──────────────────────────────────────────────────────────────

    def languages(self) -> dict[str, int]:
        """File count per language, most common first. Cheap archetype signal."""
        mapping = {
            ".py": "Python", ".sh": "Shell", ".bash": "Shell", ".ts": "TypeScript",
            ".tsx": "TypeScript", ".js": "JavaScript", ".jsx": "JavaScript", ".go": "Go",
            ".rs": "Rust", ".java": "Java", ".rb": "Ruby", ".c": "C", ".cpp": "C++",
            ".cu": "CUDA", ".ps1": "PowerShell", ".tf": "Terraform", ".ipynb": "Notebook",
            ".sql": "SQL", ".yaml": "YAML", ".yml": "YAML",
        }
        counts: dict[str, int] = {}
        for relative in self.files():
            language = mapping.get(Path(relative).suffix.lower())
            if language:
                counts[language] = counts.get(language, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))

    def python_files(self) -> list[str]:
        return self.by_suffix(".py")

    def code_files(self) -> list[str]:
        """Source files, excluding documentation and configuration.

        Several scanners only make sense against code -- a ``print()`` in a README code block is
        not an observability finding.
        """
        return [
            f for f in self.files()
            if Path(f).suffix.lower() in {
                ".py", ".sh", ".bash", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java",
                ".rb", ".c", ".cpp", ".cu", ".ps1",
            }
        ]


class Scanner(Protocol):
    """What every scanner module exposes.

    A module in this package qualifies by defining ``PILLAR`` and ``scan(view) -> list[Fact]``.
    Discovery walks the package, exactly as the API blueprint loader does, so adding a scanner is
    adding a file.
    """

    PILLAR: str

    def scan(self, view: RepoView) -> list[Fact]:  # pragma: no cover - protocol
        ...
