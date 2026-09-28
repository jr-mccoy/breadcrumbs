# WP12: latest intent apart from retrieval, and honest telemetry (2026-09-27)

This implements work package WP12 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), findings F15
and F16. The starting commit is `f534a77`, after WP11.

## Cause

- **F15: the latest task depended on a match.**
  - `hook_prompt` called `record_prompt_state` only after the lookup found
    something. A later task that matched nothing left the earlier one in
    `last_prompt`.
  - After a compaction, `SessionStart` restored the earlier task and ordered
    the packet around it. The preamble listed that task's records as
    "surfaced for it".
- **F16: usage counted what was never delivered.**
  - The guard hook called `_record_guard_surfacings` before its READ_FIRST
    dedupe exit. A repeat the hook stayed silent on still counted
    (`guard_usage_dedupe` probe: 2 counts for 1 emission).
  - The guard hook's reason names at most three matches, but every shown match
    was counted.
  - The prompt hook counted every selected id, then `render` dropped lines to
    fit the 800-token budget.
- **F16: shared state had no concurrency semantics.**
  - `record_surfaced` read `usage.json`, added to it, and wrote it back. In the
    recorded run, six parallel writers lost 110–130 of 180 increments per trial
    ([behavior.txt](behavior.txt)).
  - Hook state files (`session-state.json`, `hook-guard-seen.json`, …) were
    read-modify-written the same way.
  - The hook log was cut back by rewriting it, which could drop lines a
    parallel hook appended meanwhile (0–7 lines per trial in the recorded run,
    up to 12 in an earlier one).

## Change

**The latest task is its own state** (`hooks_common`, `hooks_prompt`).
- `record_task` runs for every substantive prompt, **before** the lookup, so
  "matched nothing" and "lookup failed" still replace the task.
- Acknowledgements and slash commands never reach it. A slash command is now
  noted `retrieval: slash_command` in the hook log.
- `record_retrieval` keeps the latest lookup apart from the task: `for_task`
  (a digest of the prompt it ran for), `mode`, `selected` and `emitted`. The
  query text is not stored twice.
- `prompt_state` still returns `last_prompt` and `matched`. `last_prompt` is
  now the latest task. `matched` is what memory selected for *that* task, or
  `[]`. A pre-WP12 file still reads as written.
- **Privacy.**
  - The task text stays local: at most 300 characters.
  - It is withheld when it carries a credential (`transcript.redact_secrets`).
  - The new manifest key `retain_prompt_text: false` keeps only the digest and
    the time.
- **The compaction preamble.** It reads "Latest task before compaction (the
  user's words): …". It lists "Records memory matched for it" only for that
  task, and otherwise says "Memory matched nothing for it", or that the text
  was not retained. The rebuilt packet is ordered for the latest task.

**Usage counts emissions** (`cli`, `hooks_prompt`, `usage`). The stages are
distinct, and only the last is counted:
- **retrieved:** `candidates`, the records scored;
- **selected:** `matches`, current records under the cap;
- **emitted:** the ids in printed output, after trimming and dedupe.

Each hook notes the stages in its hook-log line (plus `trimmed` for the prompt
hook).
- **The guard hook** counts after the dedupe exit, just before each non-empty
  output, and only `shown[:_HOOK_GUARD_REASON_MATCHES]` (3), the matches its
  reason names.
- **The prompt hook** renders first (`render_emitted` returns the text and the
  ids that survived trimming). It dedupes on those ids and counts those ids.
- **The session hook** passes its session id. The packet ids were already read
  after trimming.
- **`crumb guard`** prints every match, and still counts every match.
- **"Outcome-confirmed" is not inferred from these counts.** Confirmation comes
  only from authored records (`crumb verify`, `crumb traps --confirm`). Decay
  and the promotion hint still only print commands; a test pins that.

**Contention-safe local state.**
- **`lock.side_lock(path, timeout)`.** The store's OS lock primitive on an
  auxiliary file. It yields `held`, `busy` or `unsupported` and never raises.
  Telemetry never takes the store lock.
- **Usage events.** `record_surfaced` writes one event file per emission
  (`private/usage-events/*.json`, atomic rename) and returns the number of ids
  it acknowledged.
  - `fold` adds pending events to `usage.json` under `.usage.lock`.
  - `folded_last`, written in the same atomic replace, names the events it
    counted, so a fold that dies before deleting them cannot count them twice.
  - Readers add pending events, so a fold that has not run loses nothing.
  - In the uncontended case the fold runs at once, and `usage.json` looks as
    it did.
