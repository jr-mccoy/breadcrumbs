# WP18: delivered-context evaluation and critical gates (2026-09-27)

This implements work package WP18 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), finding F19.
The starting commit is `f75716d`, after WP09.

## Cause

`evals/run.py` measured ranking, and gated only on "not worse than the
baseline":

- **`prompt`** called `hooks_prompt.retrieve` directly. The hook's
  12-character length gate, session dedupe and rendering were never run. The
  webapp's `npm test` was scored as found, while the real hook says nothing
  for an 8-character prompt.
- **`packet`** kept only the entries with a positive task score and re-ranked
  them. The recency floor and every other line of the printed packet were
  invisible, so its precision (0.59) described a list no reader sees.
- **`guard`** checked eight verdict tasks. Its one miss, `npm test` getting
  `PROCEED` against a trap that says `npm test` truncates the database, was
  inside the accepted baseline (webapp 0.5, overall 0.875), so CI was green.
  Nothing marked that case as unacceptable in itself.
- **The metrics' definitions and denominators were never serialized.**
  precision@5 divides by the number shown, not by 5. guard accuracy is over 8
  tasks, so one miss is 0.125.
- **A baseline rewrite was one flag** (`--write-baseline`), with no record of
  why, no task-level view, and no held-out scenarios.

## Change

**`evals/run.py`: three layers, reported separately.**

1. **Ranking diagnostics, unchanged.** The same systems, the same
   definitions, the same numbers: every value in the old `baseline.json` is
   identical in the new one.
2. **Delivery.**
   - `prompt_delivered` runs `crumb hook prompt` through `cli.main`, with JSON
     on stdin and JSON on stdout, one fresh session per task. It fires a second
     time in the same session to measure `dedupe`. Correction capture is
     switched off, because it is a write and would leak state between tasks.
   - `packet_delivered` runs `crumb resume --task TASK`. It scores the first 5
     entries in reading order, recency floor included (`precision_at_5`),
     every entry in the packet (`recall_in_view`, `reject_hits`), the printed
     text's `approx_tokens`, and whether it is within the budget its WP08
     header declares.
   - `hook_guard_accuracy` runs `crumb hook guard` on the task as an Edit of
     `files[0]` or a Bash command. It checks that a warning is delivered
     exactly when `PROCEED` is not an allowed verdict.
   - Ids are read from the printed entries (`delivered_ids`). Warnings and
     "landed since" lines, which may name a record without presenting it, do
     not count.
3. **Critical cases** (`evals/critical/cases.yml`). Six checks: `guard_not`,
   `hook_guard_warns`, `never_delivered`, `delivered`, `quiet` and
   `delivery_bounded`. Each case is pass/fail against a suite's store.
   - An unmarked failure fails the run whatever the aggregates, and
     `--write-baseline` refuses to write while one fails.
   - `known: <finding>` makes a tracked failure `known`. It is printed on every
     run and annotated in GitHub Actions. It does not fail the ordinary run
     (CI stays usable during the repair program), but it fails `--release`.
   - A `known` case that passes is `stale` and fails the run, so the marker
     must be removed with the fix.
   - `waiver: <reason>` is reported and never gated.
   - 19 cases across the four suites. Three are `known: F10`:
     - `npm test` gets `PROCEED`;
     - the guard hook is silent on it;
     - the prompt hook never delivers its trap (length gate).

**Definitions and denominators.** `METRIC_DEFINITIONS` (definition +
denominator per metric) goes into every `--json` run and every
`baseline.json`, and each summary gains `n`.

**Reviewed baselines.**
- `--write-baseline` requires `--reason`.
- It prints task-level deltas against the old baseline's new per-task
  `tasks` snapshot: new misses and rejects per system, lost guard or hook
  answers, controls that started speaking, and removed tasks.
- It refuses any regression without `--accept-regressions`.
- The reason and the deltas are appended to `changes`.
- This commit's baseline was written that way. Its reason is recorded, and
  the old snapshot was absent, so every task was "added".

