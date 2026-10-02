# Fix plan: the DoWhat retest of crumb-kit 0.5.0

Written 2026-10-02 on branch `claude/sharp-hopper-g0wbvw`, at `b250409` (the
v0.5.0 tag, the same code as the PyPI 0.5.0 wheel). The report under review is
the 0.5.0 retest on the DoWhat Android project, after upgrading that project's
store from schema 1 to 4 on Windows 11 under Git Bash.

The 0.4.0 report's plan, `2026-10-01-dowhat-field-report-plan.md`, is the
record of what 0.5.0 changed. This plan does not redo it.

## How the claims were checked

Each claim was read against the code at `b250409` and, where possible,
reproduced.

- **Guard claims.** The `android` eval store was extended with the retest's
  own record shapes (see *Eval cases*) and used as the scratch store:
  - a do-not-retry attempt tagged todo/migration/schema;
  - a decision about `.project-memory` merges tagged crumb/git/memory;
  - Gradle and git attempts that share one tag with half the commands;
  - the e2e-quoting and Remote Config traps behind item 9.
- **Speed.** Profiled in-process: wall time, import time, `git` processes
  started, and records parsed. The 400-record benchmark in `benchmarks/` was
  also run.
- **Stop hook (section F).** Re-run in scratch repos with a bare "origin" and
  a second clone standing in for a cloud session.

Nothing was measured on Windows; Windows costs below are estimates and are
marked as such.

**Verdict.** Every item is real. Three need correcting (table below), and
checking section F found one new problem (F1).

## Corrections to the report

| # | The report said | What the code shows |
|---|---|---|
| 1 | `cut`, `tr`, `sort`, `uniq`, `wc` and `diff` also need adding. | They were already read-only. Only `sed` and `awk` were missing (plus a few others found while checking the list: `tac`, `rev`, `paste`, `comm`, `od`, `xxd`, `strings`, and listing forms of `git branch`/`remote`/`tag`/`stash`/`config`). |
| 10 | Use guard's stricter path extractor. | Repair already uses guard's extractor (`_paths_from_text`). `Asia/Tokyo` is a real path *shape*; there is no stricter extractor to switch to. The fix is the other half of the request: suggest only paths that exist on disk or in HEAD. |
| 14 | A minimum version "won't stop 0.4.x". | 0.4.0 and 0.5.0 already refuse to write a store whose `manifest.yml` lists a `requires:` feature they don't know (`compat.py`, audit WP21). So 0.4.x *can* be stopped today, at the price of stopping 0.5.0 too. Decision D14 uses exactly that as a bridge. |
| 5 | The README says the hook drops repeats. | The repeat filter covers READ_FIRST only, and keys on the action's target plus the exact set of records shown (`_hook_guard`). The same record shown for `git status`, then `cp`, then a README edit is three different keys; a PAUSE or ASK_HUMAN is never filtered. That is why it came back "again and again with changing verdicts". |

| — | 0.5.0 reached PyPI hours after its tag. | They went out together. Run 41 of `release.yml` uploaded the wheel and sdist at 02:30:24–26 UTC on 2026-10-02 and created the tag and GitHub Release at 02:30:28–31 UTC, in the same job, PyPI first. The earlier time on the release page (00:09 UTC) is the merge commit's date, which GitHub shows as the release's creation date. The workflow already does what was asked; nothing to change. |

## New finding

| ID | Finding | Where |
|---|---|---|
| F1 | A `git pull` of a commit another session made **after this session started** (a cloud session working at the same time, then merged) is asked about by the Stop hook as this session's work. The author-time filter only drops commits made *before* the session started. Reproduced with a bare origin and two clones. | `cli._session_commits` |

## Decisions (answered 2026-10-02)

- **D7, speed:** fix in place, then remeasure. No new moving parts: no
  `git` processes on the guard path, fewer firings take the full path, and
  per-phase timings go into the hook log. A slim entry point, a helper
  process or a compiled pre-check waits for Windows numbers.
- **D8, the prefilter:** machine-local. It moves to `index/` (already
  gitignored), and the next reindex deletes the committed
  `generated/guard-prefilter.json`. It is also written compact and stably
  sorted.
- **D14, minimum writer:** the field is `min_crumb_version`. `crumb migrate`
  sets it (it only ever raises it) to the oldest release whose writes this
  build considers safe, `0.5.0`. migrate also adds
  `requires: min-crumb-version`, so 0.4.x and 0.5.0 (which don't know that
  feature) refuse to write until upgraded. Every later build honours the
  version itself.

## Issue by issue

Each item has its cause, the fix, and the test that fails at `b250409` and
passes after.

