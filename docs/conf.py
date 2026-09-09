# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""Sphinx configuration for the NVIS Software Factory documentation.

Author: Rafael M. Koike & Cursor Agent ("Ada")

Matches the house style established in nvws-documentation: MyST for content, nvidia_sphinx_theme
for chrome, sphinx-external-toc so navigation lives in one reviewable file rather than being
scattered across toctree directives.

Two settings differ from that reference, both deliberately:

* ``nitpicky = True``. Every broken cross-reference is a 404 for a reader, and this site's
  reference section is generated -- a dangling link there means the generator and its source have
  diverged, which is precisely the drift the generator exists to prevent.
* No ``autosectionlabel``. It generates a label for every heading in the project, which in a site
  with eight pillar pages that all contain "Remediation patterns" produces ambiguous-label
  warnings that then have to be suppressed. Explicit anchors via ``myst_heading_anchors`` are
  unambiguous, and this site cross-references headings often enough for that to matter.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The generators import from backend/ to read the config registry and the standards loader. Same
# path setup the application itself uses, so a docs build reads exactly what the app reads.
sys.path.insert(0, str(REPO_ROOT / "backend"))

# -- Project information -----------------------------------------------------

project = "NVIS Software Factory"
copyright = "2026, NVIDIA Corporation"
author = "NVIDIA Corporation"
root_doc = "index"


def _version() -> str:
    """The contract version, which is the version readers actually care about.

    An application version would be a number nobody can act on. "Which NRM am I looking at" is a
    question that changes what a team writes, so that is what the site announces.
    """
    published = sorted(p.name for p in (REPO_ROOT / "contracts" / "nrm").glob("v*"))
    return published[-1] if published else "v0.1"


def _release() -> str:
    """Version plus the commit, when git can tell us.

    A reader who found a discrepancy needs to say which build they were reading. Without this the
    only answer available to them is "the one on the VM last Tuesday".
    """
    version = _version()
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return version
    return f"{version} ({sha})" if sha else version


version = _version()
release = _release()

# -- General configuration ---------------------------------------------------

extensions = [
    "myst_parser",
    "sphinx_external_toc",
    "sphinx_design",
    "sphinx_copybutton",
    "sphinxcontrib.mermaid",
]

external_toc_path = "_toc.yml"
# False: a page that exists but is in no toc is unreachable except by search, which is how a docs
# site accumulates orphans. This makes that a build failure.
external_toc_exclude_missing = False

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "README.md"]

# A broken reference is a 404. See the module docstring.
nitpicky = True

# -- MyST --------------------------------------------------------------------

source_suffix = {".md": "markdown"}

myst_heading_anchors = 4
myst_enable_extensions = [
    "colon_fence",      # ::: directives, which nest more legibly than backtick fences
    "deflist",          # the natural shape for a field or setting reference
    "fieldlist",        # per-page Diataxis frontmatter renders as a field list
    "linkify",          # bare URLs in prose become links
    "substitution",
    "tasklist",
]

myst_substitutions = {
    "nrm_version": version,
    "release": release,
    "pillar_count": "8",
}

# -- HTML output -------------------------------------------------------------

html_theme = "nvidia_sphinx_theme"
html_title = "NVIS Software Factory"
html_static_path = ["_static"]
html_favicon = "_static/favicon.ico"
html_css_files = ["custom.css"]

html_theme_options = {
    # This is an internal deployment behind OIDC on an ITSS VM, not a public docs site.
    "public_docs_features": False,
    "show_toc_level": 2,
    # No "logo" key: nvidia_sphinx_theme raises if one is set, and points at SVGs that ship in
    # its own static directory. Those land in the output _static/, but the parent theme checks
    # for them under html_static_path at config time and warns. See _LOGO_ASSETS below.
}

html_show_sourcelink = False
html_show_sphinx = False

# Served from /docs by the same Flask app that serves the API, so links must be relative.
html_baseurl = os.environ.get("NVSF_DOCS_BASEURL", "")

# -- Extension configuration -------------------------------------------------

copybutton_prompt_text = r">>> |\$ |# "
copybutton_prompt_is_regexp = True
copybutton_exclude = ".linenos, .gp, .go"
copybutton_line_continuation_character = "\\"

# -- Diataxis page type ------------------------------------------------------

#: Frontmatter value -> what the reader is told the page is for. The second half of each label is
#: the part that does the work: someone who arrived from a search engine needs to know whether
#: this page will teach them or get them unblocked, and those are different needs.
DIATAXIS_LABELS = {
    "tutorial": "Tutorial — a lesson. Follow it start to finish.",
    "how-to": "How-to guide — steps to a goal. Assumes you know the basics.",
    "reference": "Reference — a description of the machinery. Look things up here.",
    "explanation": "Explanation — background and reasoning. No instructions.",
}


def _diataxis_banner(app, docname, source):
    """Render each page's ``diataxis`` frontmatter as a visible banner.

    A page's mode is already implied by the section it sits in, which works for a reader browsing
    the sidebar and not at all for the far more common one who arrived from a search engine
    directly onto a page. Diataxis only helps if the reader can tell what kind of page they are
    on before they invest in reading it, so the classification is stated rather than implied.

    Sourced from the frontmatter rather than the file path so that the docs rule, the CI check and
    the rendered page are all reading one declaration.
    """
    text = source[0]
    if not text.startswith("---"):
        return

    end = text.find("\n---", 3)
    if end == -1:
        return
    # Read the key out of the raw frontmatter rather than from ``env.metadata``: this event fires
    # before the parser runs, so the metadata for this page does not exist yet.
    body_start = text.index("\n", end + 1) + 1
    match = re.search(r"^diataxis:\s*(\S+)\s*$", text[:body_start], re.MULTILINE)
    label = DIATAXIS_LABELS.get(match.group(1)) if match else None
    if not label:
        return

    mode = match.group(1)
    banner = f"\n:::{{div}} nvsf-diataxis nvsf-diataxis-{mode}\n{label}\n:::\n"

    # Below the page title, not above it. Above the H1 the banner reads as a site-wide element
    # and pushes the title -- the thing the reader is looking for -- down the page.
    title = re.search(r"^# .+$", text[body_start:], re.MULTILINE)
    at = body_start + title.end() + 1 if title else body_start
    source[0] = text[:at] + banner + text[at:]


def setup(app):
    # source-read rather than a template override: the banner is content, it should appear in
    # any builder's output, and overriding the theme's page template to inject it would couple
    # this site to pydata's block structure.
    app.connect("source-read", _diataxis_banner)
    return {"parallel_read_safe": True, "parallel_write_safe": True}
