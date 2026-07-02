# Releasing Breadcrumbs to PyPI

The package is build-clean: `python -m build` produces a wheel + sdist that pass
`twine check`, with all template files bundled as package data. This doc covers
how to publish it.

There are two supported paths. **Trusted Publishing (recommended)** stores no
secrets; **manual token upload** is the fallback if you want to publish by hand.

---

## Path A — Trusted Publishing via GitHub Actions (recommended)

No API tokens are stored anywhere. GitHub mints a short-lived OIDC token per run.
The workflow lives at [`.github/workflows/release.yml`](.github/workflows/release.yml).

### One-time setup

1. Go to **https://pypi.org/manage/account/publishing/**.
2. Add a **pending publisher** with:
   - **PyPI project name:** `crumb-kit`
   - **Owner:** `jumbodaddystack`
   - **Repository:** `breadcrumbs`
   - **Workflow name:** `release.yml`
   - **Environment:** `pypi`
3. (Optional but recommended) In the GitHub repo, create a matching
   **Environment** named `pypi` under *Settings → Environments*, and add
   required reviewers if you want a manual approval gate before each publish.

No secrets to add. That's the whole setup.

### The whole release, in two steps

The workflow does the fiddly, order-sensitive parts (tagging the right commit,
checking PyPI, cutting the GitHub Release). You do exactly two things:

**Step 1 — bump the version (one line) and merge to `main`.**

The version lives in **exactly one place**: `__version__` in
[`breadcrumbs/__init__.py`](breadcrumbs/__init__.py). `pyproject.toml` reads it
dynamically at build time, and `breadcrumbs/cli.py` reads it as its
source-checkout fallback — so there is **nothing to hand-sync**. Bump that one
line, add a `CHANGELOG.md` entry, and merge to `main`.

> A PyPI version is **permanent**. If you forget to bump, the workflow stops up
> front with *"already on PyPI — bump the version"* rather than a cryptic
> `400 File already exists`.

**Step 2 — run the release workflow from `main`.**

*Actions → release → Run workflow*, with the `main` branch selected:

- **`mode: dry-run`** (default) — builds and runs every check CI does, but
  publishes nothing. Use it to confirm the artifact is clean.
- **`mode: publish`** — builds, validates, uploads to PyPI, **and then creates
  the git tag + GitHub Release itself**, on the exact commit it just built.

You never create a tag or a GitHub Release by hand. That is deliberate: cutting
the tag by hand (on a pre-bump commit) was the single most common cause of failed
releases. The workflow tags the commit it builds, so the tag can never mismatch.

Or trigger it from the CLI:

```bash
gh workflow run release.yml --ref main -f mode=publish
```

After it runs, confirm:

```bash
pipx install crumb-kit
crumb --version
```

### If a release fails

- **"already on PyPI — bump the version"**: you forgot Step 1. Bump
  `__version__`, merge, re-run.
- **PyPI upload failed partway**: nothing to clean up — no tag or release was
  created (PyPI is uploaded *before* the tag is cut). Fix the cause and re-run;
  `skip-existing` tolerates any file that did make it up.
- **"Publish must run from main"**: you ran it from a feature branch. Merge to
  `main` and select `main` in the branch dropdown.

---

## Path B — Manual upload with an API token (fallback)

If you'd rather not use Actions:

1. Create a token at **https://pypi.org/manage/account/token/** (scope it to the
   `breadcrumbs` project after the first upload; before that, an account-wide
   token is required for the initial publish).
2. Build and upload from a source checkout:

```bash
cd breadcrumbs
python -m build                      # writes dist/*.whl and dist/*.tar.gz
python -m twine check dist/*         # must PASS
python -m twine upload dist/*        # username: __token__   password: <your token>
```

To dry-run on TestPyPI first:

```bash
python -m twine upload --repository testpypi dist/*
```

> **Note on `twine check`:** it needs a current `packaging` (≥24.1) to recognize
> Metadata-Version 2.4's `License-File` field. If you see a spurious
> `unrecognized or malformed field 'license-file'` error, upgrade in a clean
> venv: `python -m venv .venv && .venv/bin/pip install -U twine packaging`.

---

## Versioning reminder

`__version__` in `breadcrumbs/__init__.py` is the **single source of truth** for
the **package** version (semver). `pyproject.toml` reads it dynamically
(`[tool.setuptools.dynamic] version = {attr = "breadcrumbs.__version__"}`) and
`breadcrumbs/cli.py` reads it as its source-checkout fallback — bump the one line,
nothing else to touch.

The package version is independent of the on-disk **record `schema_version`**
(manifest `schema_version: 1`). `crumb --version` prints both. Bump the package
MAJOR only alongside a breaking record-schema change.

A PyPI version is **permanent** — once `0.1.0` is uploaded it cannot be replaced,
only yanked.
