# WP10: indexed retrieval, short prompts and named commands (2026-09-27)

This implements work package WP10 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md): findings F09
and F10, and what WP07 left of F11 and F12. The starting commit is `293a90b`,
after WP18. As the operator asked, it also wires the WP18 critical eval gate
into the release workflow, in a separate commit, once WP10 made it pass.

## Cause

- **F09: a size cliff.** `hooks_prompt.retrieve` first called
  `_candidate_items`, which parses every record, only to count them. Above
  `PROMPT_HOOK_MAX_CORPUS` (500) it returned nothing, retired records
  included. One live decision beside 500 stale ones was never injected, at
  exactly the size where the search index exists to help (`prompt_cliff`
  probe).
- **F10: short prompts.** `hook_prompt` skipped any prompt under
  `MIN_PROMPT_CHARS` (12) as an acknowledgement. `quasar`, `npm test` and
  `ruff` were never looked up (`short_prompt_and_stale_task` probe).
- **F10: a named command came out `PROCEED`.**
  - `npm test` against a trap titled "npm test truncates the database" matched
    only through the short-query title rule, scored 3, and landed under
    `GUARD_READ_FIRST_SCORE` (5). The verdict was `PROCEED`, with the advice
    "likely unrelated".
  - The pre-filter's two-specific-token rule (`test` is generic) sent the hook
    down the silent path (`guard_prefilter` probe; webapp eval, `known: F10`
    in WP18).
- **F11: a proxy for "has records".** `_store_has_content` was "does the
  pre-filter file exist", which says nothing about decisions.
- **F12: no mode reporting.** Nothing reported whether a lookup used the index
  or fell back, or why.

## Change

**`breadcrumbs/retrieval.py` (new).**
- **`is_acknowledgment`.** A prompt made only of acknowledgement words (at most
  four: "ok", "yes please", "go on", "thanks", "lgtm", …), or only of
  punctuation and emoji, is not looked up. Anything else is, however short.
- **`prompt_lookup` returns a `Lookup`** (`matches`, `mode`, `complete`,
  `reason`, `records`, `candidates`). It calls `cli.search` directly, with
  no pre-count. The index narrows when it is current. Otherwise it scans in
  full, up to `PROMPT_FULL_SCAN_MAX` (2,000) records. Past that it returns
  `skipped` rather than stalling every prompt.
- **`eligible(match, purpose)`.** The prompt's current-records rule, moved
  from `hooks_prompt._is_current`, which now delegates to it. It is applied
  *before* the five-match cap, so history never takes a slot.
- **`corpus_summary`.** The record count from the verified generation manifest
  (`corpus`, new, written by every publication). Otherwise a file count with
  no parsing (`count_records`).

**`breadcrumbs/hooks_prompt.py`.**
- The acknowledgement check replaces the length gate.
- `retrieve` wraps `prompt_lookup`.
- A `skipped` lookup injects a one-line notice, once per session: "memory was
  not searched for this prompt — … Run `crumb reindex` …".
- The hook log records `retrieval` (`indexed`, `full_scan`, `skipped`,
  `acknowledgment`).
- `_store_has_content` uses the corpus summary.
- `MIN_PROMPT_CHARS` and `PROMPT_HOOK_MAX_CORPUS` are kept, documented as no
  longer gating.

**`breadcrumbs/cli.py`: exact command hazards.**
- **Command heads.** `_trap_command_heads` collects the commands a trap names:
  the leading words of its summary, and backticked spans in its *hazard* text.
  A command in the remedy, such as "use `npm run test:unit`", is what to run
  instead, and is excluded.
- **Matching.** `_names_command` matches when the action and a head share at
  least two leading tokens, covering the whole action or stopping at a flag.
  Commands are normalized: `cd x &&`, pipes and `2>&1` are folded, as in the
  miner.
- **The `command` signal.** `search` adds it (making a match if needed) and
  raises the score to at least `GUARD_READ_FIRST_SCORE`. `_decide_verdict`
  floors a live trap with it at `READ_FIRST`, the advisory ceiling: the reader
  is told, and the permission flow is untouched. `command` joins
  `GUARD_SURFACING_SIGNALS`.