- **Hook state.** `update_state` does the read-modify-write under the file's
  side lock. `advisory_seen`, `record_task`, `record_retrieval`,
  `record_compaction` and `record_extraction_asked` use it. A busy lock skips
  the update and notes `state_dropped`. An unsupported filesystem writes
  uncoordinated, as before.
- **The hook log** rotates: at half of `HOOK_LOG_MAX_LINES` the current file
  is renamed to `hook-log.1.jsonl`. This happens under `.hook-log.lock`, and
  the size is re-checked once the lock is held. `read_log` reads both files.
  Lines leave only by retention.
- **Drops are visible.**
  - `usage_dropped`: the event could not be written, or 2,000 were pending
    unfolded.
  - `state_dropped`: a state update was skipped.
  - `crumb usage` prints the accounting model and a *Completeness* line
    (pending, unreadable, evicted). `--json` returns it as `accounting`.

**Docs.**
- `cli-spec.md`: the prompt and session hook rows, the usage accounting model,
  and hook-log fields and rotation.
- `record-schema.md`: the `private/` tree, `usage.json` accounting,
  `session-state.json`, and `retain_prompt_text`.
- `architecture.md`, `README.md` and `CHANGELOG.md`.

**Tests changed.**
- `test_hooks_phase1`'s compaction test now looks for the new label, "Latest
  task before compaction".
- `test_hooklog`'s bound test reads the whole log through `read_log`. The
  current file can be absent right after a rotation. The test also asserts the
  bound and that only the oldest lines leave.

## Tests

`tests/test_emission_accounting.py` has 9 tests, including the four the
roadmap names.

- **`test_unmatched_new_task_replaces_old_matched_task`.**
  - Matched task A, then unmatched task B: `last_prompt` is B, `matched` is
    `[]`, and the retrieval state belongs to B.
  - After "ok" and `/compact`, still B. The compaction preamble names B, says
    memory matched nothing, and mentions neither A nor its record.
  - Then `ruff` (short and meaningful) and "thanks": the preamble names `ruff`,
    and the rebuilt packet's task is `ruff`.