**Holdout.** `evals/suites/holdout-ops` (`split: holdout`) is an
infrastructure store: 11 records, 8 tasks, and 4 critical cases. It was
written once, and its tasks are not to be edited to suit the tool. It is
reported as its own `holdout` scope, and `overall` stays the development
suites, so the old `overall` numbers keep their meaning.

**Found by the delivery evals, fixed** (`breadcrumbs/hooks_common.py`, outside
the package's listed files):
- `write_state` keeps the 8 most recently updated sessions by `updated_at`,
  which has one-second resolution.
- On a tie the sort kept dict order, so a *new* session written in the same
  second as eight others was the one dropped, and its dedupe record was lost
  as it was written.
- Under the evals' fixed clock this showed as `dedupe` 0.67 to 0.89. In real
  use it takes nine sessions' hook state updated within one second.
- `write_state(..., current=)` now always keeps the session being written.
  The four callers pass it.

**CI.** The `evals` job's step and comment now describe the three layers. The
command is unchanged: `python evals/run.py --verbose` now includes the critical
gate.

**Not changed: the release workflow.** Wiring `python evals/run.py --release`
into `.github/workflows/release.yml` would make a publish fail while any
`known` case remains. `release.yml` is not in WP18's file list, and
`crumb guard` returned **ASK_HUMAN** for the edit. It is left for the
operator; see Limits.

**Docs.** `evals/README.md` (rewritten: the three layers, definitions, critical
markers, holdout, and reviewed baseline changes), the `run.py` docstring,
`ci.yml` and `CHANGELOG.md`.

## Tests

`tests/test_evals.py` has 23 tests; 9 are new and 2 were updated for the new
systems and the required `--reason`.

- **`test_baseline_cannot_approve_critical_false_safe`.** A hazard store; a
  task whose `verdict` list tolerates `PROCEED`, so the aggregate cannot see
  it; and `cli.guard` forced to `PROCEED`, so the test does not depend on what
  F10's fix will do. The test checks, in order:
  1. `--write-baseline` refuses.
  2. With a baseline written without the case, every aggregate equals it, yet
     the run exits 1 with `CRITICAL`, and not `REGRESSION`.
  3. Marked `known: F10`, the failure is printed and the run exits 0, while
     `--release` exits 1.
  4. With the verdict fixed, the stale marker fails the run.
- **`test_delivery_metric_includes_recency_noise_and_wrappers`.** Four newer,
  unrelated decisions. The ranking diagnostic scores 1.0. The delivered packet
  scores under 0.5, with the newest entries first, `recall_in_view` is 1.0,
  and the cost is the whole printed packet.
- **`test_hook_length_dedupe_and_render_paths_are_evaluated`.**
  - Retrieval finds the `npm test` trap, but the delivered prompt is silent
    (length gate) and scores recall 0.
  - A normal prompt is rendered with its header and footer, and deduplicated
    (1.0).
  - With dedupe disabled, the metric reads 0.0.
- **`test_metric_definitions_and_denominators_are_serialized`.** Every metric
  in every system has a definition, a denominator and an `n`. Counts are
  checked, "not divided by 5" is stated, and the written baseline carries the
  definitions, the reason and the task snapshot.
- **Also covered:**
  - a task-level regression needs `--accept-regressions`, and is recorded;
  - a holdout suite is reported apart from `overall`;
  - a waiver is never gated;
  - malformed critical cases are errors;
  - the session just written survives a timestamp tie, which fails without
    the fix at the ninth session.

Against the pre-change harness (`f75716d`), all 11 new or updated evals tests
fail. The harness had no delivery, critical, definition or review machinery
to call. The behavioral failure is the one the audit names: the old
`python evals/run.py` exits **0** on the committed suites while `npm test`
gets `PROCEED`. The new run reports it as a known critical failure, and
`--release` exits 1 ([evals-release.txt](evals-release.txt)).

## Results

| Command | Exit | Result |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` (3.11.15) | 0 | 1275 run, 0 failures, 6 skipped |
| evals, hook and transcript-recovery tests on 3.9.23 | 0 | 117 OK. `python3.9 evals/run.py` exits 0 |
| `test_mcp` with MCP SDK 2.2.0 | 0 | OK (2 skipped) |
| `python evals/run.py` | 0 | Ranking tables identical to WP09. Delivery table and 19 critical cases: 16 pass, 3 known (F10) ([evals.txt](evals.txt)) |
| `python evals/run.py --release` | 1 | The 3 known F10 failures block a release |
| `python evals/run.py --write-baseline` (no reason) | 2 | "needs --reason" |
| `regression_probes.py … --fail-on-observed` | 2 | Unchanged from WP09: 7 defect signals, 2 recorded probe errors. No probe covers F19 ([probe-results.json](probe-results.json)) |
| CI `test` job fixture steps, replayed | 0 | All 7 pass |
| `ruff check . && ruff format --check .` (0.16.1) | 0 | Clean |
| Eval runtime | — | About 6 s, was about 3 s (every task now also runs three hook or CLI deliveries) |

What delivery shows, overall across the development suites:

| | Ranking diagnostic | As delivered |
|---|---|---|
| Prompt precision@5 / recall@5 | 0.66 / 0.87 | 0.63 / 0.84 (the length gate) |
| Packet precision@5 | 0.59 (re-ranked) | 0.13 (reading order, recency floor first) |
| Packet recall | 0.97 (top 5) | 1.00 (anywhere in view) |
| Packet reject hits | 2 | 3 |
| Guard accuracy | 0.88 (library) | 0.88 (hook) |
| Prompt dedupe | — | 1.00 (was 0.67 to 0.89 before the tie fix) |
| Tokens (mean / max) | — | prompt 166 / 312; packet 1,354 / 1,576, all within budget |

## Compatibility

- **`--write-baseline` now needs `--reason`,** and refuses task-level
  regressions without `--accept-regressions`. It refuses outright while a
  critical case fails. Scripts that ran it bare exit 2.
- **The evals exit 1 on a critical failure** even when every metric matches
  the baseline.
- **`baseline.json` gains** `definitions`, `tasks` (a per-task snapshot) and
  `changes` (reasons and deltas). The old `scopes` values are unchanged; new
  systems and the `holdout` scope are added.
- **The JSON output gains** `definitions`, `critical_checks`, `critical` and
  `task_deltas`. Summaries gain the delivery systems and `n`.
- **`--critical PATH`** selects the cases file. By default it is used only with
  the default suites directory, so a custom `--suites` run carries no cases
  unless given some.
- **Hook session state:** `hooks_common.write_state` gains `current=`.
  Behavior only changes on a timestamp tie across more than 8 sessions.

## Limits

- **The release gate is built but not wired.** `python evals/run.py --release`
  fails while a `known` case remains, but nothing in `release.yml` runs it yet.
  The release workflow requires the `ci` workflow, whose evals job runs the
  ordinary mode, so a publish today is not blocked by the three F10 cases.
  - Wiring it is a one-step change to `release.yml`.
  - `crumb guard` returned ASK_HUMAN for it, and it is outside this package's
    files, so it waits for an operator decision.
  - Wired now, it would block every release until F10 (WP10) is fixed or the
    cases are waived.
- **Delivery runs in-process** through `cli.main` with a mocked clock, not as a
  separate process, so a startup-time or import failure is not measured.
- **Delivered ids come from the printed entries.** A record mentioned only in
  a warning line is not counted as delivered, either for recall or as a
  forbidden leak.
- **The holdout is small** (8 tasks). It was written by the same author as
  the rest, in the same session, before being run, which is weaker than an
  independently written holdout.
- **Token cost is `approx_tokens`** (WP08's estimator), not a model tokenizer,
  and is reported, never gated.
