# WP15: rebuild cost falls without dropping work (2026-09-27)

This implements work package WP15 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), finding F23.
The starting commit is `9a28ed4`, after WP14. The operator authorized the
remaining work on 2026-09-27.

## Cause

Profiled before any change (`benchmarks/continuity_scale.py` and cProfile, on
a synthetic 1,000-record store):

- **Every record was parsed about seven times per publication.**
  - A 1,000-record reindex made 7,200 parses.
  - The packet, the guard pre-filter, related, conflicts and the search index
    each re-read the store.
  - The conflict report was computed twice: once for the packet, once for
    `conflicts.json`.
- **`_base_stem` stemmed the same words tens of thousands of times.**
- **Related and conflicts compared every pair.**
  - Past 2,000 items, `related.json` was skipped (with a `skipped` reason).
  - Past 2,000 items of one type, the audit's near-duplicate sweep was
    skipped, and nothing said so.
- **A machine-local jot ran a full publication.** It took 2.9 s at 1,000
  records and rewrote about 288 KB of shared files, although no shared view
  reads `private/inbox/`.

## Change

- **`cli.operation()`.**
  - Every CLI command (locked or not), hook, MCP call (`_data_tree`,
    `_data_view`) and publication runs inside one operation.
  - `Record.from_bytes` caches a parse under (path, type, sha1 of the exact
    bytes), so a changed file always re-parses. Each caller gets its own
    frontmatter dict.
  - `op_memo(key, compute)` memoizes a derived result under a key that names
    its inputs. `content_key(records)` is the key for "exactly these records'
    bytes".
  - Nothing survives the operation, so a long-lived MCP server never serves a
    stale view. The state is thread-local.
- **`_base_stem` is memoized** (`lru_cache`). It is a pure function of the
  token.
- **`related.compute_related` scores only pairs that can score.**
  - Pairs come from postings of shared files, tag stems and non-ubiquitous
    stems. A pair sharing none of these scores 0, and `GUARD_NOISE_FLOOR` is
    positive, so the result is exactly the all-pairs result.
  - The all-pairs version is kept as `_compute_related_full`, the test oracle.
  - Pairs are enumerated one item at a time, and only each item's best 3 are
    kept. The order is total (score, then unique id), so this equals a full
    sort. Memory is linear in the store.
  - There is no corpus cutoff; `skipped` is always `null`.
- **The pair budget.**
  - Past `RELATED_PAIR_BUDGET` (3,000,000) candidate pairs, the most widely
    shared features stop generating pairs.
  - `related.json` then carries `degraded: {reason, dropped_features,
    largest_dropped_posting}`, and `crumb audit` raises `related-degraded`.
  - Nothing is dropped silently.
- **`lifecycle` pairs records by exact prefix filtering.** This applies to
  both contradiction rules and to the near-duplicate sweep.
  - Why it is exact: every threshold is a Jaccard bound, once the capped file
    and tag bonus is subtracted. Two sets that reach Jaccard *t* share at least
    ceil(*t*·|A|) stems. So their prefixes, ranked rarest first, must
    intersect.
  - A 0.01 margin covers rounding.
  - The pairwise versions are kept as `_find_contradictions_full` and
    `_near_duplicate_pairs_full`.
  - The sweep's 2,000-item skip is gone.
  - The contradiction report is memoized per operation under `content_key`.
- **`inbox.write_jot` skips the publication for a local jot.** A committed
  jot still publishes, because the packet's inbox section is shared.
- **`benchmarks/continuity_scale.py` (new).**
  - It measures reindex, remember, local jot, the prompt and guard hooks, and
    search.
  - For each it reports median untraced wall time, parse count, whole-store
    input hashes, and bytes written (write amplification). Peak memory comes
    from one extra tracemalloc run.
  - It also reports what related and conflicts still produce.
  - A command that exits non-zero stops the run, so a refusal can never be
    measured as the command.

**Docs:**
- `cli-spec.md` covers `reindex` (related) and the `audit` checks
  (`near-duplicates`, `related-degraded`).
- `record-schema.md` covers `related.json` (`skipped`, `degraded`).
- `architecture.md` code map rows.
- `CHANGELOG.md`.

## Tests

`tests/test_incremental_equivalence.py` has 6 tests.

- **`test_incremental_related_and_conflict_results_match_full_oracle`.**
  - Three seeded stores (60, 200 and 350 records, with narrow and wide
    vocabularies).
  - Rounds of adding, editing and removing records.
  - After every round, related, contradictions and the near-duplicate sweep
    equal their pairwise oracles, both outside and inside one operation.
- **`test_local_capture_does_not_rebuild_unaffected_shared_views`.**
  - A local jot does not call `_publish_projections`.
  - Every file in `generated/`, and `index/generation.json`, is byte- and
    mtime-identical afterwards.
  - `validate` passes and `search` finds the jot.
  - A committed jot still publishes once.
- **`test_1000_and_10000_record_quality_does_not_collapse`.**
  - At both sizes: related is never skipped, two planted records find each
    other, more than 90% of items have a related entry, and the share with
    one does not fall at 10,000.
  - 1,000 records must not degrade.
  - The 10,000-record store is far denser than a real one (ten area tags, a
    40-word vocabulary), so the budget does apply there. The test requires the
    report to say so.
- **`test_the_parse_cache_never_serves_stale_content`.** A file edited
  mid-operation re-parses, and a caller's edit to a loaded record's
  frontmatter does not reach the next caller.
- **`test_budget_degrades_visibly_not_silently`.** With the budget patched to
  50: `degraded` is present and `skipped` stays `null`. After a reindex, the
  committed file carries the report and `audit` raises `related-degraded`. A
  normal reindex clears both.
