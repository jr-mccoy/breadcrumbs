# Fix plan: the DoWhat field report (crumb-kit 0.4.0)

Status: **plan only, nothing implemented.** Written 2026-10-01 on branch
`claude/zealous-hamilton-ba7e5m`, at commit `295c6db` (the 0.4.0 release
commit). That is the same code the field session ran, so the report's line
numbers in `breadcrumbs/cli.py` still match.

## How the claims were checked

Every claim in the report was read against the code and, where possible,
reproduced in a scratch git repo with a scratch store. The scratch stores
were:

- a 400-record store with 120 traps at schema 4;
- the same store reshaped to schema 1, with a 175 KB `known-traps.md`;
- schema-1 stores with hand-written trap statuses;
- stores committed on `claude/...` and `ccr-...` branches and then merged by
  merge commit, squash and rebase.

Nothing in the repo was changed during verification. Timings are from Linux.
Windows numbers in the report are explained by reasoning, not by
measurement, and that is marked where it matters.

**Verdict.** All 13 issues are real. Several have a different or wider root
cause than the report says (see *Corrections*). Verification also found 12
further problems, four of them data loss or safety problems (see *New
findings*).

---

## Corrections to the report

| # | The report said | What the code shows |
|---|---|---|
| 3 | The repeat nag needs the snapshot to fail. | It also repeats when the snapshot lands but does not sort as "newest", for example a record from another machine with a later clock (`created_at` ordering, `cli.py:5217-5245`). |
| 6 | The 204 KB `known-traps.md` on schema 1/2 may be the cost. | It is not: parse time is 3 ms at schema 1 versus 7 ms at schema 4. The cost is **git subprocesses**. Guard spawns 2–3 `git` processes per distinct record commit that is not on HEAD's history (`CommitDistanceIndex.distance_reaches`, `cli.py:6282-6292`). On Linux that was 127 spawns for one Edit; at Git for Windows' ~40 ms per spawn that is ~5 s, which matches the field p50. (The Windows figure is inferred.) |
| 8 | The robolectric trap may lose because it was promoted from a jot with low confidence. | Confidence is not the cause. **The trap's tags were thrown away when it was written**: `note` / `inbox promote … trap` write `tags: []` (`cli.py:4537`, `blockfiles.py:253`), and trap scoring hard-codes `tags = set()` (`cli.py:9146`). The trap was never tagged `robolectric` at all. Section headings in attempt bodies (`Why It Failed`) also count as matching words, so "**why** is my test **failing**" matches every attempt. |
| 8 | `git push --force origin main` got ASK_HUMAN "because of the action type". | The action type only *raises* a verdict that matched records already lifted to READ_FIRST (`cli.py:9779-9784`). The irrelevant records are what caused the ASK_HUMAN. On a store with no git records, the same command gets PROCEED. |
| 9 | Squash merges or renames may break the "has this reached HEAD" check. | That check (`HeadTree`, `cli.py:6639`) is correct for merge, squash, rebase and rename, and resume uses it. Guard, search and the prompt hook **don't use it**: they compare only the record's `branch:` field with the current branch name (`cli.py:9443-9453`). |
| 12 | Most of the 133 failures came from migration. | Most were already failing at schema 1. The dry run listed them, but only as counts by category ("frontmatter: 3, status: 1, …"), not by file. |
| 12 | The README's plain-file fallback invites hand-writing. | `README.md:1082-1087` is about *reading* without the CLI. The real invitations are the bundled template README (`templates/project-memory/README.md:33`, "or write a session record by hand") and the `known-traps.md` header, which tells people to add `## trap_…` blocks by hand. |
| 13 | stdout needs setting to UTF-8. | `configure_output` (`cli.py:126-147`) already reconfigures stdout, but only to `errors="replace"` and not to UTF-8. An em dash *is* encodable in cp1252, so Python writes byte `0x97`, and Git Bash's UTF-8 terminal renders it as `�`. |

---

## New findings (not in the report)

| ID | Kind | Finding | Where |
|---|---|---|---|
| N1 | **data loss** | `crumb note trap` and `inbox promote … trap --tags x` drop every tag. The trap file gets `tags: []`; the jot it came from kept its tags. | `cli.py:4537`, `blockfiles.py:145,253` |
| N2 | **data loss** | Migration step 3 silently keeps only the first of two `## trap_x:` blocks with the same id. It reports success, and the second body survives only in the gitignored backup. | `blockfiles.py:655,691` |
| N3 | **safety** | A record with an invalid status (for example a decision marked `fixed`) is silently dropped from Active Decisions. Guard then answered **PROCEED** to the exact action the decision forbids. A verification with no frontmatter is shown as outcome **open** even when its body says "Fixed". `resume` does not warn about either. | `cli.py:6316,7436,7602,1798` |
| N4 | **safety** | Guard's read-only check looks only at the first word and treats a single `\|` as harmless. So `find … \| xargs rm -rf` is "read-only", and the read-only cap *downgrades* a destructive command to READ_FIRST. | `cli.py:8458-8478,9786` |
| N5 | trust | With more than 25 dirty files, the Stop hook's "nothing changed" check compares a capped list against an uncapped one, so it re-snapshots on every turn. | `cli.py:1598,13285-13301` |
| N6 | trust | An incompatible store (`IncompatibleStore`, a `StoreLocked` subclass) is logged as `locked`, so the Stop hook goes permanently quiet without saying why. | `lock.py:77-100`, `cli.py:13591-13599` |
| N7 | trust | The Stop hook counts the agent's own commit of `.project-memory/` as "new work", so an agent that commits its records is asked about that commit next turn. | `cli.py:13318-13337` |
| N8 | trust | Commits are compared as *short* shas by string, so a different `core.abbrev` gives a phantom "(HEAD moved…)" block. A backwards checkout also shows as "1 new commit". | `cli.py:1536-1540,13299,13329,13337` |
| N9 | trust | A failed migration backup leaves a partial `private/migrations/<stamp>/` behind with no manifest. `--restore` deletes each store entry *before* copying the backup back in. | `migrate.py:234-252`, `restore()` |
| N10 | trust | At schema 3+, a hand-added trap block with a bad status makes index rebuilding fail silently (`except Exception: return`). | `blockfiles.py:517-519` |
| N11 | trust | Guard's action classifier reads class words out of quoted text. `crumb capture session --next "cut the release"` is classed as an external side effect because of the word *release*. | `classify_action`, `cli.py:8983` |
| N12 | polish | The migrate step-3 error shows only the first 5 failures, so a store with many bad traps means fix five, re-run, repeat. | `blockfiles.py:710` |

---

## Order of work

The order follows the request: data loss first, then wrong or noisy output,
then polish. The work is grouped into three releases. Each release is
something that has to land together.

### Release 1: "stop losing things" (0.5.0, because `--next` changes behaviour)

