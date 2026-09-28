# WP17: adapters, the MCP contract and native platforms, qualified (2026-09-27)

This implements work package WP17 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), findings F22
and F25. The starting commit is `e2b769c`, after WP16. The operator authorized
the remaining work on 2026-09-27.

## Cause

- **Tools were translated by hand, and not all of them.**
  - The guard hook's matcher named `Bash|Edit|Write|MultiEdit|Task|Agent`, and
    `_hook_action_from_tool` translated those six.
  - A `PowerShell` command became an empty action and the hook said nothing.
    That is the audit's `powershell_translation` probe.
  - `NotebookEdit`, which transcript mining already knew, was never guarded.
  - An unknown tool was silently empty, which is indistinguishable from
    "nothing to guard".
- **No MCP contract.** Tool names, parameters and the error envelope were
  held only by counts in `ci.yml` and scattered tests. There were no advisory
  annotations.
- **Linux only.** Every CI job ran on Ubuntu. Windows and macOS quoting,
  encodings, locks, atomic replacement, installed-wheel behavior and replay
  containment (F25) were untested.

## Change

- **`breadcrumbs/adapters/claude.py` (new).** Contract version 2.
  - It declares the guarded tools (`Bash`, `PowerShell`, `Edit`, `Write`,
    `MultiEdit`, `NotebookEdit`, `Task`, `Agent`) and the ignored ones (reads,
    searches, web fetches, …).
  - It normalizes each guarded tool's documented input into an `Action`.
    `NotebookEdit` covers replace, insert and delete. An unknown tool is
    `supported: False`.
  - `GUARD_MATCHER` is built from the declaration. `_HOOK_SPECS` uses it, so
    `crumb init --with-hooks` installs it and updates an owned entry.
  - `cli._hook_action_from_tool` delegates to it; the old constant names
    remain as aliases.
- **The versioned MCP contract.**
  - `mcp_core.contract()`, version 1, covers every tool's parameters, required
    parameters and advisory annotations, plus the resources, prompts, error
    envelope and refusal envelope.
  - It is pinned by `tests/fixtures/mcp_contract_v1.json`.
  - `mcp_server` registers every tool through `_tool_registrar`, which
    attaches `ToolAnnotations` on SDKs whose `tool()` accepts them
    (feature-detected).
  - The annotations are hints, not access control; `mcp-spec.md` says so.
- **Native platforms.**
  - `tools/platform_smoke.py` (new) runs against the *installed* console
    script, in a project path with spaces and non-ASCII characters. It checks:
    - install and templates;
    - Unicode and quoting on disk;
    - search and `resume --json`;
    - guard exit codes;
    - a PowerShell hook payload;
    - lock contention across processes;
    - no temporary files left;
    - replay containment.

    It always prints a report, even when it crashes.
  - A `native` CI job (`windows-latest` and `macos-latest`, Python 3.9 and
    3.13) builds the wheel and runs the smoke test (gating) and the adapter
    and MCP contract tests (gating) on every push.
  - A `native-full` job runs the whole unit suite on the same four
    combinations (reported, not gating). To limit runner time it runs only
    on `main`, weekly and on demand. Until the operator's request on
    2026-09-28 it ran on every push, which is how runs 246 and 247 below
    came about.
- **Replay containment on Windows (F25), found by the native job.**
  - `checks.run_check` put a check in a process group and, on Windows, ended
    it with `taskkill /T`. Once the shell had returned, that could not find a
    child the command left running, and the child outlived its check.
  - Each check on Windows now runs in a kill-on-close **Job Object**.
  - A Job Object alone was not enough on Python 3.13, whose venv launcher's
    child escaped the job. So the **process tree is also tracked while the
    check runs** (a snapshot every 100 ms, each descendant recorded with its
    creation time). Every tracked process still alive is ended afterwards,
    and a reused PID is never touched.
  - Every run reports its `containment` in the recheck output:
    `process-group`; or `job-object` / `taskkill (why)` plus
    `tracked N descendant(s), M still running and ended`.
