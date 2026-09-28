# WP02: truthful transcript outcomes (2026-09-27)

This implements work package WP02 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), finding F01. The
starting commit is `f9f72f7`, after WP01.

## Cause

`pair_tool_calls` gave every call `is_error=False` until a result said
otherwise, so a call with no result counted as a success: an unanswered
`pytest` became "pytest passed". Failure detection ran on the first 400
characters of the output, so a failure printed later read as a pass. The
failure regex matched `0 failed`, so a clean summary read as a failure. The
attempt candidate also claimed a cause: "failed **until** N file(s) changed …
**Fixed after** editing".

## What Claude Code actually writes

Checked against this session's real transcript (168 tool calls):

- A non-zero exit sets `is_error: true`, and the result text starts
  `Exit code N`. There is no numeric exit-code field.
- A call the harness refuses is `is_error: true` with `<tool_use_error>…`. The
  command never ran; the old miner would have mined it as a failure.
- Bash entries carry `toolUseResult.interrupted`.

## Change (`breadcrumbs/transcript.py`)

- **`ToolCall` fields.** Each call now has `result_received` and an `outcome`:
  `success`, `failure`, `interrupted`, `not_run` or `unknown`. `is_error` is
  now a read-only property meaning `outcome == failure`.
- **`classify_result()` order.** The checks run in this order:
  1. A refusal (`<tool_use_error>`, a rejected tool use) → `not_run`.
  2. An interrupt (the structured flag, or the harness text) → `interrupted`.
  3. The harness error flag → `failure`.
  4. Failure words in the *full* Bash output. For a test, lint or build
     command, a pipeline like `pytest | tail` hides the exit code, so these mean
     `failure`. For any other command they mean `unknown`: a `grep` that found
     "error:" has not failed, and `python x.py | tail` printing a traceback has
     not passed.
  5. Otherwise → `success`.
- **Anchored markers.** The refusal and interrupt markers only match at the
  start of the result, so a `cat` of a file that quotes one is not taken as the
  harness speaking.
- **Zero counts.** Phrases like `0 failed`, `failures: 0` and `no errors` are
  removed before the failure test.
- **Excerpts last.** The 400-character excerpt is cut after classification,
  around the failure when it comes late.
- **Rules.** An attempt needs an observed `failure` and a later observed
  `success` of the same command. Verifications need `success`. Edits count (for
  attempts and churn) only when they succeeded.
- **Wording.** The attempt title is now "… failed, then passed after N file(s)
  changed", and the note says the edits are "not shown to be the fix". The
  verification note is now "Exited without a reported error and printed no
  failure in this session".
- **Unchanged safeguards.** Candidates are still `confidence: low`,
  machine-local jots, and a candidate carrying a secret is still dropped.
- **Docs.** `cli-spec.md` → *What the miner writes* documents the outcome
  vocabulary.

## Tests

`tests/test_transcript_outcomes.py` has 22 tests, including the four the roadmap
names:

- `test_missing_result_never_produces_passed_candidate`
- `test_failure_after_excerpt_limit_is_failure`
- `test_zero_failed_summary_is_not_failure`
- `test_edit_then_success_does_not_assert_unproven_causality`

Against the old `transcript.py`, the first 18 tests written all failed or
errored. The errors are partly the missing `outcome` attribute; the three F01
behaviors were already shown on the old code by the WP00 probes.
`test_transcript.py`'s one wording assertion was updated from "failed until" to
"failed, then passed after".

## Results

| Command | Exit | Result |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` (3.11.15) | 0 | 1187 run, 0 failures, 6 skipped |
| transcript + hook tests on Python 3.9.23 | 0 | OK |
| `python evals/run.py` | 0 | Unchanged (the miner is not in the evals) |
| `regression_probes.py … --fail-on-observed` | 1 | 16 defect signals, 0 errors. `transcript_results` and `split_pair` are no longer observed ([probe-results.json](probe-results.json)). |
| CI `test` job fixture steps, replayed | 0 | All 7 pass |
| `ruff check . && ruff format --check .` (0.16.1) | 0 | Clean |

**Real transcript.** This session's transcript has 168 tool calls. The old and
new miners produce the same candidates except one: the old miner's
"`python -m unittest test_note…` passed". That run printed
`FAILED (failures=1)` after the first 400 characters, so the candidate was
false. The outcomes break down as 118 success, 10 failure, 39 unknown, 1 not_run
and 1 unknown-without-result. Almost all of the unknowns are `sed`, `grep` and
`cat` reads of source and docs. The old miner counted 22 failures, most of them
file contents that merely contained failure words.

## `split_pair` is only partly fixed

The probe no longer observes its defect because the first firing no longer
invents a "passed" for a call with no result. But the result that arrives in
the second firing is still never joined to its call: the second firing sees an
orphan result and mines nothing from it. That cross-firing join is WP09 (with
F02's cursor), as the roadmap assigns it. Nothing false is written now; a real
outcome can still be missed.

## Compatibility

- No schema, store or CLI change.
- `ToolCall(is_error=…)` is no longer a constructor argument. Nothing outside
  the miner constructs `ToolCall`.
- Attempt titles change, and a title is half of a candidate's fingerprint. So
  within a session already mined by the old code, the same attempt can be
  written once more under its new title. It is a private, expiring jot.
- Fewer candidates overall. Failures in non-verdict commands, refused calls
  and interrupted calls no longer start attempts. A test run whose output
  shows a late failure is no longer a verification.

## Limits

- The verdict-command list (`_TEST_CMD_RE`, `_BUILD_CMD_RE`) is a fixed
  allowlist. A test run launched another way (`bash run_tests.sh | tail`) that
  prints a failure reads as `unknown`, not `failure`.
- A success needs no positive pass summary. An unflagged verdict command that
  prints nothing is `success`; that is correct for `tsc`, and it is what the
  exit status says.
- The failure vocabulary is still English-only regex.
- Only the Claude Code transcript shape is handled. PowerShell and other
  adapters belong to WP17.
