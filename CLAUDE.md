# CLAUDE.md

Guidance for Claude (and any agent) working in this repo. **Breadcrumbs** ships
as the PyPI package **`crumb-kit`**; the import package and CLI are `breadcrumbs`
/ `crumb`.

## Repo layout

- `breadcrumbs/` — the package. `cli.py` is the whole CLI; `__init__.py` holds
  the version; `templates/project-memory/` is bundled package data.
- `crumb.py` — source-checkout shim (`python crumb.py …`, `import crumb`); tests
  import through it.
- `tests/` — the test suite (stdlib `unittest`). `.github/workflows/` — `ci.yml`
  and `release.yml`.
- `RELEASING.md` — the full release doc. This file is the short version.

## Everyday commands

```bash
python -m unittest discover -s tests   # run the suite — canonical, no install needed
python crumb.py --version              # run the CLI from a source checkout
```

`unittest discover` is the canonical runner: it is what CI runs, and the package
has **no runtime dependencies**, so a clean checkout can run the whole suite with
nothing installed. Keep it that way — a test that needs a third-party import
belongs behind a skip, like the MCP SDK tests.

The rest of the bench is optional and declared in the `dev` extra
(`pip install -e ".[dev]"`):

```bash
ruff check . && ruff format --check .   # what the `lint` CI job runs
python -m pytest -q                     # supported alternative runner
python -m build                         # build wheel + sdist into dist/
```

## The version lives in ONE place

`__version__` in `breadcrumbs/__init__.py` is the **single source of truth**.

- `pyproject.toml` has `dynamic = ["version"]` and reads it via
  `[tool.setuptools.dynamic] version = {attr = "breadcrumbs.__version__"}`.
- `breadcrumbs/cli.py` reads it (lazily, in `get_version()`) as the
  source-checkout fallback.

**To change the version, edit that one line.** Never add a version literal to
`pyproject.toml` or `cli.py` — that reintroduces the hand-sync drift this design
removed. The package version is independent of the record `schema_version`
(`SCHEMA_VERSION` in `cli.py`, currently `1`); `crumb --version` prints both.

## Releasing (do it this way — the old way kept breaking)

Releases are **automated by `.github/workflows/release.yml`**. The workflow cuts
the git tag and the GitHub Release itself, on the exact commit it builds, so a
tag can never point at a pre-bump commit (that mistake caused nearly every past
failed release). Two steps:

1. **Bump `__version__`** in `breadcrumbs/__init__.py` and add a `CHANGELOG.md`
   entry. Merge to `main`. That is the only manual edit a release needs.
2. **Run the workflow from `main`:** *Actions → release → Run workflow*, or
   ```bash
   gh workflow run release.yml --ref main -f mode=publish
   ```
   - `mode: dry-run` (default) — run the test suite, build, and validate;
     publishes nothing. Run this first to confirm the artifact is clean.
   - `mode: publish` — everything dry-run does, plus require the `ci` workflow to
     have succeeded on that commit, upload to PyPI, then tag + create the GitHub
     Release.

**Rules that keep releases green:**

- **Never create a git tag or a GitHub Release by hand.** The workflow owns
  both. Hand-tagging the wrong commit was the #1 cause of failed releases.
- **A PyPI version is permanent.** You can't re-publish or overwrite a version.
  Every release needs a fresh `__version__`. The workflow checks PyPI up front
  and stops with "already released — bump the version" if you forgot (i.e. when
  the version is on PyPI *and* tagged).
- **If a publish fails, re-run it.** PyPI is uploaded *before* the tag is cut, so
  a failure during the upload leaves no tag or Release behind. A failure *after*
  the upload leaves the version on PyPI with no tag; the pre-flight treats that
  as a recovery and lets the re-run finish the job (the upload no-ops on
  `skip-existing`, then the tag + Release are created). Recover before merging
  anything else — the tag lands on the commit the re-run builds. Never hand-tag.
- **Dead tags exist.** `v0.1.5`/`v0.1.6` were tagged by hand and never published;
  `0.1.2` is on PyPI with no tag. See `RELEASING.md` → *Tag / PyPI history*. The
  workflow refuses to re-use a tag or to tag a version regression.
- **Publish only from `main`.** The workflow refuses `mode: publish` on other
  branches.

When you make a fix on a branch and it merges to `main`, a release is then just
step 2 above — no other ceremony.
