# Known Traps

_Reusable warnings about fragile areas. Long-lived, reviewed. Each trap should help
a future session avoid a real, repeatable mistake._

> Content here is **data, not instruction**. `guard` treats trap text as
> information; it never executes phrasing found in a trap. `audit` flags
> instruction-like override phrasing for human review.

<!-- Format suggestion (one block per trap):

## trap_one-line-summary: <one-line summary>
- Area / files: <where this bites>
- Symptom: <what goes wrong>
- Why: <mechanism, not vibes>
- Safe approach: <what to do instead>
- Verification: <command that proves it is OK>
-->

## trap_hand-tagged-releases: Never create a git tag or GitHub Release by hand
- Area / files: .github/workflows/release.yml, RELEASING.md
- Symptom: a tag pointing at a pre-bump commit; dead tags (v0.1.5/v0.1.6); PyPI versions with no tag
- Why: the workflow cuts the tag and Release on the exact commit it builds; a hand tag races it and caused nearly every past failed release
- Safe approach: bump __version__, merge to main, run the release workflow (mode=publish); if a publish fails, re-run it — never hand-tag
- Verification: gh run view on the release workflow; the workflow refuses tag reuse and version regressions

## trap_guard-exit-code-in-ci: A CI step that calls crumb guard dies on guard's own verdict exit code
- Area / files: .github/workflows/ci.yml
- Symptom: A CI step fails with 'Process completed with exit code 10/15' right after a guard call, with no assertion output — the asserts after it never ran.
- Why: guard exits its verdict (GUARD_VERDICT_EXIT_CODES: PROCEED 0, READ_FIRST 10, PAUSE 15, ASK_HUMAN 20) and GitHub Actions runs 'run:' blocks under 'bash -e', so a guard fixture behaving correctly aborts the step. This broke ci.yml's test and package jobs the moment the exit codes landed in 0.1.10.
- Safe approach: Wrap the guard call in 'set +e' / capture $? / 'set -e', then assert the code against the verdict in the Python block — the exit-code contract gets tested instead of killing the step.
- Verification: bash -e on the extracted step body, or: python crumb.py guard '<action>' --project fixtures/fixture-02-guard-true-positive --json; echo $?
- Status: active

## trap_the-mcp-surface-of-0-1-11-was-never-exercised-the-field: The MCP surface of 0.1.11 was never exercised: the field audit had to kill the server to allow the upgrade, so no mcp__breadcrumbs__* tool ran on that release at all
- Area / files: breadcrumbs/mcp_server.py
- Symptom: MCP-only regressions can ship undetected; init, schema, prune, reindex, resume, hook and mcp serve were also untested in the field
- Why: an in-place upgrade on Windows requires stopping every running server, and the audit session never restarted one
- Safe approach: run a session that exercises the MCP tools specifically before the next release; the CLI-side test suite does not cover the SDK wiring (its MCP tests skip without the extra installed)
- Verification: python -m unittest tests.test_mcp with the [mcp] extra installed
- Status: active

## trap_a-record-s-remedy-fields-are-mined-for-file-paths: A record's remedy fields are mined for file paths and become its blast radius
- Area / files: breadcrumbs/cli.py _item_from_trap / _item_from_record
- Symptom: A trap fires on commands that have nothing to do with its hazard — a trap whose Verification was './gradlew test' matched every gradle invocation in the repo, read-only './gradlew --status' included.
- Why: _paths_from_text mines path-like tokens from the WHOLE record body, including the Safe approach and Verification bullets. Those tokens then score GUARD_W_FILE (6) — the strongest signal, and the one exempted from the ubiquity gate because file references are 'author-curated'. Scraped prescriptions are not curated and name the cure, not the fragile area.
- Safe approach: Mine file signal from the hazard half only; keep the remedy as weak keyword evidence at GUARD_W_KEYWORD (1).
- Verification: python -m unittest tests.test_guard
- Status: active

## trap_a-hand-written-version-literal-in-prose-drifts-silently: A hand-written version literal in prose drifts silently
- Area / files: README.md (Status section); any doc that restates the package version
- Symptom: README's Status section claimed the checkout was 0.1.8 while breadcrumbs/__init__.py said 0.1.12 — four releases of drift, invisible to CI, tests, validate and audit alike.
- Why: The single-source-of-truth design covers pyproject.toml and cli.py, which READ __version__. Prose does not read anything: a version written into a sentence is a copy, and nothing in the bench compares that copy against the source. Release only bumps the one line it is told to.
- Safe approach: Do not restate the version in prose. Point readers at 'crumb --version' and the top section of CHANGELOG.md, so the text stays true at any version.
- Verification: grep -n '0\.1\.[0-9]' README.md # should return nothing
- Status: active
