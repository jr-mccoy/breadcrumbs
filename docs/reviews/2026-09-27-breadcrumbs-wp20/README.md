# WP20: onboarding and operation, documented and checked (2026-09-27)

This implements work package WP20 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), findings F24
and F26. The starting commit is `e835448`. The operator authorized the
remaining work on 2026-09-27.

## Cause

- **A new user met a 1,159-line README** that mixes onboarding with a full
  command reference.
- **No page said, in one place, what the store promises and what it does
  not:**
  - capture, durable memory and standing rules;
  - profiles, privacy and budgets;
  - that a guard verdict is not an authorization.
- **`crumb doctor` missed four states an operator must recover from:**
  - a store this build may not write (WP21);
  - records failing validation;
  - an incomplete "see also" map (WP15);
  - a guard hook matcher older than the adapter's (WP17).
- **The default `handoff.md` said "Phase 2 is next".** It was last updated
  2026-09-22, before the 0.3.1 release. An agent reading it first would redo
  finished work, which is F24's own example.
- **There was no path for an outside contributor** that did not start with
  the implementation.

## Change

- **[`docs/quickstart.md`](../../quickstart.md) (new): the golden path.**
  - Steps: install, init (with an `AGENTS.md` signpost), record one decision,
    resume, see why it surfaces (`search --explain`, `guard` and its exit
    code, `show`), supersede and retire it, break a record on purpose and
    recover (`validate`, `doctor`).
  - Ids are written `dec_YYYYMMDD_<slug>` and explained.
- **`tools/quickstart_check.py` (new).**
  - It executes every `$` line of the quickstart in order, in a fresh
    repository, and checks each exit code (`# exit N`).
  - It makes the page's manual edits (`<!-- quickstart-check: set-field … -->`)
    and resolves id placeholders from what the CLI printed.
  - The CI `package` job runs it against the installed wheel.
- **[`docs/operator-guide.md`](../../operator-guide.md) (new)** covers:
  - the three kinds of memory;
  - profiles, privacy and budgets;
  - what guard does and does not do, and how to retire or correct a record;
  - platforms;
  - a recovery table, one row per `doctor` finding;
  - reconciling the handoff after a merge or release.
- **[`docs/continuity-contract.md`](../../continuity-contract.md) (new).**
  Seven promises, each with where it is tested; what is not promised; and
  what to do when a memory is wrong.
- **`crumb doctor` gains four rows:** `compatibility`, `records`,
  `related_map` (only when degraded) and `hook_matcher` (only when hooks are
  installed). Each names its fix, and none changes the exit code.
- **The default `.project-memory/handoff.md` is reconciled** to the actual
  state. It points at the tracker as authoritative, says which approvals are
  pending, and says when it goes stale.
- **`CONTRIBUTING.md`:** a first-contribution path (a failing scenario as
  data, a regression test, an evidence-backed fix, and how to regenerate a
  published result deliberately).
- **`README.md`:** a "New here?" pointer to the four pages. The reference is
  kept, not deleted.
- **`security.md`:** "What a guard verdict is not". **`cli-spec.md`:** the new
  `doctor` rows.

## Tests

`tests/test_operator_path.py` has 6 tests.

- **`test_quickstart_works_as_written`.** It runs the quickstart check against
  the source checkout. It also passed against an installed wheel locally, and
  CI runs it there.
- **The `doctor` recovery tests:**
  - a record edited to `confidence: certainly` is named with `crumb
    validate`;
  - `requires: some-future-feature` is named, with "writes are refused";
  - an old guard matcher is named with `crumb init --with-hooks`, and running
    that fix clears it;
  - a related map degraded by a patched budget is named.
- **`test_default_handoff_is_reconciled_after_the_latest_release`.** The
  handoff's `_Last updated_` must not predate the newest release in
  `CHANGELOG.md`. It failed before the handoff was reconciled.

**The roadmap's acceptance checks:**
- *Clean-checkout quickstart works with the installed package.* Yes (the CI
  `package` step).
- *A reader can identify why a memory surfaced and how to retire or correct
  it.* Quickstart §4–5, operator guide §3, continuity contract "If a memory is
  wrong".
- *Default-branch handoff does not direct the next agent to redo completed
  phases.* Reconciled, and held by the test above.

**Behavior comparison.** [behavior.txt](behavior.txt), from
[behavior.py](behavior.py):

| Check | Before (`e835448`) | After |
|---|---|---|
| `doctor` silent on a record failing validation | yes | no |
| `doctor` silent on a store it may not write | yes | no |
| `doctor` silent on an outdated guard matcher | yes | no |
| No executed quickstart | yes | no |
| No operator guide or continuity contract | yes | no |
| The default handoff predates the latest release | yes | no |
| No contributor path | yes | no |
| **Defects observed** | **7** | **0** |

## Results

Run on commit `68c8075` (local battery, Python 3.11 unless noted) and CI run
247 on the same commit.

| Check | Result |
|---|---|
| `python -m unittest discover -s tests` | 1,364 run, 0 failures, 8 skipped |
| The same, with a symlinked `TMPDIR` (macOS path spellings) | 1,364 run, 0 failures |
| Python 3.9: `test_operator_path`, `test_task_replays`, `test_adapter_contracts`, `test_lifecycle` | 6, 2, 6 (1 skipped) and 50: all OK |
| MCP SDK 2.2.0, full suite / SDK 1.30.0, contract tests | 1,364 OK / 6 OK |
| `python evals/run.py` / `--release` | pass / 20 of 20 critical cases pass |
| `tools/quickstart_check.py` (source checkout) | works as written |
| CI `package` job: the quickstart against the installed wheel | passed (run 247) |
| CI fixture steps, replayed locally | 7 of 7 |
| `regression_probes.py … --fail-on-observed` | exit 2: the 2 recorded false positives, 3 recorded probe errors, as at WP17 |
| `ruff check` / `ruff format --check` | clean (CI `lint`, run 247) |

## Limits

- **The README is still long.** It now points new readers elsewhere first.
  Deriving the command reference from the parser, and moving it out, is
  follow-up work (F24 asks for it "where practical").
- **The handoff check is a date check.** It catches a handoff older than the
  latest release, not a wrong sentence in a fresh one. The reconciliation
  workflow (operator guide §6) is what keeps the content true.
- **`doctor`'s `records` row runs a full `validate`,** linear in the store:
  about 0.15 s per 1,000 records (WP15).
- **The quickstart shows Claude Code's hooks only by name.** Wiring a
  harness is in the compatibility matrix.