1. **#1** `capture session --next` adds an entry instead of replacing; only `--replace` overwrites, and it saves what it replaced. `current.md` stops being overwritten by the git log.
2. **N1** Trap and question tags survive `note` and `inbox promote`.
3. **N2** Migration never drops a duplicate trap id.
4. **#4** The migration dry run runs the same checks as the real run, and maps legacy statuses (decision D2).
5. **#5** A migration backup that hits long paths gets a pre-flight check and a readable error, and leaves nothing behind (N9). `--restore` copies before it deletes.
6. **#2 + #3 + N5–N8** One redesign of the Stop hook's memory: a per-session cursor, asked at most once per HEAD, and every failure logged.
7. **#13c** The Stop hook, README and `CLAUDE.md` block say that `--next` adds an entry above the earlier ones.
8. **N3** `resume` names every record it cannot use, and shows a missing outcome as "unknown", not "open".

Why these ship together: items 1–5 are data loss. Items 6–7 are the path
that *triggered* the data loss (the Stop hook told the agent to run the
command that overwrote the file). Item 8 is the read-side half of the same
problem: memory that is present but silently ignored. None of it changes
guard verdicts, so the eval baseline is not touched.

### Release 2: "a guard you can trust" (0.6.0)

9. **N4** Close the `| xargs rm` read-only hole. This is a safety fix: if Release 2 slips, ship it on its own in a patch.
10. **#7** Split compound commands; stay silent on writes outside the project; stop longer commands earning higher scores; classify crumb's own commands; ignore class words inside quoted text (N11).
11. **#10** Stop treating `/dev/null`, `and/or` or URLs as files, and stop pulling file names out of written file content.
12. **#8** Make the do-not-retry boost need topical evidence; remove template headings from matching; make traps score their tags; treat `./gradlew` as a command; give the prompt hook its own ranking; add an `evals/` suite built from the field cases.
13. **#9** Show the "another branch" label only for records that have not reached HEAD.
14. **#11** Connect commands to the files they write (crumb's own commands first).
15. **#6** Meet a 300 ms budget on the common path: no per-commit git spawns, a cheap freshness check, an early exit for read-only commands, a per-record pre-filter.

Why these ship together: every item changes which records guard returns or
what verdict it gives. Each would make the eval CI job fail until the
baseline is rewritten (`trap_eval-baseline-after-retrieval-change`), so they
should share one baseline rewrite and one review. #6 goes last because its
pre-filter changes must be checked against the new scoring, not the old.
Guard behaviour changes are a minor-version change under
`dec_20260927_pre-1-0-releases-bump-the-minor-…`.

### Release 3: polish

16. **#12** `crumb repair` (assisted repair), and documentation of a "write it later" path.
17. **#5 (rest)** A `doctor` check for over-long record paths, and a rename tool.
18. **#13a** UTF-8 output on Windows terminals that aren't consoles (Git Bash, mintty).
19. **#13b** Upgrade documentation for `uv tool`, and the MCP registration change (decision D4).
20. **N12** Show every migration failure, not the first five. This is small: fold it into item 4 if convenient.

**Schema version:** none of the fixes below needs a `schema_version` bump or
a new migration step. The details are in each issue. Two machine-local
format numbers do change (`GUARD_PREFILTER_FORMAT`, and the search-index
format if commit distances move into the index). Those files are gitignored
and rebuilt automatically, so they need no migration.

---

## Decisions (answered 2026-10-01)

- **D1. What is "Next Action"?** **Append unless `--replace`** (your choice).
  Issue 1 has the design.
  - **Still open, D1b:** should the first append set
    `requires: next-action-log`, so that 0.4.0 machines refuse to write
    instead of wiping the log? My lean is yes.
- **D2. Legacy trap statuses at migration.** **Map by default** to `stale`
  (questions to `answered`), keep the original wording as a note, and list
  every mapping in the dry run.
- **D3. A destructive command with no relevant memory.** **Built-in floor:**
  a short list of high-impact actions gets ASK_HUMAN with "no project memory
  about it", and cites no unrelated records.
- **D4. MCP registration on Windows.** **Docs now, local scope later.**
  Document the `uv tool` case now. Later, register the interpreter form in
  Claude Code's per-user local scope and keep the committed `.mcp.json`
  portable.
- **D5. Branch-scoped records after their branch is merged** (not asked;
  lower stakes). The plan treats them as live project memory once their file
  has reached HEAD. Say if you'd rather they stay history.

---

## Issue by issue

Each section gives: whether the claim was confirmed, the root cause, the
options, the recommendation, the test that fails today and passes after the
fix, and whether a schema bump is needed.

### 1. `capture session` overwrites hand-written handoff and current notes (DATA LOSS)

**Confirmed.**

**Root cause.** There are three separate overwrites:

- `update_handoff` (`cli.py:5908-5960`) does
  `sec["Next Action"] = next_action or sec.get("Next Action", "")` at
  `cli.py:5933`. Any non-placeholder `--next` replaces the whole section.
- `update_current` (`cli.py:5963-5996`) does the same for Recently Changed
  at `cli.py:5972`.
- `cmd_capture_session` passes `recently = sections["Work Completed"]` into
  `update_current` (`cli.py:5651`, `5663`), and that value is the git-log
  prefill.

The silent Stop-hook snapshot (`_hook_capture_snapshot`,
`cli.py:13450-13480`) protects Next Action, because its stand-in text counts
as a placeholder. It does **not** protect Recently Changed: whenever new
commits exist, the snapshot replaces whatever a person wrote there with a git
log. `README.md:984` promises the snapshot "never overwrites one you set";
that is true for Next Action only.

Nothing keeps the old text anywhere. The mutation journal deletes its
before-images when the write succeeds (`mutations.py`, docstring). The
session record stores only the new Next Action.

One more point: resume never reads Recently Changed. It computes its own
"Landed Since The Handoff Was Written" from git (`cli.py:7974`). So the git
log that capture writes into `current.md` duplicates something resume
already shows, and it is the only reason the overwrite happens.

**Decision D1 (yours): append unless `--replace`.** The options considered
were (A) keep one slot but move aside any text crumb didn't write, (B) a
crumb-managed log with automatic archiving, and (C) append by default with an
explicit `--replace`. You chose C. The design below is C.

**Next Action: the design**

- `--next "text"` **adds** a dated entry at the **top** of `## Next Action`.
  The entry starts with a header line such as
  `**2026-10-01** · `abc1234` · main`, followed by the text.
  - Everything already in the section stays below it, byte-for-byte. That
    includes undated, hand-written text.
  - The newest entry goes at the top, not the bottom, because that is how
    DoWhat's log was kept and what a reader (and resume) sees first.
- **Repeats don't stack.** If the text equals the newest entry's text, the
  run changes nothing. This keeps the Stop hook's "run just the final capture
  command" from adding the same line on every turn.
- **`--replace` overwrites the whole section.**
  - The replaced text is copied into the new session record under
    `## Replaced Next Action`.
  - A warning names the file and how many lines were replaced.
  - Nothing in crumb (the Stop hook, `CLAUDE.md` block, README) ever suggests
    `--replace`.
- **The Stop-hook snapshot** still passes a placeholder and changes nothing,
  as today.
- **Resume** shows the newest entry in full, then a line such as
  "_14 earlier entries in handoff.md_". It finds where the newest entry ends
  by crumb's header line; text with no header counts as one earlier block.
  The existing 2,000-character excerpt (`PROTECTED_EXCERPT_CHARS`,
  `cli.py:6097`) stays as a backstop.
