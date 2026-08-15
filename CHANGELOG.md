# Changelog

All notable changes to **crumb-kit** (the `breadcrumbs` package) are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/), and the project
uses semantic versioning. The package version is independent of the on-disk record
`schema_version` (still `1`); `crumb --version` prints both.

## [Unreleased]

Triage of the 0.1.10 production field test (a full working session in a real
Android repo, 83-session store). The headline from that test — the agent-driven
hooks pivot — worked and is untouched; everything here is tuning the signal
quality around it. The guard was the uninstall risk: a ~1-in-30 relevance rate
trains an agent to ignore the one warning that matters.

### Added

- **`crumb prune sessions` (P1-9).** The Stop hook snapshots eagerly — right
  for capture (an interrupted session with dirty files is exactly the handoff
  worth keeping), wrong for retention: the field-test store held 83 session
  files against 17 durable records, and `audit` could only complain about
  bloat the tool itself created. `prune sessions` deletes machine snapshots
  (placeholder Next Action) beyond the newest `--keep N` (default 20); a
  session a human gave a real Next Action is never a candidate. `--dry-run`
  lists; deletions reindex the projections. `audit`'s bloat note now points
  here.

### Fixed

- **`audit`'s instruction-like detector learned tense (P2-11).** "E2E has
  never run in production" is a fact; "never run the migration by hand" is an
  instruction. An auxiliary (`has/have/had/is/are/was/were/been`) before
  "never/always run" now suppresses the flag — the field test's 7 warnings
  were 7 false positives on exactly this pattern.
- **`init` reports what actually happened (P2-12).** Each adapter/MCP target
  prints `(updated)` or `(already current)`; it no longer claims
  `adapter signpost -> CLAUDE.md` while leaving CLAUDE.md byte-identical.
  `--json` carries `adapter_states` / `mcp_state`.
- **`.mcp.json` entries breadcrumbs does not own stay byte-identical (P2-13).**
  Registering the server splices its own key in (verified by re-parse) instead
  of round-tripping the whole file through the serializer; a semantically
  unchanged merge writes nothing at all. No more collapsing another server's
  one-line `args` array.
- **`doctor` can be all-green immediately after `init` (P2-14).** `init` now
  builds the `generated/` projections (resume packet + guard prefilter) in both
  the fresh-store and integrations-only paths.
- **Empty record sections are omitted, not stubbed (P2-10).** The field test's
  most valuable record had 4 of 7 sections reading `_(not recorded)_`, burying
  the one section that carried the un-rediscoverable value. `schema --template`
  still shows the full skeleton; the stored record only says what was recorded.
- **Truncated slugs no longer end on function words (P2-15).**
  `…-is-nullable-with-no` now truncates to `…-is-nullable`; an author's own
  short title ("say-no") is never rewritten.

### Docs

- The `breadcrumbsHook` marker key — an extension key inside Claude Code's
  hook schema — is now documented as a deliberate choice with its failure
  story and migration path (P3-16), instead of being an unexplained surprise.

### Changed

- **The extraction turn no longer claims authorship it can't verify (P1-7).**
  Its commit range is HEAD-based, and the workspace may be shared with other
  terminals and agents — so the prompt now says "N commit(s) *landed* since
  the last recorded session (this turn's work, or another actor's)" and scopes
  the instruction to the session's own work ("skip commits you did not make"),
  instead of asserting "this turn produced" someone else's commits.
- **The resume packet's focus claims are now falsifiable (P1-5).** The
  staleness system measured record age and commit distance — structurally true,
  semantically blind: the field-test packet told a fresh session to redo two
  work items that had already landed, while its own Verifications section
  listed one of them as fixed. Two deterministic checks close the gap: the
  packet lists the commit subjects landed since the handoff was written
  (`commits_since_handoff`, rendered as *Landed Since The Handoff Was
  Written*), and a **fixed** verification whose subject overlaps the Current
  Focus / Next Action claims adds a warn-only `possible drift:` line. The
  extraction prompt now asks for a commit sha or file in `--next` so the claim
  stays checkable.
- **Current Focus no longer mirrors Next Action (P1-6).** `capture session`
  without `--focus` used to copy the Next Action text into Current Focus —
  ~2,800 characters of packet spent printing one field twice. An unset focus
  now keeps the previous Current Focus, and packets from older stores render
  the verbatim duplicate as `_(same as Next Action)_`.
- **Guard verdict floors need author-curated specificity (P0-2).** A
  keyword-only trap match no longer floors `READ_FIRST` unconditionally — it
  needs a file or tag signal, like decisions and verifications always did, and
  keyword-only matches of any kind escalate only through the score bands. In
  the field test the old floor made one WorkManager trap fire on all 13 edits
  of the session, across files that never touch WorkManager.
- **Corpus-ubiquitous tokens stop counting as signal (P0-2c).** Once a store
  holds ≥ 8 searchable items, a stem present in more than a third of them
  (package prefixes shed by cited file paths — "com", "kt" —, the project's own
  domain noun) carries zero keyword weight and no gate credit in both `guard`
  and `search`. File and tag matches are exempt: author-curated, deliberate
  signal.
- **`crumb guard` exits with a verdict-mapped code (P0-1):** `PROCEED` 0,
  `READ_FIRST` 10, `PAUSE` 15, `ASK_HUMAN` 20 — so "block only on ASK_HUMAN"
  is scriptable and no verdict can be mistaken for a crash. `2` stays the
  usage-error code; the hook path still always exits 0.
- **Guard staleness is risks-only (P0-4).** The per-action path now carries
  only abnormal states (cold handoff, detached HEAD, branch mismatch). The
  routine store facts that used to repeat verbatim on every call — fresh
  handoff age, low-confidence and other-branch record lists — live in
  `resume`/`doctor`/`audit`, which are read once per session.
- **`search` shares guard's keyword floor (P1-8).** A pure-text match needs
  the same shared-specific-token minimum (relaxed to the query's own length so
  one-word lookups still work), so a weak query returns an honest zero instead
  of five records that share the bare token "version".
- **Hook edits carry content and advisories dedupe (P0-3, P0-2b).** The
  `PreToolUse` guard action for an edit now includes a bounded snippet of the
  new content — successive edits of one file stop producing byte-identical
  guard output, and content-shaped traps can match. A `READ_FIRST` for the
  same file + same records fires once per host session
  (`private/hook-guard-seen.json`, machine-local, bounded); `PAUSE` and
  `ASK_HUMAN` are never deduplicated.

## [0.1.10] — 2026-08-15

The release that closes the authorship gap. Through 0.1.9 the store's most
valuable records — decisions, failed attempts, do-not-retry conditions — were
entirely hand-written, so the whole value of the tool rested on a human
remembering to run `crumb remember`. This release makes the **agent** the
author: the `Stop` hook asks for the records at the one moment the model still
holds the session's reasoning, and completing the ask is what dismisses it.
Two matching fixes make what gets written actually reachable — the hook
pre-filter now sees the files a record names via `--evidence file`, and
`guard`/`search` match across word forms, so a later session that says
"reconciliation" still finds the attempt that says "reconciler". Upgrading
invalidates stored `inputs_hash` projection stamps once; `crumb reindex`
clears it. Existing hook installs pick up the extraction prompt automatically
— set `extraction_prompt: false` in `manifest.yml` to opt out.

### Added

- **The Stop hook makes the agent the memory author (the extraction turn).**
  The store's most valuable records — decisions, failed attempts, do-not-retry
  conditions — were 100% manual: auto-capture only ever wrote git snapshots, so
  the whole payload depended on a human (or a standing signpost the agent read
  hundreds of turns ago) remembering to run `crumb remember`. That is the
  discipline tax that kills tools of this shape. Now, when the ending turn
  produced **new commits** since the last session record, `crumb hook capture`
  holds the stop once (`decision: block`) and hands the agent a concrete
  instruction: record any durable decision / failed attempt / verification from
  this session, mark any record the session contradicted, then
  `crumb capture session --next "…"` — which is also exactly what clears the
  prompt, so completing the instruction and moving on are the same act. The
  request lands while the model still holds the session's "why".
  Proportionality keeps it quiet: edit-only and no-change turns never prompt; a
  `stop_hook_active` continuation is never held again (if the agent ignored the
  instruction, the machine snapshot is the floor — behavior never drops below
  what 0.1.9 did); the first firing in a store takes a silent baseline rather
  than interrogating the agent about pre-existing history; and the commit
  listing in the prompt is bounded. Per-project kill switch:
  `extraction_prompt: false` in `manifest.yml` (absent = on, so existing stores
  get the behavior on upgrade — this line is the notice).

- **`guard`/`search` match morphological variants of the recorded words.**
  Matching was exact-token set intersection, which missed the main case the
  tool exists for: a *different* session phrases the same intent differently.
  "Group reconciliation writes into batches" scored zero shared keywords
  against an attempt titled "Batched the billing reconciler writes" — a
  recorded do-not-retry, invisible to the exact phrasing that repeats it.
  Query and record tokens (and tags) are now folded by a small deterministic
  suffix-stripper — every rule a plain strip applied longest-first to a
  fixpoint, so whole families (reconciliation/reconciler/reconciling,
  batch/batched/batching, migrations/migrate) land on one stem — plus a
  deliberately tiny alias table for abbreviations stemming cannot derive
  (authentication/authorization→auth, configuration→config, database→db,
  repository→repo). The fixpoint makes stemming idempotent, which is what lets
  the hook pre-filter re-stem tokens read from an older on-disk
  `guard-prefilter.json` without diverging from freshly written ones. Stop-word
  filtering runs on stems too, so inflections the raw list missed ("changes"
  when the list has "change changed changing") drop out with it. On a 16-case
  paraphrase eval this took guard recall from 9/12 to 11/12 with zero new false
  positives; matched tags still display in their original spelling, and
  `keyword_overlap` in `--json` output now contains stems.