### A. Guard classification

**1. `sed -n` is not read-only.** Cause: `sed` and `awk` are not in
`shellcmd.READ_ONLY_COMMANDS`, because both can write.
- **Fix:** read their arguments.
  - `sed` is read-only unless it has `-i`/`--in-place`, a `-f` script it
    cannot see, or a `w`/`W`/`e` command or `s///w`/`s///e` flag in its
    script (a small script reader).
  - `awk` is read-only unless it has `-i inplace`, `-f`, `system(`, a
    `print`/`printf` redirect, or a pipe.
  - Add the other plain filters listed in the corrections table.
- **Tests:** `_is_read_only_action` is True for the two field commands, and
  False for `sed -i`, `sed 's/a/b/w out'`, `awk '{print > "f"}'` and
  `awk 'BEGIN{system("rm x")}'`.

**2. A crumb read command piped into a filter is classed by its name.**
Cause: `classify_action` used crumb's own effect table only when *every*
segment was a crumb command.
- **Fix:** classify each segment.
  - A crumb segment counts by its effect.
  - A read-only segment counts for nothing.
  - Only the remaining segments are read for class words.
- **Test:** `crumb migrate --dry-run | sed -n '1,22p'` is `routine_edit`,
  read-only, and not ASK_HUMAN.

**3. High-impact verdicts cite unrelated records.** Cause: `guard` sets
ASK_HUMAN for a high-impact action but keeps every live match.
- **Fix:** for a high-impact action, keep only matches with direct evidence:
  a file, a file the command writes, the exact command, or a topical match
  built from rare words (item 5). Otherwise say "no project memory about it".
- **Tests:**
  - `crumb migrate` on the extended android store cites no Room, Gradle or
    git record.
  - `rm -rf app/build/test-results` still cites the attempt that names that
    directory.

**4. Edits are scored on the prose they write.** Cause: the edit action
`edit <path>: <content>` is matched as one string, so content words score.
- **Fix:** an edit matches on its path, plus the code identifiers in the new
  content when the file is code (`MigrationTestHelper`,
  `inMemoryDatabaseBuilder`). An edit inside `.project-memory/` is a routine
  memory write: path only, capped at READ_FIRST.
- **Test:** an edit of `.project-memory/handoff.md`, or of `tools/run.sh`,
  whose text says "migrated the schema" is not PAUSE and does not cite the
  MigrationV21ToV22Test attempt.

**5. A few records turn up on almost everything.** Three causes, each
reproduced:
- a crumb command's own words (`crumb`, `migrate`, `reindex`) were matched
  against project records;
- a tag shared by many records counted as much as a rare one;
- the hook's repeat filter is narrower than the README suggests (see the
  corrections table).

Fixes:
- **crumb commands match on what they touch, not their words.** They match
  only through the files they write and records that name the exact command.
- **Rarity (IDF).** A tag or word carried by more than 8% of the store (once
  the store has at least 25 records) is *common*. It scores half, and it
  cannot make a match topical, so it can't floor a verdict or make a
  do-not-retry line blocking.
- **Session damping.** The hook shows an advisory record at most once per
  session, unless the action names that record's file or command. A blocking
  record and the high-impact list are never damped.

Tests:
- `git status`, `cp a b` and a README edit do not cite the merge decision.
- On a store where `migration` is common, a "migrated schema" edit is not
  PAUSE.
- In one session, the same advisory record is delivered once across three
  different commands.

**6. A read-only command shows a record as `[objects]`.** Cause: stance is
computed before the read-only cap.
- **Fix:** for a read-only action every match is advisory.
- **Test:** `git status` against a topical do-not-retry git attempt: verdict
  READ_FIRST, stance advisory, no `[objects]` in the human output.

**7. Speed.** Where one firing's time goes, measured on Linux (400-record
benchmark, plus the eval store):

| Phase | Linux | Windows estimate | Notes |
|---|---|---|---|
| Python start | 12 ms | 60–120 ms | The venv `crumb.exe` launcher starts a second process. |
| `import breadcrumbs.cli` | 23–45 ms | 80–150 ms | 15,000 lines; Defender scans each `.pyc` read. |
| Silent path (prefilter + fingerprint) | 35–40 ms | 50–100 ms | Stats every record file. |
| `git` processes, full path | 5 per firing | 5 × 50–80 ms | `rev-parse` ×2, `rev-list`, `symbolic-ref`, `rev-parse --verify`. |
| Scoring, full path (400 records) | ~85 ms | 150–250 ms | ~150 records parsed. |

