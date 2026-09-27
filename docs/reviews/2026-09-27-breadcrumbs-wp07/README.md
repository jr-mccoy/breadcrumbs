# WP07: coherent snapshots and projections (2026-09-27)

This implements work package WP07 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md): findings F07,
F11 and F12, plus the rest of F06. The starting commit is `5687d16`, after
WP06.

## Cause

- **F07: stamps certified content the build never read.**
  `build_resume_packet` read the records first and computed `inputs_hash`
  last. A record written in between was missing from the packet, but the stamp
  matched the store that included it, so `validate` accepted the packet
  (`snapshot_stamp_race` probe). `related.json` and `conflicts.json` had the
  same shape.
- **F07/F06: a publication was not a generation.** The four `generated/` files
  and the search index were each replaced atomically, one by one. Nothing said
  which files belonged together, so a reader could combine a new packet with a
  pre-filter from an older publication, or with one from a publication that
  failed halfway.
- **F11: an unusable pre-filter read as "no risk".** `_prefilter_trap_hit`
  returned `False` when `guard-prefilter.json` was missing or malformed. It
  never checked that the file described the current records. An unavailable
  shortcut therefore made a routine-looking command that matches a recorded
  trap pass silently.
- **F12: index freshness had a metadata shortcut.** An equal path/size/mtime
  fingerprint returned `fresh` before any content was compared. A same-size
  edit with a restored mtime left indexed search missing a word the full scan
  found (`index_metadata_collision` probe).

## Change

**`breadcrumbs/snapshots.py` (new): a stamp is the snapshot that was read.**

- `stable_build(memory_dir, root, build)` works in three steps:
  1. hash the inputs;
  2. build, stamping with that hash;
  3. hash again.
- If the two hashes match, the stamp names exactly what the build read. If not,
  it retries, up to `ATTEMPTS = 3`.
- A store that keeps changing is stamped `UNSTABLE` (`"unstable"`), never a
  digest:
  - the packet leads its warnings with `UNSTABLE_WARNING`;
  - `_stamped_inputs_hash` accepts the stamp, so `validate` reports `freshness`.
- `build_resume_packet` is now `stable_build` over `_build_resume_packet_once`,
  which takes its stamp as an argument instead of hashing at the end.

**`breadcrumbs/projections.py` (new): the generation manifest.**

- `index/generation.json` records `{format, inputs_hash, stable,
  published_at, files: {name: sha256}, stat_fingerprint}`.
- It is machine-local, under the gitignored `index/`, because it describes this
  checkout's publication.
- `verified(memory_dir, root, name)` returns a generated file's bytes only when
  all of these hold:
  - the manifest exists and is `stable`;
  - the file's sha256 matches its entry;
  - the canonical inputs' stat fingerprint is unchanged since publication.

  Otherwise it returns `None`.

**`_publish_projections` in `cli.py`: one snapshot, one generation.**

- All outputs are built inside one `stable_build` with the same digest:
  - the packet;
  - the guard pre-filter, now stamped with a top-level `inputs_hash`;
  - `related.json` and `conflicts.json`, via a new `inputs_hash=` on
    `render_related` / `render_conflicts`;
  - the search index.
- The index is **staged** (`build_index(..., inputs_hash=digest,
  publish=False)`) in its own `mkstemp` file. It goes live (`publish_index`)
  only when the snapshot proved stable. A `finally` discards every other staged
  file, from unstable attempts or a publication that raised.
- The stat fingerprint for the manifest is taken inside the verified window.
- On an unstable outcome, the views are rebuilt stamped `unstable` (the packet
  with the warning) and no index is published. `try_reindex_projections`
  returns `(False, "the store kept changing during publication; projections
  stamped unstable")`.
- The old manifest is removed before any output is replaced. The new one is
  written **last**, so a partly replaced set has no manifest.

**The guard hook (`_prefilter_trap_hit`) reads its pre-filter through
`projections.verified`.** When the pre-filter is unverified, the call counts as
possibly risky: the hook runs the full guard against the records and logs
`prefilter: "unverified"`. Only a verified pre-filter can keep the hook quiet
(`skipped: "prefilter"`).

**`breadcrumbs/searchindex.py`: strict freshness.**

- `_is_fresh` compares the format and the content hash only. The stat shortcut
  is gone, and so is `stat_fingerprint` in the index meta.
