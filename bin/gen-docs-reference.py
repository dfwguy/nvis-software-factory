#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
# Author: Rafael M. Koike & Cursor Agent ("Ada")
"""Generate the reference section of the docs from the code and the contract.

Diátaxis is explicit that reference material should be austere, neutral and *describe the
machinery*: "the only concern of reference material is to describe, clearly and accurately."
Generating it is the strongest available way to hold that line. A hand-written schema table is a
second implementation of the schema, and the two diverge the first busy week.

WHAT IS GENERATED, AND FROM WHAT
--------------------------------
======================================  ============================================
``docs/reference/nrm/*.md``             ``contracts/nrm/<version>/*.schema.json``
``docs/reference/crosswalks.md``        ``contracts/crosswalk/*.yaml``
``docs/reference/pillars/*.md``         ``standards/pillars/*.md``
``docs/reference/api.md``               the live Flask routes, via ``api.openapi.build()``
``docs/reference/configuration.md``     ``backend/config_registry.py``
======================================  ============================================

Everything else under ``docs/`` is written by hand and this script does not touch it.

``--check`` regenerates into memory and diffs against the tree. CI runs it, so a schema change
without a docs rebuild fails the pipeline rather than shipping a reference that lies. It is the
same pattern as ``bin/gen-factory-example.py`` and ``bin/gen-nvl72-fixture.py``.

WHY THE OPENAPI PAGE IS BUILT FROM THE LIVE APP
-----------------------------------------------
``api/openapi.py`` derives the document from Flask's URL map and the ``@action`` decorators, so an
endpoint cannot be added without appearing here, and cannot document a permission it does not
actually enforce. Reading a checked-in ``openapi.json`` instead would reintroduce exactly the
drift this file exists to prevent -- so importing the app is worth the cost, and the app is
importable without a real environment because ``_configure_for_import`` supplies the minimum.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

DOCS = REPO_ROOT / "docs"
REFERENCE = DOCS / "reference"

BANNER = """:::{{admonition}} Generated page
:class: generated-page