- **Docs.**
  - [`docs/compatibility-matrix.md`](../../compatibility-matrix.md) (new):
    capabilities by host, Claude Code tool handling, MCP, platforms, and what
    is not supported on purpose.
  - `mcp-spec.md`: the versioned contract.
  - `cli-spec.md`: the guard matcher.
  - `CHANGELOG.md`.

## Tests

`tests/test_adapter_contracts.py` has 6 tests.

- **`test_supported_tool_names_normalize_expected_actions`.**
  - The 16 payloads in
    [`tests/fixtures/claude_hook_payloads.json`](../../../tests/fixtures/claude_hook_payloads.json)
    each normalize to the expected kind, text, files and supported flag,
    through both the adapter and `cli._hook_action_from_tool`.
  - The cases cover every guarded tool, ignored tools, another server's MCP
    tool, a future tool, and a non-dict input.
- **`test_installed_matcher_is_the_declared_tool_set`.** `init --with-hooks`
  installs `GUARD_MATCHER`. Every guarded tool matches it, and no ignored tool
  does.
- **`test_powershell_and_notebook_edits_reach_the_guard`.** End to end through
  `crumb hook guard`: a PowerShell deletion and a notebook edit both surface
  the recorded attempt.
- **`test_mcp_errors_and_resources_match_versioned_contract`.**
  - The contract equals the pinned fixture.
  - With no store, all 13 tools return `{ok: false, error}`.
  - A policy refusal carries exactly `ok`, `error` and `refused_by`; other
    errors carry exactly `ok` and `error`.
  - Every static resource serves text, and every template raises for an
    unknown id.
- **`test_live_server_matches_the_contract`.** With the SDK, it checks the
  live server's tool names, input schemas (properties and required), prompts,
  and annotations where supported. Verified locally on SDK 1.30.0 and 2.2.0;
  the CI `mcp` job runs both majors on Python 3.10–3.14.
- **`test_cross_harness_resume_uses_same_records_and_rules`.** Claude Code's
  `SessionStart` packet (with `CLAUDE.md` loaded) and a hookless MCP client's
  portable packet show the same canonical record ids and the same rules in
  effect.

**Behavior comparison.** [behavior.txt](behavior.txt), from
[behavior.py](behavior.py):

| Check | Before (`e2b769c`) | After |
|---|---|---|
| A PowerShell command yields no action | yes (`""`) | no |
| A notebook edit yields no action | yes | no |
| The installed matcher misses PowerShell or NotebookEdit | yes | no |
| No versioned MCP contract | yes | no |
| MCP tools carry no annotations | yes | no |
| No native Windows or macOS CI job | yes | no |
| **Defects observed** | **6** | **0** |

The audit probe `powershell_translation` now reports no defect. The probe
total drops from 3 signals to 2.

## The first native full-suite run, and what it found

CI run 246 (commit `e835448`) was the first to finish the full unit suite on
macOS and Windows. Of 1,346 tests:

| Platform | Python | Failures | Errors |
|---|---|---|---|
| macOS | 3.9 | 10 | 0 |
| macOS | 3.13 | 6 | 0 |
| Windows | 3.9 | 49 | 1 |
| Windows | 3.13 | 49 | 1 |

The failure lists are in [native-run-246.txt](native-run-246.txt). Each
failure was traced to a cause. Two local simulations reproduced most of them
on Linux before any fix:
- a symlinked `TMPDIR` reproduced all six macOS 3.13 failures;
- `os.linesep = "\r\n"` in every process (a `sitecustomize`) reproduced the
  Windows writers.

Each fix is in commit `48bc814`.

**Product defects (42 of the 50 Windows failures; 3 of macOS 3.9's 10 and 2 of macOS 3.13's 6):**

