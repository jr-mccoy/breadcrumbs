# Compatibility matrix

What breadcrumbs does on each host and platform, and what evidence stands
behind each claim (audit WP17, finding F22). A cell says **tested** only where
CI or a named test exercises it. Anything else is either stated as
**untested** or marked **not supported**. Nothing here says a Claude Code hook
works in another agent.

For the store format across *versions* (which build reads and writes which
store), see [`compatibility.md`](compatibility.md).

## 1. Capabilities by host

| Capability | Claude Code | Any MCP client (Codex, Cursor, Gemini CLI, …) | Any agent with a shell | A person |
|---|---|---|---|---|
| **Plain files** (`.project-memory/*.md`) | yes | yes | yes | yes |
| **CLI** (`crumb …`) | yes | yes, if it can run commands | yes | yes |
| **MCP** (`breadcrumbs-mcp`, 13 tools, 14 resources, 6 prompts) | yes (`init --with-mcp` writes `.mcp.json`) | yes; register the server by that client's own mechanism | n/a | n/a |
| **Standing rules** (`crumb promote`) | `CLAUDE.md` (loaded each session) | `AGENTS.md`; or the rule rides in the portable packet over MCP | read the file | read the file |
| **Resume at session start** | `SessionStart` hook | `memory://resume-packet` or `memory_build_resume_packet`, when the agent is told to call it | `crumb resume` | `crumb resume` |
| **Automatic capture** (session snapshot, transcript mining) | `Stop`, `PreCompact`, `SubagentStop` hooks | **not supported**: no hook mechanism is used | `crumb capture session` by hand | same |
| **Prompt retrieval** | `UserPromptSubmit` hook | **not supported** (call `memory_search`) | `crumb search` | same |
| **Guard before a tool call** | `PreToolUse` hook, for the tools below | **not supported** automatically (call `memory_guard_before_action`) | `crumb guard` | same |

Instruction-file signposts (`init --with-adapter`) are written for
`AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `.clinerules`, `.windsurfrules` and
`.github/copilot-instructions.md`. A signpost tells the agent the store
exists; whether that agent reads the file is up to the agent.

**Cross-harness continuation is tested.**
`test_cross_harness_resume_uses_same_records_and_rules`
(`tests/test_adapter_contracts.py`) resumes one store two ways: Claude Code's
`SessionStart` packet with `CLAUDE.md` loaded, and a hookless MCP client
reading the portable packet. Both see the same canonical record ids and the
same rules in effect.

## 2. Claude Code hook payloads

Declared in `breadcrumbs/adapters/claude.py`, contract version 2, and
exercised by `tests/fixtures/claude_hook_payloads.json`.

| Tool | Handling | Action the guard scores |
|---|---|---|
| `Bash`, `PowerShell` | guarded | the command as typed |
| `Edit`, `Write`, `MultiEdit` | guarded | `edit <path>: <snippet of the new content>` |
| `NotebookEdit` | guarded | `edit <notebook>: <new cell source>`, or `delete a cell in <notebook>` |
| `Task`, `Agent` | guarded, capped at `READ_FIRST` | the subagent's launch prompt, and the paths it names |
| `Read`, `Glob`, `Grep`, `LS`, `WebFetch`, `WebSearch`, `TodoWrite`, `NotebookRead`, `BashOutput`, `KillShell`, `ExitPlanMode` | ignored (not in the matcher) | none |
| anything else (another server's MCP tools, a future tool) | unknown: reported unsupported | none |

The installed matcher is built from this declaration
(`Bash|PowerShell|Edit|Write|MultiEdit|NotebookEdit|Task|Agent`). Re-running
`crumb init --with-hooks` brings an existing install up to date. Before audit
WP17, a `PowerShell` call became an empty action and the hook said nothing.

## 3. MCP

The versioned contract is in `mcp_core.contract()`, version 1, and
[`mcp-spec.md`](mcp-spec.md) describes it: tools, parameters, advisory
annotations, resources, prompts and the error envelope. The CI `mcp` job holds
the live server to it on Python 3.10–3.14 with both SDK majors (`mcp<2` and
`mcp>=2,<3`). Locally it was also checked with SDK 1.30.0 and 2.2.0.
Annotations are advisory; policy is enforced by `admission.py`.

## 4. Platforms

| Platform | Python | Evidence | Status |
|---|---|---|---|
| Linux (Ubuntu, CI) | 3.9–3.14 | the full unit suite, the fixture checks, the installed-wheel smoke test (`package` job), evals, lint | **tested** |
| macOS (CI `native` job) | 3.9, 3.13 | installed-wheel smoke test and adapter/MCP contract tests (gating); the full unit suite (reported): 1,364 run, 0 failures (CI run 247) | **tested** |
| Windows (CI `native` job) | 3.9, 3.13 | installed-wheel smoke test and adapter/MCP contract tests (gating); the full unit suite (reported) | **tested, full suite being confirmed**: run 246 found 50 failures, 42 of them product defects, all fixed; run 247 found 16 from one regression, fixed in `f528a24`. A confirming run on the fixed revision is pending. |

The first native full-suite runs, and each failure's cause, are in the
[WP17 review record](reviews/2026-09-27-breadcrumbs-wp17/README.md).

`tools/platform_smoke.py` runs against the *installed* console script, in a
project whose path has spaces and non-ASCII characters. It checks:
- `init` finding the bundled templates;
- a non-ASCII title and a spaced evidence path written as UTF-8;
- `search` and `resume --json`;
- the guard's exit code against its verdict;
- a `PowerShell` hook payload;
- lock contention across processes (a write fails fast, then succeeds once the
  lock is released);
- no temporary files left behind;
- replay containment: `verify --recheck` on an assertion that prints 10 MB
  and starts a child that outlives it, where the output must be recorded
  bounded and truncated, and the child must not survive the check.

## 5. Not supported, on purpose

- **Hooks for hosts other than Claude Code.** There is no daemon and no
  generic hook shim. Another agent gets memory through files, the CLI and
  MCP, and an instruction file that tells it to use them.
- **Guarding tools the matcher does not name.** A new host tool is unknown
  until the adapter declares it, and then it is tested.
- **Enforcement through MCP annotations.** They are hints for a client's UI.
