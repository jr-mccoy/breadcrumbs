# WP11: close the known-command guard miss without warning spam (2026-09-27)

This implements work package WP11 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), findings F10
and F11. The starting commit is `d270e14`, after WP10.

WP10 already made a trap that names the exact command floor `READ_FIRST`,
listed named commands in the guard pre-filter, and documented `PROCEED` as "no
applicable memory warning". WP11 finishes the guard side.

## Cause

- **The hook's pre-filter could drop what full guard would surface (F11).**
  - `crumb hook guard` runs full guard only when an action looks risky: a
    non-routine action class, the destructive-shape regex, or a hit in the
    pre-filter.
  - The pre-filter was built from traps and do-not-retry attempts only. An
    edit to a file that only a *decision* (or a verification, or an open
    question) declares, or a routine command matching one on tags or words,
    drew `READ_FIRST` from `crumb guard` and silence from the hook.
  - Over actions generated from every eval store, the WP10 code's hook was
    silent on **27 of 193** warnings full guard gives ([behavior.txt](behavior.txt)).
- **Head kinds were positional (a WP10 bug).** `_names_command` treated the
  first named-command head as the trap's summary and every later one as a
  backticked span that must be named whole. The pre-filter stores heads
  sorted, so a summary head could land in a later position and be judged as a
  span. `npm test` against "npm test truncates …" then missed whenever another
  head sorted first. The WP10 test passed because `npm` happened to sort
  first.
- **No opt-in transport convenience existed** for a caller that cannot take the
  verdict-mapped exit codes (trap_guard-exit-code-in-ci).

## Change

**`_build_guard_prefilter` is a strict superset of full guard** (format 3).
It walks every record that could drive a verdict (`_may_drive_verdict`: live
decisions, attempts and traps, open questions, actionable verifications,
expired or other-branch included, erring wide). From each it collects what
`_score_item` can match on. `_prefilter_trap_hit` passes an action when:

| `_score_item` gate | Pre-filter test | Why it is a superset |
|---|---|---|
| ≥2 specific stems shared with one record (ubiquitous stems discounted) | ≥2 stems shared with `tokens`, the union | per-record overlap ≤ union overlap; discounting only shrinks guard's side |
| short-query title hit (the live stems ⊆ a title) | a single-stem action in `titles` | a longer action whose other stems guard discounted as ubiquitous shares 2 stems with `tokens` (ubiquitous stems are in some record) |
| a shared tag stem | a shared stem in `tags` | the same union |
| a shared declared or **mentioned** file | a shared path in `paths` (plus paths in trap and attempt text) | mentions open the gate too |
| a named command (WP10) | `commands` | the same heads |

It may admit more than full guard surfaces, which costs a full guard run. It
cannot drop a warning. A pre-filter of any other format is treated as
unverified.

**Named-command heads carry their kind.** A head is `["title", …]` or
`["span", …]`, in the item and in the pre-filter. A summary that opens with
"run"/"running"/"runs"/"calling"/"executing" also names the command after the
verb ("Running make deploy pushes to prod" names `make deploy`).

**`crumb guard --exit-zero`** (opt-in): status 0 whatever the verdict. The
verdict is still printed and in `--json`, and the default mapping (0/10/15/20)
is unchanged.