- **Per-branch handoffs are unchanged.** A new branch's handoff still starts
  with an empty Next Action (`handoffs.seed_text`, `handoffs.py:126-142`), so
  main's log is never copied into a branch.
- **Growth is the known cost of C.** The section grows without limit; DoWhat's
  was already 10,749 characters.
  - `doctor` and `audit` report when Next Action passes about 8,000
    characters.
  - An optional, manual `crumb handoff trim --keep N` (Release 3) moves older
    entries to a committed `handoff-history.md`. It never runs on its own.

**Older crumb versions (sub-decision D1b).** A 0.4.0 crumb on another machine
still replaces the whole section on its next `--next`, which is the exact
field incident. The new code can't change what an old client does. Two
choices:

- **Release note only.** Tell users to upgrade every machine that shares the
  store. Recovery after an old client overwrites the log is git history.
- **Use the existing `requires:` mechanism** (`compat.py`, WP21; 0.4.0
  already honours it). The first append adds `requires: next-action-log` to
  `manifest.yml`.
  - 0.4.0 then refuses every write to the store with "needs a newer
    crumb-kit": loud, and nothing is lost.
  - The cost: until that machine upgrades, it can't write at all. Its Stop
    hook goes quiet (logged as `incompatible` once N6 is fixed).
  - 0.3.1 and older don't check `requires`.

My lean is **`requires:`**: a loud refusal on an old machine beats silently
losing the log again. I'll take your call on it before implementing.

**Recently Changed: the design**

This follows the same append rule:

- Capture stops writing the git log into `current.md`. Resume already shows
  "Landed Since The Handoff Was Written" from git, and nothing reads the copy
  in `current.md`.
- `--set "Recently Changed" "…"` adds a dated entry at the top and keeps the
  rest. `--replace` applies here too.
- Stop-hook snapshots never touch `current.md`.

The alternative was to keep writing the git log between
`<!-- crumb:auto -->` markers and leave text outside the markers alone. That
is more machinery for content resume ignores.

**Defense in depth.** Any rewrite of a managed section that removes text
saves the removed text into the session record and prints a warning. In this
design only `--replace` can remove text, but the rule also guards future
code. Under `full` tracking that record is committed, so `git log` can always
find it.

**Tests that fail today**

- `test_next_adds_an_entry_and_keeps_the_rest`: write a `handoff.md` whose
  Next Action is a 139-line hand-written dated log, then run
  `capture session --next "x"`.
  - Every original line is still there, in order.
  - "x" is the first entry, with a dated header.
  - Running it again with the same text changes nothing.
- `test_replace_saves_what_it_replaced`: `--next "y" --replace` leaves "y"
  alone in the section. The session record holds the old 139 lines under
  `## Replaced Next Action`, and the warning names the file.
- `test_snapshot_never_touches_hand_written_recently_changed`: hand-write
  Recently Changed, make a commit, fire the Stop-hook snapshot. `current.md`
  is byte-identical.
- `test_resume_shows_newest_entry_and_count`: three entries give a packet
  showing the newest and "2 earlier entries".
- If D1b is `requires:`: `test_first_append_sets_requires`, and a 0.4.0-style
  write is refused by the lock (`IncompatibleStore`).
- Keep `test_repeat_firings_write_one_record_and_keep_next_action` and the
  per-branch handoff tests green. The per-branch handoff behaviour is on the
  "worked well" list.

**Schema.** No `schema_version` bump: `handoff.md` and `current.md` are not
records. It is a behaviour change to `--next`, so it is a minor release
(0.5.0) under the pre-1.0 policy. If D1b is `requires:`, add
`next-action-log` to `KNOWN_FEATURES` and give it a row in
`docs/compatibility.md`.

### 2. The Stop hook asks about commits this session didn't make

**Confirmed, and wider than reported.**

**Root cause.** `_extraction_commits` (`cli.py:13318-13337`) uses
`git log {last}..HEAD`. Here `last` is the commit of the newest session
record in the whole store, sorted by `created_at`, with no filter by branch,
by host session or by author (`_last_session_commit`,
`cli.py:5226-5245`). The first-firing silent baseline exists only when the
store has no session record at all.

So the block fires on any movement of HEAD since *anyone's* last record:

- a long gap;
- a `git pull`, which counts every pulled commit and both sides of a merge;
- a branch switch, where a backwards checkout shows as "1 new commit" (N8);
- the agent's own commit of `.project-memory/` (N7).

**SessionStart writes nothing that Stop reads.** `_hook_session`
(`cli.py:13073-13124`) only builds the packet. The per-session state
plumbing already exists, though: `hooks_common.update_state`, keyed by
`session_id`, capped at 8 sessions, locked, never raises. It already holds
`hook-guard-seen.json`, `extraction-asked.json` and
`compaction-marker.json`, and the last of these already stores a commit per
session.

**Options**

