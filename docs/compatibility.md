# Compatibility and upgrades

What each crumb-kit release promises about the files it reads and writes, how
a store is upgraded, and what happens when two versions meet one store. This
is the policy audit WP21 asked for (findings F05, F18, F24). The operator
approved it on 2026-09-27.

`tests/test_store_upgrade_contract.py` checks the tables marked
*machine-checked* against the code, so this page cannot drift from what the
package emits.

## 1. The version policy (before 1.0)

crumb-kit is pre-1.0. It still promises something, so an upgrade can be
predicted from the number:

- **`0.MINOR` changes when anything breaks compatibility**:
  - the store's `schema_version` changes;
  - the manifest gains a `requires` feature;
  - a *compatibility surface* (§5) changes in a way an existing reader,
    script or integration would notice.
- **`0.x.PATCH` is for fixes and compatible additions**: a new optional
  field, a new command or flag, a new JSON key, a bug fixed without
  changing a surface.
- **`1.0` is not scheduled.** At 1.0 the same rules move up one place.
- **`schema_version` is separate from the package version.** It changes only
  when the on-disk format changes. A `schema_version` change always comes with
  a minor bump. `crumb --version` prints both.

A release that changes `SCHEMA_VERSION` must bump the minor in
`breadcrumbs/__init__.py`, and the test suite fails otherwise. The release
workflow runs the suite before it publishes, so the existing release process
enforces this rule with no second tagging or publishing path.

Under this policy **the audit branch's release is 0.4.0**. It changes
compatibility surfaces: stricter `validate` (WP01), pre-filter formats 2 and 3,
new verdict floors (WP10), refused links (WP13) and refused writes to newer
stores (this page).

## 2. What carries a version

<!-- compat:surfaces:begin (machine-checked) -->
| Surface | Current | Defined in | When it changes | A reader that finds another value |
|---|---|---|---|---|
| `package` | `__version__` | `breadcrumbs/__init__.py` (the one place it is written) | every release | `crumb --version` reports it; nothing reads it from a store |
| `schema_version` | 4 | `cli.SCHEMA_VERSION`, written to `manifest.yml` | on-disk record format | older: read as is, `crumb migrate` upgrades; newer: writes refused, reads warned (§4) |
| `requires` | min-crumb-version, review-profiles | `compat.KNOWN_FEATURES`, `manifest.yml` `requires:` | a change old readers must not ignore without a format change | an unknown feature is treated like a newer `schema_version` |
| `generation-manifest` | 1 | `projections.MANIFEST_FORMAT` (`index/generation.json`) | projection publication format | treated as unverified; the next publication rewrites it |
| `guard-prefilter` | 4 | `cli.GUARD_PREFILTER_FORMAT` (`index/guard-prefilter.json`, machine-local since 0.6.0; earlier `generated/`) | pre-filter contents | treated as unverified (the hook runs full guard) until republished |
| `search-index` | 2 | `searchindex.INDEX_FORMAT` (`index/search.sqlite`) | index schema | ignored (full scan); `crumb reindex` rebuilds it |
| `miner-state` | 2 | `hooks_common.MINER_STATE_VERSION` (`private/miner/`) | transcript cursor state | started fresh; the acknowledged-event ledger prevents duplicates |
| `usage-event` | 1 | `usage.py` event `v` (`private/usage-events/`) | usage event shape | an unreadable event is dropped and counted (`accounting`) |
| `migration-backup` | 1 | `migrate.backup_store` (`backup-manifest.json`) | backup manifest shape | a backup without a readable manifest is not restored automatically |
<!-- compat:surfaces:end -->

Projection, index and machine-local formats are **rebuilt, never migrated**.
They are derived from the records (or are local telemetry), so a mismatch
costs a rebuild, never data. Only `schema_version` (and `requires`) describe
content that must be converted or must not be misread.

## 3. Releases