**A new critical eval case**, `edit-of-a-decision-file-warns` (holdout-ops,
`infra/backend.tf`): an edit to a file only a decision declares must draw a
warning from the real hook. It fails on the WP10 code ("the hook was
silent") and passes now. The release gate covers it.

**Docs.**
- `cli-spec.md`: the pre-filter superset, head kinds and run-verbs, and
  `--exit-zero`.
- `record-schema.md`: pre-filter format 3.
- `README.md` and `CHANGELOG.md`.

## Tests

`tests/test_guard_delivery.py` has 6 tests, including the four the roadmap
names.

- **`test_known_destructive_npm_test_never_proceeds_silently`.**
  - `npm test`, `npm test --watch`, `cd web && npm test` and
    `npm test 2>&1 | tail -5` are never `PROCEED`.
  - Through the real hook, in all 7 permission modes (absent, default,
    acceptEdits, plan, bypassPermissions, dontAsk, unknown), each delivers a
    warning naming the trap.
  - With the generation manifest removed (pre-filter unverified), it still
    warns.
- **`test_full_guard_and_hook_agree_on_required_warning`.** For every eval
  suite, actions are generated from every task, and from every live record's
  title, first two title words, files and command heads. Wherever full guard
  says anything but `PROCEED`, the pre-filter admits the action (or it is
  risky enough to bypass the pre-filter) and the real hook speaks. The test
  asserts more than 200 actions and more than 20 warnings; the recorded run
  covered 227 actions and 193 warnings.
- **`test_safe_remedy_and_unrelated_controls_remain_nonblocking`.**
  - `npm run test:unit` (the remedy), `npm install`, `git status`, `ls -la`,
    `make` and `pytest -q` are `PROCEED` and the hook is silent.
  - `git log --all`, named by a trap, is capped `READ_FIRST` (read-only) and
    delivered as context with no permission decision.
  - A do-not-retry attempt's file edit keeps `PAUSE` (stance preserved).
- **`test_permission_mode_never_gains_auto_allow`.** All four verdicts ×
  7 modes × `CRUMB_GUARD_ADVISORY` on/off:
  - never `allow` or `deny`;
  - `ask` exactly for `PAUSE`/`ASK_HUMAN` in prompting modes without the
    advisory override;
  - a warning delivered exactly when the verdict is not `PROCEED`.
- **Also covered:**
  - the F11 shape directly (an edit to a decision-only file: guard
    `READ_FIRST`, pre-filter hit, hook speaks);
  - the exit-code mapping 0/10/15/20, and `--exit-zero` returning 0 with the
    verdict still in `--json`.

Against the WP10 code (`d270e14`), 3 of the 6 fail:
- the decision-file test **behaviorally** (the pre-filter missed it);
- the agreement test on the missing `_may_drive_verdict` (its behavioral
  version is [behavior.txt](behavior.txt): 27 silent);
- `--exit-zero` (the flag is new).

The `npm test`, boundary and permission-mode tests pass there: WP10 fixed
those behaviors, and WP11 pins them through the real hook.

## Results

| Command | Exit | Result |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` (3.11.15) | 0 | 1290 run, 0 failures, 6 skipped |
| guard, hook, note, retrieval and evals tests on 3.9.23 | 0 | 242 OK |
| `test_mcp` with MCP SDK 2.2.0 | 0 | OK (2 skipped) |
| `python evals/run.py --verbose` | 0 | 20 critical cases pass (the new one included); ranking and delivery metrics unchanged, so no baseline rewrite ([evals.txt](evals.txt)) |
| `python evals/run.py --release` | 0 | Passes |
| `regression_probes.py … --fail-on-observed` | 2 | Unchanged from WP10: 4 defect signals (`symlink_read`, `powershell_translation`, `guard_usage_dedupe`, and the recorded `resume_ignores_lock` false positive), 2 recorded probe errors ([probe-results.json](probe-results.json)) |
| CI `test` job fixture steps, replayed | 0 | All 7 pass |
| `ruff check . && ruff format --check .` (0.16.1) | 0 | Clean |
| Hook vs full guard over generated actions | — | Silent on required warnings: 27/193 before, 0/193 after |
| Routine commands (15 per store × 4 stores) | — | Pre-filter admits 0 → 4 of 60; the hook speaks on 2 → 3; median hook 1.7 → 2.1 ms |

The one routine command that now draws a warning is `python -m pytest -q` in
the library store. The decision "Python 3.9 is the supported floor" is tagged
`python`, and full guard already gave `READ_FIRST` for it on the WP10 code; the
old pre-filter only hid it from the hook. The hook now says what guard says.
How broadly a tag should match is a guard-policy question, outside this
package.

## Compatibility

- **The guard hook now warns wherever `crumb guard` does.** Sessions will see
  warnings the pre-filter used to drop: edits to files decisions declare,
  commands matching a tagged decision. Each is still deduplicated per session.
- **More actions reach full guard.** On the eval stores, 4 of 60 routine
  commands, at about +0.3 ms median.
- **Pre-filter format 3** (`tokens`, `titles`, `tags`, `paths`, `commands`
  with kinds). A format-2 pre-filter is treated as unverified until the next
  publication.
- **New flag:** `crumb guard --exit-zero`. Exit codes are otherwise unchanged.

## Limits

- **The superset is guaranteed against the gate, not the score.** The
  pre-filter mirrors every condition that lets a match through `_score_item`.
  It does not predict verdicts, so it admits some actions full guard then
  passes over.
- **A tag match is guard's `READ_FIRST` policy.** A broadly used tag (such as
  `python` on a Python project) warns on many commands. The hook no longer
  hides that, and narrowing tag matching belongs to a guard-policy change.
- **The agreement test covers generated actions over four synthetic stores,**
  not arbitrary real-world actions. The proof is by construction (the table
  above), and the test checks it.
- **The named-command rule keeps WP10's limits:** at least two tokens, and a
  non-flag argument breaks the match.
