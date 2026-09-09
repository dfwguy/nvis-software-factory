# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Replace credential-shaped values with descriptions of their shape.

Author: Rafael M. Koike & Cursor Agent ("Ada")

The redaction boundary. This runs in the evidence layer, **before** serialization -- not in the
prompt builder. That placement is the whole point: if redaction happened at the prompt, then the
evidence document persisted in the database would still hold the credential, and so would the
audit trail, and so would any future export.

WHAT MAKES THIS DIFFERENT FROM A LOG SCRUBBER
----------------------------------------------
``logging_config.redact`` replaces a value with ``***REDACTED***``, which is right for a log line.
Here we replace it with a *description*: ``<redacted: AWS-access-key-shaped, 20 chars>``.

The difference matters because the finding has to survive redaction. "There is a hardcoded
credential at ``config.py:14``" is the useful output, and the model needs enough to judge how bad
it is -- an AWS key in a tracked file is worse than a placeholder that says ``changeme``. The shape
description carries that, and the value does not leave the process.

It also lets us tell a real secret from a placeholder, which is the single largest source of false
positives in secret scanning. ``password = "changeme"`` is a documentation example;
``password = "hunter2Wq!x9"`` is an incident.

LIMITS, STATED
--------------
This is a net, not a wall. A high-entropy string with no recognisable prefix, sitting in a
variable named ``data``, will pass. The wall is not putting credentials in the repository in the
first place, which is what the data-security pillar asks for. This makes the common cases visible.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

#: Values that are obviously placeholders. Case-insensitive exact match after stripping.
#: Suppressing these is what keeps the secrets scanner credible: a scanner that flags every
#: ``password = "changeme"`` in a README gets ignored wholesale, and then the real one is missed
#: too.
PLACEHOLDERS = frozenset({
    "", "changeme", "change_me", "change-me", "password", "passwd", "secret", "todo",
    "xxx", "xxxx", "yourpassword", "your_password", "your-password", "yourtoken",
    "your_token", "your-token", "yourkey", "your_key", "example", "test", "dummy",
    "placeholder", "redacted", "none", "null", "nil", "n/a", "na", "foo", "bar", "baz",
    "hunter2", "letmein", "admin", "root", "user", "sample", "insert_key_here",
    "<your-key>", "<token>", "<password>", "...", "***", "${env}", "abc123", "12345",
    "notasecret", "fake", "mock", "unset", "default",
})

#: Recognisable credential shapes. Ordered most specific first: a match reports a named shape,
#: which is far more useful to the model than "a 40-character string".
_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS-access-key", re.compile(r"^(AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}$")),
    ("GitLab-personal-token", re.compile(r"^glpat-[0-9A-Za-z_-]{20,}$")),
    ("GitLab-runner-token", re.compile(r"^(glrt|GR1348941)[0-9A-Za-z_-]{20,}$")),
    ("GitHub-token", re.compile(r"^gh[pousr]_[0-9A-Za-z]{36,}$")),
    ("Slack-token", re.compile(r"^xox[abposr]-[0-9A-Za-z-]{10,}$")),
    ("NGC-API-key", re.compile(r"^nvapi-[0-9A-Za-z_-]{30,}$")),
    ("Google-API-key", re.compile(r"^AIza[0-9A-Za-z_-]{35}$")),
    ("JWT", re.compile(r"^eyJ[0-9A-Za-z_-]{10,}\.[0-9A-Za-z_-]{10,}\.[0-9A-Za-z_-]{10,}$")),
    ("PEM-private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bcrypt-hash", re.compile(r"^\$2[aby]\$\d{2}\$[./0-9A-Za-z]{53}$")),
    ("hex-40", re.compile(r"^[0-9a-fA-F]{40}$")),
    ("hex-64", re.compile(r"^[0-9a-fA-F]{64}$")),
    ("base64-blob", re.compile(r"^[0-9A-Za-z+/]{32,}={0,2}$")),
    ("UUID", re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")),
)

#: Assignment to a credential-named identifier, in any of the syntaxes we scan.
#: Matches ``PASSWORD = "x"``, ``"api_key": "x"``, ``token: x``, ``--password=x``.
ASSIGNMENT_RE = re.compile(
    r"""(?ix)
    (?P<name> [A-Za-z0-9_.\-]{0,40}
        (?: password | passwd | pwd | secret | token | api[_-]?key | apikey
          | access[_-]?key | private[_-]?key | credential | auth[_-]?key
          | client[_-]?secret | bearer )
        [A-Za-z0-9_.\-]{0,20} )
    \s* (?P<sep> [:=] {1,2} > ? | \s )
    \s* (?P<quote> ["']? )
    (?P<value> [^\s"',;)}\]]{1,512} )
    (?P=quote)
    """
)