### Fixed

- **The hook pre-filter now sees the files named by `--evidence file`.**
  `crumb guard "edit src/billing.py"` said PAUSE while the `PreToolUse` hook on
  the *identical* Edit stayed silent. `_build_guard_prefilter` scraped paths
  only from prose (trap text, attempt titles, Do Not Retry sections) — never
  from `evidence:` frontmatter, the documented way to attach a file and the one
  the README demonstrates. So a do-not-retry attempt evidencing a
  neutrally-named file (`billing.py`, `reconciler.py`) got no automatic
  protection at all; earlier field tests passed by accident because "auth" in a
  path trips the security keyword classifier. Evidence `file`/`path` refs are
  now unioned into the pre-filter's path index, matching what full scoring
  already read.

- **Bare `--with-adapter` creates `AGENTS.md` on a green-field project.** With
  no guidance file detected it used to resolve to a (reported) no-op — which
  left the one-command wire-up (`init --with-adapter --with-mcp --with-hooks`)
  silently unwired on exactly the projects a set-and-forget install targets.
  The flag *is* the ask for a signpost; `AGENTS.md` is the cross-agent
  standard, so that is the file the fallback creates. Detected files still win,
  naming files explicitly still wins, and the interactive prompt now offers the
  creation instead of skipping it. (`--no-adapter` unchanged.)

- **An auto-derived trap slug shares the record-filename budget.** `crumb note
  trap "<a full sentence>"` slugified the entire text into the id, so every
  downstream mention of the trap (resume packet, guard reasons) carried a
  paragraph-long `trap_…` identifier. Auto-derived slugs are now cut at the
  same 60-character word boundary as record filenames; an explicit `--slug` is
  untouched. Found within minutes of this repo finally dogfooding its own
  store (`.project-memory/` now ships in this repository — see the new
  records for the decisions behind this release).

- The evidence-requirement error no longer reads "a attempt".

## [0.1.9] — 2026-08-06

### Fixed — 2026-08-06 field test, round 2 (verification pass on the same Android repo)

- **Uninstall no longer deletes a hook it cannot prove is ours.** The previous
  release made an unmarked entry removable by matching "names crumb, names a hook event".
  Two problems. First, the event only had to appear on a word boundary, and `-`
  is one — so `.claude/hooks/crumb-session-setup.sh`, a neighbouring script that
  was never breadcrumbs', matched `session` inside its own filename. The event
  must now appear as a whitespace-delimited **argument**, which keeps every real
  launcher (`crumb hook session`, `./crumb-hook.sh guard`) and drops the
  lookalikes. Second, and regardless of how good the heuristic is: deletion is
  irreversible, so `--remove-integrations` now keys on the `breadcrumbsHook`
  marker **alone**. Detection stays heuristic — over-reporting a hook as
  installed costs nothing — but a heuristic match is reported, not destroyed.
  Crucially it is not *ignored* either, which would be the original failure mode
  again: removal names each entry it left behind and says how to finish the job
  (`crumb init --with-hooks` adopts an entry, stamping the marker without
  touching your command, after which removal takes it). `remove_claude_hooks`
  now returns `{"removed": [...], "left": [...]}` instead of a bool; it is always
  truthy, so test `["removed"]`.

- **The guard stopped getting slower every session.** `_score_item` called
  `git_commit_distance` per scored record, and that is three subprocess spawns
  each (`is_git_repo`, `rev-parse --verify`, `rev-list --count`). So the
  `PreToolUse` guard cost ~3 process spawns *per record* and grew monotonically
  with the store — while the `Stop` hook adds a record per qualifying turn. The
  tool was degrading the hot path it had installed: measured at 6.4 ms/record on
  Linux in-process and ~17 ms/record on Windows, with 87% of runtime in
  `fork_exec`/`poll` rather than record I/O. One `rev-list --topo-order` now
  indexes HEAD's ancestry for the whole scoring pass. Topo order shows no parent
  before all its children, so a commit's position in that list is a *guaranteed
  lower bound* on `rev-list --count <sha>..HEAD` — which makes `position >=
  GUARD_STALE_DIST_COMMITS` a sound proof that the record is distance-stale, with
  no git call at all. Only commits positioned *under* the threshold are ambiguous,
  and there are at most `GUARD_STALE_DIST_COMMITS` of those however large the
  store; they still take the exact query. Verdicts are unchanged by construction
  and a test checks the equivalence exhaustively, including across a merge.
  `is_git_repo` is also memoized, keyed on whether `.git` exists so a later `git
  init` re-probes instead of returning a stale answer. Net at 120 records:
  **784 ms → 38 ms, and 360+ git spawns → 6**, with the per-record slope down from
  6.4 ms to 0.29 ms. The remaining cost no longer scales with the store.
- **A session record no longer contradicts its own frontmatter.** The
  diffstat summary describes the *commit range*, so a session whose work was still
  uncommitted — the normal state when a `Stop` hook fires — recorded
  `_(no file changes detected)_` in the body while `dirty_files` listed 25 paths.
  The next agent reads that as "the session did nothing". Files Touched now names
  its scope (`_(no committed changes in this window)_`) and appends the count of
  uncommitted files pointing at `dirty_files`. Count only, never paths: inlining
  them is what §6.1 keeps out of committed records.

### Fixed — 2026-08-06 field test (first real install: an Android repo, 73KB CLAUDE.md, Windows + web containers)

- **Hook identity no longer lives in the command string.** `doctor`,
  `--remove-integrations` and `install_claude_hooks` all recognized our hooks by
  `command.startswith("crumb hook")`, so a hook installed through *any*
  indirection — a wrapper script, a venv path, `python -m breadcrumbs` — was
  invisible to breadcrumbs, and all three failed at once: `doctor` reported "no
  hooks installed" while all three hooks were demonstrably firing; the documented
  clean uninstall silently left them behind, which is the worst of the three
  because the user believes they have reverted; and a later `init --with-hooks`
  appended a **duplicate** that fired alongside the original. Entries are now
  stamped with a `"breadcrumbsHook": "<event>"` key that `doctor` and removal
  match on, so a custom launcher is a supported install path — which matters,
  because the CLI is not always reachable by a bare name. Unstamped entries are still recognized when
  the command names both `crumb` and a hook event, deliberately narrow because a
  false positive here deletes someone else's hook. Removal is now per *entry*:
  a group shared with a foreign hook keeps it and loses only ours.
- **The installed hook command resolves the CLI instead of assuming it.**
  `init --with-hooks` emitted a bare `crumb hook <event>`. In a Claude Code web
  container the CLI is installed into a venv at SessionStart and exported through
  `CLAUDE_ENV_FILE`, which reaches later *tool* calls but not necessarily a
  sibling hook in the same batch; on Windows, a bash spawned from PowerShell
  inherits a PATH without the `pip install --user` Scripts directory. Both print
  `crumb: command not found`, silently, every session. The emitted command now
  tries `$PATH`, the POSIX and Windows `./.venv` layouts, then any interpreter
  that can `import breadcrumbs`. If nothing resolves it exits 0 — but
  `SessionStart` does **not** emit a bare `{}`: an empty object is a valid "no
  opinion" for every event, so a dead install would look healthy forever while
  loading nothing. It returns `additionalContext` saying memory is inactive, where
  to read the packet by hand, and how to fix it. Re-running `init --with-hooks`
  upgrades a bare legacy entry in place; a launcher *you* wrote is never rewritten.
- **The adapter bloat check measures our block, not your instruction file.**
  Both `doctor` and `audit` sized the *entire* adapter file against
  `ADAPTER_BLOAT_CHARS` (4000). `CLAUDE.md` and `AGENTS.md` are the project's own
  agent-instruction files — the reporting repo's is 73,326 chars — so `doctor`
  reported `✗ [adapter] BLOATED` permanently from the moment the signpost was
  installed *correctly*. The check punished the thing it asks for. Both now
  measure only the text between `ADAPTER_BEGIN` and `ADAPTER_END`, which is what
  `adapter_block()`'s docstring always claimed was being checked. A file with no
  managed block is not a signpost and is no longer sized at all; `audit`'s
  `adapter-duplication` check still catches records pasted into one.
- **The signpost no longer tells agents to run an interactive command.**
  The block injected into `CLAUDE.md`/`AGENTS.md` ended with "**Session end:**
  `crumb capture session`" — which prompts for five sections. Under an agent it
  died with `EOFError` *after* printing its full git summary, so it looked like it
  had half-worked; this happened verbatim on first use. The line now names the
  unattended form (`--next` plus `--set "<heading>" "<text>"`, which keeps the git
  prefill that `--fast` discards) and says the `Stop` hook already snapshots
  automatically. The prompts themselves now treat EOF as "no answer" and fall
  through to the normal "a session needs a Next Action" error instead of a
  traceback — `_interactive()` is a heuristic over two `isatty()` calls, and when
  it guesses wrong the command must degrade, not die.
- **Capture no longer attributes months of history to one session.** The
  prefill diffed from the newest session record's commit with no bound, so on a
  store idle for six weeks the first capture claimed ~50 commits and "807 files
  changed, +90962/-14441" as one sitting's work. It self-corrected once
  auto-capture ran — but the wrong number lands on the *first* capture after any
  gap, exactly when someone is deciding whether to trust the tool. The window is
  now capped at 20 commits (falling back to the same bounded recent-history window
  used when there is no prior record), and every prefill states the window and
  diff base it used, so a large number is interpretable rather than merely wrong.