- `INDEX_FORMAT` is now `"2"`.
- `build_index` changes:
  - it takes `inputs_hash=` (the caller's verified snapshot) and `publish=`;
  - without a digest it verifies its own snapshot and refuses with "the store
    changed during the build";
  - new `publish_index` and `discard_index`.

**Other changes.**

- `.gitignore`: `fixtures/**/.project-memory/index/**`. CI and the tests run
  `resume` inside fixture-01, which now writes a manifest there.
- The committed fixture-01 `guard-prefilter.json` carries its stamp
  (`5fbbdbd0b95a`, equal to its packet's).
- `tests/test_secrets.py` injects its reindex failure through
  `_build_resume_packet_once`, since the patched name moved.

**Docs.**

- `cli-spec.md`:
  - a new section, *Coherent projections*;
  - the `resume` lock and stamp bullets (the old "never waits on the write
    lock" text was out of date since WP05);
  - `reindex`, `search` freshness, the guard hook's pre-filter, the `validate`
    row, and the lock section.
- `architecture.md`: module rows for `snapshots.py` and `projections.py`, and a
  manifest row.
- `record-schema.md`: `index/generation.json` and the stamped pre-filter.
- `README.md` and `CHANGELOG.md`.

## Tests

`tests/test_snapshot_consistency.py` has 11 tests, including the four the
roadmap names.

- **`test_mutation_between_read_and_hash_cannot_false_certify`.** A decision is
  written from inside the packet build, after its decisions were read (through
  a patched `compute_staleness`). The test asserts the invariant, and then the
  concrete outcome: after the retry, the stamp equals the current store and
  the new decision is in the packet.
- **`test_mixed_generation_is_not_consumed`.** After a publication, the
  pre-filter is replaced with another generation's file, corrupted, and then
  removed. In each case, an edit of the trapped file still gets its warning,
  and the hook log says `prefilter: "unverified"`. With the verified file
  restored, an unrelated edit stays silent (`skipped: "prefilter"`).
- **`test_two_index_builders_do_not_share_temp_file`.** Two threads build the
  index at once, held together by a `Barrier` in a patched `sqlite3.connect`.
  They use two distinct temp files, both succeed, and none is left behind.
- **`test_same_size_restored_mtime_edit_invalidates_strict_index`.** Over 201
  records, one word is swapped for another of the same length and the mtime is
  restored. `index_status` says `stale`, and indexed search equals the full
  scan.
- **Also covered:**
  - a store that keeps changing is stamped `unstable` with the warning;
  - an unstable publication is not certified (`validate` freshness fails, the
    manifest says `stable: false`), and the next quiet publication certifies
    again;
  - every output of a generation carries one stamp, and the manifest lists all
    four;
  - a hazard written to disk after publication is still warned about;
  - an unstable manifest is not trusted;
  - a failed publication leaves no staged index and no manifest;
  - a self-verifying index build refuses a changing store.

Against the pre-change code (WP06, `5687d16`, with only the two new helper
modules copied in so the file imports), **all 10 original tests fail**:

- **8 behaviorally**, for example:
  - the false-certify stamp `df6a0f225730` against the store's `faa702612765`;
  - "a real hazard went silent" for all three damaged pre-filters;
  - `'fresh' != 'stale'`.
- **2 structurally:** there was no manifest to read, and the pre-filter had no
  stamp.

`test_two_index_builders_do_not_share_temp_file` fails there only on the new
`inputs_hash=` / `publish=` arguments. Its substance, a temp file per build,
was already fixed in WP05, and the test now pins it.

The 11th test was added for the cleanup this package introduced. Against the
same code without the `finally` it fails, leaking `.index.*.tmp`.

## Results

| Command | Exit | Result |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` (3.11.15) | 0 | 1245 run, 0 failures, 6 skipped |
| WP07 and affected guard/hook/lock/mutation/resume/search/index/secrets/validate tests on 3.9.23 | 0 | 328 OK |
| `test_mcp` with MCP SDK 2.2.0 | 0 | 50 OK (2 skipped) |
| `python evals/run.py` | 0 | Unchanged against the baseline |
| `regression_probes.py … --fail-on-observed` | 2 | 10 defect signals, 2 probe errors (WP04/WP05's recorded instrument errors). `snapshot_stamp_race` and `index_metadata_collision` are no longer observed ([probe-results.json](probe-results.json)) |
| CI `test` job fixture steps, replayed | 0 | All 7 pass |
| `ruff check . && ruff format --check .` (0.16.1) | 0 | Clean |

Measurements, from the recorded run on this machine:

| What | 200 records | 1,000 records |
|---|---|---|
| `_inputs_hash`, the strict index freshness check | 3.5 ms | 17 ms |
| `hook guard` on a routine `pytest` call, verified pre-filter | 2.6 ms | 8.2 ms |
| The same call, pre-filter unverified (full guard on the records) | 39 ms | 92 ms |

A scripted store also stays verified after `init`, `resume`, `remember`, `jot`,
`jot --local`, `capture session`, `guard` and `verify`. Only a hand edit that
was never reindexed unverifies it. That is the intended behavior: the hook
cannot know what the edit changed.

The remaining signals belong to other packages:

- `sliding_cursor`;
- `prompt_cliff`;
- `guard_prefilter` (F10: the pre-filter's two-token rule, not its
  availability);
- `promoted_adapter_missing`;
- `packet_bound`;
- `symlink_read`;
- `powershell_translation`;
- `short_prompt_and_stale_task`;
- `guard_usage_dedupe`;
- `resume_ignores_lock`, the false positive recorded in WP05. The probe fakes
  the holder with a pid file, which is not the OS lock.

## Compatibility

- **The committed `guard-prefilter.json` gains a top-level `inputs_hash`**, so
  `validate` now drift-checks it like `related.json`.
  - Older crumb-kit versions read only `paths` and `tokens`, so they ignore the
    stamp.
  - A pre-filter written by an older version has no stamp and is skipped by
    that check.
- **A projection can be stamped `unstable`.** Tools that parse the packet
  header's `inputs_hash` as hex must accept it. `validate` reports it stale.
- **`reindex` can report "the store kept changing"** and return not-ok. This
  happens only when the store changed across three consecutive builds.
- **The guard hook is slower until a publication exists on this machine.**
  Examples: a fresh clone before its first `resume`, or after a hand edit.
  - Calls that the pre-filter would have let through run the full guard
    instead: tens of milliseconds, not a few.
  - The first `resume`, including the `SessionStart` hook's, or any recording
    command, writes the manifest.
- **The search index format is now `2`.** An existing index is stale until the
  next reindex rebuilds it; search falls back to the full scan meanwhile.
- **New machine-local file:** `index/generation.json`, covered by the existing
  `index/` ignore rule. For fixtures committed inside the repo, a new
  `.gitignore` line covers it.
- **Library callers.**
  - `build_index` takes `inputs_hash=` and `publish=`. With neither, it
    verifies its own snapshot and may refuse with "the store changed during the
    build".
  - `render_related` / `render_conflicts` take `inputs_hash=`.
  - `build_resume_packet` keeps its signature.

## Limits

- **Snapshot verification is by re-hashing, not by an immutable copy.**
  - A change undone during the build, leaving identical bytes, is invisible,
    and the output then equals what those bytes produce.
  - Every build hashes the store twice. That is cheap at the measured sizes (17
    ms at 1,000 records) but grows with the store.
- **The hook's generation check uses a stat fingerprint, not content.** A
  same-size edit with a restored mtime made *after* a publication can still
  pass `verified()`. The strict checks, `validate` and the search index,
  compare content. This is the cost the hook path's budget allows. It is
  documented in `projections.py` and `cli-spec.md`.
- **View identity is not separated from the canonical snapshot.** The roadmap's
  first step also asks for branch, time, query and consumer context to be kept
  apart from the snapshot digest. `inputs_hash` already hashes only canonical
  inputs, but there is no separate view-identity field yet. That field belongs
  with WP08's view budgets.
- **`resume` without the lock still prints a freshly built view.** When the
  lock is busy, the packet it prints is stamped by the same verified snapshot,
  or `unstable`, but it does not fall back to the last published generation.
  WP05's `publication` report already tells the caller nothing was published.
- **A publication that fails leaves the old outputs partly replaced.** No
  manifest vouches for them, `validate` and `doctor` show it, and
  `crumb reindex` fixes it. There is no roll-forward.
