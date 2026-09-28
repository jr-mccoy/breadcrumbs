# Operator guide

How to run breadcrumbs day to day, and how to recover when something is
off. Start with [`quickstart.md`](quickstart.md). What the store promises is
in [`continuity-contract.md`](continuity-contract.md); every command is in
[`cli-spec.md`](cli-spec.md).

## 1. Three kinds of memory

| Kind | Where | Lifetime | Who writes it | What reads it |
|---|---|---|---|---|
| **Capture**: jots, session snapshots, mined corrections | `inbox/`, `private/inbox/`, `sessions/` | expires (jots: 14 days by default) | anyone; hooks write it automatically | search, the packet's inbox section; never a guard verdict |
| **Durable memory**: decisions, attempts, verifications, traps, questions | `decisions/`, `attempts/`, `verifications/`, `traps/`, `questions/` | until retired (settled verifications expire after 90 days) | a person or an agent, with evidence or `--confidence low` | the resume packet, search, guard, the hooks |
| **Standing rules** | a managed block in `CLAUDE.md` / `AGENTS.md` | until demoted | `crumb promote`, CLI only | every session that loads the file |

Promote a jot with `crumb inbox promote <id> <type>` once it proves durable.
Promote a durable record to a standing rule with `crumb promote <id>` only when
every session should obey it. The record stays active either way; `crumb
demote <id>` takes the rule back out.

## 2. Profiles, privacy and budgets

- **Profiles** (`crumb policy set solo|team`, [`security.md`](security.md) §4).
  - `solo` (the default) trusts what is written.
  - `team` makes guidance written by an agent (through MCP, a hook, or the
    CLI inside an agent session) a *proposal* (`review_status:
    needs-review`). It also refuses high-impact changes over MCP, and requires
    a person's `crumb review` before `crumb promote`.
  - `--mcp-mode read-only` serves MCP with no writing tools.
  - Profiles bind MCP clients and hooks. **They do not bind an agent with a
    shell**; Git review of `.project-memory/` and the instruction files is that
    boundary.
- **Privacy.**
  - `private/` is machine-local and gitignored.
  - `--local` jots and every automatic writer go there.
  - `crumb scan-secrets` exits non-zero on a secret-shaped string in committed
    memory. Run it before committing: in CI, or from a git pre-commit hook of
    your own. `crumb` does not install one.
  - `privacy: secret-prohibited` marks content that must not be stored at
    all; `validate` fails any record carrying it.
- **Budgets.**
  - The resume packet stays within 5,000 approx-tokens (`--budget`). Its
    header says what it used and what it left out.
  - The prompt hook injects at most 5 records. The guard hook does not repeat
    an advisory within a session for the same records and file (a `PAUSE` or
    `ASK_HUMAN` always fires).
  - `crumb doctor --hook-log` shows what each hook actually did.

## 3. What guard does, and does not do

- **What it does.** `crumb guard "<action>"` (and the `PreToolUse` hook)
  scores the store against a proposed action. It answers `PROCEED` (0),
  `READ_FIRST` (10), `PAUSE` (15) or `ASK_HUMAN` (20).
- **It is advice, not authorization.**
  - `PROCEED` means no relevant memory, not "safe".
  - `PAUSE` comes from an attempt with an explicit do-not-retry condition;
    `ASK_HUMAN`, from a high-impact action class (deletion, migration,
    external side effects).
  - Neither blocks anything by itself. Under Claude Code, `PAUSE` and
    `ASK_HUMAN` make the harness ask the person.
- **Why a record surfaced.** Every match carries its reasons: same file,
  same tag, shared keywords, named in the title, has a do-not-retry
  condition. `crumb show <id>` prints the record.
- **Retire or correct it:**
  - a newer record that replaces it: `crumb remember … --supersedes <id>`;
  - no longer true: `crumb mark-status <id> stale|rejected|superseded
    --reason …`;
  - suspicious: `crumb mark-status <id> quarantined --reason …`;
  - a standing rule that is wrong: `crumb demote <id>`.

## 4. Platforms and harnesses

See [`compatibility-matrix.md`](compatibility-matrix.md).
- Hooks (automatic capture, prompt retrieval, the guard before a tool call)
  are Claude Code's.
- Other agents get the files, the CLI and MCP, when they call them.
- Linux is tested in full, and Windows and macOS by the native CI job. A
  surface the matrix does not list as tested is not claimed.

## 5. Recovery

Run `crumb doctor` first. Each line names its fix.

| `doctor` says | What happened | Do this |
|---|---|---|
| `[resume_packet] stale vs HEAD` | records changed since the packet was built | `crumb resume` (or `crumb reindex`) |
| `[search_index] stale` / `unreadable` | the index is behind or damaged; search already falls back to a full scan | `crumb reindex` (`--search-index` to rebuild only it) |
| `[operations] N unfinished operation(s)` | a multi-record write was interrupted | `crumb recover` to see them, `crumb recover --apply` to roll each back to its before-image |
| `[projections] the last projection rebuild failed` | a reindex raised midway | fix what it names, then `crumb reindex` |
| `[records] N validation failure(s)` | a record was edited into an invalid state, or predates a rule | `crumb validate` names file, field and rule; fix the file. A store in an older layout: `crumb migrate` (a verified backup is taken first; `crumb migrate --restore` undoes it) |
| `[compatibility] … writes are refused` | the store was written by a newer crumb-kit, or needs a feature this build lacks | upgrade crumb-kit; reads keep working meanwhile |
| `[related_map] … incomplete` | "see also" hit its pair budget on a very dense store | nothing is lost; `crumb audit` names it. Fewer ubiquitous tags help |
| `[hook_matcher] … not …` | hooks installed by an older version do not guard PowerShell or notebook edits | `crumb init --with-hooks` |
| `[hooks] no hooks installed` (Claude Code) | nothing captures or injects automatically | `crumb init --with-hooks` |
| `[miner] … dropped` | transcript mining hit a cap | `crumb doctor --hook-log`; see [`field-test.md`](field-test.md) |

A lock error ("the store is locked by …") means another writer is running.
Writes wait up to 2 s (hooks 0.5 s) and then fail rather than corrupt. A lock
held by a process that died is released by the kernel.

## 6. After a merge or a release

The default branch's `handoff.md` is what the next session reads first. Stale
narrative there makes an agent redo finished work, so reconcile it when work
lands:

1. On the default branch, after the merge:
   `crumb capture session --next "<what is actually next>" --set "Current
   Focus" "<the state now>"`.
2. Retire what the merge settled: supersede or mark-status decisions it
   replaced, and close answered questions.
3. Old branch handoffs (`handoffs/<branch>.md`) are removed by
   `crumb prune handoffs` once their branch is gone and 30 days old.

`crumb resume` shows the handoff's date and commit. A handoff older than the
last release deserves a look before it is trusted.
