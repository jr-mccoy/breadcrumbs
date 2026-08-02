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
> front with *"already released — bump the version"* rather than a cryptic
> `400 File already exists`. ("Already on PyPI" alone does **not** stop it — that
> is the partial-publish recovery below; it stops when the version is on PyPI
> *and* tagged, which is what a finished release looks like.)

**Step 2 — run the release workflow from `main`.**

*Actions → release → Run workflow*, with the `main` branch selected:

- **`mode: dry-run`** (default) — runs the full test suite, builds, and runs
  every packaging check (`twine check`, bundled-template identity, an
  installed-binary smoke test), but publishes nothing. Use it to confirm the
  artifact is clean. It does **not** re-run the fixture/guard/MCP checks or the
  Python matrix — those live in the `ci` workflow, which `publish` gates on.
- **`mode: publish`** — everything dry-run does, plus: requires the `ci` workflow
  to have **succeeded on this commit**, uploads to PyPI, **and then creates the
  git tag + GitHub Release itself**, on the exact commit it just built.

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

- **"already released — bump the version"** (on PyPI *and* tagged): you forgot
  Step 1. Bump `__version__`, merge, re-run.
- **The upload failed** (nothing reached PyPI): nothing to clean up — no tag or
  Release was created, because PyPI is uploaded *before* the tag is cut. Fix the
  cause and re-run; `skip-existing` tolerates any file that did make it up.
- **The upload succeeded but the tag/Release step failed** — the version is on
  PyPI with no tag. **Re-running is the fix.** The pre-flight recognises
  published-but-untagged as a recovery: it lets the run continue, the upload
  no-ops on `skip-existing`, and the tag + Release step completes the release.
  Do it **before merging anything else to `main`** — the tag is cut on the commit
  the re-run builds, so a newer `main` would tag a commit whose build never went
  to PyPI. Never hand-tag instead; the recovery exists precisely so you don't
  have to. (This is how 0.1.2 ended up on PyPI with no tag, back when the
  pre-flight hard-failed on "already on PyPI" and left no way back.)
- **"version regression"**: the version you built is on PyPI but is *not* the
  newest published version, so this is not a recovery. Bump past the newest one.
- **"dead tag"** (tag exists, version not on PyPI): see *Tag / PyPI history*
  below. Bump to a new version — a tag is never re-used.
- **"CI is still running" / "CI concluded failure"**: `publish` requires the `ci`
  workflow to have succeeded on the exact commit. Wait for it, or fix and merge.
- **"Publish must run from main"**: you ran it from a feature branch. Merge to
  `main` and select `main` in the branch dropdown.

### Tag / PyPI history

The intended invariant is **one git tag per published PyPI version**. Three
historical entries break it, from before the workflow owned tagging. They are
recorded here rather than papered over, because `pipx install git+…@vX` resolves
tags and will happily install a version PyPI never shipped:

| Version | git tag | GitHub Release | PyPI | What happened |
|---|---|---|---|---|
| 0.1.2 | **none** | none | **published** | Published, then never tagged — the exact shape the old pre-flight made permanent (any re-run of that version hit "already on PyPI" and stopped). Deliberately left untagged: hand-tagging it now would put a `v0.1.2` tag on a commit that has nothing to do with the published 0.1.2 artifact. Fixed for the future — see the recovery bullet above. |
| 0.1.5 | `v0.1.5` | none | **never** | Tagged, never published, no Release. **Dead tag.** |
| 0.1.6 | `v0.1.6` | `v0.1.6` | **never** | Tagged and released, never published. **Dead tag and a dead Release.** 0.1.7 is the next real PyPI release after 0.1.4. |

All three predate `release.yml` owning the tag: 0.1.7 was the first release the
workflow tagged itself. Verified against the GitHub tag and release lists and the
PyPI JSON API on 2026-07-25.

Everything else (`v0.1.0`, `v0.1.1`, `v0.1.3`, `v0.1.4`, `v0.1.7`) is tagged,
released, and on PyPI.

Deleting `v0.1.5`/`v0.1.6` and the `v0.1.6` Release would restore the invariant
and is safe (nothing depends on a version that was never published); it is left as
the maintainer's call, since a deleted tag breaks any link that referenced it. The
release workflow refuses to re-use either tag in the meantime.

---

## Path B — Manual upload with an API token (fallback)

> **Path B bypasses every guardrail Path A adds.** No pre-flight (so nothing stops
> you re-using a version or regressing one), no test run, no CI gate, and no tag or
> GitHub Release — the upload is permanent and you are left to tag by hand, which
> is exactly how `0.1.2` ended up on PyPI with no tag. Use it only when Actions is
> unavailable, and read *Tag / PyPI history* above first.

If you'd rather not use Actions:

1. Create a token at **https://pypi.org/manage/account/token/** (scope it to the
   **`crumb-kit`** project — that is the PyPI project name; `breadcrumbs` is the
   import package and the GitHub repo. Before the first upload a project-scoped
   token cannot exist yet, so an account-wide token is required for the initial
   publish; replace it with a project-scoped one afterwards).
2. Build and upload from a source checkout:

```bash
# from the REPO root — the directory holding pyproject.toml, not the
# breadcrumbs/ package directory inside it (both are named "breadcrumbs")
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