The field's 24 full-path firings out of 29 explain the 764 ms median: the
full path spends about 300 ms on `git` alone on Windows. The fixes, per
decision D7:
- **No `git` processes on the guard path.**
  - Read the branch, HEAD and the default branch straight from `.git`
    (loose refs and `packed-refs`, worktrees included). Fall back to `git`
    for anything unusual, such as `reftable`.
  - Cache the commit order in `index/` keyed by HEAD's sha, so `rev-list`
    runs once per new HEAD, not once per firing.
- **Fewer full runs.** Items 1, 2, 4 and 5 make most of the field's firings
  silent or prefilter-skipped.
- **Timings in the hook log:** `import_ms`, `git_ms` (and the existing `git`
  count), and `records` parsed. `crumb doctor --hook-log` shows them, so the
  next Windows run says where the time went.

Test: a full guard firing on a store at a stable HEAD starts **0** `git`
processes (it starts 5 today).

### B. The prefilter file

**8. A 476 KB file, one token per line, rewritten on every write.** Cause:
`json.dumps(indent=0)`, and `token_sets` in record-walk order.
- **Fix (D8):** move it to `index/guard-prefilter.json`. Write it compact
  (`separators=(",", ":")`) with every list sorted. The next reindex
  deletes `generated/guard-prefilter.json`.
- **Tests:**
  - After a reindex there is no `generated/guard-prefilter.json`.
  - The new file is one line, and rebuilding with records added in a
    different order gives identical bytes.
  - The hook still uses it (verified).

**9. Words from records copied into a committed file.**
- **Fixes:**
  - `scan-secrets` and `audit` now scan `generated/` (it is committed).
  - The prefilter leaves out secret-shaped and high-entropy tokens. So does
    guard's matching, so the prefilter stays a superset of what guard can
    match.
- **Tests:**
  - A secret in `generated/resume-packet.md` is found by `scan-secrets`.
  - A record holding a high-entropy token puts nothing of it in the
    prefilter.

### C. Repair

**10. Evidence suggestions that are not files.**
- **Fix:** strip trailing punctuation, then suggest only paths that exist in
  the working tree or in HEAD.
- **Test:** a body naming `Asia/Tokyo.`, `APPDATA/npm`,
  `/home/user/android-sdk` and one real file suggests only the real file.

### D. Handoff log

**11. `handoff trim` can't split a hand-kept log.**
- **Fix:** inside `### Earlier, as written`, `trim` and `doctor` treat each
  bold dated lead-in (`**2026-10-01 …**` at the start of a line) as the start
  of an entry.
  - `--split-on REGEX` names another lead-in shape.
  - `--before DATE` moves the entries dated before DATE, instead of keeping
    a count.
  - Bytes are unchanged: kept text stays where it was, and moved text goes
    to the history file verbatim.
- **Test:** a 12-paragraph hand-kept log under `### Earlier, as written`:
  doctor counts 13 entries; `trim --keep 3` moves 10 paragraphs; the kept
  part plus the history file hold every original byte.

### E. Migration and doctor

**12. `migrate` leaves the old template README and `evidence/refs.yml`.**
- **Fix:** after the migration steps (and on a store that is already
  current), compare `README.md` with the hashes of every template README
  crumb-kit has shipped.
  - An unedited one is replaced with the current template.
  - An edited one is kept, with a warning.
  - `evidence/refs.yml` is removed if it is still the untouched scaffold.
    If it was edited, it is kept and named.
  - `--dry-run` lists all of this.
- **Test:** a store with the 0.3.x template README and the scaffold
  `refs.yml`: migrate replaces the README and removes `refs.yml`. With an
  edited README it keeps the README and warns.

**13. doctor points a current store at `crumb migrate`.**
- **Fix:** on a store at the current schema, the `[records]` line points at
  `crumb repair`. Only an older store points at `crumb migrate`.
- **Test:** a schema-4 store with one bad record: the doctor line names
  `crumb repair` and not `crumb migrate`.

**14. No minimum writer version.**
- **Fix (D14):** add `min_crumb_version` to `compat`. A build older than it
  is refused on write (at the store lock, like `requires:`) and warned on
  read, with the reason.
  - `migrate` raises it to `MIN_SAFE_WRITER = "0.5.0"`, never lowers it, and
    adds `requires: min-crumb-version`.
  - `doctor` shows it.
- **Tests:**
  - A store at `min_crumb_version: 99.0` refuses `remember`.
  - A store at `0.5.0` accepts it.
  - migrate sets both fields.
  - A pre-0.6 build (simulated by removing the feature from
    `KNOWN_FEATURES`) refuses.

### F. Not checked in the field