- **`test_deduped_guard_does_not_increment_surfaced`** (the probe's shape).
  - First call speaks, second is `{}`: `surfaced` is 1, and the hook log shows
    `emitted` 1 then 0 with `deduped`. Another session is a second emission.
  - A repeated prompt is counted once.
  - A silent `ls`, an unmatched prompt and "ok" count nothing.
- **`test_trimmed_ids_are_not_counted_as_emitted`.** Five decisions on one
  file.
  - The prompt hook, at a budget that fits two lines, counts exactly the two
    it printed. State keeps 5 selected and 2 emitted. The log says
    `matches` 5, `emitted` 2, `trimmed` 3.
  - An over-budget output is `{}` and counts nothing.
  - The guard hook counts exactly the three records its reason names.
  - `crumb resume --budget 900` counts exactly the ids it printed.
- **`test_parallel_telemetry_does_not_silently_lose_acknowledged_events`.**
  Six processes, released together, each make 30 emissions, 30 hook-log
  appends and 30 task updates. Then:
  - every acknowledged id is counted exactly (180 for the shared id), and
    still exactly after a final fold, with none pending, 180 folded and none
    unreadable;
  - all 180 log lines are present across a rotation;
  - every session's latest task is its own last one.
- **Also covered:**
  - a fold that dies after writing but before deleting does not count twice;
  - a refused emission returns 0 and notes `usage_dropped`, and `crumb usage`
    reports pending events and the model;
  - the task text follows the privacy policy (a credential is withheld; with
    `retain_prompt_text: false` only a digest is kept, and the preamble says
    so);
  - a pre-WP12 state file still reads;
  - 50 sessions of counts change no record and write no instruction file.

The test file cannot import on the pre-change code (`render_emitted`, `fold`
and `task_ref` are new). The behavioral comparison is [behavior.txt](behavior.txt),
from [behavior.py](behavior.py), which uses only APIs both versions have:

| Check | Before (`f534a77`) | After |
|---|---|---|
| Latest task after A (matched), B (unmatched), "ok" | A | B |
| Guard: spoke, then deduped → `surfaced` | 2 | 1 |
| Prompt: 5 selected, 2 rendered → counted | 5 | 2 |
| 6 parallel writers × 30: usage increments lost (5 trials) | 118, 118, 121, 110, 130 | 0 each |
| Hook-log lines lost inside the retained window | 0, 1, 7, 0, 0 | 0 each |
| Session entries lost | 0 each | 0 each |

The session-state loss was not reproduced before the change. An entry is lost
only when a session's last write is clobbered, and none was in these trials.
The side lock is defensive there. The parallel test pins the property.

## Results

| Command | Exit | Result |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` (3.11.15) | 0 | 1299 run, 0 failures, 6 skipped |
| emission, usage, hooklog, hooks, guard-delivery, lock, evals, promote and retrieval tests on 3.9.23 | 0 | 210 OK |
| `test_mcp` with MCP SDK 2.2.0 | 0 | OK (2 skipped) |
| `python evals/run.py --verbose` | 0 | 20 critical cases pass; ranking and delivery metrics unchanged, no baseline rewrite ([evals.txt](evals.txt)) |
| `python evals/run.py --release` | 0 | Passes |
| `regression_probes.py … --fail-on-observed` | 2 | 4 defect signals, 2 recorded probe errors, as at WP11 ([probe-results.json](probe-results.json)). See below for `guard_usage_dedupe` |
| CI `test` job fixture steps, replayed | 0 | All 7 pass |
| `ruff check . && ruff format --check .` (0.16.1) | 0 | Clean |
| Hook latency, median of 60 firings, 40 decisions | — | Unmatched prompt 9.4–9.9 → 10.7–11.1 ms; emitting prompt 9.1–9.5 → 10.3–11.0 ms; emitting guard 25.0–26.4 → 26.8 ms ([behavior.txt](behavior.txt)) |

**`guard_usage_dedupe` still reports `bug_observed`, as a probe false
positive.**
- Its condition is `first spoke and not second spoke and counts is not None`,
  and a correct count after one emission is not `None`.
- Its recorded output shows the fix: `usage.surfaced` is **1**, where WP11's
  run recorded **2** (`by: {"hook-guard": 1}`).
- The audit scripts stay byte-identical, so the probe is not edited. This joins
  `resume_ignores_lock` (WP05) as a recorded false positive.
- The other signals, `symlink_read` and `powershell_translation`, belong to
  later packages.

**`short_prompt_and_stale_task` now shows F15 fixed.**
- The probe's `bug_observed` covers only its short-prompt half, which WP10
  cleared.
- Its stale-task half is reported in `remembered_prompt_after_unrelated_task`.
  At WP11 that was "amber quasar routing policy", the older matched task. It is
  now "Design a completely unrelated calendar view", the latest one, equal to
  the probe's `actual_latest_prompt`.

## Compatibility

- **Compaction restores the latest task, not the last matched one.** The
  preamble's labels changed: "Latest task before compaction (the user's
  words)", "Records memory matched for it", "Memory matched nothing for it".
- **`session-state.json` has a new shape** (`task`, `retrieval`). Pre-WP12
  entries are still read, and the next prompt rewrites them.
  `record_prompt_state` is kept as a wrapper.
- **Usage counts are lower where they were inflated:** guard repeats, reasons
  past three matches, and trimmed prompt lines.
  - Existing `usage.json` files are read and extended as they are.
  - `usage.json` gains `folded_last` and `accounting`.
  - `private/usage-events/` appears.
  - An older crumb-kit reading the file ignores the new keys, and does not see
    pending events.
- **`record_surfaced` returns an int** (ids acknowledged), where it returned
  `None`.
- **Hook log.** It rotates into `hook-log.1.jsonl`, and the current file can
  be absent just after a rotation. New log fields: `candidates`, `matches`
  and `emitted` on guard lines; `trimmed` and `retrieval: slash_command` on
  prompt lines; `usage_dropped` and `state_dropped`.
- **New manifest key** `retain_prompt_text` (default `true`, the current
  behavior).
- **New lock files** under `private/`: `.usage.lock`, `.hook-log.lock`, and
  `.<state file>.lock`.
- **The prompt hook costs about 1.5 ms more per prompt.** It writes the task
  and the lookup state on every substantive prompt, where it used to write
  only on a match.

## Limits

- **Slash commands are not a task.** `/fix the login bug` is neither looked up
  nor recorded, as before. The harness's expansion of a command is not visible
  to this hook.
- **Session forks.** A forked session has a new session id and starts with no
  task. The parent's task is not carried over.
- **"Emitted" means printed to the host,** not seen by the model. Claude Code
  shows an `ask` reason to the user, not the model; it counts as emitted to a
  person.
- **The compaction preamble names record ids without content.** It is not
  counted as a surfacing.
- **What is approximate is stated, not removed.**
  - A state update that waits more than 0.25 s is skipped (`state_dropped`).
  - The 2,000-record and 20-session caps evict.
  - An emission that cannot be written is only noted in the hook log, which
    may be unwritable too.
- **Exactly-once holds within one machine's filesystem.** On a filesystem
  without OS locks, folds and state updates run uncoordinated, as before
  (`unsupported`).
- **A reader concurrent with a fold** can be briefly off for events in flight.
  The folded totals never lose or double an event.