Everything from the 2026-08-04 agent field test (run against a real Android
repo's store plus a 600-record synthetic store): the four high-severity findings
first, then the four remaining ones, plus a red
CI matrix leg found while checking that work landed clean.

### Fixed
- **CI was red on Python 3.14, and had been for several releases.**
  `test (3.14)` and both `mcp (3.14, …)` legs failed while every other Python
  passed. **3.14 colorizes argparse output**, so merely *constructing* a parser
  now reaches `_colorize.can_colorize()` → `os.isatty(sys.stdout.fileno())`.
  One test patches `sys.stdout` with a bare `mock.Mock()`, whose `fileno()`
  returns a Mock, so `os.isatty()` raised `TypeError: 'Mock' object cannot be
  interpreted as an integer` — a defect in the double, not in the CLI: every
  real stream returns an int or raises. The double now raises
  `io.UnsupportedOperation`, which is what a real non-file text stream does and
  which `can_colorize` already catches, falling back to `isatty()`. Three tests
  pin the contract directly so the next stdout double fails with a name that
  says why. This matters beyond a red badge: `mode: publish` requires the `ci`
  workflow to have succeeded on the commit being released, so a red matrix leg
  blocks a release outright — the same class of breakage as an unpinned linter. Also fixed while here: `re.split(r"\s+#", val, 1)` passed `maxsplit`
  positionally, which 3.13+ deprecates and a later Python will reject; the
  suite is now clean under `-W error::DeprecationWarning` on 3.14.
- **A record an agent wrote no longer claims a human wrote it.**
  `derive_fields()` defaulted `agent="human"`, so every write through the CLI
  without an explicit `--agent` was attributed to a person — while the MCP
  surface recorded the *same* write as `agent`. Two surfaces, two answers, and
  in a store whose `confidence` and `review_status` exist to be trust signals,
  "human · high confidence" on a record an LLM asserted is the one claim a
  missing flag must never manufacture. `detect_agent()` now reads the
  environment (`CLAUDECODE`, `CURSOR_AGENT`, `CODEX_SANDBOX`, `GEMINI_CLI`,
  `OPENCODE`, `AIDER_CHAT`) and records the harness it finds; when it finds
  none it records **`unknown`**. A person makes the stronger claim explicitly
  with `--agent human`. The surfaces that already know the writer is a machine —
  the MCP tools, the Stop hook — share the detection but floor at `agent`
  instead of `unknown`, so all three surfaces now name the same harness. No
  fixture or test pinned `agent: human`; committed fixtures are read, not
  regenerated, so they are untouched.
- **A long title no longer produces a path that breaks the clone.**
  `slugify()` had no length cap, so the whole title became the filename under
  `.project-memory/<type>/`. Past roughly 240 characters `remember` failed
  outright — `[Errno 36] File name too long`, straight out of the writer — and
  well before that `<checkout>/.project-memory/<type>/<name>` pushed a Windows
  clone past MAX_PATH (260 characters, absent `core.longpaths`), so a repo that
  had committed one record could not be cloned. Filenames now cap the slug at
  **60 characters**, cut on a word boundary, with `-2`/`-3` collision suffixes
  counted inside the budget. `slugify()` itself stays uncapped — it also names
  known traps and open-question ids, which are not files — and nothing caps on
  *read*, so records already on disk with longer names still load, validate and
  resolve by id. The full text was never in the filename's keeping anyway: it is
  the record's `title`.
- **Startup no longer charges every command for work almost none of them do.**
  The field-test report blamed eager `subprocess`/`shutil`/`hashlib`
  imports; measured, that is less than half of it. `build_parser()` resolved
  `--version` eagerly, which imports `importlib.metadata` and with it `email`,
  `zipfile`, `csv` and `socket` (~24 ms), and it constructed all 17 subparsers
  before argparse had looked at argv (~5 ms). Both were paid by the `hook guard`
  pre-filter that fires on *every* hooked tool call and usually returns `{}`
  without reading a record. Three changes: a lazy `--version` action, a
  compile-on-first-use proxy for the secret-shape and instruction-like pattern
  tables (~21 of the module's top-level `re.compile` calls, needed only by
  `audit`/`scan-secrets`), and per-subcommand parser builders selected by a
  cheap argv pre-scan — with the full parser still built for `--help`, for an
  unrecognised command (so "invalid choice" keeps listing everything), and for
  any caller that asks. Min of 25 interleaved runs on Linux, against a 13.3 ms
  bare-interpreter floor: `import breadcrumbs.cli` 53.3 → 50.3 ms, `crumb --help`
  86.1 → 58.0 ms, `crumb hook guard` **85.9 → 52.4 ms** (−39%, or −46% of the
  work above the floor). `crumb --version` is unchanged by design — it is the one
  command that still has to resolve the version. The report's headline 375 ms was
  Windows process-spawn dominated and does not transfer.
- **Staleness de-weights; it no longer erases.** Guard's branch-mismatch
  (0.8), age (0.7) and commit-distance (0.7) factors compound to 0.39, which
  pushed prose-only records under the noise floor and dropped them with no
  trace — the field test's controlled experiment turned an `ASK_HUMAN` into a
  bare `PROCEED` by re-dating one record 38 days back. A match under the floor
  on its *raw* signal is still noise and still drops; one pushed under it by
  decay is now kept, marked `stale-suppressed`, and demoted to guard's
  `history` list (mention-only, never driving the verdict). Match payloads
  carry a new `raw_score` and `suppressed` alongside `score`.
- **`init` can no longer register MCP without consent.** `_interactive()`
  gated on `sys.stdin.isatty()` alone; under an agent harness whose stdin passes
  `isatty()` while every read hits EOF (and stdout is a pipe), `init` entered the
  interactive picker and the MCP prompt's `[Y/n]` default counted as a yes —
  an unasked `.mcp.json` write, contradicting the README. The gate now requires
  *both* stdin and stdout to be terminals, and EOF at a consent prompt declines
  instead of taking the default — the same class of fix as the earlier
  `KeyboardInterrupt` hardening: a shell that cannot answer answered nothing.

### Added
- **Title matches outweigh body mentions.** A query token that appears
  in a record's own title now scores `GUARD_W_KEYWORD + GUARD_W_TITLE` (2)
  instead of 1 — a title names what the record is about; a body mention can be
  incidental. This is what recovers the field test's GUEST case: the record
  whose title literally named the proposed action scored like a passing
  reference and sat one stale factor from silence. Title tokens are a subset of
  the text bag, so this re-weights existing matches and can never create one
  the anti-noise gate would have rejected.
- **`crumb audit` warns on guard-unreachable records.** An active
  decision/attempt/verification with no `tags` and no file references can only
  surface through generic keyword overlap — the weakest signal, and the first
  one decay pushes under the floor. Audit now emits a warn-severity
  `unreachable` finding naming the record, while the author is still around to
  add tags or file evidence. Warn never changes the exit code (§10 ladder).

### Changed
- **`guard`'s synthesized advice is `recommended_action`, not `next_action`.**
  The key `next_action` meant two unrelated things in two commands.
  In `guard --json` it was advice *this code composes* from the match kinds
  behind the verdict (`_recommended_action`, §11.6) — always a non-empty string,
  and already labelled **"Recommended next action:"** in the human output. In the
  resume packet it is *recorded state*: the `## Next Action` a session handoff
  left behind, which is `""` when nobody set one. The field-test reporter read
  the empty resume value and filed it as "guard returns `null`" — a reasonable
  reading of one name used for two things. Guard's key is renamed; the resume
  packet keeps `next_action`, because that is the name of the record section it
  comes from. **This renames a key in `crumb guard --json` and in the
  `memory_guard_before_action` MCP result** (the same kind of user-visible rename
  as 0.1.8's `stale_days` → `stale_after_days`); nothing consumed the old name
  except this repo's own tests, and `crumb resume --json`, the hook payloads and
  every other command are untouched. `README.md`, `docs/cli-spec.md` and
  `docs/mcp-spec.md` now state the distinction where each field is documented.

## [0.1.8] — 2026-08-02

The first release since 0.1.7, and the one that puts nine review batches
in front of users: every entry below has been sitting in
`[Unreleased]` against a PyPI release that predates all of it. Two changes are
user-visible beyond a bug fix — the resume packet renames a JSON key
(`stale_days` → `stale_after_days`, plus two new measurement fields), and
`init` no longer scaffolds `evidence/refs.yml`. Both are called out where they
appear below. Upgrading also invalidates every stored `inputs_hash` projection
stamp once; run `crumb reindex` and it clears.

### Added
- **`ideas/` records are searchable.** `crumb note idea` has always written
  a real, validated record that nothing loaded, so an idea could only be found by
  opening the directory. `crumb search` (and the `memory_search` MCP tool) now
  include them, and `--type idea` is offered. **They remain invisible to `guard`,
  on purpose:** an idea is a proposal, exempt from the evidence rule, and guard's
  score band does not care what kind of record it is scoring — so a speculative
  note that named the right files would have gated a real edit. The corpus forks by
  who is asking (lookup vs. judging), not by record type, and defaults to the
  narrow one. New **Fixture 12** is the control: its single untried hunch scores
  8.96 against a `READ_FIRST` band of 5 when scored, and `crumb guard` still
  answers `PROCEED` with zero matches.
- **The MCP server supports SDK 2.x as well as 1.x.** See *Fixed* below for
  why this is a fix and not just a feature.
- **The MCP server advertises the package version.**
  On an SDK that allows it (2.x, via the constructor's `version=`), the server
  reports `breadcrumbs <package version>` instead of the SDK's own version.
  Whether to pass it is read from the constructor signature, never guessed: SDK
  1.x has no such parameter and raises `TypeError`, so on 1.x the previous
  behavior stands.

- **A `lint` CI job — the repo had no static analysis of any kind.** No
  ruff, flake8, mypy or formatter config existed and no workflow ran one, so every
  unused import, dead assignment and placeholder f-string was left for a human
  review round to find; this was the sixth such round. CI now runs `ruff check` and
  `ruff format --check`, configured in `pyproject.toml` so a contributor's machine
  behaves identically. `line-length` is 100 to match how the code was already
  written; E501 is deliberately off — the formatter owns layout, and the lines it
  cannot split (long string literals, URLs) are not worth failing CI over. The ten
  findings the first run surfaced are fixed here: two placeholder f-strings, three
  unused imports, five unused assignments. The codebase was formatted with
  `ruff format` in a separate, mechanical commit.
- **Workflow hygiene, with tests.** Neither workflow set a
  **top-level `permissions:`**, so any job without its own ran with the repository
  default token scope; both now floor at `contents: read`. Neither declared a
  **`concurrency`** group: `ci` triggers on both `push` and `pull_request`, so every
  PR ran the full matrix twice, and two simultaneous publish dispatches could both
  clear the pre-flight's PyPI check and race to upload — `ci` now supersedes stale
  runs (never on `main`), and `release` serializes and never cancels, since
  cancelling mid-publish is how a version lands on PyPI with no tag. Every action is
  **pinned to a commit SHA** with its version in a trailing comment; the worst
  offender was `pypa/gh-action-pypi-publish@release/v1`, a moving *branch* on the
  OIDC-publishing path. The `mcp` job now asserts the **8 resources** the README and
  mcp-spec advertise (it pinned 10 tools and 6 prompts but never the resources), and
  the **test matrix** covers 3.9–3.14: 3.10 was previously exercised only by the
  `mcp` job, which runs neither the fixture nor the packaging checks, and 3.13/3.14
  were untested despite an unbounded `requires-python`.
  `tests/test_release_process.py` pins all five so they cannot silently regress.
- **Fixture 11 — multi-machine** (`fixtures/fixture-11-multi-machine/`): the
  multi-developer store the suite had no example of, which is why all five bugs
  above stayed green. `session_tracking: distillate` with no `sessions/` directory,
  a committed packet and guard pre-filter, and an `AGENTS.md` signpost.
  `tests/test_multi_machine.py` checks it out at two different paths and requires
  `validate`, `audit` and `doctor` to come up clean at both, the committed packet
  to be accepted unchanged at either path, and a reindex on either machine to
  reproduce the same bytes.

### Changed
- **The resume packet names its staleness numbers for what they are.** The
  packet carried one number, `stale_days` — which was
  the *threshold* — while the *age* it gets compared against existed only as English
  inside a warning ("handoff is 6 day(s) old"). A consumer had the policy as data
  and the fact as prose. The threshold is now **`stale_after_days`**, and the
  measurements are their own fields: **`handoff_age_days`** and
  **`handoff_commit_distance`** (both `null` when the handoff timestamp is
  unparseable or there is no git repo). The rendered packet names the cutoff above
  the warnings it governs. **This renames a key in `crumb resume --json` and in the
  `memory_build_resume_packet` MCP result**; no code in the repo read the old name.
  `--stale-days` also has one help string across `resume`/`search`/`guard`/`audit`
  instead of being an "aged-unresolved threshold" on two of them and a "recency
  de-weighting threshold" on another — one cutoff, described as one thing.
- **`audit` no longer tells you to wait for a rollup command that does not exist.**
  The sessions-growth note said "consider a periodic rollup (forward-ref
  Phase 10)". Nothing is scheduled to build one, so the advice is now what a human
  can act on today: promote what still matters with `crumb remember`, prune the rest.

- **The tag / PyPI history is documented instead of implied.** The
  intended invariant is one git tag per published PyPI version, and three
  entries break it: `v0.1.5` (tag only, never published), `v0.1.6` (tag **and**
  GitHub Release, never published), and `0.1.2` (**on PyPI, never tagged** — the
  exact shape the pre-flight now recovers from). `pipx install git+…@v0.1.6` therefore yields a
  version PyPI never shipped. `RELEASING.md` now carries a *Tag / PyPI history*
  table recording all three and why `0.1.2` is deliberately left untagged rather
  than hand-tagged; `CLAUDE.md` points at it. The dead tags are left in place —
  deleting them is the maintainer's call — and the release workflow refuses to
  re-use either one.
- **The CLI/MCP fork on an omitted `confidence` is a stated choice, not a lying
  comment.** Non-interactive `crumb remember` exits 2 when there is no
  evidence and no `--confidence`; the identical `memory_record` payload records
  `low`. The `mcp_core` comment claimed exact parity with the CLI, which was false.
  Both behaviors are kept — the CLI's error names the flag a human forgot, while a
  tool call has no such conversation and `low` is precisely what "the caller stated
  no confidence" means — and the divergence is now documented in
  `docs/mcp-spec.md` and described accurately in the code. An *explicit*
  `medium`/`high` without evidence remains an error on both surfaces.
- **The `[mcp]` extra hint names the Python floor.** The extra is marked
  `python_version >= '3.10'`, so `pip install "crumb-kit[mcp]"` succeeds and
  installs **nothing** on 3.9 — and the hint told the user to run exactly that
  command without mentioning it. The message now says the SDK needs Python ≥ 3.10
  and what happens on 3.9.

### Removed
- **`evidence/refs.yml` is no longer scaffolded by `init`.** It was created
  for the whole life of the package and **no released version ever read or wrote
  it**. Nothing replaces it: per-record evidence already lives in each record's
  `evidence:` frontmatter, which `resume` (Likely Relevant Files, Verification
  Commands), `guard` (next-safest-action) and `search` (path matching) all
  consume. A second, hand-maintained copy would have had no validator, no
  consumer, and no way to notice a dangling reference. **Existing stores are
  unaffected** — nothing looks for the file, and you can delete it.

### Fixed
- **A single network blip cost a whole release run, and the build job blamed the
  wrong thing.** The first `publish` run of this version failed at the
  upload step with `ConnectTimeout` on `upload.pypi.org`. Nothing about the
  release was wrong: the suite, the CI gate, the pre-flight (`on_pypi=no
  tag_exists=false`), `twine check` and the installed-binary smoke test had all
  passed, and the failure landed on the action's *first* network call — the
  Trusted-Publishing token exchange, `GET /_/oidc/audience`, made with a hard
  5-second connect timeout and no retry inside the action — so not a byte was
  uploaded and no tag was cut. The publish step now **attempts the upload twice**,
  30 seconds apart; `skip-existing` is what makes that safe, since a re-upload of
  an accepted file is already a no-op (it is the same property the
  published-but-untagged recovery relies on). Only the first attempt is
  `continue-on-error`, so two failures still fail the job with no tag, and
  `RELEASING.md` now names this failure by its traceback. Separately, the build
  job of that run displayed a red **`crumb-kit 0.1.8 is already released`**
  annotation that was flatly false: the release suite runs *inside* the release
  workflow, and a pre-flight unit test called the CLI entry point without
  capturing stdout, so the annotations it printed were read by the runner as the
  step's own. Anyone debugging the failure read that first. The test now captures
  its output, and a source-level check keeps the next one from calling the CLI
  uncaptured.
- **CI's `lint` job was red on an untouched `main`, because ruff was unpinned.**
  The job ran `pip install ruff`, so it silently took whatever was
  newest. ruff **0.16 began formatting fenced Python inside Markdown**, which took
  the checked file set from 29 files to 234 and made `ruff format --check` demand
  a rewrite of a code excerpt inside an **archived review document** — an excerpt
  quoted verbatim from an older `cli.py`, which is the entire reason that document
  is kept. Nobody had changed a line: any commit pushed after that ruff release
  failed. This is not cosmetic, because `mode: publish` requires the `ci` workflow
  to have succeeded on the commit being released, so a floating linter could block
  a release outright. Both the CI job and the `dev` extra now pin `ruff==0.16.1`,
  a test asserts the two pins exist and agree, and `[tool.ruff] extend-exclude`
  keeps the archived review/audit documents out of the formatter's input —
  reformatting a quotation falsifies it. Living prose (README, CHANGELOG, the spec
  docs) stays in scope. Every GitHub Action here has been pinned to a commit SHA
  for exactly this class of failure; the tool that decides pass/fail
  was the one thing left moving.
- **`scan-secrets` missed credentials embedded in a connection string.**
  `postgres://app:<password>@db.example.com/prod`, `mongodb+srv://root:<pw>@…`,
  `redis://:<pw>@…`, `https://user:<token>@host/repo.git` — every form of it reported
  **OK**. Nothing in the covered set could see them: the password follows a bare
  `:` inside a URL, so there is no `password=`-style label for the keyword pattern
  to match, and such passwords are usually too short and too word-like for the
  standalone entropy heuristic. A "how do I run this" note carrying a
  `DATABASE_URL` is among the likeliest secrets to be written into project memory,
  which is precisely what the scanner exists to block. A new
  `url-embedded-credentials` pattern covers it, kept conservative in the module's
  own spirit: a username with no password is not a secret, `$VAR` / `${VAR}` /
  `<placeholder>` interpolations and the obvious doc placeholders are excluded, and
  a six-character floor drops well-known defaults like `amqp://guest:guest@`. The
  pattern was accepted only after a zero-hit sweep of this whole repository, which
  `tests/test_secrets.py` now re-runs as a test. `docs/security.md` §2 records the
  new coverage and the new deliberate gap.
- **`crumb init --with-adapter` could install nothing, silently, while `doctor`
  told you to run it.** In a project with no `AGENTS.md`/`CLAUDE.md`, the
  flag resolved to the *detected* guidance files — an empty list — applied nothing,
  and printed no explanation, while `doctor` reported `✗ [adapter] no
  agent-guidance files detected` and the first-run nudge recommended exactly that
  command. Naming a file was no better: `--with-adapter=CLAUDE.md` was accepted,
  `--print-integrations` promised `adapter signpost -> CLAUDE.md`, and the real run
  skipped it because the file did not exist. An explicitly named adapter file is
  now **created** (a name can only reach the plan by detection, which lists
  existing files, or by being named — so a planned name that is not on disk was
  asked for), including its parent directory for
  `.github/copilot-instructions.md`. A bare `--with-adapter` still invents nothing,
  but now says so and names the fix; `--print-integrations` marks a target as
  `(will be created)`; and `doctor`'s miss message names a command that can
  actually clear it. Removal is unchanged and still reverses a created file's
  block.
- **The `[mcp]` extra was untested on two Pythons it installs on.** The CI
  `mcp` job's matrix stopped at 3.12 while the `test` job already ran to 3.14, the
  extra is marked `python_version >= '3.10'` with no ceiling, and both SDK majors
  declare 3.13/3.14 support — so the SDK-present paths had no coverage on the two
  newest Pythons. The matrix now runs 3.10–3.14 against both majors, and
  `tests/test_release_process.py` pins the range (and the two-major axis) so it
  cannot quietly narrow again. This is the mirror image of the gap closed earlier
  for the `test` job.
- **The documented list of SDK 1.x/2.x differences was incomplete and
  miscategorized.** `docs/mcp-spec.md` said "two differences are visible to
  a caller" and listed `uriTemplate` → `uri_template`, which was simply the one
  attribute the code happened to touch. SDK 2.0 renamed **every** camelCase model
  attribute to snake_case (`Tool.inputSchema`, `Tool.outputSchema`,
  `Resource.mimeType`, `ResourceTemplate.mimeType` as well), so the table read as
  exhaustive when it was not and the next field read would have broken on 2.x. It
  is also not a protocol difference at all: dumping both majors' models shows every
  one of them keeps its camelCase **JSON alias**, so an MCP client sees identical
  bytes and only in-process readers are affected. The doc now says all of that, the
  suite and the CI job read fields through one alias-tolerant accessor instead of a
  per-field fallback, and `tests/test_mcp.py` pins the alias invariant on whichever
  major is installed (CI runs it on both).
- **The optional `[mcp]` extra installed an SDK the server could not import.**
  The extra was declared `mcp>=1.2` with no upper bound. MCP SDK **2.0
  renamed `mcp.server.fastmcp.FastMCP` to `mcp.server.mcpserver.MCPServer`**, so a
  fresh `pip install "crumb-kit[mcp]"` resolved to 2.x, the hardcoded 1.x import
  failed, and the graceful-degradation path reported the SDK as **"not installed —
  run: `pip install 'crumb-kit[mcp]'`"** from `crumb mcp serve`, `crumb mcp doctor`
  and `crumb doctor` — telling you to re-run the command that had just succeeded.
  `mcp_server` now tries both spellings, newest first (verified against real
  installs of mcp 1.29.0 and 2.0.0: 10 tools, 6 prompts and 8 resources register
  identically on both), the extra is bounded `mcp>=1.2,<3`, and the CI `mcp` job
  runs the whole suite plus a live server build against **both** majors. If the SDK
  is present but still unimportable, the import error is now printed alongside the
  install hint. One caller-visible SDK difference:
  `list_resource_templates()` returns `uriTemplate` on 1.x and `uri_template` on
  2.x.
- **The bundled store no longer ships text that promises unbuilt machinery.**
  `index/README.md` described the SQLite FTS / vector index as
  arriving "in a later phase" and "regenerated by a build command (planned)" —
  nothing builds one, and `search` scans the records directly. It now says the
  directory is a reserved, always-gitignored slot with no writer. `generated/README.md`
  advertised a "3k–5k tokens" resume packet; the bound is a 5,000-token ceiling with
  no floor. Both files are copied into every user's repo by `init`, which is why the
  template — not the doc describing it — was the thing to fix.
- **`docs/cli-spec.md` documents `search`.** The command surface spec had no
  row and no section for a command shipped in Phase 5, so `--type`, `--status`,
  `--tag`, `--file` and `--stale-days` were specified nowhere. The new section also
  records the corpus limit the omission hid: `ideas/` and `sessions/` are not
  searchable, so `crumb note idea` writes records `search` cannot find (filed as an
  open item, not fixed here).
- **Doc/code drift across the spec docs.** A sweep of
  every doc against the code it describes: `--version` and `resume --task` missing
  from the CLI spec; two dead "see the Phase 6 doc" cross-references replaced with
  the covered set and the deliberate known gaps of the secret scanner;
  `verification` absent from the architecture taxonomy entirely, and
  `verifications/` absent from the record schema's committed-by-default list;
  `guard-prefilter.json` listed as something `init` creates when the first
  `resume`/`reindex` does; shipped layers still labelled `(Ph8)`/`(Ph9)` as if
  pending; a `RELEASING.md` build step that `cd`s into the package directory where
  the build fails; and two review documents that still read as if nothing had been
  fixed. `README.md` gained an *installed vs. this checkout* note (it said PyPI's
  newest release predated everything here, which this release is what resolves),
  and `CHANGELOG.md` explains the missing 0.1.5 and the never-published 0.1.6 where
  a reader hits them.
- **`git_dirty_files` no longer corrupts the first filename in the most common
  dirty state.** `git status --porcelain` emits a worktree-only
  modification as `" M path"` — a leading space in the status columns — and
  `_git_out`'s whole-output `strip()` ate it on the *first* line, after which
  `line[3:]` chopped three characters off the path: one unstaged edit to
  `tracked.py` produced `['racked.py']`. The mangled path reached every record's
  `dirty_files` frontmatter and fed guard/search file matching. `_git_out` now
  strips only the trailing newline.
- **One undecodable byte no longer defeats the trust primitives.**
  A single invalid UTF-8 byte in committed memory used to make `crumb audit` die
  with a path-less error and emit zero findings, silently exempt the whole file
  from `crumb scan-secrets` (which then reported OK), leave `crumb validate`
  reporting OK, stop projections refreshing while `crumb reindex` printed
  "Reindex failed" with no cause, and abort `crumb resume`. Every memory reader
  now goes through one lenient decode: the readable remainder is still processed,
  and the offending path is named. `scan-secrets` and `audit` **block** with a new
  `unscannable-file` finding instead of failing open, `validate` reports the
  unreadable core file, `resume` carries it as a packet warning, `doctor` reports
  an unreadable adapter, and `reindex` prints the actual cause.
- **A verification can now influence a guard verdict.** A verification
  record carries its outcome (`open`/`regressed`/…) in the item `status` so
  `search --status` filters on what agents care about, but guard's liveness test
  only accepted `"active"` — so *every* verification landed in history and was
  excluded from the verdict. A `regressed` verification on the exact file being
  touched scored 17 (the PAUSE band is 9) and still produced `PROCEED` with
  `matches: []`. Liveness now also accepts a verification whose record is active
  and whose outcome is unsettled (`open`, `regressed`, `inconclusive`, mirroring
  `active_verifications`); a specific match on one floors `READ_FIRST`. Settled
  outcomes (`fixed`, `not_applicable`) stay history, as before.
- **The `PreToolUse` guard hook no longer auto-approves the calls it warns about.**
  For any non-`PROCEED` verdict other than `ASK_HUMAN` the hook emitted
  `permissionDecision: "allow"`, which in the Claude Code hook contract *approves
  the tool call outright* — skipping the permission prompt the user would
  otherwise have seen — and shows its reason only to the user, never to the model.
  So on exactly the actions memory had something to say about, the hook removed a
  safety gate and swallowed the warning. The mapping is now: `PROCEED` → silent,
  `READ_FIRST` → the matched records as `additionalContext` with the normal
  permission flow left untouched, `PAUSE`/`ASK_HUMAN` → `"ask"` with the reason.
  The hook emits neither `allow` nor `deny`: memory informs, it never decides.
- **The `Stop` capture hook no longer floods `sessions/` or clobbers your Next
  Action.** Claude Code's `Stop` fires every time the agent finishes
  responding — every turn, not once per session — and the hook ran a full
  `capture session --fast` each time, producing a run of near-empty session
  records and overwriting `handoff.md`'s Next Action with the stand-in text
  `(session ended; see git log)`, destroying the one field a session record
  requires and `resume` leads with. Three guards now apply: a firing is skipped
  when the HEAD commit and the dirty-file set (the store's own churn excluded) are
  unchanged since the newest session record; the stand-in Next Action is treated
  as placeholder text, so it can never overwrite a real Next Action or Current
  Focus; and the payload's `stop_hook_active` flag is honored.
- **`session_tracking: distillate` no longer makes `validate` fail on every clone,
  permanently.** The projection freshness stamp (`inputs_hash`) hashed
  every record directory including `sessions/` — which that policy *gitignores* —
  while generated projections are committed by default. The committed packet was
  therefore stamped with a value no clone could reproduce, so every teammate's
  `validate` reported `stale projection … Run crumb reindex`, and following that
  advice restamped it with *their* session-less hash and broke the author instead:
  it ping-ponged on every push, forever, from the one check the project asks you to
  believe. The hash now covers only what the store's own policy shares — it skips
  `sessions/` under `distillate`, and skips any record directory the **committed**
  `.gitignore` excludes (machine-local excludes such as `.git/info/exclude` are
  deliberately not consulted, since folding one developer's personal excludes into
  a shared stamp would recreate the same bug). The policy value itself is part of
  the hash, so flipping it invalidates stamps once, deliberately.
- **The committed resume packet no longer embeds the author's absolute host path.**
  `generated/resume-packet.md` is tracked by default and served over
  MCP, and it rendered `**project** — \`/Users/<name>/…\``: every commit published
  the author's local directory layout, a byte-identical clone at a different path
  read as *stale* (`crumb doctor`: ✓ fresh in one checkout, ✗ stale in the copy),
  and two developers rewrote that line against each other on every reindex. The
  packet now records the project path as `.` in both the rendered file and
  `--json`. Packets written by older versions are handled too: the staleness
  comparison ignores the project line.
- **The freshness gate can now see a rename.** `inputs_hash` hashed file
  *contents* only, concatenated without separators, while record identity is
  filename-derived — so renaming `2026-01-01-foo.md` to `2026-02-02-bar.md`
  changed that record's id everywhere in the packet without moving the hash, and
  `validate`/`audit` certified a projection full of ids that no longer exist.
  Moving text between two records was invisible for the same reason. Each file's
  store-relative path and explicit separators are now folded into the hash.
  **This invalidates every existing `inputs_hash` stamp once:** the first
  `validate` or `audit` after upgrading reports a one-time
  `stale projection`/`packet-drift` finding on `generated/*.md`. Run
  `crumb reindex` once and it clears; no record data is affected.
- **`crumb resume` refreshes every projection, atomically.** It wrote
  `generated/resume-packet.md` directly with a plain (non-atomic) `write_text`
  instead of going through the reindex every mutation uses, so
  `generated/guard-prefilter.json` was left unrebuilt — `crumb hook guard` stayed
  blind to a newly recorded trap — while the freshly stamped `inputs_hash` made
  `audit` report zero packet drift, hiding the staleness until the next mutation.
  The store-global write now calls `reindex_projections`, which writes both files
  atomically. `--fast` and `--task` remain print-only.
- **`guard-prefilter.json` now obeys `commit_generated_projections: false`.**
  The local-only branch of the managed `.gitignore` block ignored only
  `generated/*.md`, so the JSON index — rebuilt on every write — stayed tracked and
  churning in a repo whose owner had asked for local-only projections. The branch
  now also ignores `generated/*.json`. The file was undocumented everywhere; it is
  now in the bundled `generated/README.md` table, `docs/record-schema.md` and
  `docs/cli-spec.md`. Existing stores pick the rule up by re-running `crumb init`
  (a tracked `guard-prefilter.json` needs one `git rm --cached`).

- **A partial publish is recoverable by re-run, and the docs say so.**
  The publish job uploads to PyPI first and creates the tag + GitHub Release
  afterwards, so a failure in that last step leaves the version permanently
  published with no tag and no Release — and the build job's pre-flight then
  hard-failed every re-run with "already on PyPI", so the run never reached the
  `skip-existing` upload or the tag step. The only escapes were hand-tagging
  (forbidden) or burning a version, leaving the published one untagged forever;
  `0.1.2` is exactly that state. The pre-flight now blocks on "already on PyPI"
  only when tag `v$VERSION` **also** exists (a finished release). Published but
  untagged is treated as a recovery: the run continues, the upload no-ops, and
  the tag + Release step completes it. The recovery is refused when the version
  is not the newest on PyPI, so it cannot be used to tag today's commit with an
  old version. An existing tag for a version that is *not* on PyPI (a dead tag)
  still stops the run. The rules moved into
  `.github/scripts/release_preflight.py` with unit tests, instead of being
  discovered during a release. The false recovery advice in `RELEASING.md`, the
  workflow header comment and `CLAUDE.md` is corrected.
- **`mode: publish` now runs the test suite and gates on CI.** The
  release workflow ran `twine check`, a bundled-template identity check and a
  two-command installed-binary smoke test, but never the test suite, and had no
  check that `ci` had succeeded on the commit being published — a commit that
  broke the suite could be published permanently. The build job now runs
  `python -m unittest discover -s tests` in **both** modes (stdlib-only, no
  install step), and `publish` additionally requires the `ci` workflow to have
  concluded `success` on the exact commit, so the fixture/guard/MCP checks and
  the Python matrix are covered too. `RELEASING.md`'s claim that dry-run "runs
  every check CI does" is corrected to what it actually runs.

- **`crumb init` validates integration flags before it writes anything.**
  `--with-hooks=bogus` used to reach `_HOOK_SPECS[ev]` and escape as a raw
  `KeyError` traceback — *after* the scaffold had been swapped in and `.gitignore`
  written, leaving a store with no hooks that `init` would then refuse to touch
  again. `--with-adapter=README.md` was worse: it injected the managed signpost
  block into an arbitrary file, and `--remove-integrations` (which knew only the
  canonical guidance filenames) answered "No integrations to remove." and left it
  there — irreversible via the documented path. Both lists are now checked against
  `HOOK_EVENTS` / `ADAPTER_FILENAMES` before a single filesystem mutation, exiting
  2 with a message naming the valid values. For stores already in the bad state,
  `--remove-integrations` now discovers managed blocks in the project root's own
  files, not just the canonical list, and reverses them.
- **`Record.sections` is fence-aware — there is one section splitter now.**
  The earlier fence fix landed in `split_md_ordered`/`split_md_sections` and
  never reached `Record.sections`, a second hand-rolled copy. A body whose fenced
  code block contained `## Next Action` — routine, since `--set 'Commands /
  Verification' …` writes fences — reported a section that does not exist: validate
  §16.10 false-passed a session with no real Next Action, `_decision_rationale` /
  `_attempt_do_not_retry` / `_build_guard_prefilter` read torn sections so guard
  could cite the wrong text, and content after the fake heading vanished from the
  dict view. `Record.sections` now delegates to `split_md_sections`, which also
  merges duplicate headings instead of last-wins.
- **`memory_record` returns the documented error envelope.** It called
  `cli.write_record` bare while every other write path wrapped it, so a newline in
  `title` (and any other value the writer refuses) escaped as a raw `ToolError`
  instead of the `{ok:false, error}` `docs/mcp-spec.md` promises.
- **MCP write tools no longer return absolute host paths.** `mcp_core`
  states the rule at the top of the module — never hand the MCP client an absolute
  host path — and applied it to the missing-store error while every success payload
  did exactly that. `memory_record`, `memory_note`, `memory_verify`,
  `memory_mark_status` and `memory_reindex` now return store-relative paths
  (`decisions/2026-07-24-x.md`), the same form validate/audit/doctor findings use;
  the choice is stated in `docs/mcp-spec.md`. The CLI still prints absolute paths
  for humans.
- **Open-question ids no longer collide on a shared 48-character prefix.**
  Ids were `q:` + the first 48 characters of the slug, so two distinct questions
  ("… to the new **columnar store this quarter**" / "… to the new **row store next
  quarter**") produced one id, and `search`'s by_id map kept only the last — which
  `guard`'s `_next_safest_action` resolves through, silently serving one question's
  advice for another's. A truncated slug now carries a short digest of the full
  question; ids short enough not to be cut are unchanged. `_candidate_items` also
  disambiguates any residual duplicate (traps derive ids from free text too).
- **Interactive `remember` no longer prompts for sections already given.**
  `sections.setdefault(heading, input(...))` evaluated the prompt eagerly, so a
  heading supplied via `--set` was asked for anyway and the answer discarded.
- **`crumb hook` with no subcommand reports usage instead of hanging.**
  It read stdin before validating the event, so from a terminal it blocked until
  EOF and only then printed the usage error.
- **Ctrl+C at an `init` prompt aborts instead of consenting.** `_prompt_yes`
  and `prompt_session_tracking` mapped `KeyboardInterrupt` to the prompt's default,
  and the adapter/MCP prompts default to *yes* — so aborting at "Register the MCP
  server in .mcp.json?" was recorded as consent and went on to edit `.mcp.json`.
  Ctrl+C now aborts the command with exit 130 and a one-line message; `EOFError`
  still takes the default, so piped input behaves exactly as before.
- **A comment-only frontmatter value parses as null.** `_strip_inline_comment`
  requires a space before the `#`, so `superseded_by: # none yet` survived as the
  literal string `"# none yet"` — truthy garbage that satisfied validate §16.6's
  "a superseded record needs a `superseded_by`" check. YAML reads it as null; so
  do we.
- **Filename canonicality rejects impossible dates and stray slug characters.**
  `RECORD_STEM_RE` was `(\d{4})-(\d{2})-(\d{2})-(.+)`, which accepted
  `9999-99-99-My Slug!.md` and derived the id `dec_99999999_My Slug!` — spaces and
  punctuation inside an exact-match key. The date must now be a real calendar date
  and the slug must match the charset `slugify` emits. Writers always produced
  clean names; `validate` §16.4 exists for hand-created files, which is where this
  mattered, and its finding now names the rule.
- **The two projection files nothing ever generated are gone.**
  `generated/stale-report.md` and `generated/memory-index.md` were scaffolded by
  `init` into every store, carried the `GENERATED PROJECTION` marker and a
  "Rebuilt by `crumb audit`" header, and were written by nothing — `stale-report`
  even said "planned, Phase 6", three phases after Phase 6 shipped. Since
  projections are committed by default, every user repo permanently carried two
  files misstating their own provenance. Not one of the eleven fixtures ships
  them, which is the clearest evidence they were never real. Both templates are
  removed, and `docs/record-schema.md` §1/§2 and the bundled `generated/README.md`
  no longer list them. Existing stores can delete both files; nothing reads them.
- **The MCP resource registries are a checked manifest instead of dead code.**
  `STATIC_RESOURCES`/`TEMPLATE_RESOURCES` carried a comment saying the
  server consumed them, and nothing referenced them anywhere. `build_server` binds
  each URI explicitly on purpose, so the registries are kept as the *declared*
  surface — the "8 resources" the README and mcp-spec advertise — the comment now
  says so, and a test pins the bound URIs to the registry keys (read from the AST,
  so it runs without the optional SDK).
- **The missing-store envelope test covers all ten tools.** It listed
  eight; the two it omitted (`memory_verify`, `memory_reindex`) were the only ones
  whose envelope nothing else exercised. The test now enumerates the tools by name
  and fails if `mcp_core` grows one that is not listed. `memory_record`'s explicit
  medium/high-without-evidence branch and the templated resources' unknown-id
  rejection are covered too.
- **Contributor tooling is declared.** `CLAUDE.md` told contributors to run
  `python -m pytest -q` while pytest was declared nowhere — no dev extra, no
  requirements file — and CI ran `unittest discover`. `unittest discover -s tests`
  is now documented as canonical (it needs nothing installed, which is the point of
  a zero-dependency package), a `[dev]` extra declares pytest/ruff/build/twine, and
  `[tool.pytest.ini_options] testpaths` stops a stray root `.pytest_cache`.
- **`import breadcrumbs` no longer imports the CLI.** The module docstring
  said importing the package avoided importing the (heavier) CLI just to read
  `__version__`; the next statement was an unconditional
  `from breadcrumbs.cli import …`, so the claim held only for setuptools' static
  read. The re-exports are lazy now (PEP 562 `__getattr__`), so the docstring is
  true for a real import and `from breadcrumbs import main` still works.
- **Docs corrected where they described something the code does not do.** The
  bundled store README documents
  `verifications/`, the directory `crumb verify` writes to, which it had never
  mentioned. The README's install line no longer calls PyPI "(future)" three weeks
  after 0.1.7 shipped there. `RELEASING.md` Path B scopes its token to
  **`crumb-kit`** (the PyPI project) rather than `breadcrumbs` (the import package),
  and warns that Path B bypasses every guardrail Path A adds.
  `docs/record-schema.md` says `git diff --shortstat` (what capture has used since
  0.1.2), and `docs/cli-spec.md` no longer claims `guard` writes a session note —
  `cmd_guard` performs no writes.
- **The stray review file at the repo root is gone.**
  `crumb-kit-agentic-review-2026-06-26.md.txt` (34 KB, double extension) sat beside
  the package while every other review doc lives in `docs/`; its findings shipped in
  0.1.2/0.1.3, and this repo deletes a review doc once its findings are resolved
  ('s was). The one reference to it now explains where it went.
- **A new fixture was invisible to CI and to half the test suite.** CI
  looped over `fixtures/fixture-0[2-9]-* fixtures/fixture-1[01]-*`, so a twelfth
  fixture would simply not have been globbed — `validate` and `audit` would have
  reported success over eleven of twelve. `tests/test_mcp.py` also kept a second,
  independent hand-maintained copy of the fixture roster. CI now globs
  `fixtures/fixture-*/`, both test modules derive the roster from the directory,
  and `tests/test_fixtures.py` fails if a fixture on disk is not registered.
- **The `init` tree test never checked `verifications/`.** `EXPECTED_TREE`
  listed `decisions/`, `attempts/`, `sessions/` and `ideas/` but not
  `verifications/.gitkeep`, although the template has shipped it since the record
  type landed — so removing it from the scaffold would have gone unnoticed. It is
  listed now, and the tree is additionally compared against the bundled template
  itself, because an inclusion list only catches deletions someone remembered to
  enumerate.
- **A dead "see the Phase 6 doc" pointer survived in the code.** An earlier pass
  replaced that cross-reference in `docs/security.md` and `docs/cli-spec.md` — no
  phase doc has ever existed — but missed the copy above `SECRET_PATTERNS` in
  `cli.py`, which is where someone looking for the scanner's covered set actually
  lands. It now names the real record: the pattern tuple, `docs/security.md` §2,
  and `tests/test_secrets.py`.
- **The two projection-freshness checks are documented as complementary, and
  pinned.** `detect_packet_drift` ("is the stamped inputs hash stale?") and
  `_packet_is_stale` ("would a rebuild produce different bytes?") were read as
  redundant. They are not, in either direction: an edit to a section the *bounded*
  packet never renders invalidates the stamp while the bytes are identical, and a
  change to the **renderer** changes the bytes while no hash over inputs can see
  it. Both cases are now reproduced by `tests/test_audit.py`, with a map of the
  three functions above `_inputs_hash`. No behavior change — this stops a future
  refactor from collapsing them.

## [0.1.7] — 2026-07-02

Release-process hardening. No runtime behavior change; this is the first version
published through the rebuilt release workflow. (Versions 0.1.5 and 0.1.6 were
tagged but never reached PyPI — the release workflow failed to publish them — so
0.1.7 is the next real PyPI release after 0.1.4.)

### Changed
- **Single source of truth for the package version.** `__version__` in
  `breadcrumbs/__init__.py` is now the only place the version is defined.
  `pyproject.toml` reads it via dynamic metadata
  (`[tool.setuptools.dynamic] version = {attr = "breadcrumbs.__version__"}`) and
  `breadcrumbs/cli.py` reads it as its source-checkout fallback, so there is
  nothing to hand-sync and a build can never ship a mislabeled binary.
- **The release workflow now cuts the tag and GitHub Release itself**, on the
  exact commit it builds, after PyPI accepts the upload. Releasing is a
  `workflow_dispatch` with an explicit `dry-run`/`publish` mode; there is no more
  hand-tagging (the recurring cause of failed releases) and no manual Release
  creation. A pre-flight PyPI check fails fast with a plain "already published —
  bump the version" message instead of a cryptic `400 File already exists`.

## [0.1.6] — 2026-07-02

> **Never published to PyPI.** `v0.1.6` was tagged and given a GitHub Release, but
> the upload never happened, so no one can install this version — its changes first
> reached PyPI inside 0.1.7. The entry stays because the work is real and 0.1.7's
> notes assume it.

Resolves the six high-severity findings from the third full-system review and —
in a second pass — all twenty of its medium/low findings, completing the round.

### Added
- **`crumb mark-status <id> <status>` ** — the record lifecycle mutation
  (stale/disputed/superseded/…) as a CLI command; it previously existed only as
  the MCP `memory_mark_status` tool despite README/docs describing the flow.
  `--superseded-by ID` sets the pointer validate requires when superseding
  (mirrored on the MCP tool as a new optional param) — this is the "supersede
  flow" mcp-spec referenced.
- **Trap-token guard pre-filter index ** — reindex now also writes
  `generated/guard-prefilter.json`, a token/path index over known traps and
  do-not-retry attempts. The `PreToolUse` hook consults it (one small-file
  read; still no record walk on the common path), so a trap-shaped but
  routine-looking command (`pytest -n auto`) escalates to full guard scoring —
  the near-miss class that motivated hooks in the first place, previously covered
  only by a hardcoded regex.

### Fixed
- **`capture session` reindexes on write ** — the session-end flow (and the
  `Stop → crumb hook capture` hook) mutates three packet inputs (session record,
  `handoff.md`, `current.md`) but was the one canonical mutation that never
  refreshed the `generated/` projections, so `crumb validate` failed on
  freshness immediately after the documented workflow.
- **Integrations-only `init` on an existing store ** — `crumb init
  --with-adapter/--with-mcp/--with-hooks` against a project that already has a
  store now applies just those integrations and leaves the store untouched;
  previously it errored and steered users toward `--force`, which replaces the
  scaffold and deletes every record. The clobber-guard message now spells out
  that `--force` is destructive.
- **Round-trip-safe frontmatter re-rendering ** — values containing both
  quote kinds are now emitted single-quoted with YAML `''` escaping (and parsed
  back), block lists render both scalar and map items under *any* key (scalar
  `evidence` items no longer crash; list-of-maps under generic keys no longer
  persist as Python `repr` strings), unrepresentable nesting raises instead of
  corrupting, and `set_record_status` refuses to write any rendering the parser
  would read back differently (fail-closed round-trip check).
- **Fence-aware markdown section splitting ** — `## ` lines inside
  ``` / ~~~ code fences are content, not section boundaries, so `capture
  session` no longer structurally corrupts a `handoff.md`/`current.md` whose
  sections contain fenced command output.
- **MCP server on Python 3.10/3.11 ** — tool schemas now use
  `typing_extensions.TypedDict` (with a stdlib fallback for SDK-less installs);
  pydantic rejects `typing.TypedDict` before Python 3.12, so `breadcrumbs-mcp`
  crashed at startup on two of the three advertised Python versions.
- **Release dry-run publishes to TestPyPI ** — `release.yml` now routes
  `workflow_dispatch` to TestPyPI (environment `testpypi`) and only a published
  GitHub release to real PyPI, matching RELEASING.md; previously the documented
  "dry-run" performed an irreversible real publish.
- **Trust loop ** — `_inputs_hash` now covers `manifest.yml` (a packet
  input), so the freshness check can no longer certify a packet built from a
  since-edited manifest; the packet's `warnings` list is capped (20) with an
  omitted-count disclosure and is budget-trimmable *after* every substantive
  section, so the ≤5k-token bound holds even on warning-heavy stores.
- **MCP parity ** — `memory_build_resume_packet(task=…)` passes
  `task` through to the engine (scoped `likely_files`, `starting cold` label —
  identical to `crumb resume --task`) instead of merely echoing it;
  `memory_record` returns the CLI's error for an explicit evidence-less
  medium/high confidence instead of silently downgrading it to low (unstated
  confidence still defaults to low); `crumb mcp serve --project PATH` actually
  serves that project (exports `BREADCRUMBS_PROJECT`) instead of silently
  serving cwd.
- **Hook robustness ** — a truthy non-dict `tool_input` (and a valid but
  non-object JSON stdin payload) degrades to `{}` like every other malformed
  payload instead of crashing with a traceback.
- **Content preservation ** — `update_handoff`/`update_current` keep user
  intro text between the header and the first `## `, and duplicate-heading
  bodies are merged instead of last-wins dropped (shared fence-aware ordered
  splitter).
- **Shallow clones ** — `capture session` diffs from the shallow boundary
  instead of the empty tree, so "Files Touched" no longer claims the entire
  repo in a depth-limited clone.
- **Validate robustness ** — a non-string verification `subject` and
  a non-UTF-8 `handoff.md`/`generated/*.md` are reported as findings instead of
  crashing the trust primitive; session done-markers are word-boundary matched
  ("done" no longer matches "abandoned").
- **CI blindness ** — the test job runs a 3.9/3.11/3.12 matrix (3.9 is the
  documented floor); a new `mcp` job installs the `[mcp]` extra on 3.10–3.12,
  runs the suite (un-skipping the SDK registration test that would have caught
  R5) and asserts the server builds with all 10 tools + 6 prompts; the
  bundled-template guardrail compares the wheel against `git ls-files` identity
  instead of duplicated magic counts. Also repairs the "validate Fixtures 2-10"
  step, red on `main` since the 0.1.4 freshness check landed: fixture-08's
  projection is *deliberately* stale, so that step now asserts the freshness
  failure instead of tripping over it (the unit suite already pinned this).
- **Signal quality ** — template placeholder values in the handoff
  header are treated as absent, so a fresh store no longer warns "branch
  mismatch … '<branch>'" / "timestamp is not parseable" on every resume/guard
  until first capture; `audit` reports the unconditional handoff age/distance
  line as INFO unless it is actually cold (⚠), so a seconds-old store audits
  quietly.
- **Record integrity ** — git's C-quoted porcelain paths
  (spaces/quotes/non-ASCII) are decoded before storage in `dirty_files`;
  recency ordering parses timestamps instead of comparing strings (mixed UTC
  offsets no longer pick the wrong "newest" record); unborn-HEAD repos record
  the real branch name; `load_manifest` no longer truncates values at a bare
  `#`; record/singleton/projection writes go through tmp+rename (no truncated
  files on interruption); a status-change `reason` containing `-->` can no
  longer escape the trailing HTML comment.
- **Note hygiene ** — question/trap text and field values are flattened to
  one line (embedded `\n## …` can no longer forge headings) and comment markers
  are neutralized (a `<!--`/`-->` pair across two traps could comment-join
  everything between them out of every reader); duplicate trap slugs and
  duplicate questions are refused instead of accumulating shadowed blocks; the
  template-placeholder filter matches the exact template lines instead of any
  user line shaped like `_No … yet._`.
- **MCP envelope + docs ** — every tool success now carries `ok`
  (search/guard/packet gained it; `scan_secrets` keeps `clean` alongside);
  the dead `fast` parameter is gone from the packet adapter;
  `breadcrumbs-mcp --help` prints usage instead of silently starting the stdio
  server; mcp-spec's tool table matches reality (incl. `files` on
  `memory_search`).
- **Heuristic coverage ** — the instruction-like scan catches natural
  phrasings ("ignore failing tests", "ignore all prior instructions", "bypass
  the code review"); the secret scan adds `refresh_token`/`private_key`/
  `id_token`/`session_token`/`signing_key` labels, matches JSON-quoted keys,
  and scans `.yaml`/`.json`/`.txt` under memory, not just `.md`/`.yml`.

> **There is no 0.1.5 entry — the version was never released.** `v0.1.5` was tagged
> by hand and never reached PyPI; it has no changes of its own to record. See
> `RELEASING.md` → *Tag / PyPI history* for the full tag/PyPI ledger.

## [0.1.4] — 2026-06-29

Resolves the high-leverage findings from the second full-system review (MCP
integration, write path, cloud portability). The CLI remains the single source of behavior; the MCP layer stays a thin wrapper
over it. The on-disk record `schema_version` is unchanged (still `1`): the new
`verification` records use the same frontmatter contract as existing record types.

### Added
- **`verification` record type (F1)** — a first-class home for "I checked X; here
  is its state", the most common agentic output, which previously had to be
  mis-filed as a decision/attempt. `crumb verify <subject> --status <outcome>
  --method <static|runtime|test> --evidence …` and the `memory_verify` MCP tool.
  The record-level `status` stays the lifecycle value; the finding-about-reality
  lives in an `outcome` field (`fixed|open|regressed|not_applicable|inconclusive`).
  Verifications are searchable (`crumb search --type verification --status open`,
  where `status` filters on the outcome) and surfaced in the resume packet under a
  new **Verifications** section, actionable outcomes first.
- **`crumb reindex` + `memory_reindex` (F2)** — explicit rebuild of the
  `generated/` projections from the canonical records.
- **`crumb mcp doctor` (F11)** — report MCP wiring (the `[mcp]` extra and
  `.mcp.json` registration) from the CLI's own help surface.
- **`crumb resume --task` (F4/F6)** — resume *for a task*: `likely_files` is scoped
  to the records that actually match it (empty + a `starting cold` note when the
  store has nothing), and the requested task is echoed above the last-session
  focus so the two are not conflated.

### Fixed
- **Reindex-on-write (F2)** — every canonical mutation (`remember`, `note`,
  `verify`, `mark-status`, and their MCP equivalents) now refreshes the
  `generated/` projections, so the static snapshots can no longer silently desync
  from the records on the write path.
- **`validate` projection-freshness check (F3)** — `validate` now fails on a
  `generated/` projection whose stamped `inputs_hash` no longer matches the live
  records, with an actionable `Run \`crumb reindex\`` hint. It no longer stays
  green (and thereby *certifies* drift) on a desynced store.

## [0.1.3] — 2026-06-27

Resolves the four issues deferred from the 2026-06-26 full-codebase bug review
(#4). No behavior changes to stored data; the CLI remains the single source of
behavior.

### Fixed
- **Secret scanner** now flags a long hex token when it sits behind a credential
  label (`token:`, `Authorization:` without "Bearer", `X-…-Key:` / `X-…-Token:`
  headers) via a new `labeled-hex-secret` pattern. A bare git sha / `inputs_hash`
  digest stays unflagged, preserving the deliberate false-negative tradeoff (#5).
- **MCP tool inputs** advertise structured schemas instead of opaque `dict`:
  `memory_search` filters and `memory_record` payload are now `TypedDict`s, so the
  derived JSON Schema lists properties and marks `title` required (#6).
- **MCP error contract** unified — every tool returns `{ok: false, error}` when no
  memory store exists (matching `memory_record` / `memory_mark_status`), instead of
  some tools raising `FileNotFoundError`. The message is now project-relative and no
  longer leaks the absolute host path. Resources still raise (the correct MCP
  resource contract) but share the same message (#7).
- **Cleanup batch (#8):** clear "tabs are not allowed" parser error for tab-indented
  frontmatter; removed the `audit` double trailing newline; non-canonical
  frontmatter keys are preserved on a status change; `inputs_hash` is read only from
  the generated source-header (not a stray match in body text); manifest values are
  unquoted; no redundant identity `pass` alongside a duplicate-id fail; future-dated
  handoffs render as a clock-skew note instead of a negative age; the omitted-note
  wording distinguishes a per-section cap from the token budget.

## [0.1.2] — 2026-06-27

Implements the fixes from the 2026-06-26 agentic review. The headline change makes
the memory store get *used* automatically instead of depending on an agent
remembering to invoke the CLI.

### Added
- **`crumb init` bootstrapper** — opt-in integrations that wire the store into your
  agent, each fenced and reversible: inject a signpost block into detected
  agent-guidance files (`CLAUDE.md`/`AGENTS.md`/…), merge a `breadcrumbs` entry into
  `.mcp.json`, and install Claude Code hooks. Flags: `--with-adapter[=files]`,
  `--with-mcp`, `--with-hooks[=session,guard,capture]` (and `--no-*`),
  `--print-integrations` (dry run), `--remove-integrations` (clean reversal). On a
  TTY with none specified, `init` asks once per integration; default non-interactive
  `init` is unchanged and prints a one-line nudge.
- **`crumb doctor`** — reports integration health (adapter block, `.mcp.json`,
  hooks, resume-packet staleness); exits non-zero when a store exists but nothing is
  wired up.
- **`crumb hook session|guard|capture`** — Claude Code hook translators.
  `SessionStart` auto-loads the resume packet; the cost-aware `PreToolUse` guard runs
  a cheap local risk pre-filter (no record I/O on the common path) and surfaces
  matched memory as context but **never denies from memory alone**; `Stop` snapshots
  a session record.
- **`crumb note question|trap|idea`** plus the `memory_note` MCP tool — a
  validate-gated, projection-refreshing write-surface for the three record kinds that
  previously had no writer. Adds the `idea` body-section vocabulary.
- **`crumb schema [--json] [--template]`** — print the record contract (sections,
  vocabularies, rules) or a fill-in `remember` command skeleton, so the contract is
  discoverable without probing `--help`.
- **Named attempt flags** on `remember attempt`: `--problem`, `--tried`, `--result`,
  `--why`, `--do-not-retry`, `--related`.
- **`crumb mcp serve|register`** — surfaces the optional MCP server from the CLI.

### Changed
- `capture session` now records **Files Touched** as a one-line
  `git diff --shortstat` summary (`N files changed, +X/-Y`) instead of inlining the
  full per-file `--stat`. This removes record bloat and the self-inflicted
  high-entropy secret false-positive on path-shaped tokens.
- The secret scanner allowlists path- and CamelCase-identifier-shaped tokens
  (e.g. `MigrationV14ToV15Test`) without lowering the entropy floor; real
  base64/`=`-padded blobs still flag.

## [0.1.1] — 2026-06-26

- Packaging and metadata fixes over 0.1.0 (bundled templates, `twine`-clean
  wheel + sdist, console scripts `crumb` / `breadcrumbs-mcp`).

## [0.1.0] — 2026-06-26

- Initial release: `init`, `validate`, `remember`, `capture session`, `resume`,
  `search`, `guard`, `audit`, `scan-secrets`, and the optional MCP server.