<!-- compat:releases:begin (machine-checked) -->
| Release | schema_version | Notes |
|---|---|---|
| 0.1.0 | 1 | first release |
| 0.1.1 | 1 | |
| 0.1.2 | 1 | on PyPI, never tagged (RELEASING.md) |
| 0.1.3 | 1 | |
| 0.1.4 | 1 | |
| 0.1.6 | 1 | tagged with a GitHub Release, never on PyPI |
| 0.1.7 | 1 | first release the workflow tagged |
| 0.1.8 | 1 | |
| 0.1.9 | 1 | |
| 0.1.10 | 1 | |
| 0.1.11 | 1 | |
| 0.1.12 | 1 | |
| 0.2.0 | 1 | |
| 0.3.0 | 4 | schema 1 → 4 in one release (phases 0–6); `crumb migrate` |
| 0.3.1 | 4 | hotfix: hook launchers never pass a failure through |
| 0.4.0 | 4 | the audit remediation (WP00–WP22); `requires: review-profiles`; OS write lock |
| 0.5.0 | 4 | the DoWhat field-report fixes; `--next` appends; guard reworked |
<!-- compat:releases:end -->

The rows are the CHANGELOG's released sections. Checked against PyPI on
2026-09-27: every row is on PyPI except 0.1.6, which was tagged and never
published. 0.1.5 was tagged, never published, and has no CHANGELOG section. A
stray tag `0.1.13` (no `v`) points at a 0.1.12 commit and was never published
either (`RELEASING.md` → *Tag / PyPI history*).

## 4. Two versions, one store

### A newer store, read by this build

"Newer" means one of three things:
- the store's `schema_version` is above this build's;
- the store's manifest lists a `requires:` feature this build does not
  implement;
- the store's `min_crumb_version` is above this build's version (0.6.0 on).

The approved rule is **refuse writes, warn reads** (`breadcrumbs/compat.py`).

- **Writes are refused.** The check runs when the store's write lock is
  taken, which every committed write already does. It fails as
  `lock.IncompatibleStore`, a `StoreLocked`, so every writer handles it the
  way it handles a busy store:
  - `remember`, `note`, `capture`, `reindex` and the rest exit 1 with "…
    Upgrade crumb-kit.";
  - MCP writing tools return `{ok: false, error}`;
  - the capture hooks skip their write (they never block the host);
  - `resume` prints its packet and reports the publication as refused.
- **Reads keep working, with a warning.** The resume packet shows it under
  its title (also in the `SessionStart` hook and `memory://resume-packet`).
  `guard` reports it in `compatibility`, in its human output and in the guard
  hook's advisory. Other read commands print it on stderr.
- **Repair is the one exception.** `crumb migrate --restore` can write a
  store this build cannot otherwise write. Returning to a verified backup is
  how such a store is recovered.

### A store read by crumb-kit 0.3.1 or earlier

Released versions do not run this check. They read and write a newer store as
if it were theirs, and only their `validate` fails ("upgrade crumb-kit").
This was reproduced on 0.3.1 against a `schema_version: 5` store: `remember`
wrote a record, `guard` and `resume` ran, and `validate` failed. So a change
that such readers must not misread is designed to **fail safe for them**:

1. **A store-wide change bumps `schema_version`.** Their `validate` fails, and
   so does CI that runs it.
2. **An opt-in change** (a policy only some stores enable) is declared with a
   `requires:` feature on the stores that enable it. Every build from 0.4.0 on
   refuses to write such a store unless it implements the feature. This avoids
   forcing every store through a migration for something most never use.
3. **Keep the new meaning out of what old readers already interpret.** Put it
   in a field they ignore (unknown keys are ignored and kept) or a directory
   they do not read, never in a changed meaning of an existing field or value.

**A minimum writer version** (DoWhat retest of 0.5.0, item 14).
`min_crumb_version: 0.5.0` in `manifest.yml` names the oldest crumb-kit that
may write the store. It is for a change in how a build *writes* that needs no
format change: 0.5.0 made `capture session --next` add an entry to the Next
Action log, and a 0.4.x capture still replaced the whole log. `crumb migrate`
raises it to `compat.MIN_SAFE_WRITER` (never lowers it), on a current store
too, and lists `min-crumb-version` under `requires:`. That bridge makes 0.4.0
and 0.5.0, which predate the field, refuse to write until upgraded; every
build from 0.6.0 compares the version itself. It can also be set by hand, and
`crumb doctor` shows it. A release that changes how a store must be written
raises `MIN_SAFE_WRITER`.

