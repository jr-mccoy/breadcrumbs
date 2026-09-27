# WP06: recoverable multi-record mutations (2026-09-27)

This implements work package WP06 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), finding F20. The
starting commit is `c2544bb`, after WP05.

## Cause

`remember --supersedes` wrote the new decision and then called
`mark_superseded`. From the results it extracted only the demotion
information, and it never checked that the retirement succeeded. A refused
retirement therefore left **two live decisions** and exited 0 (the
`partial_supersession` probe). The same shape recurs across the writers:

- **MCP `memory_record`, `note`, `verify`:** same code path.
- **`inbox promote`:** returned `ok` with a warning when the jot's retirement
  failed.
- **`consolidate --merge`:** retired sources one by one, ignoring failures.
- **`rollup sessions`:** wrote the rollup, then deleted its sources.
- **`mark-status` on a promoted record:** ignored a failed automatic demotion,
  leaving the rule in `CLAUDE.md`.
- **`demote`:** removed the rule, then could fail to clear the record's fields.

Each write was atomic; none of the sequences were. There was no record of an
interrupted sequence, and no way to recover from one.

## Change

**`breadcrumbs/mutations.py` (new).**

- **`transaction(memory_dir, kind)`.** It runs under the store lock (WP05),
  taking it if the caller does not hold it.
  - Before the first write or delete of any tracked file, it journals that file
    to `private/operations/<id>/`: the before-image (bytes or "absent") and the
    digest of each state about to be written. The journal is written ahead of
    the change.
  - Tracked files are records, singletons, and project files such as
    `CLAUDE.md` / `AGENTS.md`. `generated/`, `index/` and `private/` are not
    tracked; they are rebuilt.
  - Commit deletes the journal. Any exception, or a step the caller checked
    (`MutationFailed`), restores every tracked file, rebuilds the projections,
    and re-raises.
  - A nested `transaction()` joins its parent. A failure inside it dooms the
    parent even if an intermediate caller turns the exception into a return
    value, so a partial inner change can never be committed.
- **`recover(memory_dir, apply=)`.** It rolls back journals left by a writer
  that died. It restores a file only when it still holds its before-image or a
  state the operation wrote; any other file is a `conflict`, left alone, and
  the journal is kept. A file the operation created and the rollback removes is
  first copied to `private/recovered/<id>/`.
- **`write_text_atomic(…, expected=)`** raises `RevisionConflict` when the file
  no longer holds the text the writer read.

**Writers converted.** Each is now one transaction, and every retirement result
is checked. `lifecycle.retire_all` raises instead of letting callers ignore
failures.

- `cmd_remember`, MCP `tool_record`, `note()` and `verify()` (including
  `recheck`): the new record plus its retirements.
- `inbox.promote_jot`: the target, `--supersedes` and the jot's retirement. A
  failed jot retirement now undoes the promotion, closing WP03's documented
  `warning` gap.
- `lifecycle.merge_records` (consolidate) and `lifecycle.rollup_sessions`.
  Rollup deletes its sources through `mutations.delete`, so the deletions are
  journaled.
- `cli.set_record_status`: the status change plus automatic demotion. A
  promoted record whose rule cannot be removed is not retired.
- `promote.promote` and `promote.demote`: the record and the instruction file.
  Any refusal after the first write rolls both back.
- Revision checks (`expected=original`) apply to every record rewrite: status,
  retitle, trap and question status, trap confirm, and promotion fields.
  `rewrite_managed_block` (adapter files) and `write_text_atomic` journal
  through `mutations.before_write`.

**Visibility.**
- **New command `crumb recover [--apply] [--json]`** (locked). It lists
  unfinished operations with a per-file plan (`restore`, `remove`, `unchanged`
  or `conflict`), or rolls them back. It exits 1 while any remain unfinished.
- **`crumb doctor`** gains an `operations` row and a `projections` row.
- **`_publish_projections`** writes `private/projections-pending` when a
  rebuild raises, and clears it on the next success.
- **`resume`** warns on stderr about unfinished operations, and its `--json`
  `publication` gains `unfinished_operations`. Private state is never put into
  the committed packet.

**Docs.**
- `cli-spec.md`: a new section *Multi-record operations and `recover`*, a
  `recover` row in the command table, and the new `doctor` rows.