- **Stop hook on Windows.** The logic has no OS-specific parts beyond git
  itself; the new tests drive it end to end with real repos. F1 above is
  fixed: only commits **created in this checkout** count, judged from HEAD's
  reflog (`commit`, `cherry-pick`, `revert`, and rebase picks). A `pull`,
  `merge` or `reset` doesn't count. With no reflog, the author-time filter
  applies as before.
  - Test: a cloud clone pushes during the session; after `git pull` the
    Stop hook says nothing. A local commit is still asked about once.
- **Hook repeat filter per session.** Covered by item 5's damping test. It
  also checks that another session is not damped.

## Eval cases (android suite)

The suite's store gains the retest's records. `tasks.yml` and
`critical/cases.yml` gain the retest's commands:
- `crumb migrate --dry-run | sed -n '1,22p'`;
- `sed -n '867p' file | grep -oiE x`;
- `crumb migrate`, which must cite none of the unrelated records;
- `git status`, which must show nothing as blocking;
- the `.project-memory/handoff.md` edit;
- the `tools/run.sh` edit;
- the protect list.

A new critical check, `guard_cites_none`, fails when guard's matches
include a forbidden id.

## Protect list (unchanged behaviour, each pinned by a test or eval case)

- `capture session --next` on a hand-kept handoff: only the two header lines
  change; the new dated entry goes on top; current.md is untouched.
- The migrate dry run names blocking traps by line; legacy statuses map to
  stale; the placeholder question is skipped.
- Guard:
  - `./gradlew --stop` cites the STOPREQUESTED attempt.
  - `cd app && grep -r Foo . 2>/dev/null | head` is PROCEED.
  - `rm -rf app/src` and `git push --force origin main` are ASK_HUMAN with
    high_impact set.
  - "change the color of the settings button" is PROCEED.
  - `crumb capture session --next …` matches the trap about the files it
    writes.
  - No "written on another branch" label on merged records.
- UTF-8 output under Git Bash.

## Version

Guard verdicts change, the prefilter moves, and `min_crumb_version` is new
store metadata. So this is a minor release: **0.6.0**. `schema_version`
stays 4, and no migration step is added: the template refresh and the
minimum version are applied by `crumb migrate` on a current store too.

## Implementation status (2026-10-02)

Every item and F1 is fixed on `claude/sharp-hopper-g0wbvw`, one commit per
group:

| Items | Commit subject | Tests |
|---|---|---|
| 1–6, eval cases | guard: read sed/awk and crumb pipelines by effect; cite only direct evidence | `tests/test_guard_retest.py`; 14 critical cases and 5 tasks in `evals/` |
| 7 | guard hook: no git processes on the guard path; phase timings in the hook log | `tests/test_gitrefs.py` |
| 8, 9 | guard pre-filter: machine-local in index/, compact and sorted, no secret-shaped tokens | `tests/test_prefilter_retest.py` |
| 10 | repair: suggest only evidence files that exist in the tree or in HEAD | `tests/test_repair.py` `EvidenceSuggestionTests` |
| 11 | handoff trim: split a hand-kept log into entries; --before DATE; --split-on REGEX | `tests/test_rename.py` `HandKeptLogTests` |
| 12–14 | migrate refreshes untouched template files and sets min_crumb_version; doctor points a current store at repair | `tests/test_store_maintenance.py` |
| F1 | Stop hook: count only commits made in this checkout (HEAD's reflog) | `tests/test_hooks.py` `SessionCursorTests` |

**Where the implementation differs from the plan, and why**

- **Common words (item 5)** need a floor of more than 10 records as well as
  8% of the store. With 8% alone, a 38-record eval store treated a tag on 4
  records as common, and the prompt hook lost relevant matches on the webapp
  suite.
- **Common evidence cannot raise a verdict.** A match carried only by common
  tags and words is shown, but its score band is ignored. Without this, two
  common tags still reached READ_FIRST on score, and a class word then
  escalated it.
- **The prompt hook** reads a prompt that *is* a crumb command the way guard
  does. Otherwise `crumb migrate --dry-run` typed as a prompt matched every
  crumb-tagged record.
- **Damping** keeps 0.5.0's per-target repeat filter and adds per-record
  delivery state to the same per-session file (`private/hook-guard-seen.json`).

**Not verified on Windows.** These were tested on Linux, with real git repos
and the same code paths:

- the `.git` reader on Git for Windows checkouts (`core.autocrlf`, a
  `gitdir:` worktree);
- the Stop hook's reflog reading;
- the new `import_ms` / `git_ms` numbers.

The next Windows session's `crumb doctor --hook-log` shows the phase medians,
which settles decision D7's "then remeasure".