This page is generated from `{source}` by `bin/gen-docs-reference.py`. Edits here are lost on the
next build, and CI fails if the two disagree — change the source.
:::"""

#: Frontmatter on every generated page. `nvsf_generated` is what the drift check greps for, so a
#: hand-written page can never be mistaken for a generated one or vice versa.
FRONTMATTER = """---
diataxis: reference
nvsf_generated: {source}
---"""


def _page(source: str, title: str, body: str) -> str:
    """Assemble a page: frontmatter, title, generated banner, body.

    One function so every generated page has the same shape, and so the drift check can rely on
    that shape rather than on a per-page convention.
    """
    return f"{FRONTMATTER.format(source=source)}\n\n# {title}\n\n{BANNER.format(source=source)}\n\n{body.rstrip()}\n"


# ── Helpers ──────────────────────────────────────────────────────────────────────────────────


def _md_escape(text: str) -> str:
    """Make a schema description safe inside a Markdown table cell.

    Pipes would split the cell and newlines would end the row. Schema descriptions are prose
    written for developers and contain both.
    """
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _type_of(prop: dict[str, Any]) -> str:
    """A field's type as a reader needs it, following one level of ``$ref``.

    A bare ``$ref`` target name is more useful than the JSON Pointer: "uuid" tells a reader what
    to put in the field, ``common.schema.json#/$defs/uuid`` tells them where to go and read.
    """
    if ref := prop.get("$ref"):
        return f"`{ref.rsplit('/', 1)[-1]}`"

    declared = prop.get("type")
    if isinstance(declared, list):
        return " \\| ".join(f"`{t}`" for t in declared)
    if declared == "array":
        items = prop.get("items") or {}
        return f"`array` of {_type_of(items)}" if items else "`array`"
    if declared:
        return f"`{declared}`"
    if prop.get("enum"):
        return "`enum`"
    if prop.get("oneOf") or prop.get("anyOf"):
        return "`one of`"
    return "—"


def _constraints(prop: dict[str, Any]) -> str:
    """Everything about a field that is not its type or its description."""
    parts: list[str] = []
    if fmt := prop.get("format"):
        parts.append(f"format `{fmt}`")
    if (const := prop.get("const")) is not None:
        parts.append(f"must be `{const}`")
    if enum := prop.get("enum"):
        parts.append("one of " + ", ".join(f"`{v}`" for v in enum))
    if pattern := prop.get("pattern"):
        parts.append(f"pattern `{pattern}`")
    for key, label in (("minimum", "min"), ("maximum", "max"),
                       ("minLength", "min length"), ("maxLength", "max length"),
                       ("minItems", "min items")):
        if (value := prop.get(key)) is not None:
            parts.append(f"{label} {value}")
    if (default := prop.get("default")) is not None:
        parts.append(f"default `{json.dumps(default)}`")
    return "; ".join(parts) or "—"


def _field_table(schema: dict[str, Any]) -> str:
    """Every property of one schema, required first."""
    properties: dict[str, Any] = schema.get("properties") or {}
    if not properties:
        return "_This schema declares no properties._"

    required = set(schema.get("required") or [])
    rows = ["| Field | Type | Required | Constraints | Description |",
            "|---|---|---|---|---|"]

    # Required fields first, then alphabetical. A reader implementing an exporter needs the
    # mandatory set as a block; alphabetical-only buries it.
    for name in sorted(properties, key=lambda n: (n not in required, n)):
        prop = properties[name] or {}
        rows.append(
            f"| `{name}` | {_type_of(prop)} | {'yes' if name in required else 'no'} "
            f"| {_md_escape(_constraints(prop))} | {_md_escape(prop.get('description', ''))} |"
        )
    return "\n".join(rows)


def _defs_section(schema: dict[str, Any]) -> str:
    """The ``$defs`` of a schema, as a definition list.

    ``common.schema.json`` is entirely ``$defs`` and is referenced by every other entity, so a
    reader who followed a `$ref` here needs to find the target.
    """
    defs: dict[str, Any] = schema.get("$defs") or {}
    if not defs:
        return ""

    out = ["\n## Shared definitions\n"]
    for name, definition in sorted(defs.items()):
        out.append(f"`{name}`")
        description = definition.get("description") or definition.get("title") or ""
        detail = _constraints(definition)
        out.append(f": {_md_escape(description)}" if description else ": —")
        if detail != "—":
            out.append(f": {_md_escape(detail)}")
        if definition.get("properties"):
            out.append("")
            out.append(_field_table(definition))
        out.append("")
    return "\n".join(out)


# ── NRM schema reference ─────────────────────────────────────────────────────────────────────


def _nrm_pages(version: str) -> dict[Path, str]:
    from contracts import loader

    pages: dict[Path, str] = {}
    entities = loader.entity_names(version)

    for entity in entities:
        schema = loader.load_schema(entity, version)
        relative = f"contracts/nrm/{version}/{loader.schema_path(entity, version).name}"

        body = [schema.get("description", "").strip(), ""]
        body.append(f"**Schema id:** `{schema.get('$id', '')}`\n")
        body.append("## Fields\n")
        body.append(_field_table(schema))
        if extra := _defs_section(schema):
            body.append(extra)
        if schema.get("additionalProperties") is False:
            body.append(
                "\nThis schema is closed: a property not listed above is a validation error. "
                "Tool-specific data belongs in `attributes`.\n"
            )

        pages[REFERENCE / "nrm" / f"{entity}.md"] = _page(
            relative, schema.get("title", entity), "\n".join(body),
        )

    # Index for the NRM part of the reference: a table, not prose.
    rows = ["| Entity | What it is | Schema |", "|---|---|---|"]
    for entity in entities:
        schema = loader.load_schema(entity, version)
        summary = _md_escape((schema.get("description") or "").split("\n")[0])
        rows.append(
            f"| [{schema.get('title', entity)}]({entity}.md) | {summary} "
            f"| `{loader.schema_path(entity, version).name}` |"
        )

    pages[REFERENCE / "nrm" / "index.md"] = _page(
        f"contracts/nrm/{version}/",
        f"NVIS Resource Model {version}",
        "\n".join([
            f"The {len(entities)} entities of NRM {version}, as JSON Schema 2020-12.\n",
            "\n".join(rows),
            "",
            (
                "Each schema is fetchable from the running application at "
                f"`/api/contracts/nrm/{version}/<entity>.schema.json`, and all of them at once "
                "from `/api/contracts/bundle`."
            ),
        ]),
    )
    return pages


# ── Crosswalk reference ──────────────────────────────────────────────────────────────────────


def _crosswalk_page() -> dict[Path, str]:
    from contracts import crosswalk, loader

    version = loader.versions()[-1]
    coverage = crosswalk.coverage(version)["systems"]

    body: list[str] = [
        (
            "A crosswalk states how one external system's model maps onto NRM, in which "
            "direction, and what it cannot carry. Each one is validated against both its own "
            "schema and the NRM schemas at application startup.\n"
        ),
    ]

    rows = ["| System | Role | Entities | Fields | Documented gaps |", "|---|---|---|---|---|"]
    for system, summary in sorted(coverage.items()):
        entities = summary["entities"]
        rows.append(
            f"| [`{system}`](#{system}) | {str(summary['role']).replace('_', ' ')} "
            f"| {len(entities)} | {sum(e['mapped_fields'] for e in entities.values())} "
            f"| {sum(e['documented_gaps'] for e in entities.values())} |"
        )
    body.extend(["## Systems\n", "\n".join(rows), ""])

    for system, summary in sorted(coverage.items()):
        data = crosswalk.load(system)
        body.append(f"## `{system}`\n")
        body.append(f"**Role:** {str(summary['role']).replace('_', ' ')}\n")
        if authority := data.get("authority"):
            body.append(f"**Authority:** {authority}\n")
        if join := data.get("join"):
            body.append(
                f"**Join key:** `{join.get('nrm_field')}` ↔ `{join.get('system_field')}`\n"
            )
        if missing := summary["missing_entities"]:
            body.append(f"**Not mapped:** {', '.join(f'`{m}`' for m in missing)}\n")

        for mapping in data.get("entities") or []:
            body.append(
                f"### {mapping['nrm_entity']} ↔ `{mapping['system_model']}` "
                f"({mapping['direction']})\n"
            )
            if note := mapping.get("note"):
                body.append(f"{note}\n")
            fields = ["| NRM field | System field | Notes |", "|---|---|---|"]
            for pair in mapping.get("fields") or []:
                note_parts = []
                if pair.get("unreliable"):
                    note_parts.append("**unreliable**")
                if pair.get("transform"):
                    note_parts.append(f"via `{pair['transform']}`")
                if pair.get("note"):
                    note_parts.append(pair["note"])
                fields.append(
                    f"| `{pair['nrm']}` | `{pair.get('system') or '—'}` "
                    f"| {_md_escape(' — '.join(note_parts))} |"
                )
            body.extend(["\n".join(fields), ""])

            if unmapped := mapping.get("unmapped_nrm"):
                body.append("**Cannot be carried:**\n")
                for gap in sorted(unmapped, key=lambda g: g.get("field", "")):
                    body.append(f"`{gap['field']}`\n: {_md_escape(gap['reason'])}")
                body.append("")

    return {REFERENCE / "crosswalks.md": _page(
        "contracts/crosswalk/", f"Crosswalks to NRM {version}", "\n".join(body),
    )}


# ── Pillar reference ─────────────────────────────────────────────────────────────────────────


def _pillar_pages() -> dict[Path, str]:
    """The pillars, rendered verbatim.

    Verbatim on purpose. The pillar files are already reference-shaped prose and they are what the
    model is given, so a summary here would create a second, subtly different baseline -- the
    exact drift ``standards/`` exists to prevent. The generator adds navigation and the criteria
    table; the text is untouched.
    """
    from factory import standards

    loaded = standards.load()
    pages: dict[Path, str] = {}

    for pillar in loaded.pillars:
        relative = f"standards/pillars/{pillar.path.name}"
        table = ["| Criterion | Statement | Deterministic detector |", "|---|---|---|"]
        for criterion in pillar.criteria:
            detector = {"yes": "yes", "partial": "partial", "no": "no — judgement"}[
                criterion.detector
            ]
            table.append(f"| `{criterion.id}` | {_md_escape(criterion.title)} | {detector} |")

        body = [
            (
                f"**Severity ceiling:** `{pillar.severity_ceiling}` — no finding against this "
                "pillar can exceed it, however strongly the model argues.\n"
            ),
            "\n".join(table),
            "",
            "---",
            "",
            # The pillar's own H1 is dropped: this page already has one from `_page`.
            "\n".join(pillar.body.split("\n")[1:]).strip(),
        ]
        pages[REFERENCE / "pillars" / f"{pillar.id}.md"] = _page(relative, pillar.title, "\n".join(body))

    rows = ["| Pillar | Severity ceiling | Criteria | Measured | Judgement |", "|---|---|---|---|---|"]
    for pillar in loaded.pillars:
        measured = sum(1 for c in pillar.criteria if c.detector in {"yes", "partial"})
        rows.append(
            f"| [{pillar.title}]({pillar.id}.md) | `{pillar.severity_ceiling}` "
            f"| {len(pillar.criteria)} | {measured} "
            f"| {len(pillar.criteria) - measured} |"
        )

    pages[REFERENCE / "pillars" / "index.md"] = _page(
        "standards/pillars/",
        "Quality pillars",
        "\n".join([
            (
                f"Baseline version `{loaded.version}`. The version is content-addressed, so an "
                "assessment records which baseline judged it and an edit here makes older results "
                "identifiable as judged against different criteria rather than silently stale.\n"
            ),
            "\n".join(rows),
            "",
            (
                "The **measured** column is the number of criteria a deterministic scanner "
                "checks. Those findings form a floor the reasoning stage may raise but never "
                "lower. The **judgement** column is the number that depend on the model reading "
                "the evidence, and every finding in the application says which kind it is."
            ),
        ]),
    )
    return pages


# ── REST API reference ───────────────────────────────────────────────────────────────────────


def _configure_for_import() -> None:
    """The minimum environment for importing the app to read its URL map.

    Development mode with the mock provider, a throwaway data directory and a syntactically valid
    LLM endpoint. Nothing is served and no request is made; the app is imported for its routes.
    """
    os.environ.setdefault("NVSF_ENV", "development")
    os.environ.setdefault("NVSF_OIDC_MOCK", "true")
    os.environ.setdefault("NVSF_PUBLIC_URL", "http://127.0.0.1:8000")
    os.environ.setdefault("NVSF_LLM_BASE_URL", "http://127.0.0.1:9/v1")
    os.environ.setdefault("NVSF_LLM_MODEL", "docs-build-placeholder")
    os.environ.setdefault("NVSF_LLM_API_KEY", "docs-build-placeholder")
    os.environ.setdefault("NVSF_DATA_DIR", str(REPO_ROOT / "var" / "docs-build"))


def _api_page() -> dict[Path, str]:
    _configure_for_import()

    from api import openapi
    from app import app

    with app.app_context():
        document = openapi.build()

    body: list[str] = [
        document["info"].get("description", "").strip(),
        "",
        (
            "The same description is served as OpenAPI 3.1 at `/api/openapi.json`, which is the "
            "form to hand to a client generator or an agent.\n"
        ),
    ]

    # Grouped by tag, because a flat list of thirty paths is a list nobody reads.
    #
    # `verbs` filters out `parameters`, which is a sibling of the method keys in an OpenAPI path
    # item rather than an operation.
    verbs = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}
    by_tag: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for path, item in sorted(document["paths"].items()):
        for method, operation in sorted(item.items()):
            if method.lower() not in verbs:
                continue
            tag = (operation.get("tags") or ["other"])[0]
            by_tag.setdefault(tag, []).append((path, method.upper(), operation))

    descriptions = {t["name"]: t.get("description", "") for t in document.get("tags", [])}

    for tag in sorted(by_tag):
        body.append(f"## {tag}\n")
        if note := descriptions.get(tag):
            body.append(f"{note}\n")
        rows = ["| Method | Path | Permission | Summary |", "|---|---|---|---|"]
        for path, method, operation in by_tag[tag]:
            # `x-nvsf-action` comes from the @action decorator, so this column reports what is
            # actually enforced rather than what someone wrote down.
            action = operation.get("x-nvsf-action") or "_public_"
            rows.append(
                f"| `{method}` | `{path}` | `{action}` "
                f"| {_md_escape(operation.get('summary', ''))} |"
            )
        body.extend(["\n".join(rows), ""])

    return {REFERENCE / "api.md": _page(
        "backend/api/openapi.py", "REST API", "\n".join(body),
    )}


# ── Configuration reference ──────────────────────────────────────────────────────────────────


def _configuration_page() -> dict[Path, str]:
    import config_registry

    body: list[str] = [
        (
            "Every setting is declared once in `backend/config_registry.py`, and three things are "
            "derived from that declaration: `factory.toml.example`, this page, and the startup "
            "gate's required-setting check. A setting that is missing at boot fails at boot, not "
            "at first use.\n"
        ),
        (
            ":::{warning}\n"
            "A setting marked secret may come from an environment variable or a mounted secret "
            "file, and is **refused** if it appears in `factory.toml`. Config files get "
            "committed; by the time a warning is noticed the credential is in git history.\n:::\n"
        ),
    ]

    for section in config_registry.sections():
        settings = [s for s in config_registry.all_settings() if s.section == section]
        body.append(f"## `[{section}]`\n")
        rows = ["| Setting | Environment variable | Type | Default | Required | Description |",
                "|---|---|---|---|---|---|"]
        for setting in settings:
            default = "_(none)_" if setting.default is None else f"`{setting.default}`"
            if setting.secret:
                default = "_(secret)_"
            required = "yes" if setting.is_required() else "conditional" if callable(
                setting.required
            ) else "no"
            description = setting.description
            if setting.choices:
                description += " Choices: " + ", ".join(f"`{c}`" for c in setting.choices) + "."
            if setting.note:
                description += f" {setting.note}"
            rows.append(
                f"| `{setting.key}` | `{setting.env}` | `{setting.type}` | {default} "
                f"| {required} | {_md_escape(description)} |"
            )
        body.extend(["\n".join(rows), ""])

    return {REFERENCE / "configuration.md": _page(
        "backend/config_registry.py", "Configuration", "\n".join(body),
    )}


# ── Orchestration ────────────────────────────────────────────────────────────────────────────


def generate() -> dict[Path, str]:
    """Every generated page, as ``path -> content``. Writes nothing."""
    from contracts import loader

    version = loader.versions()[-1]
    pages: dict[Path, str] = {}
    pages.update(_nrm_pages(version))
    pages.update(_crosswalk_page())
    pages.update(_pillar_pages())
    pages.update(_api_page())
    pages.update(_configuration_page())
    return pages


def _write(pages: dict[Path, str]) -> list[Path]:
    written: list[Path] = []
    for path, content in sorted(pages.items()):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.read_text(encoding="utf-8") == content:
            continue
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def _check(pages: dict[Path, str]) -> int:
    problems: list[str] = []

    for path, expected in sorted(pages.items()):
        relative = path.relative_to(REPO_ROOT)
        if not path.is_file():
            problems.append(f"{relative} is missing")
            continue
        actual = path.read_text(encoding="utf-8")
        if actual == expected:
            continue
        diff = "\n".join(list(difflib.unified_diff(
            actual.splitlines(), expected.splitlines(),
            fromfile=f"{relative} (committed)", tofile=f"{relative} (regenerated)",
            lineterm="",
        ))[:40])
        problems.append(f"{relative} is out of date:\n{diff}")

    # A generated page whose source was deleted. Left in the tree it becomes a reference page for
    # something that no longer exists, and the toc keeps it reachable.
    for existing in sorted(REFERENCE.rglob("*.md")):
        if existing in pages:
            continue
        if "nvsf_generated:" in existing.read_text(encoding="utf-8"):
            problems.append(
                f"{existing.relative_to(REPO_ROOT)} is generated but has no source any more. "
                "Delete it and its _toc.yml entry."
            )

    if not problems:
        print(f"docs reference: {len(pages)} generated page(s) are in sync with their sources")
        return 0

    print("docs reference is out of date:\n", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}\n", file=sys.stderr)
    print("Run: python bin/gen-docs-reference.py", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--check", action="store_true",
        help="exit non-zero if the committed pages differ from what would be generated",
    )
    args = parser.parse_args()

    pages = generate()

    if args.check:
        return _check(pages)

    written = _write(pages)
    if written:
        print(f"docs reference: wrote {len(written)} page(s)")
        for path in written:
            print(f"  {path.relative_to(REPO_ROOT)}")
    else:
        print(f"docs reference: {len(pages)} page(s) already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