| Defect | Where it showed | Fix |
|---|---|---|
| The mutation journal recorded text before newline translation. On Windows, rollback took every file the operation had written for someone else's edit and left it, so a failed replacement left two live decisions. | 9 `test_mutation_recovery` | The journal records the bytes written; the adapter-block writer too. |
| The inputs hash and the generation's file digests treated CRLF as content. A Windows writer or an autocrlf checkout read every stamp as stale. | 3 fixtures, 2 MCP validate, 1 multi-machine packet, packet drift, 7 parity sub-tests, the prefilter tests | CRLF is normalized before hashing. LF-only stores hash as before. |
| The generation's stat fingerprint named files by absolute path. A reader using another spelling of the directory never trusted the prefilter. | the 2 prefilter tests on macOS | Store-relative names. |
| Store-relative paths printed with OS separators. | `scan-secrets`, `show` drift, stamps, packet drift, init tree | `as_posix()` at the 13 sites. |
| `git check-ignore` read `\r\n`-terminated paths on Windows. | the multi-machine gitignore test | `-z`, NUL-separated bytes. |
| `cmd.exe` exits 1, not 9009, for a missing program, so a missing runner read as a failed assertion (a false "regressed"). | the replay-contract settlement test | Decided from the command line: not a builtin, and not on PATH or in cwd. |
| The Windows lock covered byte 0, where the owner line is, so no waiter could read the pid. | 6 lock tests | The lock covers a byte past the owner line. The lock is unreleased, so no released version is affected. |
| The hook log's append raced its rotation (inferred: it did not reproduce on Linux). | the parallel-telemetry test, on macOS 3.9 and Windows | Append and rotation share one hold of the log's lock. |
| `configure_output` probed the current markers, so a second call after an ASCII choice switched back to glyphs. | the 2 cp1252 tests on Windows | It probes the glyphs. |
| `read_text_lenient` had no universal newlines. | adapter duplication | It uses `path_policy.decode`. |
| `/etc/hosts` is not absolute to `Path` on Windows. | evidence staleness | Either platform's absolute form is skipped. |

**Test portability (8 Windows failures, and the rest on macOS):**
- handoff paths compared unresolved (macOS `/private`, a Windows 8.3 name);
- the parity normalizer replaced the shorter root spelling first and missed
  JSON-escaped Windows paths;
- the git-calls test counted one extra probe for an unresolved root, because
  `is_git_repo` memoizes per spelling;
- UTF-8 files read with the locale encoding;
- a POSIX-shell command in the recheck test;
- `str()` of a relative path in the init-tree test.

**The next run, and a regression it caught.** CI run 247 (`68c8075`, after
the fixes) is in [native-run-247.txt](native-run-247.txt):
- **macOS:** 1,364 run and 0 failures, on Python 3.9 and 3.13.
- **Windows:** 16 failures on both versions, and none of them among run 246's
  50. All 16 came from one site `48bc814` missed. The write gate matched a
  record's findings with `str(relative path)`, which is backslashed on
  Windows, against the now-POSIX finding paths. It matched nothing, so an
  invalid promotion, `mark-status` or supersession was let through (6
  failures). A test helper had the same pattern (10). It was never released.
- **Fix:** `f528a24`.
- **Guard:** Linux cannot show this difference, so a test now refuses the
  pattern itself, `str(…relative_to(…))` or an f-string rendering of one,
  anywhere in the package. It fails on `68c8075`.

**Regression tests.** `tests/test_platform_portability.py` (8 tests) holds each
product fix in a form Linux runs, so the gating jobs keep it. The first 7 fail
on `e835448` and pass after; the path-rendering guard fails on `68c8075`. `WindowsLineSeparatorTests` reruns the
truthful-failure cases under a CRLF line separator: 6 fail on `e835448`.

## Results

Local results are on `68c8075` (Python 3.11 unless noted), plus the fix
`f528a24`. CI results are from runs 246 and 247.

