# WP04: replay is execution, not proof (2026-09-27)

This implements work package WP04 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), findings F04 (P1)
and F25 (P2). The starting commit is `c1375d7`, after WP03.

## Cause

`lifecycle.recheck` ran every `command` **and `test`** evidence string through
`subprocess.run(shell=True)`. It wrote `fixed` when all of them exited 0 and
`open` otherwise, in a new verification that did not pass the old scope, so it
became `project`. So:

- a `python -c pass` "fixed" an authentication bug;
- a test-file path was executed as a program;
- a branch-scoped finding became project-wide.

The runner used `capture_output` with a timeout on the immediate child. Output
was held whole and trimmed afterwards, and descendants were never terminated.

## Change

**`breadcrumbs/checks.py` (new).** It keeps execution separate from what a run
may claim.

- **`CheckResult`** records one run: `status` (`passed`, `failed`,
  `unavailable`, `timeout`, `killed` or `unsupported`), plus the exit code,
  signal, timeout, duration, bytes seen, whether output was truncated, a
  scrubbed 3-line tail, the working directory, the platform and a detail.
  `evaluated` is true only for `passed` and `failed`.
- **The assertion spec (version 1).** An assertion is an evidence item
  `{type: assert, ref: <command>, spec: "1"}`, declaring that the command exits
  0 exactly when the subject is fixed. Any other `spec` is reported
  `unsupported` and not run.
- **`settle()`.** Only assertions can settle a claim:
  - all passed → `fixed`;
  - one failed on a claim recorded as `fixed` or `not_applicable` →
    `regressed`;
  - one failed otherwise → `open`;
  - any assertion not evaluated → no outcome.