- `architecture.md`: a module row for `mutations.py`.
- `record-schema.md`: the new `private/` entries.
- `README.md` and `CHANGELOG.md`.

## Tests

`tests/test_mutation_recovery.py` has 10 tests, including the four the roadmap
names:

- **`test_failed_retirement_is_not_success_with_two_live_decisions`.** The CLI
  replacement with a refused retirement exits 1 and says `nothing was changed`.
  One live decision remains, every canonical file is byte-identical, and no
  journal is left.
- **`test_failure_after_each_participant_is_recoverable`.** A real subprocess
  replaces a *promoted* decision and is killed with `os._exit` right after its
  k-th file write, for every k until the operation completes. In the recorded
  run:
  - crashes after writes 1–12 left a journal. `recover` restored the store
    byte-for-byte, removing the new record and restoring the old record and
    `CLAUDE.md`;
  - crashes after writes 13–16 came after the commit, during the projection
    rebuild, and left the complete replacement;
  - run 17 completed.
- **`test_expected_revision_prevents_lost_update`.** Another editor saves
  between the read and the write. The status change is refused and the other
  edit survives.
- **`test_retry_does_not_duplicate_or_orphan_records`.** After a failed
  replacement, the retry yields exactly one successor with the correct
  back-pointer, and a repeated `recover` is a no-op.
- **Also covered:**
  - MCP record, consolidate and inbox promote all roll back;
  - a failed jot retirement undoes the promotion;
  - a failed demotion rolls back the retirement;
  - `recover` leaves a later edit alone and keeps its journal (exit 1);
  - a rolled-back new record is kept, not erased;
  - a failed projection rebuild appears in `doctor` and clears.

All 10 fail against the pre-change writers (8 behaviorally).

## Results

| Command | Exit | Result |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` (3.11.15) | 0 | 1234 run, 0 failures, 6 skipped |
| WP06 and affected lifecycle/promotion tests on 3.9.23 | 0 | OK |
| `test_mcp` with MCP SDK 2.2.0 | 0 | OK |
| `python evals/run.py` | 0 | Unchanged |
| `regression_probes.py … --fail-on-observed` | 2 | 12 defect signals, 2 probe errors (WP04/WP05's recorded instrument errors). `partial_supersession` is no longer observed: exit 1, one live decision ([probe-results.json](probe-results.json)) |
| CI `test` job fixture steps, replayed | 0 | All 7 pass |
| `ruff check . && ruff format --check .` (0.16.1) | 0 | Clean |
| `crumb remember` ×15, before vs after | — | 13.8 ms vs 13.3 ms per write: no measurable journal cost |

## Compatibility

- **A replacement whose retirement fails now exits 1 and writes nothing,**
  where it used to exit 0 with two live records. The MCP tools return
  `{ok: false}`.
- **`inbox promote` never returns `ok` with a `warning` any more.** A failed
  jot retirement is a failed promotion.
- **`mark-status` of a promoted record fails** if its rule cannot be removed.
- **A record rewrite can refuse with "changed since it was read".** Re-running
  the command is the remedy.
- **New store paths:** `private/operations/`, `private/recovered/` and
  `private/projections-pending`. All are machine-local and gitignored.
- **New command:** `crumb recover`.
- **Library callers.** The mutating functions (`set_record_status`,
  `note(… supersedes=)`, `verify(… supersedes=)`, `promote`/`demote`, and the
  others above) now take the store lock themselves when the caller does not
  hold it.

## Limits

- **Rollback, not roll-forward.** A crash mid-operation undoes the operation,
  and the command must be re-run. The removed new record is kept under
  `private/recovered/`, but it is not replayed.
- **The revision check is not an atomic compare-and-swap.** It rereads the file
  immediately before replacing it, which leaves a tiny window against a
  non-cooperating writer. Cooperating writers are serialized by the lock.
- **Only the listed multi-step writers are transactions.** Single-record writes
  (a plain `remember`, `jot`, `capture session`) are single atomic writes, and a
  `capture session` handoff update is not yet journaled with its session record.
- **Projections after a crash stay stale until rebuilt.** A crash after commit
  but during projection publication leaves them stale; `validate` freshness and
  `doctor` show it, and `crumb reindex` fixes it. Snapshot-coherent publication
  is WP07.
