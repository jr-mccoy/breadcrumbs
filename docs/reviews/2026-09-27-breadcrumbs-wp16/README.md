# WP16: an application layer the CLI, MCP and hooks share (2026-09-27)

This implements work package WP16 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), finding F21.
The starting commit is `fa2df0e`, after WP15. The operator authorized the
remaining work on 2026-09-27.

This is a first extraction, not the whole of F21. Its "done when" is that the
CLI is an adapter rather than "the dependency every internal module must
import". **That is not yet true**: most domain functions still live in
`cli.py`, and 18 modules still import it. See [Limits](#limits). The tracker
records the package as `review_required` for that reason.

## Cause

- **`cli.py` was the CLI and the domain kernel at once.** Importing any domain
  function defined the `argparse` layer and imported `argparse`.
- **Two copies of one write.** `crumb remember` (`cmd_remember`) and
  `memory_record` (`mcp_core.tool_record`) each implemented the same
  pipeline: admission, the supersede check, the near-duplicate gate, the
  mutation transaction, the write, the `validate` gate, retirement and the
  reindex. Only their wording differed, and a fix to one could miss the other.
- **Admission was assembled per transport.** MCP called `admission` directly,
  `crumb mark-status` did not call it at all (a no-op for the CLI channel, but
  by accident, not by design), and the hooks set the channel by hand.
- **Store-global state.** The search-alias table was one module-level dict.
  With two stores in use at once, one store's aliases leaked into the other
  (reproduced below). The only way to set the clock was to patch `cli._now`
  for the whole process.

## Change

- **`breadcrumbs/service.py` (new): the application layer.**
  - `Context(root, memory_dir, channel, clock, agent)`, and `open_context`.
  - `active(ctx)` makes the context current for one operation. It sets the
    admission channel, the clock (`cli.clock`), the store's aliases
    (`cli.store_aliases`, per thread) and one parse cache (`cli.operation`).
    Every service function enters it, so it is re-entrant.
  - The operations:
    - `record`: the decision/attempt write, the only implementation;
    - `mark_status`;
    - `admit` and `review_status_for`: one admission decision for every
      channel;
    - `search`, `guard`, `resume_packet` and `prompt_lookup`.
  - Failures are a `ServiceError` whose `kind` the adapter words: `usage`,
    `refused`, `needs-evidence`, `duplicate`, `invalid`, `rejected`, `failed`
    or `missing-store`. The service never prints.
- **The transports call it.**
  - The CLI: `remember`, `mark-status`, `search`, `guard` and `resume`. The
    channel is whichever transport is running the command.
  - MCP: `memory_record`, `memory_mark_status`, `memory_search`,
    `memory_guard_before_action`, `memory_build_resume_packet`, and the
    `_admit` gate used by every writer.
  - The hooks: `crumb hook` runs each firing inside a hook-channel context;
    the guard hook and the prompt hook's lookup call the service.
- **What stays at the edges, on purpose:**
  - prompts and argument parsing;
  - wording ("new record failed validation" versus "record rejected by
    validate");
  - exit codes versus `{ok: false}` envelopes;
  - one documented difference: an unstated confidence without evidence is an
    error at the CLI and `low` over MCP (`docs/mcp-spec.md`).
- **`breadcrumbs/cli_parser.py` (new): the argument parser, moved out of
  `cli.py`.**
  - Moved mechanically: 43 top-level nodes, via the AST, with free references
    rewritten to `cli.NAME` and scope respected.
  - `cli.main` builds it lazily. `cli.build_parser` is kept as a function, the
    other moved names are forwarded by a module `__getattr__`, and the
    `crumb.py` shim re-exports them.
  - `cli.py` imports `argparse` only for type checking, plus once locally
    where a hook builds a `Namespace`.
- **Aliases and the clock are scoped, per-thread state.**
  - `cli.store_aliases(memory_dir)` activates and restores the alias table;
    `cli.active_store_aliases()` reads it.
  - `cli.clock(fn)` sets the operation's clock. `_now` consults it, and
    patching `_now` still works.
  - Changed test: `test_aliases` read and reset the old module globals; it now
    uses the accessor. The behavior it checks is unchanged.

**Docs.** `architecture.md` §6 has the layers and the new modules;
`CHANGELOG.md`.

## Tests

`tests/test_application_parity.py` has 5 tests.

- **`test_refactor_preserves_ids_scores_and_wire_contracts`.**
  - It replays one scripted session through every transport, with a pinned
    clock and jot suffixes:
    - CLI `remember` (three writes, a duplicate, a missing-evidence refusal),
      `note trap` and `jot`;
    - MCP `memory_record` (a write, a policy refusal, a missing-evidence
      refusal, a duplicate) and `memory_jot`;
    - CLI and MCP search, guard and the resume packet;
    - `crumb hook guard` and `crumb hook prompt`;
    - `generated/related.json` and `conflicts.json`, and the record ids.
  - The outputs are compared with
    [`tests/fixtures/application_parity.json`](../../../tests/fixtures/application_parity.json).
    That golden was captured and committed (`83628b3`) from the code at
    `fa2df0e`, before any of the extraction. Only the temp path, commit
    hashes and durations are normalized.
  - It passes after the extraction, on Python 3.11 and 3.9.
  - `test_scenario_is_deterministic` shows two runs agree, so a failure would
    be a behavior change, not noise.
- **`test_service_import_does_not_import_cli_parser`.** In a fresh
  interpreter, `import breadcrumbs.service` followed by a search and a guard
  loads neither `breadcrumbs.cli_parser` nor `argparse`, and prints nothing.
  The CLI still builds its parser.
- **`test_cli_mcp_and_hook_admission_parity`.**
  - For four policies (solo/write, solo/propose, team/propose,
    team/read-only), four payloads (plain, `agent: human`,
    `review_status: reviewed`, `reviewed_by`) and three channels:
    - the transport refuses exactly when `service.admit` does for that
      channel;
    - a written record's `review_status` is what `service.review_status_for`
      says;
    - the write went through `service.admit` (spied).
  - The CLI skips the review-field payloads, because it has no flags that set
    them.
  - A CLI write from inside an agent session is a proposal under `team`,
    matching the service.
- **`test_two_store_contexts_do_not_share_alias_or_policy_state`.**
  - Two stores, one with `aliases.txt` (billing = payments) and a team
    policy, are active at once in two threads.
  - Each thread sees its own aliases: the trap is found for "payments" only
    in the store with the alias.
  - Each sees its own policy: `needs-review` versus `unreviewed`, and its own
    clock.
  - Nested contexts in one thread restore the outer aliases. Nothing is left
    active afterwards.

**Behavior comparison.** [behavior.txt](behavior.txt), from
[behavior.py](behavior.py), one subprocess per tree:

| Check | Before (`fa2df0e`) | After |
|---|---|---|
| Importing the domain module loads the argument parser | yes | no |
| Record-write implementations (`cmd_remember`, `tool_record` calling `write_record`) | 2 | 0 (both call `service.record`) |
| Two stores' aliases shared across threads ("payments" stems to) | yes (`bill` / `bill`) | no (`bill` / `pay`) |
| No operation-scoped clock | yes | no |
| **Defects observed** | **4** | **0** |

## Results

| Command | Exit | Result |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` (3.11) | 0 | 1337 run, 0 failures, 7 skipped |
| parity, parser, aliases, MCP, admission, remember, hooks and integrations tests on 3.9.23 | 0 | 236 OK (6 skipped: MCP SDK) |
| `test_mcp`, `test_admission_policy` and `test_application_parity` with MCP SDK 2.2.0 | 0 | 62 OK (2 skipped) |
| `python evals/run.py --verbose` | 0 | Identical to WP15 apart from timings ([evals.txt](evals.txt)) |
| `python evals/run.py --release` | 0 | 20 critical cases pass |
| `regression_probes.py … --fail-on-observed` | 2 | Unchanged: 3 defect signals, 3 probe errors ([probe-results.json](probe-results.json)) |
| CI `test` job fixture steps, replayed | 0 | All 7 pass |
| `ruff check . && ruff format --check .` (0.16.1) | 0 | Clean |

## Compatibility

- **No output changes.** The golden covers ids, scores, verdicts, packets,
  JSON envelopes, exit codes, hook output and the generated files.
- **Python API.**
  - New: `breadcrumbs.service` and `breadcrumbs.cli_parser`;
    `cli.store_aliases`, `cli.active_store_aliases`, `cli.clock` and
    `cli.build_parser` (forwarding).
  - Removed: the module globals `cli._STORE_ALIASES` and
    `cli._STORE_ALIASES_KEY`. Nothing outside the tests read them.
  - Parser names (`cli._CrumbParser`, `cli._SUBCOMMAND_BUILDERS`, …) still
    resolve through `cli`.
- **The CLI entry point is unchanged** (`breadcrumbs.cli:main`).

## Correction (after the WP16 commit)

CI failed on the WP16 commits (run 238): the parity test's `inputs_hash`
differed on GitHub's runners. The scenario's `git commit` used the machine's
global git config, and this development container signs commits
(`commit.gpgsign`). The commit hash — which records carry and every inputs
hash covers — therefore differed between machines. The scenario now runs git
with `GIT_CONFIG_GLOBAL=/dev/null` and `GIT_CONFIG_NOSYSTEM=1`, on a branch
named `main`.

The golden was regenerated from the pre-extraction tree (`fa2df0e`), not from
the extracted code: the corrected test file was copied into a worktree of
`fa2df0e` and `--write-golden` run there, twice, with identical output. The
extracted code matches it. Nine lines changed, all of them the branch name and
values derived from the commit hash. No output of the code under test
changed. I had not checked CI after pushing WP16; WP17 onwards does.

## Limits

- **F21 is not finished.**
  - `cli.py` is still 13,915 lines, down from 15,025, and holds record I/O,
    validation, packet building and search/guard scoring.
  - 18 modules still import it, and `service.py` does too, for those domain
    functions.
  - This package gives those functions one application entry and moves the
    parser out; moving the functions themselves into domain modules is the
    remaining work. The roadmap warns against a single large rewrite, so it
    is left for follow-ups, each held to the parity golden.
- **Not every command goes through the service.** `note`, `verify`, `jot`,
  `inbox`, `promote`, `review`, `policy`, capture and the lifecycle commands
  still call domain functions directly. Their admission already came from
  `admission.py`, keyed on the channel the transport sets.
- **The hook channel has no guidance-writing transport.** Hooks write jots
  (routine capture). The parity test exercises hook-channel guidance writes
  through `service.record` inside the context `crumb hook` sets.
- **Policy is read per call from `manifest.yml`, not cached in the context.**
  That is what keeps two stores' policies apart, and a policy change applies
  to the next call.