- **`run_check()`.** It keeps shell semantics exactly as recorded (the
  platform's shell, never POSIX parsing of a Windows string).
  - Each run gets its own process group (`start_new_session` /
    `CREATE_NEW_PROCESS_GROUP`).
  - Output is kept in a rolling 64 KiB window while the command runs.
  - The whole group gets SIGTERM, then SIGKILL, on timeout, on Ctrl-C (then
    re-raised) and after a normal return. `taskkill /T` is used on Windows.
  - A child that escaped the group (`setsid`) is reported, not waited for.
  - Shell exit 126 or 127 (9009 from `cmd`) and spawn errors are `unavailable`.

**`lifecycle.recheck`.**
- Assertions run first; `command` evidence runs as diagnostics.
- `bind_commands=True` (the CLI's `--bind-commands`) is the operator binding a
  record's commands as its assertion; the new record then stores them as one.
- A settled recheck writes a new verification that supersedes the old one and
  keeps its subject, **scope, branch, confidence**, tags and evidence.
- An unsettled recheck writes nothing and returns
  `{settled: false, reason, runs}`.

**`recheck_targets`.**
- `test` evidence no longer qualifies a record, and is never executed.
- A branch-scoped verification from another branch is refused with a reason:
  a run from this checkout would describe this branch.

**CLI.**
- `verify --assert CMD` (repeatable) declares an assertion.
- `verify --recheck … --bind-commands` binds a record's commands for that run.
- The preview marks each command `[assert]` or `[diagnostic]`, and says when a
  run cannot settle anything.
- The output lists each run's status and says whether the claim settled.
- The JSON summary adds `settled`, `not_settled` and `regressed`.
- Consent is unchanged, and there is still no MCP replay endpoint.

**Docs.** `cli-spec.md` → *verify --recheck* is rewritten, and the `verify` row
mentions `--assert`. The README's recheck paragraph is updated. CHANGELOG.

## Tests

`tests/test_replay_contract.py` has 16 tests, including the four the roadmap
names:

- `test_noop_diagnostic_does_not_fix_claim`
- `test_recheck_preserves_branch_scope_across_checkout`: real git; recheck on
  the feature branch keeps scope, branch and confidence; the record is absent
  from main's packet; a recheck from main is refused.
- `test_assertion_failure_differs_from_runner_unavailability`: failed →
  `regressed`/`open`; a missing tool → `unavailable`, not settled.
- `test_output_and_descendant_processes_are_bounded`: 5 MB of output held to
  4 KiB; a background child is ended with the check.

The others cover:
- a timeout, and an unknown spec (not run);
- diagnostics beside an assertion, and `--bind-commands` being recorded;
- a `test` file never executed, even when it is executable;
- a timeout ending the whole tree, a detached (`setsid`) child being reported
  rather than waited for, secret-shaped output being dropped, and a check that
  cannot start;
- the CLI preview and output, and `verify --assert`.

Against the pre-change `cli.py`, `lifecycle.py` and `lifecycle_cmds.py`, 11 of
the first 15 fail. The 4 that pass exercise `checks.py` directly, and there was
no bounded runner to compare against.

With process-tree cleanup disabled, both tree tests fail. Ctrl-C was checked by
hand: the interrupt re-raises about 0.4 s after it arrives, and the background
child is dead.

`test_lifecycle` encoded the old rule "exit 0 → fixed". Its two recheck tests
now check three things:
- a plain command settles nothing;
- a command bound with `--bind-commands` records `fixed` and supersedes;
- a bound failing command on a `fixed` claim records `regressed`.

## Results

| Command | Exit | Result |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` (3.11.15) | 0 | 1217 run, 0 failures, 6 skipped |
| `test_replay_contract test_lifecycle` on 3.9.23 and 3.10.20 | 0 | OK |
| `python evals/run.py` | 0 | Unchanged |
| `regression_probes.py … --fail-on-observed` | 2 | 14 defect signals, **1 probe error** (below) ([probe-results.json](probe-results.json)) |
| CI `test` job fixture steps, replayed | 0 | All 7 pass |
| `ruff check . && ruff format --check .` (0.16.1) | 0 | Clean |

### The `recheck_scope_and_claim` probe now errors

The probe rechecks a branch-scoped open finding whose only evidence is a
`python -c pass` *command*. It then dereferences the new record. Under the new
contract that command is a diagnostic, so nothing is written: `new_id` is
`None`, and the probe raises `AttributeError`.

Per the audit, a probe error does not demonstrate a repair, so this is recorded
as an error, not as "fixed". The audit scripts are kept byte-identical, so the
probe is not adapted. Its two questions are answered by ordinary tests:

- `test_noop_diagnostic_does_not_fix_claim`: the same no-op leaves the claim
  `open` and active, with no new record.
- `test_recheck_preserves_branch_scope_across_checkout`: when an assertion does
  settle the claim, the new record keeps scope `branch` and its branch, and does
  not appear on `main`.

## Compatibility

- **`verify --recheck` on a verification that only names commands no longer
  changes it.** It runs the commands (with consent) and reports them. To keep
  the old behavior for a record, pass `--bind-commands` once, or re-record it
  with `--assert`.
- **`test` evidence is no longer executed.** A record whose only check was a
  test-file path is now "nothing to recheck".
- **Recheck JSON items gain `settled`, `reason` and richer `runs`.** `runs`
  keep `command`, `exit_code` and `tail`, and `new_id` / `outcome` may be
  `null`. The summary adds keys.
- A settled recheck can now write `regressed`. Before, it only wrote `fixed` or
  `open`.
- No stored record is rewritten. The `assert` evidence type is additive and
  passes the WP01 contract (`type` and `ref`, plus a `spec` key).

## Limits

- **The environment is not filtered.** The runner inherits it, and the
  permitted environment inputs are not recorded (F25 asks for this). Filtering
  it would change what recorded commands mean; that needs a policy decision.
- **Windows cleanup is untested here.** It uses `taskkill /T`, which cannot
  reach a child whose parent already exited; a Job Object would. Native Windows
  qualification is WP17.
- **Only exit codes are assertions.** Spec 1 has no expected-output matching or
  platform guards. Commands are still shell strings, not argument vectors.
- **A detached child keeps running.** A process that leaves the group
  (`setsid`, a daemon) is reported in `detail`, but not ended.
- **No local audit log.** An unsettled recheck leaves no trace in the store;
  only the command output and JSON record it.