#: How a redacted value is rendered. Deliberately unmistakable, and deliberately not the same
#: token the log scrubber uses, so a reader can tell which layer produced it.
MARKER = "<redacted: {shape}, {length} chars>"

#: Shannon entropy above which an unrecognised string is treated as a real secret rather than a
#: placeholder. 3.5 bits/char is high for English prose (~2.5-3.0) and low for random base64
#: (~5.5-6.0), which puts it comfortably between the two populations.
ENTROPY_THRESHOLD = 3.5

#: Below this length, entropy is not a meaningful signal -- a short random string and a short word
#: score similarly.
MIN_SECRET_LENGTH = 12


@dataclass(frozen=True)
class Redaction:
    """One redacted value: what shape it had, and whether it looks real."""

    shape: str
    length: int
    entropy: float
    placeholder: bool

    @property
    def marker(self) -> str:
        if self.placeholder:
            return f"<placeholder: {self.length} chars>"
        return MARKER.format(shape=self.shape, length=self.length)


def entropy(value: str) -> float:
    """Shannon entropy in bits per character."""
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    total = len(value)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def is_placeholder(value: str) -> bool:
    """Whether a value is documentation rather than a credential."""
    stripped = value.strip().strip("\"'")
    lowered = stripped.lower()
    if lowered in PLACEHOLDERS:
        return True
    # Template syntax of every flavour: ${VAR}, {{ var }}, %(var)s, <var>, $VAR
    if re.fullmatch(r"[\$%{<]{1,2}[A-Za-z0-9_.\s|'\"-]{1,60}[}>)s]{0,3}", stripped):
        return True
    if lowered.startswith(("env.", "os.environ", "vault:", "secret:", "file:")):
        return True
    # Repeated single character: "xxxxxxxx", "00000000"
    if len(set(stripped)) <= 2 and len(stripped) > 3:
        return True
    # Too short to be a real credential, so treating it as one produces noise.
    return len(stripped) < 6


def classify(value: str) -> Redaction:
    """Describe a value's shape without disclosing it."""
    stripped = value.strip().strip("\"'")
    placeholder = is_placeholder(stripped)

    shape = "unrecognised"
    for name, pattern in _SHAPES:
        if pattern.match(stripped) or pattern.search(stripped):
            shape = name
            break

    measured = entropy(stripped)
    if shape == "unrecognised" and not placeholder:
        if len(stripped) < MIN_SECRET_LENGTH or measured < ENTROPY_THRESHOLD:
            # Long enough to be assigned to a credential-named variable, not random enough to be
            # a credential. Treated as a placeholder so it does not become a false finding.
            placeholder = True
        else:
            shape = f"high-entropy ({measured:.1f} bits/char)"

    return Redaction(
        shape=shape, length=len(stripped), entropy=round(measured, 2), placeholder=placeholder,
    )


def redact_value(value: str) -> str:
    """Replace one value with its shape description."""
    return classify(value).marker


def redact_line(line: str) -> tuple[str, list[Redaction]]:
    """``(redacted_line, what_was_found)``.

    The line's structure is preserved -- variable name, operator, quoting -- because that is what
    tells the model *what* was hardcoded. Only the value goes.
    """
    found: list[Redaction] = []

    def _replace(match: re.Match[str]) -> str:
        classified = classify(match.group("value"))
        found.append(classified)
        quote = match.group("quote")
        return (
            f"{match.group('name')}{match.group('sep')}{quote}{classified.marker}{quote}"
        )

    redacted = ASSIGNMENT_RE.sub(_replace, line)

    # A PEM header is not an assignment, so it needs its own pass.
    if "-----BEGIN" in redacted and "PRIVATE KEY" in redacted:
        found.append(Redaction(
            shape="PEM-private-key", length=len(redacted), entropy=0.0, placeholder=False,
        ))
        redacted = re.sub(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*",
            "<redacted: PEM-private-key block>", redacted,
        )

    return redacted, found


def redact_excerpt(text: str) -> str:
    """Redact every line of a multi-line excerpt."""
    return "\n".join(redact_line(line)[0] for line in text.splitlines())


def scrub(value: object) -> object:
    """Recursively redact strings inside a structure.

    The final gate before anything is serialized into the evidence document. Applied to the whole
    document rather than to the fields we remember to handle, because "the fields we remember" is
    the failure mode this design is trying to remove everywhere else too.
    """
    if isinstance(value, str):
        return redact_line(value)[0]
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    return value