- **`PROCEED` advice is reworded.** It now reads "No applicable memory warning
  found (PROCEED is not an authorization or a safety check)".
- **The pre-filter gains `format: 2` and `commands`.** `_prefilter_trap_hit`
  sends any action naming one to the full guard, and treats a pre-filter
  without `format: 2` as unverified.

**Lookup mode reporting.**
- `cli.search(..., allow_full_scan=, info=)` fills `info` with `mode`,
  `reason` and `candidates`.
- `searchindex.candidate_items(..., explain=)` gives the reason it could not
  serve: no index, stale, unreadable, under 200 records, no query terms, or no
  sqlite3.
- `crumb search --json` includes `lookup`, and `--explain` prints it.
- The stale `_stat_fingerprint` docstring (from before WP07) is corrected.

**Release gate** (separate commit, as the operator asked).
`.github/workflows/release.yml` runs `python evals/run.py --release --verbose`
after the test suite, in dry-run and publish modes. `RELEASING.md` describes
it.

**Evals.**
- The three `known: F10` critical cases pass, so their markers were removed.
  A stale marker fails the run, which is how the gate made them come off.
- The baseline was rewritten through the reviewed path. There were three
  task-level improvements and no regressions, all on webapp `npm test`:
  - `prompt_delivered` finds its trap;
  - the guard verdict is right;
  - the hook's answer is right.
- `test_evals`'s delivery test now shows the short prompt answered, and
  pins the measurement by forcing the acknowledgement check.

**Tests updated.** `test_guard` and `test_note` compared the pre-filter to an
exact `{"tokens", "paths"}` dict. They now check those keys and `commands`.

**Docs.**
- `cli-spec.md`: the command rule and the meaning of `PROCEED`, the
  pre-filter, the prompt hook row, *How the prompt hook looks up*, and
  `search`'s lookup report.
- `record-schema.md`: the pre-filter format and the manifest's `corpus`.
- `architecture.md`: a `retrieval.py` row.
- `README.md`, `evals/README.md`, `RELEASING.md` and `CHANGELOG.md`.

## Tests

`tests/test_retrieval_boundaries.py` has 9 tests, including the four the
roadmap names.

- **`test_one_active_plus_500_stale_records_still_retrieves`.** The live
  decision is found via the index, `complete`, through the real `crumb hook
  prompt`, and the log says `indexed`.
- **`test_199_200_201_and_499_500_501_preserve_results`.**
  - At each size, the real hook delivers the live record.
  - Indexed search equals the full scan (ids and scores).
  - The count check confirms each size.
- **`test_short_meaningful_prompt_is_not_acknowledgment`.**
  - `quasar` and `npm test` are answered.
  - Eight acknowledgements are silent without searching at all (a `search`
    that raises proves it), and each logs `acknowledgment`.
  - `ruff`, "no, use the amber queue" and "ok quasar" are not
    acknowledgements.
- **`test_index_missing_stale_or_corrupt_has_honest_fallback`.**
  - With an index, the lookup reports `indexed`.
  - Deleted: `full_scan`, "no search index", still found.
  - Edited after the build: `full_scan`, "stale", still found.
  - Garbage bytes: `full_scan`, "unreadable", still found.
  - Over the scan bound: `skipped`, with the notice once per session, then
    silence, and the log says `skipped`.
  - `crumb search --json` reports `full_scan` and finds the record.
- **Also covered:**
  - superseded records never take the live record's slot;
  - store content comes from the manifest's corpus, not the pre-filter;
  - named commands warn and nothing else does. `npm test`,
    `npm test --watch`, `pytest -n auto` and `cd web && npm test 2>&1` are
    READ_FIRST through guard, the pre-filter and the hook, as context with no
    permission decision. `npm run test:unit` (the remedy), `npm install`,
    `git status`, `pytest -q`, `make` and `npm testing` stay `PROCEED` and
    silent;
  - `PROCEED` is explained;
  - an old-format pre-filter is not trusted.

