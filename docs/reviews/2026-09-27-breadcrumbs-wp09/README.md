# WP09: durable incremental transcript ingestion (2026-09-27)

This implements work package WP09 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), finding F02.
The starting commit is `22a1bff`, after WP08.

## Cause

`mine_transcript_into_jots` read the last 8 MB of the transcript on every
firing and kept, in `private/miner-cursor.json`, how many *entries* of that
tail it had mined. It stored the count as if it were a position in the file,
and never moved it back.

- **Past 8 MB the tail slides**, so the count stops meaning anything. A new
  correction appended to a 9 MB transcript landed at entry 15 of a 15-entry
  tail, and the stored cursor was already 15. It was never mined, and the
  firing reported no work skipped (`sliding_cursor` probe).
- **A later rewrite or truncation** left the cursor past the end of the new
  entries, so nothing in the new file was mined either.
- **A call and its result in different firings were never joined.** Each
  firing paired calls only within its own slice, so the attempt rule could not
  see a failure, edits and a pass that spanned firings.
- **The cursor moved past the whole slice** whatever happened to its
  candidates. The 10-per-firing cap, a refused write or lock contention lost
  them silently.
- **The shared `miner-cursor.json` was rewritten by any session**, without a
  lock (WP05 left this for WP09).

## Change

**`breadcrumbs/transcript.py`: `ingest()`**, which `mine_transcript_into_jots`
now calls. It runs under the store lock with the hook's 0.5-second wait. On
contention it returns `locked` and consumes nothing.

1. **Reading (`_read_new`).** A byte offset, always at a line boundary. At most
   `MAX_BYTES_PER_FIRING` (8 MB) past it per firing; the rest is reported as
   `unread_bytes`.
   - A trailing partial line is left for the next firing.
   - A line longer than a whole read is skipped once it has ended, and counted
     (`oversize_lines`). One still being written is waited for.
   - **File identity:** a digest of the first 4 KB (or less) and of the 256
     bytes before the offset. A file that is shorter (`truncated`), or whose
     head or anchor changed (`replaced`), is read from byte 0.
   - Lines are split on the byte `\n`, not `str.splitlines`, which would break
     a record on a U+2028 inside a JSON string. `read_transcript` shares the
     parser.