- **A. Per-session baseline (the report's idea).**
  - SessionStart records the full sha of HEAD and a timestamp under
    `private/session-baseline.json`, keyed by `session_id`.
  - Stop counts `baseline..HEAD`.
  - A Stop with no baseline (SessionStart hook not installed, or a session
    started before the upgrade) records one silently and does not block.
- **B. A plus filters.**
  - Drop commits that touch only `.project-memory/` (`git log -- . ':!.project-memory'`).
  - If HEAD is not a descendant of the baseline (a checkout or reset),
    re-baseline silently.
  - Compare full shas.
- **C. B plus an author filter.** Count only commits whose author email
  matches `git config user.email` and whose author date is after the session
  started.
  - This excludes a fast-forward `git pull` of other people's work.
  - Downside: cloud sessions often share one identity across many sessions,
    so this only partly helps there, and a rebase rewrites dates.

**Recommendation: B**, with C's author-date filter applied only to commits
that arrived by fast-forward (HEAD jumped more than one commit between two
firings without any tool call in between). If that proves fiddly, ship B and
note the pull case.

Install note: only the session, guard and capture hooks are installed in
DoWhat. A baseline written by SessionStart works there; the silent fallback
covers the case where SessionStart is missing.

**Tests that fail today**

- A capture by session "OTHER", then 7 commits, then
  SessionStart(session_id="NEW"), then Stop("NEW"): expect `{}`.
- A snapshot, then a commit touching only `.project-memory/`, then Stop:
  expect `{}`.
- A record on `feature`, then `git checkout main`, then Stop: expect `{}`.
- In a real session, commit, then Stop: expect a block that lists exactly
  that one commit. This is the existing
  `test_new_commits_block_once_with_a_concrete_instruction`, re-pointed at the
  baseline.

**Schema.** No bump. The new state file lives in `private/` (local,
gitignored).

### 3. A nag at the end of every turn

**Confirmed.** It reproduced four ways:

1. The snapshot raises. The exception is swallowed (`cli.py:13476-13480`),
   and the log still says `snapshot: True`.
2. `cmd_capture_session` returns non-zero without raising. The return code
   is ignored (`cli.py:13478`).
3. The store lock is held for more than 0.5 s during the continuation. The
   whole handler is skipped and logged as `locked`.
4. The new snapshot is not the "newest" record: another machine's record
   with a later clock, or a same-second tie broken alphabetically by title.

In all four, the next turn computes the same commit list and blocks again.
`stop_hook_active` only prevents two blocks in a row within one stop cycle.
`extraction-asked.json` remembers jot ids only, never commits.

**Root cause.** The only memory of "already asked" is the newest session
record's `commit`. Asking writes nothing of its own.

**Options**

- **A. A per-session "asked at HEAD X" marker.** Block at most once per
  `(session_id, HEAD)`.
- **B. Fold it into #2's cursor.** After the hook asks once, advance the
  session's baseline to HEAD, *whether or not the capture succeeded*. The
  question is then "commits since I last asked", which can never repeat.
- **C. Keep today's design but make the snapshot failure loud.** Log it, and
  retry it next turn instead of re-blocking.

**Recommendation: B + C.**

- The cursor guarantees at most one ask per batch of new commits.
- Failures become visible:
  - `_hook_capture_snapshot` returns a status;
  - the hook log records `snapshot: failed (<reason>)`, never `True`;
  - `doctor --hook-log` counts snapshot failures.
- Also fix the related problems:
  - **N5:** compare capped with capped in `_hook_capture_is_redundant`.
  - **N6:** log `IncompatibleStore` as `incompatible`, not `locked`, and have
    SessionStart's packet say so once.
  - **N8:** compare full shas.

**Tests that fail today**

- Patch `cmd_capture_session` to raise (and, separately, to return 2). Run:
  commit → Stop (block) → Stop(stop_hook_active) → Stop. Expect the last one
  to return `{}`.
- The same sequence with the continuation run inside
  `held_by_another_process(mem)`.
- A record with `created_at` in 2027: after one block and its continuation,
  the next Stop should return `{}`.
- After a failed snapshot, the hook log must not say `snapshot: True`.
- With more than 25 dirty files, the second firing must be redundant.

**Schema.** No bump. The state lives in `private/`.

### 4. `migrate --dry-run` gave a false all-clear

**Confirmed, and wider than reported.**

**Root cause.** The dry run simulates nothing (`migrate.py:530-545`). Its
only check is `legacy_report()` (`migrate.py:424`), which runs `validate` on
the store *as it is now*. At schema 1/2, traps and questions are `## …`
blocks inside one file, not records, so their statuses are never checked:
`_block_status` (`cli.py:6420`) accepts any string.

Step 3 (`_m3_traps_and_questions_as_files` → `blockfiles.migrate_blocks_to_files`)
copies the status verbatim (`blockfiles.py:635`; questions at `:682`),
writes the files without validating them, then validates them all at once
and rolls back on failure (`blockfiles.py:695-711`).

Other values the dry run also passes but the real run rejects (all
reproduced):

- `Status: superseded` with no superseded-by line;
- `Last confirmed: last tuesday`;
- a `Superseded by:` that names a missing record;
- a question with `Status: resolved`.

The policy is also inconsistent. An invalid status on a *decision* is
"left for you to fix" and the migration goes ahead. On a *trap* it stops the
migration.

Before the migration, those `fixed` / `resolved` traps were already hidden:
`active_traps` keeps only `active`. Mapping them to `stale` therefore
preserves exactly what readers already did.

There is a working manual fix the error never mentions: at schema 2,
`crumb mark-status trap_x stale --reason …` edits the block, and the re-run
then resumes cleanly.

**Options**

- **A. Real dry run.** Copy the store to a temporary directory, run every
  step there, and report what fails.
  - Most faithful.
  - Downsides: costs a full copy, has the same long-path exposure as #5, and
    is slow on 400+ records on Windows.
- **B. Shared pre-flight per step.** Each step gets a `check(memory_dir)`
  function that parses and validates exactly what it will write, without
  writing anything. The dry run calls every check. **The real step calls the
  same check first**, so the two can't drift apart.
- **C. B plus legacy mapping.** A small table maps legacy status values to
  valid ones:
  - traps: `fixed`, `resolved…`, `done`, `closed` → `stale`;
  - questions: `resolved…`, `done` → `answered`.

  The original line is kept in the record body as
  `- Original status: resolved 2026-09-18 — <paragraph>`, so nothing is lost.

**Recommendation: C (B + mapping).**

- The dry run lists **every** blocker with its file, block id and line
  number, not only the first five (N12).
- It also lists what the mapping would do.
- It says how to fix anything the mapping can't, and names `mark-status`.

Also fix:

- **N2:** a duplicate trap id becomes `<id>-2`, and the rename is reported.
- **N10:** a failed index rebuild reports its error instead of returning
  silently.
- The policy mismatch: invalid statuses on decisions and on traps get the
  same treatment.

**Decided (D2): mapping is on by default.** Readers already treated these
traps as inactive, the backup exists, and the dry run shows every mapping
first.

**Tests that fail today**

- `downgrade_to_schema2(mem)` plus a `- Status: fixed` block, then
  `migrate(dry_run=True)`. Expect a non-empty `blockers` list naming the
  trap id and line (or, with mapping, a `mapped` list), and the CLI output to
  mention it.
- A dry run followed by a real run on the same store: every blocker the real
  run would raise is in the dry run. This is a parity test over a table of
  bad inputs.
- Two blocks with the same id: both bodies end up outside `private/`.
- Twelve bad traps: the dry run names all twelve.

**Schema.** No bump. This changes how the existing steps 1→4 behave, not
the format.

### 5. The migration backup hits Windows MAX_PATH, with an unreadable error

**Confirmed** (reproduced on Linux with an over-long path).

**Root cause.**

- `backup_store` (`migrate.py:234-252`) runs `shutil.copytree` into
  `private/migrations/<15-char stamp>/`, which adds 35 characters to every
  path.
- `shutil.Error` is a subclass of `OSError`, and `migrate()` only catches
  `BackupUnverified`. So the error reaches `main()`, which prints
  `str(exc)`, the raw list of tuples (`cli.py:13969-13973`).
- There is no `\\?\` handling anywhere.
- The 60-character slug cap (`SLUG_MAX_CHARS`, `cli.py:2716`, added in
  0.1.9) applies only when a name is generated, so older long names remain.

Arithmetic: the longest capped record path is 104 characters from the repo
root, and its backup copy is 139. With 259 usable characters, the original
fits when the repo root is ≤154 characters, but the backup only fits when it
is ≤119.

**Options**

- **A. Shorter layout.** `private/m/<stamp>/` saves about 20 characters.
  Cheap, but it only moves the cliff.
- **B. Extended-length paths on Windows.** Pass `\\?\`-prefixed absolute
  paths to the copy, verify and restore steps. This removes the 260 limit
  for crumb's own copies.
  - Upside: Python's file APIs honour the prefix even without the
    `LongPathsEnabled` registry setting.
  - Downside: it needs a Windows CI job to prove it (see
    `trap_linux-cannot-show-a-windows-path-separator-bug`).
- **C. Pre-flight plus a readable error.** Before copying anything:
  - compute the longest destination path;
  - if it would exceed the limit, stop and name the file, its length, and
    the fixes (`git config core.longpaths true`, enable Windows long paths,
    move the checkout, or rename the record).
  - Catch `shutil.Error` and print up to 10 store-relative paths with their
    causes, plus "Nothing was migrated."
  - Delete the partial backup directory (N9).

**Recommendation: B + C now, A optional.**

Also make `--restore` copy into a temporary directory first and swap after,
instead of deleting each store entry before copying the backup back in
(N9).

Later (Release 3):

- A `doctor` check that lists record paths longer than about 200 characters.
- `crumb rename <id> --slug <short>`, which renames the file and updates
  every `superseded_by` / `related` reference that points at it.

**Tests that fail today**

- Patch `shutil.copytree` to raise
  `shutil.Error([(src, dst, "[WinError 3] …")])`. Expect `ok=False`, a
  message naming the store-relative path, the cause and "Nothing was
  migrated"; no `[('` in stderr; no leftover `private/migrations/<stamp>`.
- A unit test that the Windows path helper adds `\\?\` to absolute paths and
  leaves relative paths and UNC paths correct. It runs everywhere; the path
  logic is pure.
- A pre-flight test with the length limit patched to 120 and a deep path:
  expect a refusal before any copy.
- The native Windows job runs a migrate with a root deep enough to need the
  prefix.

**Schema.** No bump.

### 6. The guard hook is too slow to run on every tool call

**Confirmed. The cause is different from what was suspected.**

Measured on Linux with a 400-record store:

| Step | Time |
|---|---|
| bare Python start | 12 ms |
| `import breadcrumbs.cli` | 57 ms |
| hook with the pre-filter verified, read-only command | 85–93 ms |
| full guard | 200–260 ms |
| one Edit where record commits sit on unmerged or squash-merged branches | 477 ms, **127 git subprocesses** |

Schema 1 versus schema 4 makes no material difference.

**Where the time goes**

1. **Per-commit git spawns** (`CommitDistanceIndex.distance_reaches`,
   `cli.py:6282-6292`; `git_commit_distance`, `cli.py:6203-6217`). Any
   record commit that is not on HEAD's history costs 2–3 spawns, memoised
   only within one call. That covers commits from squash-merged cloud
   branches, which is exactly DoWhat's workflow. At ~40 ms per spawn on Git
   for Windows, that is ~5 s, the field p50. (Inferred, not measured on
   Windows.) The existing test
   `test_git_calls_do_not_grow_with_the_record_count` misses this, because
   all its records share one commit.
2. **The index freshness check re-hashes every record** and spawns
   `git check-ignore` (`searchindex._is_fresh`, `searchindex.py:134-145`).
   Staleness then reads every record again: 807 file reads for 400 records.
3. **The branch and default-branch lookups repeat** 3–5 times per firing.
4. **The pre-filter almost never filters.**
   - It escalates on about 80 "class words" (`npm`, `version`, `session`,
     `release`…; `cli.py:13148`).
   - It matches against the *union* of every record's words, not per record
     (`cli.py:12850-12856`). On this repo's own store, 12 of 20 everyday
     commands (`git status`, `git diff`, `cat README.md`…) escalated to full
     guard.
   - "prefilter: unverified" means the machine-local index's fingerprint no
     longer matches the files, which a `git pull`/`checkout` causes. The
     hook then runs full guard rather than risk silence. That is by design
     (`dec_20260927_projections-are-stamped-from-a-verified-snapshot`), but
     nothing re-verifies it until the next crumb write.
5. **There is no early exit for read-only commands** before the store is
   loaded (`_hook_guard`, `cli.py:13127-13155`).

**Options**

- **A. Remove per-commit spawns.**
  - Option A1: treat "commit not in HEAD's history" as "unknown age, no
    decay".
  - Option A2: compute each record's commit distance once at reindex, store
    it in the index, and look it up at guard time.
- **B. Cheap freshness on the hook path.** Use the stat fingerprint the
  pre-filter already computed; reuse the loaded corpus for staleness.
  Memoise branch lookups per process.
- **C. A real pre-filter.**
  - Require at least 2 matching words *in one record*, using the existing
    sqlite postings.
  - Don't escalate on class words alone for commands that are read-only
    after #7's segmentation.
  - Have SessionStart re-verify (reindex) when the pre-filter is
    unverified, so a `git pull` costs one slow firing, not all of them.
- **D. A slim hook entry point** that does not import the 14,000-line
  `cli.py` for the silent path. Start-up on Windows is probably 150–250 ms
  of the budget.

**Recommendation.**

- A2 (or A1 as a stopgap in Release 1, since it is a one-line change), plus
  B and C, in Release 2.
- D only if measurements on Windows after A–C still miss the budget.

**Budget.** Set it as numbers a test can check on any OS, because Linux
wall-clock time can't prove a Windows budget:

- **Silent path** (read-only, or no candidate): at most 1 git spawn, no
  record-file reads, target p50 ≤ 300 ms on Windows.
- **Full guard:** git spawns constant in the record count (≤ 6), each record
  read at most once, target p95 ≤ 1 s on Windows at 400 records.
- `doctor --hook-log` flags p50 over 300 ms and names the slow phase.
- Add phase timings (start-up, load, score, git) to the hook log so the next
  field report can say where the time went.

**Tests that fail today**

- 40 attempts, each with a distinct commit on an unmerged side branch, all
  matching the action. Spawns per `guard()` stay ≤ 6 and do not grow from 3
  records to 40. Today: 11 → 127.
- A natural store, `_prefilter_trap_hit(m, "git status")`: False when no
  single record holds 2 of its words.
- A verified pre-filter and a read-only `git status`: the hook reads zero
  record files (count with a patched `read_text`).
- The `benchmarks/` timing on Linux stays as a trend line, not a gate.

**Schema.** No bump. `GUARD_PREFILTER_FORMAT` and the search-index format
change; both are machine-local and rebuilt automatically.

### 7. The guard warns on almost everything

**Confirmed, all four examples**, plus the safety hole N4.

**Root causes**

- **Compound commands.** `_SHELL_EFFECT_RE` (`cli.py:8458`) gives up the
  read-only claim on any `;`, `&&` or `>`, including `2>/dev/null`.
  `transcript.normalize_command` (`transcript.py:354`) already strips
  `cd x &&` prefixes and pager tails, but guard doesn't use it. In the other
  direction, a single `|` is not checked and only the first word is
  examined, so `find … | xargs rm -rf` counts as read-only (N4).
- **Writes outside the project.** The Claude adapter
  (`adapters/claude.py:95-118`) builds `"edit <path>: <first 400 chars of
  content>"` without checking that the path is inside the project. Bare file
  names then match (`handoff.md` in `~/.claude/.../memory/` matched the
  project's trap), and class words in the content (`schema`, `release`)
  raise the verdict to ASK_HUMAN.
- **Length.** Each shared word adds +1 with no cap and no normalisation
  (`cli.py:9355,9405`). Reproduced: a 100-character commit message scored
  11; a 5,000-character one scored 39 and matched 27–37 words.
- **crumb's own commands.** The `migration` class is
  `{migrate, migration, backfill, schema, reindex, …}` (`cli.py:8892`) and
  is high-impact. `--dry-run` is ignored. `session` is a security word and
  `version` is a dependency word. The classifier reads every word, including
  quoted text (N11).

**Options**

- **Segmenting:**
  - **A.** Split the command into segments on `;`, `&&`, `||`, `|` and
    newlines.
  - Neutral pieces: `cd X`, `2>/dev/null` / `>/dev/null` / `2>&1`, and
    pager or filter tails (`| head`, `| less`, `| grep`, `| wc`).
  - Read-only only if **every** segment is read-only.
  - A pipe into `sh`, `bash`, `xargs <writer>`, `tee`, or `sed -i` /
    `perl -i` is a write.
  - **B.** Adopt a real shell parser (`shlex` plus a small grammar). More
    correct, more code, and still stdlib-only.

  Recommend A, built on `transcript.normalize_command`, so the miner and
  guard agree on what a command is.
- **Outside the project:** a Write/Edit/NotebookEdit whose resolved path is
  outside the project root (and outside any configured extra roots) gets
  `{}`. Bash commands don't have this problem. Alternative: match outside
  paths only by full path, never by bare file name. Recommend silent: the
  store describes this project.
- **Length:**
  - Classify and match on the command, not on heredoc bodies, `-m`/`-F`
    message text or Write content.
  - Cap the keyword contribution (for example at +4).
  - Require 2 *specific* words for any match, as today.

  The alternative, scaling by command length, is harder to explain and
  still lets long text add up. Recommend strip + cap.
- **crumb's own commands:** a table that classifies `crumb <subcommand>`.
  - Read-only: resume, search, show, guard, validate, doctor, audit,
    `migrate --dry-run`, traps, `inbox list`.
  - Memory write: remember, note, verify, capture, jot, reindex,
    mark-status. These never get ASK_HUMAN from class words; they still
    match file-keyed traps (#11).
  - Store-changing: `migrate`, `migrate --restore`, prune. These keep
    today's treatment.

**Recommendation:** all four as described. Together with #8, the target is
that most routine firings on the DoWhat store are silent. Measure it with
the 23 field commands as an eval (below).

**Tests that fail today**

- `_is_read_only_action` is **True** for:
  - `cd src && grep x f`
  - `grep x f 2>/dev/null`
  - `cd a; ls`
  - `git log | head`
- `_is_read_only_action` is **False** for:
  - `ls | xargs rm -rf`
  - `cat x | sh`
  - `ls | tee out`
  - `grep … | sed -i …`
- `crumb guard "find . -name x | xargs rm -rf"` is **not** capped below its
  destructive verdict.
- A hook Write to `~/.claude/projects/x/memory/handoff.md` gives `{}`.
- The same record against a 1-line and a 40-line command with no file or tag
  match gives the same verdict, and the score difference is ≤ the cap.
- `crumb migrate --dry-run`, `crumb reindex` and
  `crumb verify "…reindex…"` against a store with a `migration` tag are not
  ASK_HUMAN.

**Schema.** No bump.

### 8. Ranking: "do not retry" attempts push out the relevant record

**Confirmed, with corrected causes** (see the Corrections table).

**Root causes, all reproduced**

1. **The do-not-retry boost ignores relevance.** The rule is
   `if item["do_not_retry"]: score += 4` (`cli.py:9420`). It applies once
   any single tag or 2 words match, so an unrelated attempt with one shared
   tag scores 9, which is the PAUSE band. That same signal is the only thing
   behind the "blocking" stance and its `[objects]` label (`_match_stance`,
   `cli.py:9689`; renderer at `cli.py:10004`).
2. **Template headings count as matching words.** The word set is built from
   `title + rec.body + tags` (`cli.py:9021`), and the body includes headings
   like `## Why It Failed / Succeeded`.
3. **Traps lose their tags** (N1), and trap scoring ignores tags anyway
   (`cli.py:9146`).
4. **Common words are dropped once they appear in more than a third of
   records** (`cli.py:8282`). `robolectric` crossed that line in a
   robolectric-heavy store, so the trap kept only `keystore`.
5. **`./gradlew` is read as a file path.** Every record mentioning
   `./gradlew` gets the +2 "mention" signal. `_command_tokens` strips the
   leading `.` (`cli.py:9082`), so the exact-command signal can't match
   either. That signal is also computed for traps only.
6. **The prompt hook uses guard's scoring and surfacing rules**
   (`retrieval.prompt_lookup`, `retrieval.py:166-191`). Do-not-retry alone is
   enough to qualify a record for injection.

**Options**

- **A. Gate the boost.** Apply +4, and the blocking stance, only when the
  match has topical evidence: a file, or a tag plus at least one specific
  word, or the title, or an exact command. Otherwise the record ranks as
  ordinary context.
- **B. Weight it.** Scale the boost by how much else matched. More
  tunable, harder to explain in output.
- **C. Separate lanes.** Guard reports at most 2 do-not-retry items, then
  the best other matches. This hides the symptom; ranking is still wrong.

**Recommendation.** A, plus fixes for causes 2–6:

- build the word set from section *contents*, not headings;
- trap and question files keep and score tags;
- a bare `./x` or `x` at the start of a command is a command, not a path;
  normalise `./` in command tokens; compute the exact-command signal for
  attempts too;
- the prompt hook gets its own lookup that ranks by relevance alone, with
  no do-not-retry surfacing rule (`hooks_prompt` keeps the same store
  reads).

**Decided (D3): a built-in floor.** Today the ASK_HUMAN for
`git push --force origin main` comes from irrelevant records; once those stop
matching it would get PROCEED. So keep a small, built-in "high-impact action"
floor for force-push to the default branch,
`rm -rf` outside build directories, and `migrate` (not dry-run). It gives
ASK_HUMAN with the text "high-impact action; no project memory about it",
and cites **no** records. Guard then says what it actually knows.

**Evals.** Add `evals/suites/android/` built from the field cases:

- five unrelated do-not-retry attempts, some tagged `robolectric` / `git`;
- a robolectric trap promoted from a jot with tags;
- the gradlew attempt;
- more than 12 decisions.

The tasks:

- the robolectric prompt and guard phrasing → expect the trap; reject the
  artwork, Room and test-results attempts;
- `./gradlew --stop` → the gradlew attempt, ASK_HUMAN;
- `git status` → no `[objects]` rows;
- `git push --force origin main` → no irrelevant citations;
- keep, as regressions: `rm -rf app/build/test-results` finds the right
  attempt; `deploy firestore rules to production` finds the TTL trap.
- A critical-case `delivered` check for the trap via the prompt hook.

**Tests that fail today**

- `inbox promote <jot> trap --tags robolectric`: the trap file's `tags`
  contains `robolectric`, and `search tag:robolectric` finds it.
- An attempt with only template sections searched with
  `"why is X failing"`: no match. Today it scores 7 on `fail`, `why`.
- `guard "./gradlew --stop"` against a trap titled
  "gradlew --stop kills other daemons": `command` is in its signals.
- An unrelated attempt that shares only one tag and has a do-not-retry line:
  `advisory`, below PAUSE.

**Schema.** No bump. `tags:` already exists in trap and question
frontmatter; it was just always empty. The eval baseline is rewritten once,
for the whole of Release 2.

### 9. "Written on another branch (possibly stale)" on records already merged to main

**Confirmed for guard, search and the prompt hook.** Resume, doctor and
audit are correct.

**Root cause.** Two implementations:

- The staleness warning uses `HeadTree` (`cli.py:6639`). It asks: is this
  file in HEAD's tree and clean? That is right for merge, squash, rebase and
  rename.
- The per-match label (`_score_item`, `cli.py:9443-9453`) compares only the
  record's `branch:` field with the current branch name. It multiplies the
  score by 0.8 and prints the label (`_match_reason`, `cli.py:9508`).

**A worse case.** `scope: branch` records whose branch is merged are treated
as history: excluded from the prompt hook (`retrieval.py:125`) and never live
in guard (`cli.py:9893`). Hook-written jots default to `scope: branch`
(`inbox.py:175`).

The README (`README.md:446-447`) and `docs/cli-spec.md:442` promise the
resume behaviour; `docs/cli-spec.md:736` describes the search label as if
any other branch counted. The docs disagree with each other.

**Options**

- **A.** Build one `HeadTree` per search pass (3 git calls total) and set
  `branch_mismatch` only when the record's file has not reached HEAD.
- **B.** Use `git merge-base --is-ancestor <record commit> HEAD`. Wrong for
  squash merges, which is exactly DoWhat's case.
- **C.** Drop the label entirely.

**Recommendation: A.** Also: once a branch-scoped record's file has reached
HEAD, treat it as project scope (decision **D5**). Fix
`docs/cli-spec.md:736` to match.

**Tests that fail today.** Reuse `_store_committed_on_feature_branch`
(merge and squash variants):

- `guard --json`: the decision has `branch_mismatch: false`, no
  `branch-mismatch` signal, and `score == raw_score`.
- With `--scope branch`, the prompt hook delivers the record.
- `BranchMismatchTests` (uncommitted record) stays green.

**Schema.** No bump.

### 10. Path extraction treats `/dev/null` as a file

**Confirmed.**

**Root cause.** `_is_path_token` (`cli.py:8552-8587`) accepts any lowercase
token with a `/`, and `_norm_files` (`cli.py:8868`) adds its bare name. So:

- `/dev/null` → `null`
- `and/or` → `or`
- `read/write` → `write`
- `ci/cd` → `cd`
- a URL → its last segment

"mentions: CLAUDE.md" came from the first 400 characters of Write content
being added to the action text (`adapters/claude.py:95-118`).

**Options**

- **A.** A deny list: `/dev/*`, `/proc/*`, URLs (`scheme://`), and two
  short words joined by a slash with no extension and no further slash.
- **B.** Require a real path shape: an extension, or ≥2 segments where one
  is a known directory, or a path that exists on disk relative to the root.
  The existence check is cheap, but unreliable for files about to be
  created.

**Recommendation: A, plus** paths are taken only from the command text and
the tool's `file_path`, never from content being written. A bare name in
prose (`CLAUDE.md`) only matches a record that names the same bare file.

**Tests that fail today.** `_is_path_token` is False for:

- `/dev/null`
- `/dev/stderr`
- `and/or`
- `read/write`
- `https://example.com/a`

Also: `guard "grep x app 2>/dev/null"` has no `null` mention. Add these
cases to `PROSE_NOT_PATHS` in `test_guard_precision.py`.

**Schema.** No bump.

### 11. The guard can't connect a command to the files it writes

**Confirmed.** There is no command-to-file map. For Bash, the adapter passes
`files=[]`. File-keyed traps match only paths written literally in the
command.

**Options**

- **A. crumb's own commands only.** A table:
  - `capture session` → `handoff.md`, `handoffs/*`, `current.md`,
    `sessions/`
  - `remember` → `decisions/`, `attempts/`
  - `migrate` → the whole store
  - `init` / `mcp register` → `CLAUDE.md`, `.mcp.json`, `.claude/settings.json`

  These are added as `files` before scoring.
- **B. A plus common tools.** Output targets of `sed -i f`, `tee f`,
  `> f`, `git checkout -- f`, `git rm f`, `mv a b`, `cp a b`. Several are
  already parsed as paths; this would make them "writes" explicitly.
- **C. B plus a user-extensible map** in `manifest.yml`
  (`writes: {"./gradlew clean": ["app/build/"]}`), so a project can teach
  guard its own tools.

**Recommendation.** A in Release 2 (small, and it would have caught the
field incident before the damage). B at the same time if segmenting (#7)
makes it nearly free. C later, only if asked for.

One caveat, from verification: a trap that says "don't hand-edit
`handoff.md`" would now fire on crumb's own sanctioned writer. Mapped writes
should therefore score as a weaker signal ("writes-file", +3) than a literal
file match (+6), and the output should say "this command writes
handoff.md".

**Test that fails today.** A trap whose only key is
`Area / files: .project-memory/handoff.md`, with no shared words. Expect
`guard "crumb capture session --next x"` to match it with a `writes-file`
signal.

**Schema.** No bump. Option C would add an optional manifest key, which
older versions ignore.

### 12. Hand-written records fail validation after migrating, with no assisted repair

**Confirmed, with corrections** (see the Corrections table). The most
important part is N3: invalid records are not just reported as failing, they
are silently dropped or misread.

**Root cause.**

- `validate` (`cli.py:1851`, `2244`) only reports.
- No `repair`, `--fix` or `normalize` exists. `mark-status` and `retitle`
  can repair two fields.
- The migration's own policy is "guessing a free scope would be inventing
  facts" (`migrate.py:424-433`), which is right for scope and outcome. Most
  other fields can be derived honestly.

**What can and can't be derived for a hand-written verification**

| Can be derived honestly | Needs a person |
|---|---|
| id, type and slug (filename) | outcome (a body saying "Fixed" is a hint, not a fact) |
| `created_at` (filename date or the adding commit) | evidence (paths found in the body can be *proposed*) |
| `created_by` / branch / commit (the adding commit) | |
| title (the `# ` heading) | |
| subject (= title) | |
| status `active` | |
| privacy `repo-safe` (it is a committed file) | |
| scope `project` (`breadcrumbs` is not a scope value; the reader already treats it as `project`) | |

**Options**

- **A. `validate --fix`.**
- **B. A separate `crumb repair`.** Dry run by default, `--apply` to write.
- **C. Interactive.** `crumb repair --ask` prompts for each field a person
  must supply. Agents use `--set <id>.outcome=fixed`.

**Recommendation: B + C**, in Release 3.

- `repair` reuses the legacy-status table from #4 (one table, two callers).
- It writes through the normal validated writer.
- It records `repaired_from:` provenance.
- It prints a final "needs a human" list with the exact command for each.
- It never sets outcome or evidence on its own.

Move the visibility half (N3) into Release 1: `resume`'s contract warning
names every record it drops or reads with defaults. A missing verification
outcome renders as "unknown", not "open".

**"Write it later" path for agents without the CLI.**

- Change the template text that invites hand-writing.
- Document one sanctioned drop folder, `.project-memory/inbox/drafts/`.
  Free-form Markdown there is ignored by `validate`.
- `crumb inbox import` turns each draft into a jot, which a person or agent
  then promotes the normal way.

This turns "hand-write a record in the wrong shape" into "leave a note
crumb knows how to adopt".

**Tests that fail today**

- A frontmatter-less verification is not shown as outcome `open`, and it is
  named in the resume contract warning.
- A decision with status `fixed` is named in the warning.
- `crumb repair` on a store with the three field failure kinds:
  - the dry run lists the derived fields;
  - `--apply` makes `validate` pass for the derivable ones;
  - outcome and evidence stay in the "needs a human" list.
- `inbox import` of a draft makes a jot and removes the draft.

**Schema.** No bump. The `repaired_from` key is optional, and older readers
ignore it: `docs/record-schema.md:395` says unknown keys are not an error.

### 13. Smaller issues

**13a. Em dashes print as `�` in Git Bash.** Confirmed by reading the code.

- `configure_output` (`cli.py:126-147`) changes only the error handling,
  not the encoding.
- Under mintty/Git Bash, stdout is a pipe, so Python uses the ANSI code page
  (cp1252), writes the em dash as byte `0x97`, and the UTF-8 terminal shows
  `�`.
- Hook JSON is unaffected: `json.dumps` escapes non-ASCII by default.

Options:

- **A.** On Windows, when stdout is not a real console, reconfigure to
  UTF-8.
- **B.** Always UTF-8 everywhere.
- **C.** Print ASCII `--` instead of `—` in crumb's own text.

Recommendation: **A**. A real Windows console already gets Unicode through
the console API, so it is left alone; B would break `cmd.exe` redirects into
cp1252 tools. Add C for crumb's own headings: `doctor — integration health`
is a decoration and costs nothing to make ASCII.

Test: a fake stream with `encoding="cp1252"`, `isatty()` False and
`os.name` patched to `nt` → after `configure_output`, it encodes `—` as
UTF-8. A console-like stream is left unchanged.

**13b. `uv tool upgrade` on Windows while an MCP server runs.** Not verified
(this needs Windows).

- `crumb mcp register` on Windows already writes `<sys.executable> -m
  breadcrumbs mcp serve` (`cli.py:11170-11212`). Under `uv tool`, that path
  is the tool's virtual-env Python.
- Whether `uv tool upgrade` replaces that `python.exe` (and so hits the same
  lock) is the open question.
- The absolute-path trade-off is already documented in the code as
  deliberate. The report's point stands, though: a committed `.mcp.json`
  holding `C:\Users\me\AppData\…\python.exe` breaks every other machine and
  every teammate.

Options:

- **A.** Keep it, and document the uv case in "Upgrading on Windows"
  (`README.md:1056-1075`).
- **B.** On Windows, register at Claude Code's *local* scope (per user,
  per project, not committed), and keep the committed `.mcp.json` portable
  (`breadcrumbs-mcp`). It needs `claude mcp add --scope local` or writing to
  the user config, and crumb doesn't own that file today.
- **C.** Keep the portable `breadcrumbs-mcp` everywhere, and make upgrades
  safe instead: `crumb upgrade` stops the running crumb MCP servers for this
  user, then runs the right upgrader (pip, pipx or uv).

**Decided (D4): A now, then B.** Documenting first costs nothing. B fixes
the "breaks other machines" problem without giving up upgrade safety. C
means killing processes, which is a bigger trust ask.

Release-gate step: a native Windows run of `uv tool upgrade` with a live
server, before the README claims anything.

**13c. The Stop hook doesn't warn that `--next` replaces Next Action.**
Confirmed (`_extraction_reason`, `cli.py:13352-13417`).

- After #1, this is no longer a hazard.
- Ship new wording in the same release that describes the new behaviour
  ("adds a new Next Action above the earlier ones").
- Update `README.md:1004`, the managed `CLAUDE.md` block, and
  `templates/project-memory/README.md:32` together.

---

## Keep these working (regression list)

Every item below has a test today, or gets one in the release that touches
its area:

| What worked well | Where it's covered | Touched by |
|---|---|---|
| A near-duplicate jot is refused with a clear message; `inbox promote` to a trap is smooth | `test_inbox.py` | N1 (promote now carries tags) |
| `verify --assert` then `--recheck --yes` writes a superseding `fixed` record | `test_verify.py` | #12 (repair must not touch superseded chains) |
| Per-branch handoffs: a capture on a feature branch writes `handoffs/<slug>-<hash>.md`; main keeps `handoff.md` | `test_handoffs.py` | #1: the Next Action log must be per branch handoff too, and `seed_text` must not copy main's log into a new branch |
| Migrate stops cleanly part-way, with a verified backup and resume/restore instructions | `test_migrate.py:130` | #4, #5: the new pre-flight sits *before* this; the mid-run safety stays |
| `doctor` catches a guard matcher that misses PowerShell, NotebookEdit, Task and Agent | `test_doctor.py` | #7 (the outside-project rule must apply to NotebookEdit too) |
| The SessionStart hook and the MCP initialize handshake work once the binary is on PATH | `test_hooks.py`, `test_mcp.py` | #2 (SessionStart gains one state write: it must never fail the hook) |
| The prompt hook stays silent on "ok" (283 ms) | `test_hooks_phase1.py` | #8 (new prompt ranking), #6 (budget) |
| `rm -rf app/build/test-results` finds the right attempt; `deploy firestore rules to production` finds the TTL trap | **new** `evals/suites/android` | #7, #8 |

---

## Plain-language summary of the choices

- **Handoff notes.** Today, ending a session replaces the "what next" note
  outright. As you chose, `--next` will instead add a dated note on top and
  keep everything below it. Only an explicit `--replace` overwrites, and even
  then the old text is saved in the session record. The "recently changed"
  note stops being overwritten by the automatic end-of-turn snapshot, because
  resume already shows recent commits on its own. One question is left
  (D1b): whether to lock out older crumb versions that would still wipe the
  notes.
- **End-of-turn questions.** The hook will remember where *this* session
  started and what it has already asked about. It will ask about a batch of
  commits once, and never about other people's commits or about saving
  memory itself.
- **Migration.** The preview will run the same checks as the real thing and
  list every problem with its file and line. Old status words (`fixed`,
  `resolved`) are translated to `stale`, and the original wording is kept.
  Windows long paths get a check up front and a readable message, and a
  failure leaves nothing half-copied behind.
- **Guard noise and speed.** Guard will understand `cd x && grep …` as
  read-only (and `… | xargs rm` as *not* read-only, which is a safety hole
  today). It will ignore files outside the project, stop scoring long
  commands higher just for being long, and know which of its own commands
  are harmless. Speed comes mainly from not starting dozens of `git`
  processes per check.
- **Ranking.** A "do not retry" record has to actually be about the same
  thing before it can push other results out. Traps keep the tags they were
  given (today those tags are silently thrown away).
- **Repair.** A new `crumb repair` fills in what can be known honestly
  (dates, titles, ids) and asks a person for what can't (did the fix work?
  what's the evidence?).
