# WP21: the compatibility and migration policy (2026-09-27)

This implements work package WP21 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), findings F05,
F18 and F24. The starting commit is `9064d2e`, after WP13.

The policy is [`docs/compatibility.md`](../../compatibility.md). WP21 asks for
it to be *approved*. Before implementing, I asked the operator three questions,
and they chose all three recommendations:

| Decision | Chosen |
|---|---|
| Pre-1.0 version policy | **Minor = breaking.** A `schema_version` change, a `requires` feature or an incompatible compatibility-surface change is a `0.MINOR` release; fixes and compatible additions are `0.x.PATCH`. The next release from this branch is **0.4.0**. |
| A store newer than this build understands | **Refuse writes, warn reads.** |
| This branch forked before v0.3.1 | **Merge `main` in now,** as a merge commit. |

## What was found

- **The branch was behind the release.** `v0.3.1` (the hotfix "a stale crumb
  on PATH can no longer block every prompt") was cut from `main` after this
  branch forked at `30e41f6`. The branch still said `0.3.0` and lacked the
  fix. It is merged in now (`751283f`, below).
- **Both 0.3.1 and this branch wrote into a newer store.** Against a
  `schema_version: 5` store, `remember` wrote a record, and `guard` and
  `resume` ran without a word. Only `validate` objected ("upgrade crumb-kit").
  Nothing stopped an old build from recording old-semantics data into a store
  whose meaning had moved on (the F18 concern for WP14's review profiles).
- **There was no way to say "this store needs feature X"** without a format
  change.
- **Migration could not be undone, verified or resumed with its original
  backup.**
  - The backup was an unverified copy.
  - An interrupted migration re-ran with a new backup of the half-migrated
    store.
  - There was no restore.
  - The preview did not mention the legacy values it would leave alone.
- **`crumb --version` could report a version the running code was not.**
  `get_version()` preferred installed package metadata. A leftover
  `crumb_kit.egg-info` in the checkout (left by my own wheel check in WP13,
  before the merge) made a 0.3.1 checkout report `0.3.0`. The same happens to
  any editable install after a version bump.
- **The tag history had an undocumented entry.** A tag `0.1.13` (no `v`) on
  `abd2bfd` (2026-09-04), whose `__version__` is 0.1.12. It was never
  published: PyPI's list is 0.1.0–0.1.4, 0.1.7–0.1.12, 0.2.0, 0.3.0 and 0.3.1,
  checked 2026-09-27.
- **Pre-1.0 policy language did not match history.** 0.3.0 moved the schema
  from 1 to 4 in a minor release, which the new policy calls correct, and
  nothing recorded which release carried which schema.

## Change

**Merge of `origin/main` (0.3.1).** One merge commit, no rebase or
force-push, in a separate commit before the WP21 changes.
- `cli.py` merged cleanly.
- `CHANGELOG.md` keeps both sections (`[Unreleased]` above `[0.3.1]`).
- `.project-memory/current.md` keeps this branch's state.
- The generated projections were rebuilt with `crumb reindex`.
- The full suite (1310), the critical eval gate and the CI fixture steps
  passed on the merge before it was committed.

**`breadcrumbs/compat.py` (new).** Classifies a store against this build:
current, older, newer (`schema_version` above `SCHEMA_VERSION`), unknown
features (a `requires:` manifest entry not in `KNOWN_FEATURES`, empty today),
or unreadable.

**Refuse writes.** `lock.store_lock` checks compatibility before taking the
lock and raises `lock.IncompatibleStore`, a `StoreLocked`. Every committed
write already takes that lock, and every caller already handles
`StoreLocked`, so every writer refuses a newer store the way it refuses a
busy one:
- CLI writers exit 1 with "… Upgrade crumb-kit. Reads still work; writes are
  refused.";
- MCP writing tools return `{ok: false, error}`;
- the capture hooks skip their writes;
- `resume` prints its packet and reports the publication as refused.

The one exception is `crumb migrate --restore`, which takes the lock with
`compatible_only=False`: restoring a verified backup is how such a store is
repaired.

**Warn reads.**
- The resume packet carries `compatibility`, rendered under its title and
  never trimmed; this reaches the `SessionStart` hook and
  `memory://resume-packet`.
- `guard` returns `compatibility`, and shows it in its human output and the
  guard hook's advisory.
- Other read commands print it on stderr.

**Migration** (`breadcrumbs/migrate.py`).
- **Verified backup.** `backup_store` writes `backup-manifest.json` (a
  SHA-256 per committed file) and checks the copy against it. A backup that
  does not verify stops the migration before any step: "Nothing was
  migrated."
- **Interruption.** `private/migrations/in-progress.json` records the backup
  and the version reached, and is updated after each step. The next `crumb
  migrate` resumes against the same backup, and the marker is cleared on
  success (or when a finished-but-uncleared run is re-run).
- **Restore.** `crumb migrate --restore [BACKUP]` (default: the interrupted
  migration's backup, else the newest):
  - verifies the backup;
  - refuses a store containing links;
  - replaces the committed store (never `private/` or `index/`);
  - verifies the result against the manifest;
  - with `--dry-run`, lists the files that would change.
- **Preview.** `--dry-run` also reports how many files the backup will copy,
  the legacy findings migration leaves alone (`legacy_report`: record-contract
  codes such as `scope-unsupported`), and whether it would resume.
- **Stable content.** No step renames a record, and unknown frontmatter keys
  are kept (tested).

**`get_version()` returns `__version__`,** the version of the running code.
Metadata built from that same line cannot disagree with it except when stale.
`breadcrumbs/__init__.py` and `RELEASING.md` now say so.

**`CLAUDE.md`, three statements corrected.**
- The `get_version()` description.
- `SCHEMA_VERSION` "currently `1`" now says `4`, and adds that a schema change
  is always a minor release.
- Release step 1 includes the compatibility-table row, since the suite now
  requires it.

**Docs.**
- **`docs/compatibility.md` (new).** The version policy; the machine-checked
  table of every versioned surface and what a mismatch does (rebuilt vs
  migrated vs refused); the machine-checked release table; two versions and
  one store, including how a semantic change is designed to fail safe for
  0.3.1-and-earlier readers that run no check; the compatibility surfaces; the
  classification of legacy data; and the upgrade guarantees.
- **`RELEASING.md`.** Which number to choose; step 1 now adds the release's
  row to `docs/compatibility.md` §3; the `0.1.13` tag in *Tag / PyPI history*,
  with the prose corrected (it came *after* the workflow owned tagging, so it
  was made by hand).
- **`record-schema.md`:** the `requires` manifest key and a pointer to the
  policy. **`cli-spec.md`:** `migrate --restore`, verification, resume and the
  preview.
- `README.md`, `architecture.md` and `CHANGELOG.md`.

## Classification (WP21 step 2)

| Data | Decision |
|---|---|
| Free-text `scope`, invalid `confidence`, `review_status`, evidence, timestamps | **Report, never rewrite.** `validate` codes (WP01) and `migrate --dry-run`'s legacy report. Guessing a scope or raising a confidence would invent facts (F05). |
| `superseded_by` to a record that is gone (for example rolled up) | Report (`superseded-by-missing`). |
| Unknown frontmatter keys | Kept by every step and writer. Not an error. |
| `review_status: reviewed` enforcement | Not enforced yet (F18). WP14 ships it as a schema bump plus a `requires:` feature, designed so old readers fail safe (`compatibility.md` §4). |
| Traps and questions as blocks | Migrated (schema 3). Readers accept blocks until then. |
| Projections, index, pre-filter, private state | Rebuilt, never migrated. |

No new migration step was needed: nothing in the approved policy changes the
on-disk format. `SCHEMA_VERSION` stays 4.

## Tests

`tests/test_store_upgrade_contract.py` has 9 tests, including the three the
roadmap names and its documentation check.

- **`test_upgrade_preserves_content_ids_scope_and_unknown_fields`.** A
  schema-2 store holds trap and question blocks, a branch-scoped decision, a
  legacy `scope: all-machines` decision, and a decision with unknown keys
  (`x_team_owner`, `x_ticket`) and a Unicode body.
  - The dry run names schema 3, the backup and `scope-unsupported: 1`, and
    changes nothing.
  - After the migration, every id is the same and every trap summary is kept.
  - Every decision file is byte-identical; the free scope is kept, not
    rewritten, and the branch scope is kept.
  - A later `mark-status` keeps the unknown keys and the body.
- **`test_interrupted_migration_is_resumable_and_backup_restores`.** The
  schema-3 step dies after doing its work.
  - The store stays at 2, the error says how to resume or restore, and the
    marker names a backup that verifies and equals the original store.
  - `--restore --dry-run` lists the differences. `--restore` returns the store
    to exactly the original and clears the marker.
  - After a second interruption, the re-run resumes with the *same* backup
    and no new one, reaches schema 4, and `validate` passes.
  - A tampered backup is refused.
- **`test_old_reader_cannot_silently_misinterpret_new_authority_semantics`.**
  Two subtests, a `schema_version` one above this build and a `requires:
  review-profiles` store.
  - `store_lock` raises `IncompatibleStore`.
  - `remember`, `note`, `mark-status`, `capture`, `reindex` and `jot` exit 1
    with "Upgrade crumb-kit".
  - MCP `tool_record` returns `ok: false`.
  - A correction prompt and the capture hook write nothing; the committed
    store is byte-identical.
  - `resume`, `guard --json`, `search` (stderr), `memory://resume-packet` and
    the `SessionStart` hook all carry the warning, `validate` fails, and
    `migrate` without `--restore` is refused.
- **`test_documentation_matches_emitted_versions`** (the "documentation
  matches the package" check).
  - The §2 table must equal the code's constants.
  - `crumb --version` output, the manifest `crumb init` writes, the generation
    manifest, the pre-filter, a usage event and a migration backup manifest
    are checked for the formats they actually emit.
- **`test_a_schema_change_requires_a_minor_version_bump`.**
  - The §3 release table is ordered and never changes schema within a minor.
  - It equals the CHANGELOG's released sections.
  - The current `SCHEMA_VERSION` matches the table for the current
    `__version__`; an unreleased version bumps the minor if the schema moved.
- **Also covered:** older and current stores stay writable (and a known
  feature is accepted), `requires:` parsing, `--restore` repairing a store
  this build could not otherwise write, a failed backup verification stopping
  the migration, and manifest hashes being SHA-256 of the files.

The behavioral comparison is [behavior.txt](behavior.txt), from
[behavior.py](behavior.py), which drives each tree's own CLI in
subprocesses:

| Check | Before (`751283f`, and released v0.3.1) | After |
|---|---|---|
| Writes into a `schema_version: 5` store | yes | no |
| `resume` warns on a newer store | no | yes |
| Writes into a store that `requires` an unknown feature | yes | no |
| `migrate --dry-run` reports the backup and legacy values | no | yes |
| The migration backup has a verifiable manifest | no | yes |
| `migrate --restore` exists and restores exactly | no | yes |
| `--version` reports the running code despite stale metadata | no | yes |
| **Defects observed** | **7** (both) | **0** |

## Results

| Command | Exit | Result |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` (3.11.15) | 0 | 1319 run, 0 failures, 6 skipped (1310 at the merge, plus 9 new) |
| contract, migrate, lock, containment, emission, hooks, mcp, init, blockfiles, parser, release-process, integrations and validate tests on 3.9.23 | 0 | 378 OK |
| `test_mcp` and `test_store_upgrade_contract` with MCP SDK 2.2.0 | 0 | OK (2 skipped) and OK |
| `python evals/run.py --verbose` | 0 | 20 critical cases pass; identical to WP13 apart from timings ([evals.txt](evals.txt)) |
| `python evals/run.py --release` | 0 | Passes |
| `regression_probes.py … --fail-on-observed` | 2 | Unchanged from WP13: 3 defect signals, 3 probe errors ([probe-results.json](probe-results.json)). `schema_types` (F05) stays clear |
| CI `test` job fixture steps, replayed | 0 | All 7 pass |
| `ruff check . && ruff format --check .` (0.16.1) | 0 | Clean |
| Hook latency, 40 decisions, median | — | Within noise (prompt 11.2–12.4 → 11.5–12.4 ms; guard 26.7–29.7 → 26.8–27.5 ms) |

## Compatibility

- **A store newer than this build is no longer written.** A workflow that ran
  an old crumb-kit against an upgraded store now gets exit 1 on writes, and a
  warning on reads.
- **`init --force`, `reindex` and `capture` are refused on such a store too.**
  Only `migrate --restore` may write it.
- **New manifest key `requires:`.** It is optional; no feature is defined yet.
- **New:**
  - `crumb migrate --restore [BACKUP]`;
  - `backup-manifest.json` in backups and
    `private/migrations/in-progress.json`;
  - in `migrate --json`: `resumed`, and in dry runs `backup_files`, `legacy`
    and `resumes`;
  - the packet key `compatibility` and the guard key `compatibility`, present
    only when there is something to say.
- **Backups made by 0.3.1 or earlier** have no manifest, so `--restore`
  refuses them (restore by hand, as before).
- **`crumb --version` and `get_version()`** now report `__version__` even when
  installed metadata says otherwise.
- **Releasing** adds one line: the release's row in `docs/compatibility.md`
  §3. Otherwise the suite fails, and with it the release workflow.
- **The branch is at 0.3.1** (from the merge). The policy makes its next
  release 0.4.0, bumped at release time.

## Limits

- **Released readers are not protected by this check.** crumb-kit 0.3.1 and
  earlier still read and write a newer store; only their `validate` objects.
  The policy's answer (`compatibility.md` §4) is design, not code: a future
  semantic change bumps the schema, keeps its meaning out of fields old
  readers interpret, and adds a `requires:` feature.
- **The compatibility surfaces** (§5) are enforced by review and the
  CHANGELOG, not by a test for each one. The machine-checked parts are the
  version tables.
- **Restore replaces the committed store wholesale.** Any record written
  after the backup is lost unless it is saved first; the dry run lists
  exactly what would change.
- **The interruption marker lives in `private/`.** A migration interrupted on
  one machine is resumed only on that machine. The store's manifest still
  shows the last completed version everywhere.
- **Nothing was migrated in this package.** The approved policy needed no
  format change, so the new machinery is exercised against the existing
  schema-3 step.