- **`test_duplicate_sweep_covers_every_type_at_any_size`.** Among 2,050
  decisions, a planted near-identical pair is found.

**Behavior comparison.** [behavior.txt](behavior.txt), from
[behavior.py](behavior.py): one subprocess per tree, on the same seeded store
of 2,052 decisions.

| Check | Before (`9a28ed4`) | After |
|---|---|---|
| `related.json` skipped above 2,000 items | yes (0 items related) | no (2,052) |
| Duplicate sweep misses the planted twins | yes | no |
| Local jot republishes the shared views | yes | no |
| Parses per reindex exceed twice the records | yes (14,364) | no (2,052) |
| Conflict report computed more than once per reindex | yes (2) | no (1) |
| **Defects observed** | **5** | **0** |

## Performance

[benchmark.json](benchmark.json) holds the raw results. These are local
measurements on one 4-core container with Python 3.11 and synthetic stores,
for comparing versions, not production percentiles. Times are medians of
untraced runs.

| Operation, 1,000 records | Before: ms / parses / bytes written | After: ms / parses / bytes written |
|---|---|---|
| `reindex` | 2,751 / 7,200 / 287,172 | 857 / 1,000 / 287,172 |
| `remember` (write + publish) | 2,821 / 8,217 / 288,756 | 984 / 1,002 / 288,756 |
| `jot --local` | 2,909 / 8,238 / 288,562 | 147 / 1,006 / 600 |
| prompt hook | 166 / 604 / 5,359 | 121 / 604 / 5,359 |
| guard hook | 244 / 1,399 / 4,011 | 155 / 1,004 / 4,011 |
| `search` | 159 / 510 / 0 | 105 / 510 / 0 |

- **Peak Python memory for reindex** is 22.8 MB before and 11.5 MB after.
- **Input hashes are unchanged**: 2 for reindex, 3 for remember. A local jot
  now makes 1 (was 3).
- **Quality:** related covers 1,004 items both before and after, and `skipped`
  is `null`.

**10,000 records (after only).**

| Operation | ms / parses / peak MB |
|---|---|
| `reindex` | 20,018 / 10,000 / 116 |
| `remember` | 20,696 / 10,001 / 116 |
| `jot --local` | 1,438 / 10,003 / 78 |
| prompt hook | 1,254 / 5,856 / 60 |
| guard hook | 1,447 / 10,002 / 80 |
| `search` | 1,087 / 4,950 / 51 |

- Related covers all 10,002 items, with `skipped` null.
- **Not measured before WP15:** the pre-WP15 build compares every decision
  pair for conflicts. At this size that is roughly 28 million comparisons per
  reindex, so it was not run. Its related map would have been skipped.
- Before the bounded top 3, this reindex peaked at 470 MB. The profile
  attributed it to related holding every scored pair.
- On the denser test store, prefix filtering took the 5,000-record
  contradiction pass from 21 s to 6 s under cProfile, with an identical
  result.

## Results

| Command | Exit | Result |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` (3.11) | 0 | 1332 run, 0 failures, 7 skipped |
| incremental, show, snapshot, inbox, admission and MCP tests on 3.9.23 | 0 | 129 OK (6 skipped: MCP SDK) |
| `test_mcp` and `test_admission_policy` with MCP SDK 2.2.0 | 0 | 57 OK (2 skipped) |
| `python evals/run.py --verbose` | 0 | Identical to WP14 apart from timings ([evals.txt](evals.txt)) |
| `python evals/run.py --release` | 0 | 20 critical cases pass |
| `regression_probes.py … --fail-on-observed` | 2 | Unchanged: 3 defect signals, 3 probe errors ([probe-results.json](probe-results.json)) |
| CI `test` job fixture steps, replayed | 0 | All 7 pass |
| `ruff check . && ruff format --check .` (0.16.1) | 0 | Clean |

## Compatibility

- **On-disk data.**
  - No record changes, and `SCHEMA_VERSION` stays 4.
  - `related.json` gains an optional `degraded` object, and `skipped` is now
    always `null`. A reader that treated a non-null `skipped` as "empty map"
    loses nothing.
  - The contents of `conflicts.json`, and of `related.json` for a store under
    the budget, are unchanged: the oracle tests check them against the
    pairwise versions, and the benchmark's bytes written are identical.
- **New `audit` check:** `related-degraded` (warn).
- **`crumb jot --local` no longer refreshes generated files or the search
  index.** None of them read `private/inbox/`.
- **Python API.**
  - `lifecycle.DUP_SWEEP_MAX_ITEMS` is removed; nothing in the repo read it.
  - `related.RELATED_MAX_CORPUS` is kept for importers.
  - `cli.operation`, `cli.op_memo` and `cli.content_key` are new.

## Limits

- **Capture still validates the whole store.** Every write runs one
  `run_validate` (the WP01 write gate, which also checks cross-record rules),
  so a local jot costs 0.15 s at 1,000 records and 1.4 s at 10,000. Narrowing
  that gate to the records a write can affect is a separate change.
- **Hooks are linear in the store.** At 10,000 records the prompt and guard
  hooks take 1.2 to 1.5 s here. WP10 and WP11 set their shape; this package
  only removed repeated parsing.
- **Publications are not coalesced across operations.** Each shared write
  still publishes once, synchronously. There is no pending-generation queue
  or daemon; within one operation the work is shared.
- **The pair budget is a count, not a time.** A pathologically dense store
  stays bounded, but it reports `degraded` rather than finishing everything.
- **Synthetic stores.** The benchmark store shares vocabulary more densely
  than the real stores the evals use. Timings on real stores should be lower,
  but they are not measured here.