| Check | Result |
|---|---|
| Full suite (`f528a24`) | 1,365 run, 0 failures, 8 skipped |
| The same, with a symlinked `TMPDIR` (macOS path spellings; `68c8075`) | 1,364 run, 0 failures |
| The same, with a CRLF line separator in every process (Windows writers) | 1 failure: a same-size-edit test whose own `write_text` stays LF under the simulation; it passes on real Windows |
| Python 3.9: `test_platform_portability`, `test_mutation_recovery`, `test_validation_contract`, `test_adapter_contracts`, `test_lifecycle` | all OK |
| MCP SDK 2.2.0 full suite / SDK 1.30.0 contract tests | 1,364 OK / 6 OK |
| `evals/run.py` / `--release` | pass / 20 of 20 critical cases |
| `regression_probes.py … --fail-on-observed` | exit 2: 2 recorded false positives (`guard_usage_dedupe`, `resume_ignores_lock`) and 3 recorded probe errors; `powershell_translation` no longer observed |
| CI `native`, installed-wheel smoke test and contract tests (gating) | pass on Windows and macOS, Python 3.9 and 3.13 (runs 246 and 247) |
| CI `native` full suite, macOS | run 246: 10 and 6 failures; run 247: 0 on both |
| CI `native` full suite, Windows | run 246: 49 failures and 1 error on both; run 247: 16 on both, all the regression fixed in `f528a24` |
| CI `test`, `mcp`, `package`, `evals`, `lint` | green (run 247) |

**Confirmed by CI run 248** (`9b55822`, which includes `f528a24`): the native
full suite ran 1,365 tests with 0 failures on all four combinations (Windows
3.9 in 1,384 s and 3.13 in 1,334 s; macOS 3.9 in 430 s and 3.13 in 380 s).

## Compatibility

- **Hook output changes only where it was missing.**
  - A `PowerShell` or `NotebookEdit` tool call now reaches the guard.
    Re-running `crumb init --with-hooks` updates the installed matcher; an
    existing install without it keeps working as before for the other tools.
  - Every other tool's action text is byte-identical (the fixture cases and
    the WP16 parity golden).
- **MCP.**
  - Tool annotations are new metadata. Tools, parameters, results and errors
    are unchanged, which the WP16 parity golden and the contract fixture
    confirm.
  - A client that ignores annotations sees no difference.
- **Replay reports** gain a `containment` field.
- **Python API:** `breadcrumbs.adapters.claude`, `mcp_core.contract()`,
  `MCP_CONTRACT_VERSION`, `TOOL_CONTRACT`, `WRITE_TOOLS` and `PROMPTS`.
- **The native fixes (`48bc814`).**
  - Hashes: an LF-only store hashes exactly as before, so no committed stamp
    on Linux or macOS changes. A store with CRLF files (written on Windows, or
    checked out with autocrlf) now hashes like its LF twin, so its stamps read
    as current instead of stale.
  - Store-relative paths in `--json` and reports are POSIX on Windows too.
    They were backslashed there, which a consumer on another machine could
    not match.
  - The Windows lock covers a different byte. The OS lock is itself
    unreleased (WP05), so no released version is affected.
  - Everything else is unchanged on Linux; the parity golden still matches.

## Limits

- **One harness has hooks.** Claude Code is the only host whose payloads are
  normalized, because it is the only one breadcrumbs installs hooks for. Other
  agents get files, the CLI and MCP (the matrix says so).
- **The payload fixtures are written from Claude Code's documented field
  names, not captured from a live session of every version.** They say what
  is handled; a new version that renames a field would show up as an empty
  action. Contract version 2 is the place to record that.
- **The Windows tree tracking polls.** A process that starts a child and
  exits between two 100 ms polls hides that child. The Job Object remains
  the first line.
- **The native full suite is reported, not gating.** Its results are in the
  matrix. On Windows it takes about 20–25 minutes, and making it gate is
  WP22's decision.
- **Two causes are inferred, not reproduced.**
  - The hook-log race did not reproduce on Linux; the native telemetry test
    passing (runs 247 onward) is the evidence.
  - The `cmd.exe` exit code of 1 for a missing program is taken from the
    native log. The fix decides from the command line, so a program found on
    PATH that exits 1 is still a failure.
- **Simulation is not the platform.** The symlinked `TMPDIR` and CRLF
  simulations reproduced most failures, but the path-rendering regression
  shows what they cannot see. The native job remains the evidence.
- **The stdout encoding on a Windows console** is the code page. Non-ASCII
  output is replaced with `?` (the CLI sets `errors="replace"`; files on disk
  are UTF-8). The smoke test records this as an observation, not a failure.
