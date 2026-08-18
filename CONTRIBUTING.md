# Contributing to Breadcrumbs

Thanks for looking. This is a small, deliberately dependency-free project; the
bar for a change is that it stays that way and that CI proves it.

Package names, because there are three: the PyPI distribution is **`crumb-kit`**,
the import package is **`breadcrumbs`**, and the CLI binary is **`crumb`**.

## Getting set up

The package has **no runtime dependencies**, so a clean checkout can run the whole
test suite with nothing installed:

```bash
git clone https://github.com/jr-mccoy/breadcrumbs.git
cd breadcrumbs
python -m unittest discover -s tests    # canonical runner — this is what CI runs
python crumb.py --version               # run the CLI from a source checkout
```

`python crumb.py` is a source-checkout shim, so you never have to install the
package to try a change.

The rest of the bench is optional and declared in the `dev` extra:

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .   # what the `lint` CI job runs
python -m pytest -q                     # supported alternative runner
python -m build                         # build wheel + sdist into dist/
pip install -e ".[mcp]"                 # only if you touch the MCP server
```

## House rules

- **Keep the runtime dependency count at zero.** Plain files and the stdlib come
  first. A test that needs a third-party import belongs behind a skip, the way
  the MCP SDK tests are — a clean checkout must still run the full suite.
- **The version lives in exactly one place:** `__version__` in
  `breadcrumbs/__init__.py`. `pyproject.toml` reads it via dynamic metadata and
  `breadcrumbs/cli.py` uses it as the source-checkout fallback. Never add a
  version literal anywhere else; that reintroduces hand-sync drift.
- **Never create a git tag or a GitHub Release by hand.** The release workflow
  owns both, and hand-tagging the wrong commit caused nearly every past failed
  release. See [`RELEASING.md`](RELEASING.md).
- **Never commit secrets to `.project-memory/`.** `crumb scan-secrets` gates it,
  and CI runs the gate against a fixture that deliberately leaks.
- **Formatting is `ruff format`**, line length 100, pinned to the exact version
  the `dev` extra declares. Bump the pin in `pyproject.toml` and in the `lint` CI
  job together — an unpinned formatter has turned an untouched `main` red before.

## Changes that need a test

Anything touching record parsing, `guard` ranking, `resume` projection freshness,
the secret scanner, or the hook payloads. `tests/` mirrors the command surface
(`test_guard.py`, `test_resume.py`, `test_hooks.py`, …) — put it next to its
neighbours. The `fixtures/` tree holds whole example stores that CI walks with
`validate` and `audit`; a new behaviour that is easier to show than to unit-test
usually wants a fixture.

## Submitting

1. Branch off `main`.
2. Make the change, add tests, and run `python -m unittest discover -s tests`
   plus `ruff check . && ruff format --check .`.
3. Add a `CHANGELOG.md` entry under `[Unreleased]`.
4. Open a PR describing what broke or what is now possible. CI runs the suite on
   Python 3.9–3.14, the MCP server against both SDK majors, and a full
   packaging/install smoke test; all of it must be green.

## Project memory

This repo uses its own tool on itself — `.project-memory/` is committed, and it
is both the continuity ledger and the live demo. If you are working here with an
agent, `crumb resume` is the fastest way in, and `crumb guard "<action>"` before
a risky change is the intended workflow. See [`CLAUDE.md`](CLAUDE.md).
