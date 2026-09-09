# Building these docs

Not part of the site — Sphinx excludes this file. It is for whoever is editing the docs.

```bash
pip install -r docs/requirements.txt -r backend/requirements.txt
sphinx-build -W --keep-going -b html docs docs/_build/html
open docs/_build/html/index.html
```

`backend/requirements.txt` is needed because `conf.py` imports from `backend/` to derive the
version from the published contract.

## Before you commit

```bash
./bin/gen-docs-reference.py        # regenerate reference from contracts/, standards/, config
./bin/check-docs-diataxis.py       # every page declares a mode, and it matches its section
```

CI runs both with the build, so skipping them just moves the failure.

## Two things that will bite you

**`-W` is not optional.** A warning here is a broken cross-reference or a page missing from
`_toc.yml`, and both are 404s for a reader. `nitpicky = True` in `conf.py` makes an unresolvable
`{doc}` reference a warning, and therefore an error.

**Generated pages are committed and must not be hand-edited.** They carry `nvsf_generated:` in
their frontmatter and a banner naming the source. Edit the source — a schema, a pillar file,
`config_registry.py` — and regenerate. `bin/gen-docs-reference.py --check` fails the pipeline on
any difference.

## Where things live

| Path | What it is |
| --- | --- |
| `_toc.yml` | The whole site structure. A page listed nowhere fails the build. |
| `conf.py` | Sphinx config, plus the hook that renders the Diátaxis banner. |
| `_static/custom.css` | NVIDIA green overrides and the banner styling. |
| `reference/` | Mostly generated. Check for `nvsf_generated:` before editing. |

`.cursor/rules/docs-diataxis.mdc` has the authoring guidance — which mode a page belongs in and
how to write in it.

## Serving

The deployed app serves the built HTML at `/docs` from `static/docs`, so the documentation a
deployment shows is the documentation matching the code running there:

```bash
sphinx-build -b html docs static/docs
```