2. **Mining (`mine_window`).** Calls carried from earlier firings come first,
   and a result in the new bytes resolves a carried call (`pair_tool_calls(…,
   carried)`).
   - Candidates already acknowledged are removed *before* the per-rule caps, so
     re-detections never crowd out new ones.
   - What the caps hold back is counted (`policy_capped`).
   - Candidates gain a stable `key` (attempt: command and failing call id;
     verification: command; churn: file; correction: the entry's `uuid`) and
     `events` (the tool_use ids or entry id behind them).
3. **Queuing.**
   - A candidate carrying a credential is refused here and counted.
   - The others go to a backlog of at most 50 (overflow is counted).
   - The offset, identity, carried calls and backlog are saved (`private/miner/
     <session>.json`) **before any jot is written**. If that save fails, the
     firing stops and the next one re-reads the same bytes.
4. **Writing (`_flush_backlog`).** Oldest first, at most 10 jots per firing.
   - A candidate leaves the backlog when written, when found already written
     (its fingerprint is on a jot from a firing that died before saving), or
     when validate refuses it.
   - A write that raises (disk, permissions) keeps the candidate and stops the
     flush. After five attempts the candidate is dropped and counted.
   - Every acknowledged candidate's events go to `private/miner/acked.json`
     (5,000 newest), checked in every session.

**Carried calls (`_carry_forward`).** Only Bash and edit calls are carried:
every one still waiting for a result, plus the newest resolved ones, 200 in
all. Pending calls beyond 200 are evicted and counted. A carried command is
normalized, and a command or failure excerpt that matches a credential pattern
is blanked. Nothing else of the transcript is kept.

**`breadcrumbs/hooks_common.py`.**
- The per-session state files `private/miner/<sha1(session)[:16]>.json`, of
  which the newest 32 are kept. `save_miner_state` raises, so the caller knows
  whether progress is durable.
- The `acked.json` ledger.
- `miner_states()` for `doctor`.
- `miner_cursor()` now returns the byte offset.
- `set_miner_cursor` and the `miner-cursor.json` reads are gone; the file is
  left on disk.

**Visibility.**
- `transcript.note_report()` puts `mined`, `miner_backlog`,
  `miner_unread_bytes`, `miner_capped`, `miner_dropped`, `miner_reset` and
  `miner_locked` on the hook-log line. It is used by `capture`, `compact` and
  `subagent`.
- `crumb doctor` gains a `miner` row: sessions, candidates waiting, unread
  bytes, held back by caps, and dropped. It fails only on drops.

**Subagents** (`use_cursor=False`): the finished transcript is mined once,
from its last 32 MB, with the rest reported as `skipped_bytes`. Its candidates
go through the parent session's backlog, so the cap defers them too.

**Docs.**
- `cli-spec.md`: a *Mining is incremental and durable* section, replacing the
  cursor sentence and the "not joined yet" note.
- `record-schema.md`: the `private/miner/` entries.
- `architecture.md`: the `transcript.py` row.
- `hooks_common.py`'s table, `README.md` and `CHANGELOG.md`.

## Tests

`tests/test_transcript_recovery.py` has 13 tests, including the four the
roadmap names. `tests/test_hooks_phase1.py` gains one.

- **`test_sliding_tail_does_not_freeze_cursor`.** A 9 MB transcript of
  500 KB lines, then four corrections appended one per firing, each past the
  window. Each correction becomes exactly one jot, nothing is written on a
  further firing, the first firing reported unread bytes, and the cursor ends
  at the file size.
- **`test_call_and_late_result_join_across_firings`.** Across five firings:
  `pytest` is called, its failure arrives, an edit, `pytest` again, and its
  pass arrives.
  - No "passed" appears until the pass arrives.
  - Then both the attempt ("failed, then passed after 1 file(s) changed") and
    the verification are written.
  - A call that never gets its result never reads as passed.
- **`test_partial_line_rotation_and_restart_preserve_progress`.**
  - A half-written line is not consumed, then is mined once completed.
  - A new process continues from the saved cursor.
  - A rotated file (same history plus one line) mines only the new line.
  - A truncated file is read from the start (`reset: truncated`), with no
    duplicate jots.
- **`test_crash_between_jot_and_cursor_is_idempotent`.** A real subprocess is
  killed by `os._exit` right after its first jot is written. The next firing
  recognises that jot, writes the other, and a further firing writes nothing.
- **Also covered:**
  - the per-firing cap defers instead of dropping;
  - rule caps are counted;
  - `doctor` reports the backlog;
  - a real process holding the lock means nothing is consumed, then
    everything is mined after;
  - a failing write keeps the candidate, and drops it (counted) after five
    tries;
  - an over-long line is skipped and counted, and the next line is mined;
  - a forked session copying its parent's transcript writes only its own new
    event;
  - the carried state holds no credential;
  - jots written by the old miner, under the old title fingerprints, are not
    offered again when the new miner re-reads the session from byte 0.
    Without the title-fingerprint check this fails, with both re-offered.
- **`test_a_growing_transcript_is_mined_across_stop_and_compact`** (hooks):
  a `Stop` firing, then `PreCompact` on the grown transcript. Each candidate is
  written once, the compaction marker lists only the new one, and the cursor
  sits at the end.

Against the pre-change code (`22a1bff`), the 12 original recovery tests and
the new hook test **all fail**. The upgrade test was written afterwards, for
this package's own compatibility fix.

- **4 behaviorally:**
  - the sliding tail: 0 of 4 corrections mined;
  - the late result: no attempt;
  - truncation: the new correction is never mined;
  - the fork: 3 jots written for 1 new event.
- **7 on missing API or report fields that are their substance:**
  - the deferring cap, counted caps, `doctor`, lock contention, write failure
    (`backlog`, `policy_capped`, `locked`);
  - the oversize line (`ingest`);
  - carried secrets (`miner_state_path`).
- **The crash test** passes its behavioral part on the old code, because
  per-session fingerprints already prevented a duplicate there. It fails only
  on the new backlog field, and now pins that idempotency.
- **The new hook test** passes its jot assertions on the old code (a small
  transcript never slid). It fails on the cursor's new unit.

## Results

| Command | Exit | Result |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` (3.11.15) | 0 | 1266 run, 0 failures, 6 skipped |
| WP09 and affected transcript/hook/inbox/lock/promotion tests on 3.9.23 | 0 | 213 OK |
| `test_mcp` with MCP SDK 2.2.0 | 0 | OK (2 skipped) |
| `python evals/run.py` | 0 | Identical to WP08's output |
| `regression_probes.py … --fail-on-observed` | 2 | 7 defect signals, 2 probe errors (WP04/WP05's recorded instrument errors). `sliding_cursor` is no longer observed: the appended correction is written, and the stored cursor is 7,501,610 bytes ([probe-results.json](probe-results.json)) |
| CI `test` job fixture steps, replayed | 0 | All 7 pass |
| `ruff check . && ruff format --check .` (0.16.1) | 0 | Clean |
| One firing after a small append to a 20 MB transcript, before vs after | — | 34 ms vs 6 ms (median of 5): only the new bytes are read |

The remaining signals belong to other packages:

- `prompt_cliff`;
- `guard_prefilter` (F10);
- `symlink_read`;
- `powershell_translation`;
- `short_prompt_and_stale_task`;
- `guard_usage_dedupe`;
- `resume_ignores_lock`, the false positive recorded in WP05.

## Compatibility

- **`private/miner-cursor.json` is no longer read.** The first firing after the
  upgrade starts each session at byte 0 and works forward 8 MB at a time.
  Candidates already written for that session are recognised by their new
  fingerprint or by the old title fingerprint older jots carry. Only a churn
  candidate whose count has since grown has a new title, and it is offered
  once more.
- **New machine-local state:** `private/miner/<session>.json` and
  `private/miner/acked.json`, gitignored with the rest of `private/`.
- **Mining reads forward, not the tail.** A very long transcript seen for the
  first time is mined from its start over several firings rather than from
  its last 8 MB, and the backlog of unread bytes is reported. A subagent
  transcript is still mined once, from its last 32 MB (was 8 MB).
- **The report gains fields.** `mine_transcript_into_jots` returns the old
  `written` / `skipped` / `dropped_for_secrets` plus:
  - `policy_capped`, `backlog`, `dropped_backlog`;
  - `consumed_bytes`, `unread_bytes`, `skipped_bytes`;
  - `oversize_lines`, `malformed_lines`;
  - `reset`, `locked`, `error`.

  `skipped` no longer counts cap overflow, which is now deferred.
- **Library.**
  - `transcript.mine()` and `write_candidates()` are unchanged in signature.
  - `pair_tool_calls` gains `carried=`, and `ToolCall` gains `call_id`.
  - `Candidate` gains `key` and `events`; its fingerprint uses `key` when set.
  - `hooks_common.set_miner_cursor` is removed.

## Limits

- **Forward catch-up can lag.** A session that appends more than 8 MB between
  firings falls behind. The lag is reported (`unread_bytes`, `doctor`), not
  hidden, and there is no time-based catch-up within a firing.
- **Carried history is bounded.** A failure whose fixing pass comes more than
  200 Bash/edit calls later is not joined into an attempt. Churn counts only
  the edits still carried.
- **Fork detection relies on shared event ids.** A fork is recognised by the
  tool_use ids (and entry `uuid`s) that Claude Code copies. A harness that
  renumbers them would have its forked history mined again under the new
  session.
- **The acknowledged-event ledger keeps the newest 5,000 events.** A replay of
  events older than that, in a session whose jots have expired, could propose
  them again.
- **Secret handling is pattern-based.** It uses the same structured patterns
  as `scan-secrets`. A credential with no known shape can be carried in a
  command until the carried call ages out.
- **A candidate whose writes keep failing is dropped after five firings.** It
  is counted, but not recoverable.