The test file cannot import on the pre-change code (there is no `retrieval`
module). The behavioral comparison is [behavior.txt](behavior.txt), a script
using only APIs both versions have:
- **Before (`293a90b`), 5 of 10 fail:** delivery at 501 records, `quasar`,
  the `npm test` prompt, the `npm test` verdict, and the `npm test` hook.
- **After, all 10 pass.**

## Results

| Command | Exit | Result |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` (3.11.15) | 0 | 1284 run, 0 failures, 6 skipped |
| retrieval, guard, note, hooks, search, index, evals and snapshot tests on 3.9.23 | 0 | 279 OK |
| `test_mcp` with MCP SDK 2.2.0 | 0 | OK (2 skipped) |
| `python evals/run.py --verbose` | 0 | 19 critical cases pass; webapp guard and hook-guard accuracy 0.5 → 1.0; ranking diagnostics otherwise unchanged ([evals.txt](evals.txt)) |
| `python evals/run.py --release` | 0 | Passes (it exited 1 at WP18) ([evals-release.txt](evals-release.txt)) |
| `regression_probes.py … --fail-on-observed` | 2 | 4 defect signals (was 7), 2 recorded probe errors. `prompt_cliff`, `guard_prefilter` and `short_prompt_and_stale_task` are no longer observed ([probe-results.json](probe-results.json)) |
| CI `test` job fixture steps, replayed | 0 | All 7 pass |
| `ruff check . && ruff format --check .` (0.16.1) | 0 | Clean |
| Prompt hook latency, one live decision among n records, current index | — | 501: 42 → 22 ms; 2,000: 193 → 60 ms; 5,000: 463 → 147 ms. It delivered nothing before, and delivers the record after |

The remaining signals belong to other packages:

- `symlink_read`;
- `powershell_translation`;
- `guard_usage_dedupe`;
- `resume_ignores_lock`, the false positive recorded in WP05.

## Compatibility

- **Short prompts are looked up.** A one- or two-word prompt that is not an
  acknowledgement can now inject records, where it used to be silent.
- **No store-size cutoff.** A store above 500 records now gets injections.
  Above 2,000 records with no current index, it gets a once-per-session
  notice instead.
- **A trap naming the exact command raises `guard` to `READ_FIRST`** (exit code
  10 from `crumb guard`), and the guard hook delivers context for it. Scripts
  that treated `npm test`-style commands as always `PROCEED` will see the
  change.
- **`PROCEED`'s `recommended_action` text changed.**
- **New data.**
  - Match signal `command`.
  - Pre-filter `format` and `commands`. An older pre-filter is treated as
    unverified, so the full guard runs until the next publication.
  - Manifest `corpus`.
  - `crumb search --json` `lookup`.
  - Hook-log field `retrieval`.
- **Library.** `cli.search` gains `allow_full_scan=` and `info=`, and
  `searchindex.candidate_items` gains `explain=`.
- **Releases.** Publishing (and dry-run) now also requires every critical eval
  case to pass.

## Limits

- **The command rule is deliberately narrow.** It needs at least two leading
  tokens (a single-word command like `make` never matches), and arguments other
  than flags break the match (`npm test tests/x`). A trap that describes a
  command without naming it, in its title or in backticks, is not covered.
- **The acknowledgement vocabulary is English and fixed.** An acknowledgement
  in another language is looked up (a false negative costs a lookup). A
  vocabulary word used as a task ("next", "resume") on its own is not.
- **`PROMPT_FULL_SCAN_MAX` (2,000) is a latency bound, not a correctness
  one.** Above it, with no current index, the prompt hook reports `skipped`
  rather than answering. `crumb search` and `guard` are unbounded.
- **The `corpus` count is of files**, not of eligible records. It answers "is
  there anything", not "how much is current".
- **Guard's own lookup** still scans in full when the index cannot serve. Only
  the prompt hook has the scan bound.