**Review profiles** (audit WP14) are an opt-in change. A team store declares
`requires: review-profiles`. Its proposals use an existing value,
`review_status: needs-review`, and keep `status: active`: they are ordinary
guidance to an old reader, which is what they were before profiles existed.
What an old reader cannot do is *enforce* the team profile. It would promote
an unreviewed record, and nothing local stops a 0.3.1 install from that. The
documented boundary for team stores is Git review of `CLAUDE.md` and
`AGENTS.md` changes, plus `crumb validate` from a current build in CI
(`security.md` §4.2).

### An older store, read by this build

It is read as it is: readers accept the previous shape for one major version
(`migrate.py`). `validate` names `crumb migrate` as the fix, and writes are
allowed.

## 5. Compatibility surfaces

Changing any of these in an incompatible way is a minor bump (§1), and the
CHANGELOG entry says what changed.

- **`crumb guard` exit codes** 0 / 10 / 15 / 20 (verdicts), 2 (usage), 1
  (error). New behavior is opt-in (`--exit-zero`).
- **`--json` output:** the `ok`, `command` and `items` envelope, and every
  documented key. Adding a key is compatible; removing or renaming one is not.
- **Record ids** (filename-canonical), the frontmatter keys and vocabularies
  in `record-schema.md`, and the directory layout.
- **Adapter managed blocks** (`CLAUDE.md`, `AGENTS.md`, `.gitignore`), the
  MCP registration in `.mcp.json`, and the hook entries in
  `.claude/settings.json`: their markers and the commands they run.
- **MCP tool and resource names**, their arguments, and their result keys.
- **Hook input and output:** the events handled, and the JSON returned to the
  host.

## 6. Legacy and invalid data

What an upgrade does with data that predates, or breaks, the current contract.
**Migration never rewrites a record's meaning.** Guessing what a free `scope`
meant, or raising a confidence, would invent facts.

| Data | Found by | What upgrade does |
|---|---|---|
| Free-text `scope` (`all-machines`, …) | `validate`: `scope-unsupported` | Left as is and reported by `crumb migrate --dry-run`; a person picks `project` or `branch` |
| Invalid `confidence`, `review_status`, evidence or timestamps | `validate`: the `record-schema.md` §4 codes | Left as is and reported; never auto-corrected, never raised |
| `superseded_by` naming a record that is gone (for example rolled up) | `validate`: `superseded-by-missing` | Reported; `supersedes` targets are deliberately not checked (§4) |
| Unknown frontmatter keys | Nothing: not an error | Kept by every migration step and every writer |
| `review_status: reviewed` without a `crumb review` stamp | `admission.review_state` reports it as `claimed` | Kept as is. In the team profile it is not authority: promotion needs a stamp that matches the content (`security.md` §4) |
| Traps and questions as blocks (schema ≤ 2) | `validate`: `schema-version` | Migrated (schema 3) with ids kept; readers accept blocks until migrated |
| Projections, indexes, pre-filters, private state | Format markers (§2) | Rebuilt, never migrated |
| Links inside the store | `validate`: `path-link` | `migrate` refuses until they are replaced (WP13) |

## 7. Upgrading a store

```bash
crumb migrate --dry-run     # the steps, what the backup will hold, what is left for you
crumb migrate               # verified backup, then the steps, one version at a time
crumb migrate --restore     # back to the backup, verified before and after
crumb migrate --restore --dry-run   # which files a restore would change
```

- **Preview.** `--dry-run` lists every step and says how many files the
  backup will copy. It lists the legacy findings (§6) the migration will
  leave alone, and whether it would resume an interrupted migration. It
  changes nothing.
- **Verified backup.** The committed store is copied to
  `private/migrations/<timestamp>/` with `backup-manifest.json` (a SHA-256
  per file). The copy is checked against the store before any step runs, and
  a backup that does not verify stops the migration.
- **One version at a time.** Each step writes the manifest when it finishes,
  so a failure leaves the store at the last completed version, never between
  versions.
- **Interruption.** `private/migrations/in-progress.json` names the backup
  and the version reached. The next `crumb migrate` resumes from there,
  against the same pre-migration backup, and clears the marker when done.
- **Restore.** `--restore` checks the backup against its manifest, replaces
  the committed store with it (`private/` and `index/` are untouched), then
  checks the store against the manifest. Backups made by 0.3.1 or earlier
  have no manifest and are not restored automatically; copy one back by hand.
- **Stable ids and kept content.** No step renames a record, and unknown
  frontmatter keys survive.
