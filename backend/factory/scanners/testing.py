# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Tests, quality gates, and whether either runs automatically.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Two distinct questions, and the second is the one that actually predicts whether a repository stays
working. A test suite nobody runs is documentation of past intent. A CI pipeline that runs on every
push is the thing that stops a regression reaching a customer cluster.

The scanner also looks for *untestable structure* -- work at import time, hardcoded hosts, a single
enormous function. Those are why a repository has no tests, and telling an author "add tests"
without naming them produces an agent plan that stalls on the first attempt.
"""

from __future__ import annotations

import re

from store.models import Severity

from .base import Fact, RepoView

PILLAR = "testability"

_TEST_PATH_RE = re.compile(
    r"(?i)(^|/)(tests?|__tests__|spec|testing)(/|$)|(^|/)test_[^/]+\.py$|"
    r"[^/]+_test\.(?:py|go|ts|js)$|[^/]+\.(?:test|spec)\.(?:ts|tsx|js|jsx)$"
)

_CI_FILES = (
    (".gitlab-ci.yml", "GitLab CI"),
    (".github/workflows", "GitHub Actions"),
    ("Jenkinsfile", "Jenkins"),
    (".circleci/config.yml", "CircleCI"),
    ("azure-pipelines.yml", "Azure Pipelines"),
    (".drone.yml", "Drone"),
    ("bitbucket-pipelines.yml", "Bitbucket"),
)

_LINTER_CONFIGS = (
    "ruff.toml", ".ruff.toml", ".flake8", "setup.cfg", ".pylintrc", "pylintrc",
    ".eslintrc", ".eslintrc.json", ".eslintrc.js", "eslint.config.js", "eslint.config.mjs",
    "tslint.json", ".rubocop.yml", ".golangci.yml", ".golangci.yaml", "clippy.toml",
    ".shellcheckrc", "mypy.ini", ".mypy.ini", "pyrightconfig.json", ".pre-commit-config.yaml",
)

#: Import-time side effects: the reason a module cannot be imported in a test.
_IMPORT_TIME_WORK_RE = re.compile(
    r"""(?ix)
    ^ (?!\s)                       # module level, no indentation
    (?: \w+ \s* = \s* )?
    (?:
        requests\. (?:get|post|put|delete)
      | \w*(?:connect|Client|Session|Engine|Pool) \s* \(
      | subprocess\. (?:run|call|check_output|Popen)
      | os\.system
      | \w*\.read_(?:csv|json|parquet|sql)
      | load_dotenv \s* \(
      | \w+\.mkdir \s* \(
      | open \s* \(
    )
    """
)

#: A literal IP or hostname in code -- nothing to point at a fixture.
_HARDCODED_HOST_RE = re.compile(
    r"""(?ix)
    (?<![\w.])
    (?:
        (?:10|172|192)\.\d{1,3}\.\d{1,3}\.\d{1,3}
      | \w[\w-]*\.(?:nvidia\.com|nvidia\.net|internal|local|corp)
    )
    (?![\w.])
    """
)


def _function_lengths(view: RepoView) -> list[tuple[str, int, str, int]]:
    """``(path, line, name, length)`` for each Python function, by indentation."""
    results: list[tuple[str, int, str, int]] = []
    for relative in view.python_files():
        lines = view.lines(relative)
        for index, line in enumerate(lines):
            match = re.match(r"(\s*)(?:async\s+)?def\s+(\w+)", line)
            if not match:
                continue
            indent = len(match.group(1))
            length = 0
            for following in lines[index + 1:]:
                if not following.strip():
                    length += 1
                    continue
                if len(following) - len(following.lstrip()) <= indent:
                    break
                length += 1
            results.append((relative, index + 1, match.group(2), length))
    return results


def scan(view: RepoView) -> list[Fact]:
    facts: list[Fact] = []
    all_files = view.files()
    code = view.code_files()

    # ── T1: is there a test suite ────────────────────────────────────────────────────────────
    test_files = [f for f in all_files if _TEST_PATH_RE.search(f)]
    test_code = [f for f in test_files if f.endswith((".py", ".ts", ".tsx", ".js", ".go", ".rs"))]
    production_code = [f for f in code if f not in set(test_files)]
    assertions = view.count_matches(r"\bassert\b|expect\(|\.should\b|require\.(?:Equal|NoError)",
                                    test_code)

    if not test_code:
        facts.append(Fact(
            pillar_id=PILLAR, key="no_tests",
            title="No test files",
            detail=(
                f"{len(production_code)} source file(s) and nothing that looks like a test. Every "
                "change is validated by running it against real hardware, which means the "
                "feedback loop is a maintenance window."
            ),
            criterion="T1", severity=Severity.MAJOR,
            remediation=(
                "Start with the highest-consequence path, not with coverage. One test that "
                "proves state survives a restart is worth more than fifty that check getters."
            ),
        ))
    else:
        ratio = len(test_code) / max(len(production_code), 1)
        facts.append(Fact(
            pillar_id=PILLAR, key="test_inventory",
            title=f"{len(test_code)} test file(s), {assertions} assertion(s)",
            detail=(
                f"{len(production_code)} production source file(s); ratio "
                f"{ratio:.2f} test files per source file. File counts are a weak proxy — what "
                "matters is whether the durability and failure paths are among them."
            ),
            criterion="T1",
            severity=Severity.MINOR if assertions < 5 else None,
            data={"test_files": test_code[:20], "assertions": assertions,
                  "production_files": len(production_code)},
        ))

    # ── T2: does anything run them ───────────────────────────────────────────────────────────
    ci_found = [
        label for path, label in _CI_FILES
        if any(f == path or f.startswith(f"{path}/") for f in all_files)
    ]
    if not ci_found:
        facts.append(Fact(
            pillar_id=PILLAR, key="no_ci",
            title="No CI configuration",
            detail=(
                "Nothing runs on push. Whatever checks exist run when somebody remembers, which "
                "over a quarter means they stop running."
            ),
            criterion="T2", severity=Severity.MAJOR,
            remediation=(
                "Add a pipeline that runs the linter and the tests on every push and blocks the "
                "merge on failure. Advisory CI trains people to ignore red."
            ),
        ))
    else:
        ci_text = " ".join(
            view.read(f) or "" for f in all_files
            if any(f == path or f.startswith(f"{path}/") for path, _ in _CI_FILES)
        )
        runs_tests = bool(re.search(r"(?i)pytest|unittest|go test|cargo test|npm (?:run )?test|"
                                    r"vitest|jest|tox|nox", ci_text))
        runs_lint = bool(re.search(r"(?i)ruff|flake8|pylint|eslint|golangci|clippy|shellcheck|"
                                   r"mypy|pyright|tsc", ci_text))
        allow_failure = ci_text.count("allow_failure: true") + ci_text.count(
            "continue-on-error: true")
        facts.append(Fact(
            pillar_id=PILLAR, key="ci_posture",
            title=f"CI present ({', '.join(ci_found)})",
            detail=(
                f"Runs tests: {runs_tests}. Runs a linter: {runs_lint}. "
                + (f"{allow_failure} job(s) are non-blocking, so their failures do not stop a "
                   "merge." if allow_failure else "All jobs are blocking.")
            ),
            criterion="T2",
            severity=Severity.MINOR if (test_code and not runs_tests) else None,
            data={"systems": ci_found, "runs_tests": runs_tests, "runs_lint": runs_lint,
                  "non_blocking_jobs": allow_failure},
        ))

    # ── T3: linters and formatters ───────────────────────────────────────────────────────────
    linters = [f for f in all_files if f.rsplit("/", 1)[-1] in _LINTER_CONFIGS]
    pyproject = view.read("pyproject.toml") or ""
    if "[tool.ruff" in pyproject or "[tool.black" in pyproject or "[tool.mypy" in pyproject:
        linters.append("pyproject.toml")
    facts.append(Fact(
        pillar_id=PILLAR, key="linter_config",
        title=f"{len(linters)} linter/formatter config(s)" if linters else
              "No linter or formatter configuration",
        detail=", ".join(linters) if linters else
               "Style is per-author, so diffs mix reformatting with logic changes and review gets "
               "harder than it needs to be.",
        criterion="T3",
        severity=None if linters else Severity.MINOR,
        data={"configs": linters},
    ))

    # ── T4: structure that resists testing ──────────────────────────────────────────────────
    import_time = view.grep(_IMPORT_TIME_WORK_RE, production_code, limit=25)
    if import_time:
        facts.append(Fact(
            pillar_id=PILLAR, key="import_time_side_effects",
            title=f"{len(import_time)} module(s) doing work at import time",
            detail=(
                "Opening a connection, running a subprocess, or reading a file at module scope "
                "means importing the module requires the environment to exist. A test cannot "
                "import it on a laptop, which is usually the real reason a repository has no "
                "tests."
            ),
            criterion="T4", severity=Severity.MINOR,
            file_path=import_time[0][0], line_start=import_time[0][1],
            excerpt=view.excerpt(import_time[0][0], import_time[0][1]),
            remediation=(
                "Move the work into a function the caller invokes. Import should define things, "
                "not do them."
            ),
            data={"sites": [f"{p}:{n}" for p, n, _ in import_time[:12]]},
        ))

    hardcoded_hosts = [
        (p, n, line) for p, n, line in view.grep(_HARDCODED_HOST_RE, production_code, limit=40)
        if not re.match(r"\s*#", line)
    ]
    if hardcoded_hosts:
        facts.append(Fact(
            pillar_id=PILLAR, key="hardcoded_endpoints",
            title=f"{len(hardcoded_hosts)} hardcoded host or IP address in source",
            detail=(
                "There is nothing to point at a fixture, so the code can only be exercised "
                "against that specific environment. It is also why tooling written for one "
                "customer cluster does not transfer to the next one."
            ),
            criterion="T4", severity=Severity.MINOR,
            file_path=hardcoded_hosts[0][0], line_start=hardcoded_hosts[0][1],
            excerpt=view.excerpt(hardcoded_hosts[0][0], hardcoded_hosts[0][1]),
            remediation=(
                "Read endpoints from configuration with the current value as the default. That "
                "makes the code testable and portable in the same change."
            ),
            data={"sites": [f"{p}:{n}" for p, n, _ in hardcoded_hosts[:12]]},
        ))

    long_functions = [(p, n, name, length) for p, n, name, length in _function_lengths(view)
                      if length > 80]
    if long_functions:
        worst = max(long_functions, key=lambda item: item[3])
        facts.append(Fact(
            pillar_id=PILLAR, key="long_functions",
            title=f"{len(long_functions)} function(s) longer than 80 lines",
            detail=(
                f"Longest: `{worst[2]}` at {worst[0]}:{worst[1]}, {worst[3]} lines. A function "
                "that does eight things can only be tested by doing all eight, which usually "
                "means it is not tested."
            ),
            criterion="T4",
            file_path=worst[0], line_start=worst[1],
            data={"functions": [f"{p}:{n} {name} ({length} lines)"
                                for p, n, name, length in
                                sorted(long_functions, key=lambda i: -i[3])[:10]]},
        ))

    # ── T5: coverage measurement ─────────────────────────────────────────────────────────────
    coverage_config = [f for f in all_files
                       if f.rsplit("/", 1)[-1] in {".coveragerc", "codecov.yml", ".codecov.yml"}]
    coverage_in_ci = bool(re.search(
        r"(?i)--cov|coverage run|coverage report|nyc |c8 |go test.*-cover",
        " ".join(view.read(f) or "" for f in all_files if "ci" in f.lower() or "workflow" in f),
    ))
    if test_code:
        facts.append(Fact(
            pillar_id=PILLAR, key="coverage_measurement",
            title="Coverage is measured" if (coverage_config or coverage_in_ci) else
                  "Tests exist, coverage is not measured",
            detail=(
                "Coverage is a floor, not a target — 90% of the wrong things is not safety. But "
                "without it there is no signal when a new module arrives untested."
            ),
            criterion="T5",
            data={"configs": coverage_config, "measured_in_ci": coverage_in_ci},
        ))

    return facts
