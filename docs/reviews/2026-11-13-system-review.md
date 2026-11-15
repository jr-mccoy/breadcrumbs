# System review: what needs fixing and what would make breadcrumbs better

Written 2026-11-13 on branch `ccr-5a263b6c-3gtzxn`, against `main` at
`4606001` (crumb-kit 0.6.2, record schema 4). This is a review only: no
product code, test or workflow was changed. The memory store gained this
session's capture and one trap (§1.2), nothing else.

## Summary

The engineering is careful in the places it has been pointed at. The full
suite passes (1,565 tests), concurrent writers do not lose records, crash
recovery works at almost every point, path containment holds, and the
published 0.6.2 artifacts match a local build of the tag.

Four things are broken today and should be fixed before anything else:

1. **CI on `main` has been red since 2026-11-02, so a release cannot be
   published.** The runner image moved and no longer offers Python 3.9 (§1.1).
2. **`crumb rename` deletes the record it is asked to rename**, reports
   "nothing was changed", and leaves nothing to recover (§1.2).
3. **The SessionStart packet is longer than Claude Code's 10,000-character
   limit**, so the host shows the agent a 2,000-character preview. On this
   repo's own store that preview ends inside the second decision (§1.3).
4. **Hooks and the CLI look for the store only in the current directory.**
   Once an agent runs `cd` into a subdirectory, the guard hook returns `{}`
   for every action, including a force-push to `main` (§1.4).

Below those, the review found a group of defects in the safety layer: a way to
forge a review stamp, an MCP write that ignores `propose` mode, common secret
shapes the scanner misses, and ordinary shell spellings the guard reads as
harmless (§2). Then a longer list of wrong-but-contained behaviour (§3, §4).

The larger question is in §5. The project's own benchmark says it has never
measured whether memory changes what an agent does, and this repo's own store
shows the cost of relying on the agent to maintain it: no failed attempts
recorded in 215 commits, a Current Focus four releases old, and no hooks
installed here. `docs/v2-design.md` draws the right conclusion from that. §5
says what to do first and which of the defects below v2 would inherit.

## How this was done

- Ran the canonical suite: `python -m unittest discover -s tests`, 1,565
  tests, 2 skipped, 4 min 19 s, working tree left clean.
- Read the last two scheduled CI runs' job lists and logs through the GitHub
  API.
- Five parallel audits, each reproducing findings in scratch repositories:
  guard and security modules; the write path and crash recovery; hooks and the
  MCP server (against the current Claude Code hooks reference, and a live MCP
  server over stdio with SDK 2.3.0); CI, release, packaging and docs; the read
  path and CLI core.
- I then re-ran the main findings myself. Each finding below is marked:
  - **re-run**: I reproduced it after the audit reported it;
  - **audit**: reproduced once by the audit with commands and output, not
    re-run by me;
  - **read**: from reading code, logs or documentation, not executed.

Not covered: nothing was run on Windows or macOS, and Claude Code itself was
not run. Where a finding depends on host behaviour, it cites the hooks
reference. Line numbers are as of `4606001` and will drift.

Items already in
[`2026-10-02-deferred-health-review.md`](2026-10-02-deferred-health-review.md)
are not repeated here.

---

## 1. Broken today

### 1.1 CI on `main` is red and `mode: publish` is blocked (re-run)

The scheduled `ci` runs of 2026-11-02 and 2026-11-09 failed on the same
commit that passed on 2026-10-26. Job `test (3.9)` fails in `setup-python`:

```text
##[error]The version '3.9' with architecture 'x64' was not found for Ubuntu 26.04.
```

`ubuntu-latest` now resolves to Ubuntu 26.04 (`ci.yml:44`), which has no
Python 3.9 build. Consequences:

- `release.yml:137-153` requires the newest `ci` run on the commit to have
  succeeded, so publishing from `main` stops with "CI concluded 'failure'".
- Every push and pull request now gets a red check, including the one for
  this report.
- Linux 3.9 is untested, so `docs/compatibility-matrix.md:69` and the README
  badge are no longer true.

The workflow pins every action to a commit and pins ruff "because a formatter
is a moving spec"; the runner image was the one input left floating.

**Fix.** Pin the `test` job (at least its 3.9 leg) to `ubuntu-24.04`. The
alternative is to drop 3.9, which reached end of life in October 2025; that
changes `requires-python`, the classifiers and the compatibility table
together and is a decision for the operator.

Seen in the same runs:

- `native (macos-latest, 3.13)` was cancelled after 15 minutes both weeks with
  no steps and no log. The audit found the message "The job was not acquired
  by Runner of type hosted", which is runner capacity, not a repo defect. The
  job has no `timeout-minutes`.
- `actions/checkout` v4.4.0 and `actions/setup-python` v5.6.0 target Node 20
  and are being forced onto Node 24 with a deprecation warning.
- The release gate reads only the newest `ci` run for the commit
  (`per_page=1`), of any event. A later scheduled run can therefore turn an
  already-green commit unpublishable, which is what happened here. Reading the
  newest `push` run would avoid that.

### 1.2 `crumb rename` deletes the record (re-run)

```text
$ crumb remember decision --title "Use Postgres for storage" --set Decision pg \
    --set Rationale r --confidence low
Recorded decision: dec_20261113_use-postgres-for-storage
$ crumb rename dec_20261113_use-postgres-for-storage --slug pg
CRUMB-ERROR: crumb rename: the renamed record failed validation: slug frontmatter
'use-postgres-for-storage' != derived 'pg'; nothing was changed
$ ls -A .project-memory/decisions
.gitkeep
$ crumb recover
recover: no unfinished operations.
```

Two bugs in `breadcrumbs/rename.py:69-86`:

- The rewrite sets `meta["id"]` but not `meta["slug"]`, so the validate gate
  fails for every record that has a `slug:` key. Every record the CLI writes
  has one.
- The old file is removed with a bare `rec.path.unlink()` (line 77) instead of
  `_mutations.delete()`, so the deletion is not journaled and the rollback
  cannot restore it.

An uncommitted record is lost for good. `tests/test_rename.py` passes because
its fixture record is written by hand without a `slug:` key.

**Fix.** Set `meta["slug"]`, delete through `_mutations.delete`, and add a
test that renames a record created by `crumb remember`.

### 1.3 The SessionStart packet exceeds the host's 10,000-character cap (re-run)

The hooks reference says a hook's `additionalContext` is capped at 10,000
characters; a longer value is written to a file and replaced by the path and
"a preview of up to the first 2,000 characters". "Claude can read the file,
but Claude Code doesn't ask it to."

The packet budget is in approximate tokens (`packet.py:33`, 5,000, about
20,000 characters) and `hooks_session.py:182-197` applies no character bound.
On a copy of this repo's store:

```text
$ printf '{"cwd":"%s","session_id":"s-a","source":"startup"}' "$PWD" \
    | crumb hook session | python -c "import json,sys; \
      print(len(json.load(sys.stdin)['hookSpecificOutput']['additionalContext']))"
12317
```

The first 2,000 characters end partway through the second Active Decision.
Failed Attempts, Known Traps, Open Questions and the warnings are not in the
preview. Any store with a few dozen records is in this state.

**Fix.** Give the SessionStart view a hard character budget (about 9,500 with
the preamble), trim with the existing `TRIM_ORDER`, and end with a pointer to
`crumb resume`. The same cap applies to the prompt and guard hooks' context.

### 1.4 The store is found only in the current directory (re-run)

`_hook_root` (`cli.py:9306-9307`) uses the payload's `cwd` and nothing else.
The hooks reference says `cwd` is "the new directory after Claude runs `cd`",
and that `CLAUDE_PROJECT_DIR` holds the project root.

```text
# cwd = project root
{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask", ...
# cwd = <root>/config, CLAUDE_PROJECT_DIR=<root>, same action
{}
```

The session hook returns `{}` the same way, and nothing is written to the hook
log. The CLI has the same gap (`resolve_root`, `cli.py:461-463`):

```text
$ cd breadcrumbs && python ../crumb.py guard "edit cli.py"
CRUMB-ERROR: crumb guard: no .project-memory/ found at .../breadcrumbs. Run `crumb init` first.
```

Following that advice creates a second, nested store. The `.mcp.json` entry
already anchors on `${CLAUDE_PROJECT_DIR:-.}`; hooks and the CLI do not.

**Fix.** One root resolver for CLI, hooks and MCP: `--project`, then
`CLAUDE_PROJECT_DIR`, then `BREADCRUMBS_PROJECT`, then walk up from `cwd` to
the nearest `.project-memory/`, stopping at the git top level.

---

## 2. The safety layer does not hold where it says it does

`docs/security.md` and the admission profiles make specific promises. These
findings are places where a promise is not kept. Guard is advisory by design
("memory informs and never allows or denies"), so its misses are missed
warnings, not a broken sandbox; they are still the product's central feature
failing quietly.

### 2.1 Line-separator characters split frontmatter and can forge a review stamp (re-run in part)

The writer rejects only `\n` and `\r` in a frontmatter value
(`_render_scalar`, `cli.py:2029`). The reader splits with `str.splitlines()`
(`parse_frontmatter`, `cli.py:1263`), which also breaks on U+2028, U+2029,
U+0085, `\x0b`, `\x0c` and `\x1c`–`\x1e`. A value containing one of those
becomes extra frontmatter keys when read back.

I re-ran the core of it: an `--evidence command` ref carrying U+2028 followed
by `review_status: reviewed`, `reviewed_by: …` and `confidence: high` was
accepted, read back with those three values, and passed `crumb validate`.

The audit carried it to the end under `review_profile: team`: with a
`reviewed_hash` computed in a copy of the repo, `crumb promote` wrote the rule
into `CLAUDE.md` where it had been refused before, and
`mcp_core.tool_record` accepted the same smuggled fields that it refuses when
they are sent plainly. `admission.check_write` (`admission.py:186-206`) looks
at top-level payload keys only.

The same mismatch corrupts ordinary records: a title containing U+2028 is
truncated, and a later rewrite turns those characters in the body into
newlines.

**Fix.** Split frontmatter and body on `\n` only (after CRLF normalisation),
and reject the whole `splitlines()` separator set in `_render_scalar`. Apply
`retitle`'s existing round-trip check to every writer.

### 2.2 MCP `memory_note(supersedes=…)` retires a record under `mcp_mode: propose` (re-run)

```text
policy: profile team, mcp_mode propose
tool_mark_status(..., "superseded")   -> {"ok": false, ... "a person does it" ...}
tool_note("trap", ..., supersedes=X)  -> {"ok": true, "id": "trap_gradle-stop-v2", ...}
traps/gradle-stop-hangs.md            -> status: superseded / superseded_by: trap_gradle-stop-v2
```

`tool_note` (`mcp_core.py:788-824`) never calls `_admit(mem,
supersedes=…)`; `tool_record` and `tool_verify` do. `docs/mcp-spec.md:499-501`
and `docs/security.md:208,213` say this is refused. An MCP client can retire
an active trap that drives guard verdicts.

**Fix.** Put the check in `cli.note`, so every transport gets it.

### 2.3 The secret scanner misses the most common shapes (re-run)

A record containing lines of these shapes scans as clean, exit 0 (values were
20–40 random alphanumerics):

```text
export DB_PASSWORD=<value>
POSTGRES_PASSWORD="<value>"
GITHUB_TOKEN=<value>
token: <value>
<a GitLab personal token, glpat- prefix>
AWS_SECRET_ACCESS_KEY=<40-char value>      -> one non-blocking warning only
```

Causes, in `breadcrumbs/secretscan.py:52-61`: the keyword pattern starts with
`\b`, which does not match after `_`, so any `PREFIX_PASSWORD=` form is
skipped; there is no bare `token` keyword; and there is no AWS secret-key
label. `docs/security.md` §2 claims "`secret|token|password=`-style
assignments" and AWS key shapes.

Two related gaps:

- **Files are chosen by extension** (`secretscan.py:241`): `*.md`, `*.yml`,
  `*.yaml`, `*.json`, `*.txt`, case-sensitive. An AWS key id in
  `decisions/note.MD`, `sessions/run.log` or the committed `index/README.md`
  scans as "OK" while `git add -A` stages all three. (re-run)
- **`.crumbignore` can switch the scanner off.** A pattern that matches the
  empty string, such as `EXAMPLE_FIXTURE|`, suppresses every finding and the
  output still says "OK". (re-run) The audit also found that an inline `#`
  truncates a pattern, so `C# sample fixtures` becomes `C` and exempts any
  line containing a capital C. (audit)

The scanner also blocks on ordinary prose (audit): a local development
database URL whose user and password are both `postgres`, pointing at
`localhost` (not quoted here, because this repo's own test refuses
credential-shaped URLs in its tree), and `private_key:
config/keys/deploy_private.pem`. The only way past either is `.crumbignore`.

**Fix.** Replace the leading `\b` with `(?<![A-Za-z0-9])` and allow an
uppercase prefix; add `token`, `access_key` and the common prefixed tokens;
scan every regular file git would commit from the store; treat `#` as a
comment only at line start; refuse a `.crumbignore` pattern that matches `""`
and print how many lines were suppressed.

### 2.4 Guard reads several ordinary commands as harmless (re-run)

Same store throughout: one attempt with a do-not-retry line and
`--evidence file config/deploy.yml`.

**A here-string or a quoted `<<` swallows every later line.** `_HEREDOC_RE`
(`shellcmd.py:290`) is not quote-aware and matches the last two characters of
`<<<`:

| Command (`~` is a newline) | Verdict |
|---|---|
| `sed -i 's/1/2/' config/deploy.yml` | ASK_HUMAN |
| `cat <<< hello ~ sed -i s/1/2/ config/deploy.yml` | PROCEED, read-only, no matches |
| `cat <<< hello ~ rm -rf src` | PROCEED, read-only |
| `python3 -c "print(1 << n)" ~ git push --force origin main` | PROCEED |

**Writers classified read-only**, which caps the verdict and drops the
permission prompt:

| Command | Verdict |
|---|---|
| `cat /dev/null > config/deploy.yml` | ASK_HUMAN |
| `cat /dev/null>config/deploy.yml` (no space) | READ_FIRST, read-only |
| `yq -i '.version = 2' config/deploy.yml` | READ_FIRST, read-only |
| `git reflog expire --expire=now --all` | PROCEED, read-only |
| `fd -e yml -X rm -rf` | PROCEED, read-only |

**The always-ask floor is bypassed by common spellings.** Decision D3 promises
ASK_HUMAN for a force-push to a default branch, `rm -rf` outside build
directories, and a real `crumb migrate`:

| Asks | Does not ask |
|---|---|
| `rm -rf src` | `sudo rm -rf src`, `env FOO=1 rm -rf src`, `bash -c 'rm -rf src'`, `rm -rf build/../src` |
| `git push --force origin main`, `git push origin +main` | `git push --force-with-lease origin main`, `git push -f origin refs/heads/main`, `git push origin +refs/heads/main`, `git push --delete origin main` |
| `crumb migrate` | `crumb --project . migrate` |

The verb is taken from the first token, so wrappers hide it; any path
component named like a build directory exempts the target even when followed
by `..`; `--force-with-lease` is not treated as force; and `crumb_effect`
reads the value of `--project` as the subcommand.

The module's stated contract is "anything this cannot read is treated as
capable of side effects". These cases go the other way. §5.3 argues for
changing the approach, not adding fourteen more rules.

**A trap about a `crumb` command cannot fire on that command.** After writing
this review I recorded `trap_crumb-rename-deletes-the-record` (title "crumb
rename deletes the record it renames", tag `rename`) so the next agent would
be warned. Guard then gave:

| Action | Verdict |
|---|---|
| `crumb rename dec_x --slug y` | PROCEED, "none above the noise floor" |
| `python crumb.py rename dec_x --slug short` | PROCEED |
| `rename a record with crumb rename` | READ_FIRST, cites the trap |
| `edit breadcrumbs/rename.py` | READ_FIRST, cites the trap |

Guard classifies crumb's own commands by effect and does not match their text
against records. That was a deliberate fix for warnings on every
`crumb remember`, and `CRUMB_WRITES` (`shellcmd.py:490`) lets a trap keyed to
a store file fire on the command that writes it. A trap keyed to the
subcommand itself has no route. Matching the subcommand name against a trap's
tags and title tokens (exact token, not prose) would give it one.

### 2.5 `crumb recover --apply` can undo half of a finished operation (audit)

`discard_journal` (`mutations.py:169-170`) is a plain `shutil.rmtree`, which
removes the before-images before `manifest.json`. A kill inside that window
leaves a journal that `recover --apply` then "rolls back": it removes the
files the operation created and cannot restore the ones it changed.

The audit injected a crash at every mutation point of each command. In that
window:

- `remember --supersedes`: the new record is removed and the old one stays
  `superseded_by` a missing id; `validate` fails; re-running `recover` repeats
  "NOT restored (changed since)" forever.
- `rollup sessions`: up to three of five session records permanently gone.
- `consolidate --merge`, `inbox promote`, `promote`, `handoff trim`: the same
  half-state.

The window is a few system calls wide, and every other crash point recovered
cleanly. But the command that is supposed to repair the store is the one that
damages it.

**Fix.** Commit in one atomic step (unlink `manifest.json` first, or rename
the operation directory to a `.done` name) before deleting before-images, and
have `_roll_back` verify every before-image is readable before changing
anything.

### 2.6 A credential in a long command reaches a mined jot and survives promotion (audit)

The transcript miner checks only a jot's `title` and `note` for secrets
(`transcript.py:1098-1101`, `:753-757`). The title is clipped to 120
characters; the evidence ref holds the first 200 characters of the command. A
token that starts after character 120 lands in the jot's evidence, and
`crumb inbox promote` then writes it into a committed `verifications/` record
with exit 0 and a passing `validate`. Only a later `scan-secrets` catches it,
and only if the token has a shape §2.3 covers.

**Fix.** Run the redaction over the full command, every evidence ref and every
file path, and drop the candidate on any hit.

### 2.7 Invisible Unicode passes `safetext` into hook output (re-run at function level)

`safetext.inline`, `block` and `tree` strip zero-width and bidi characters but
pass the Unicode tag block (U+E0000–E007F), the soft hyphen and several filler
characters unchanged. Tag characters are the standard carrier for hidden
instructions and do not show in a diff. The audit took a record with a hidden
sentence in its title through `validate`, `audit` and the guard hook: all 54
characters arrived in `permissionDecisionReason`. `docs/security.md` threat 10
names "an invisible character".

**Fix.** Escape by Unicode category (`Cf`, the tag block, variation selectors,
fillers), and have `audit` flag records that contain them.

### 2.8 With the search index built, guard misses an attempt that names the exact command (audit)

In a store of 200 or more records the index narrows candidates by stems, tags
and files (`searchindex.py:370-388`). The command-head match in
`scoring.py:1236-1237` can create a match on its own, but never sees a record
the index did not return. For `make build --jobs 4` the only non-stopword stem
is `job`, so an attempt titled "make build wipes the fixture directory" is not
loaded:

```text
index present:  PROCEED     (exit 0)
index removed:  READ_FIRST  "names this exact command; has an explicit do-not-retry condition" (exit 10)
```

`searchindex.py`'s docstring says results are identical "by construction".

**Fix.** Always load attempts that carry command heads directly, as traps are,
or index the command-head tokens.

---

## 3. Wrong behaviour, contained

Each of these was reproduced with commands and output.

### 3.1 Read path

| # | Finding | Where | Status |
|---|---|---|---|
| R1 | **Traps and questions are listed in filename order**, while the packet says `ordering: "recency"`. With 13 or more active traps the newest one is the entry the cap drops. This repo's packet lists its 10 traps alphabetically. | `blockfiles.py:147-195`, `packet.py:682,695,1089-1103` | re-run (order); audit (drop) |
| R2 | **A branch's own handoff is ignored** in a clone with no `origin/HEAD` and no local `main`, the shape a single-ref fetch produces. Resume serves the default branch's Next Action with no warning. | `handoffs.py:71-75,92-106` | audit |
| R3 | **A directory named `*.md` in a record directory takes down every command**, `validate` included, with `[Errno 21] Is a directory: 3` (a file descriptor, not the path). The `S_ISDIR` check runs after `os.fdopen` has already raised. | `path_policy.py:412-415` | re-run |
| R4 | **Guard's "same file(s)" matches on basename alone.** An attempt about `pkg_a/__init__.py` gives PAUSE for `edit pkg_b/__init__.py`. Absolute and `./` paths always degrade to basename matching. | `textmatch.py:410-428`, `scoring.py:851-858` | re-run |
| R5 | **`resume --json` drops every list** when Current Focus and Next Action are long non-ASCII text, and leaves about 1,900 tokens unused. Lists are emptied before the protected fields shrink, and nothing is refilled. | `packet.py:1098-1120` | audit |
| R6 | **Stopword filtering runs on stems**, so real words vanish: `crumb search projection` returns nothing on this store, where seven decision files contain the word (projection→project, a stopword). Same for `handler`, `worker`, `indexing`. | `textmatch.py:379-389` | re-run |
| R7 | **Non-ASCII text, version numbers and identifier parts are unsearchable.** The tokenizer is `[a-z0-9_]+`. `search "0.6.0"` returns nothing here; a CJK or Cyrillic title is reachable only by file path; `frontmatter` does not find `parse_frontmatter`. | `textmatch.py:61,155-157` | re-run (version); audit (rest) |
| R8 | **In a shallow clone the commit-distance warnings disappear silently.** The same store shows "15 commit(s) behind" in a full clone and nothing at depth 1; `audit`'s evidence-rewritten warnings vanish too. | `cli.py:5865-5879`, `packet.py:186-202` | audit |
| R9 | **Piping long output to `head` prints `CRUMB-ERROR … Broken pipe`**, or a double traceback under `--json`. That is the line agents are told to grep for failure. Needs output larger than the pipe buffer, so it does not show on this store. | `cli.py:9777-9785` | audit |
| R10 | Smaller: the "omitted" line names the token budget when the per-section cap did the cutting; the packet re-derives a question's id from its text, so a retitled question points at an id that does not exist; a question's age is computed from a truncated date and can read `-1d` west of UTC. | `packet.py:1105-1110,695,818`, `blockfiles.py:188` | audit |

### 3.2 Write path

| # | Finding | Where | Status |
|---|---|---|---|
| W1 | **`prune sessions --keep N` keeps the alphabetically last sessions of a day, not the newest.** It sorts by filename, which is date, then title slug, then random hex. In the audit's five-snapshot case the three newest were deleted. The docstring says the newest "anchor the Stop-hook dedupe". | `cli.py:5410` | audit; sort read |
| W2 | **One long unbroken token makes every later write slow.** `_FILE_TOKEN_RE` is quadratic on a run of word characters. A 20 KB token made `remember` take 8 s and every later `guard` 2 s; the audit measured 79 s at 60 KB, all under the store lock, whose wait is 2 s for the CLI and 0.5 s for hooks. | `textmatch.py:67-69` | re-run |
| W3 | **Only one trap and one question with a non-ASCII-only title can exist.** `slugify` keeps `[a-z0-9]`, so the id is `trap_untitled` and the second is refused. `note question` has no `--slug`, so there is no way around it. | `cli.py:2125-2128`, `blockfiles.py:229` | re-run |
| W4 | **`remember --privacy local-private` can never succeed**: the record is written to the committed directory and the validate gate rejects it. | `cli.py:2262` | re-run |
| W5 | **`resume` and two hooks fail on a read-only store** (`EROFS` on the lock file escapes as a raw `OSError`). `resume --fast`, `search`, `guard` and `validate` work on the same mount. | `lock.py:213-217` | audit |
| W6 | **`consolidate --merge` widens `scope: branch` records to `scope: project`**, so branch-only guidance becomes live everywhere. `inbox promote` preserves scope. | `lifecycle.py:957-969` | audit |
| W7 | **An interrupted write leaves a `.tmp` copy of the record in a committed directory.** It is not gitignored, not reported by `recover`, `validate` or `doctor`, and not scanned by `scan-secrets`, so `git add .project-memory` commits a record the user believes was rolled back. | `path_policy.py:445-486` | audit |
| W8 | Smaller: schema-3 migration silently drops a second block with a byte-identical heading (the backup keeps it); `capture session` is three unjournaled writes; `repair --apply` over-counts and ignores `--set` for an unknown id; `mark-status … active` leaves `superseded_by` set. | `cli.py:6086-6101,5294-5355` | audit |

### 3.3 Hooks and MCP

| # | Finding | Where | Status |
|---|---|---|---|
| H1 | **The hook payload is decoded in the locale encoding.** stdout is reconfigured to UTF-8, stdin is not. With a cp1252 stdin (Windows' default for a pipe) a store under a non-ASCII path gets `{}` from the guard, and a prompt containing `Á` exits 1. Simulated with `PYTHONIOENCODING`, not run on Windows. | `cli.py:9292-9303` | audit |
| H2 | **One long user correction becomes two jots**, one from the prompt hook and one from the miner, because they clip the title differently. Two such corrections then cross the three-jot threshold and block the Stop. | `hooks_prompt.py:165-167`, `transcript.py:438-440` | audit |
| H3 | **The Stop hook blocks a second time** for candidates it did not list the first time (it records only the six it showed), with no new work. `docs/cli-spec.md:91` says it holds the stop once. | `hooks_stop.py:504-520` | audit |
| H4 | **`crumb doctor` reports green for things that are not there.** After `init --with-hooks=session,capture` it prints "the guard hook covers Bash…" with no guard hook installed; `mcp doctor` passes when the registered `breadcrumbs-mcp` command is not on PATH; `"disableAllHooks": true` and old launcher forms stay green. | `cli.py:9040-9096,8825-8840` | audit |
| H5 | **"Every event exits 0 and prints JSON, whatever the payload" is not true.** A non-string `cwd`, a NUL in `cwd`, a lone surrogate in a prompt, a 5,000-digit integer, or a garbage `index/commit-order.txt` each exit 1 with a traceback or `CRUMB-ERROR`. The installed launcher turns that into `{}`, which hides that the guard is off. | `cli.py:9297-9307`, `hooks_common.py:345` | audit |
| H6 | **MCP contract gaps.** `memory_note` with wrong-typed `fields` returns a bare "Error executing tool"; over stdio a `review_status: reviewed` claim is silently dropped where the spec promises a refusal; the `guard_before_action` prompt omits `ASK_HUMAN`; comments still say "Tools (10)", "Resources (8)". | `mcp_core.py:811-824,1061-1064`, `mcp_server.py:74-95,255,341` | audit |
| H7 | **`~` in `transcript_path` is not expanded**, so nothing is mined and nothing is logged. The reference's own Stop example shows a `~/.claude/…` path; whether the host sends one is unverified. | `transcript.py:1033`, `hooks_compact.py:94` | audit |
| H8 | Smaller: the hook log records an absolute path in `snapshot_error`, against its own "no file path" rule; `init --with-hooks` and `doctor` print tracebacks on a `settings.json` whose `hooks` is a list. | `hooks_stop.py:362,369,546`, `cli.py:8420,9089` | audit |

Design points from the hooks reference worth acting on:

- **No hook entry has a `timeout`.** The default is 600 s (30 s for
  `UserPromptSubmit`), so a hung `crumb` stalls every tool call for up to ten
  minutes.
- **On Windows without Git Bash** the reference says a failing shell-form
  `PreToolUse` hook "can instead block the tool call". The installed command
  is POSIX `sh`. If that reading is right, the guard hook vetoes every Bash,
  Edit and Write call there. Unverified.
- **There is no `SessionEnd` hook**, so a session ended by interrupt, an API
  error or closing the window is never mined or snapshotted.
- **After a failing candidate the launcher re-runs the whole hook** with each
  fallback, up to three interpreter starts per tool call.
- **The extraction ask uses `decision: "block"`**, which the transcript shows
  as a hook error. The reference now offers `additionalContext` on Stop.

### 3.4 CI, release and packaging

| # | Finding | Where | Status |
|---|---|---|---|
| C1 | **The CI gate fails open.** If the API call fails or returns no run, the step prints a warning and continues to an irreversible upload. `CLAUDE.md` and `RELEASING.md:90-92` say publish requires green CI. | `release.yml:137-142` | read |
| C2 | **The pre-flight prints false statements when PyPI is unreachable.** For a fully released version it reports "a dead tag … or delete the dead tag and its Release". It also passes a version lower than the latest on PyPI as "good to publish", although `CLAUDE.md` says the workflow refuses a version regression. | `.github/scripts/release_preflight.py:146-177` | re-run |
| C3 | **`license = { file = "LICENSE" }` is deprecated with a stated cut-off of 2027-02-18**, and setuptools is unbounded (`>=61.0`). `python -m build` prints the warning today. | `pyproject.toml:2,13` | audit |
| C4 | **The `concurrency` group does not stop the matrix running twice per PR commit.** It keys on `github.ref`, which differs between `push` and `pull_request`. The run list shows the pair for `7fefc27` and four other commits. | `ci.yml:35-40` | read (run list) |
| C5 | **The built-in upload retry cannot recover a failure after attestations are generated**: the pinned action refuses a `dist/` that already holds `*.publish.attestation`. A whole-workflow re-run still recovers. | `release.yml:274-305` | read (action source) |
| C6 | **The sdist ships 77 test modules that cannot run from it**: it lacks `crumb.py`, `tests/_*.py`, `tests/data/`, `tests/fixtures/`, `fixtures/` and `.github/scripts/`. | no `MANIFEST.in` | audit |
| C7 | Hardening: `build` and `twine` float in the release path; the OIDC job also holds `contents: write`; three `${{ }}` values are interpolated into `run:` blocks; `main` has no branch protection; nothing runs `scan-secrets` on this repo's own store although `CLAUDE.md` says it "gates commits". | `release.yml:108,158,182,206,258-262` | audit |

### 3.5 Documentation that is false today

| Statement | Reality | Where |
|---|---|---|
| A schema change moves the package MAJOR version; the manifest carries `schema_version: 1` | A schema change is a minor release (`CLAUDE.md`, `docs/compatibility.md` §1); the schema is 4 | `pyproject.toml:67-71`, `RELEASING.md:239-241`, `README.md:110-114` |
| The adapter signpost "never creates a file you don't already have" | Bare `--with-adapter` in a repo with no guidance file creates `AGENTS.md` | `README.md:1000-1003` |
| `cli-spec.md` documents every command | `repair`, `rename`, `handoff trim` and `inbox import` are absent | `docs/quickstart.md:12-13` |
| `0.1.13` has no GitHub Release | One exists (a dead Release) | `RELEASING.md:171,185` |
| "every release … through `v0.3.1`"; "0.4.0 (prepared, not released)" | Tags and PyPI run through 0.6.2 | `RELEASING.md:180-181`, `docs/releases/reliability-release-checklist.md:1,8` |
| Add entries under `[Unreleased]` | `CHANGELOG.md` has no such section | `CONTRIBUTING.md:101`, `README.md:1243` |
| `get_version()` has a source-checkout fallback | It returns `__version__` unconditionally | `release.yml:19`, `RELEASING.md:236`, `CONTRIBUTING.md:41` |
| "Bump one line" | The suite also requires the CHANGELOG entry and the `docs/compatibility.md` §3 row | `breadcrumbs/__init__.py:22`, `release.yml:8` |
| PreCompact stdout "never reaches the model" | The reference says it becomes instructions for the compaction summary | `hooks_compact.py`, `docs/cli-spec.md:93` |
| The secret heuristic "exits non-zero on a hit" | It is warn-only by a later decision | `docs/security.md` §2 |

---

## 4. Checked and found sound

So that the list above is read in proportion:

- **Concurrent writers:** 10 to 40 parallel `remember`, `note` and `capture`
  processes. Every write that reported success landed, the store validated,
  and the block files kept every entry.
- **Crash recovery:** a kill at every mutation point of eleven commands
  recovers to fully rolled back or fully committed, outside the two windows in
  §1.2 and §2.5. `migrate` survives a crash at each of its 31 points.
- **Frontmatter round trip** for `: `, `#`, quotes, `---`, `null`, `~`,
  leading and trailing spaces, backslashes and non-ASCII. CRLF and BOM files
  are handled.
- **Path containment:** traversal in ids, titles, slugs and MCP arguments is
  refused or slugified; symlinked store files are refused.
- **Malformed input:** 36 corruptions of a record against 30 commands gave no
  traceback. Hooks given empty stdin, invalid JSON, wrong types, a missing
  store or a corrupt store exit 0 with `{}`, apart from §3.3 H5.
- **Hook contract:** event names, the guard matcher and output shapes match
  the current reference for all six events. Hooks only ever emit `ask` or
  context, never `allow` or `deny`.
- **Reads do not write:** 22 read commands left tracked files unchanged.
  Packet, search and guard output is deterministic across hash seeds.
- **Git facts** are right in a worktree, a submodule, detached HEAD, packed
  refs, a repo with no commits and outside git.
- **Release:** every action's pinned commit matches its version comment; the
  uploaded artifact is the one built and smoke-tested; the tag lands on the
  built commit; PyPI, tags, CHANGELOG and the compatibility table agree; the
  published 0.6.2 wheel and sdist match a local build of the tag.
- **Docs:** all 118 relative links resolve; every flag shown on a `crumb …`
  line exists; the 47 README quickstart commands run as written.
- **Tools and evals** run from a clean copy as documented;
  `evals/baseline.json` matches a fresh run on every gated metric.

---

## 5. How the system can be improved

### 5.1 Measure whether memory changes what an agent does

`docs/benchmarks/continuity-results.md` is honest about this: "**No agent was
run.** Whether a model acts on what it is handed is a separate question." Its
own table is the strongest argument for running one:

| Baseline | facts at start | facts at action | stale shown as current | tokens |
|---|---|---|---|---|
| hand-kept `NOTES.md` | 10/10 | 2/10 | 4/10 | 1,398 |
| breadcrumbs | 6/10 | 4/10 | 0/10 | 22,614 |

Breadcrumbs never showed stale guidance and always pointed at the right
record. The notes file delivered the full facts more often, at 6% of the
tokens, with no commands. Which of those matters to a real agent's outcome is
unknown, and about 34,000 lines of package rest on the answer.

`docs/v2-design.md` §11 puts the evals first (phase P0). I agree, with three
additions:

- Keep the `NOTES.md` baseline in E1 and E2. It is the cheapest competitor and
  it currently wins two columns.
- Count tokens delivered per useful fact, not only recall. §1.3 shows the
  packet is already too long for its main channel.
- Run E2 (repeat failure) against v1 as it is today, before building anything.
  If a warned agent still retries, the delivery format matters more than who
  writes the record.

### 5.2 This repo's own store shows the maintenance problem

The store here is the longest-running real use of the tool:

- **No attempt records**, with 62 decisions, in a history where 214 of 215
  non-merge commits were written by an agent working under `CLAUDE.md`'s
  memory instructions. The resume packet's "Failed Attempts To Avoid" section
  reads "none recorded".
- **Current Focus says** "0.6.0 is bumped on the branch … Next is merge and
  publish". 0.6.0, 0.6.1 and 0.6.2 have shipped. "Recently Changed" lists
  commits from the 0.4.0 work.
- **The handoff is 40 days and 12 commits old.** Its Next Action is "Release
  0.6.2", which is done.
- **One open question is 90 days old**; the other asks which deferred-review
  items to take next, and most of them have been taken.
- **`crumb doctor` reports no hooks and no MCP registration in this repo.**
  The tool is not running its own capture or guard hooks on the sessions that
  build it.

The packet does notice ("Landed Since The Handoff Was Written" lists the
0.6.2 release), but it prints the stale focus above that note.

**Part of this is structural, not agent neglect: a merged branch's Next
Action is stranded.** On any branch but the default, `capture session` writes
`handoffs/<branch>.md`, and nothing carries it forward on merge. In a
pull-request workflow no session ever runs on `main`, so `handoff.md` changes
only when someone edits it by hand (the 0.6.1 release commit did: "reconcile
handoff.md"). The store holds eleven branch handoffs. Ten are from earlier
sessions whose recorded commit is already in `main`. Their branches were
never deleted (the remote has 48), so `crumb prune handoffs`, which waits for
the branch to be gone, never removes them either.

This session shows it. Its capture set a new Current Focus and a Next Action.
In a clone of the result, on a fresh branch, as the next session will be:

```text
## Current Focus
0.6.2 is released. docs/reviews/2026-11-13-system-review.md is a full review ...
## Next Action
Release 0.6.2 (Windows fixes from the native-full job ...
```

The focus arrives because `current.md` is shared. The Next Action is the old
one from `handoff.md`; the new one sits in `handoffs/ccr-5a263b6c-3gtzxn.md`,
which only this branch reads.

**Fix.** When reading on any branch, also consider branch handoffs whose
recorded commit is an ancestor of `HEAD` and that are newer than `handoff.md`,
and show their Next Action entries labelled with the branch they came from.
That needs no write on merge and no agent action.

v2's curator is the structural answer to the rest. Three cheaper steps help
now:

- **Derive, do not store, what git already knows.** When the handoff's Next
  Action or Current Focus is older than the newest commits, lead with the
  commits and demote the stale text below them, labelled as stale.
- **Install the hooks in this repo.** Every hook defect in §1 and §3.3 would
  have been met in daily use.
- **Close or re-date the two open questions**, so `audit` starts from zero.

### 5.3 Stop growing the shell classifier; change what "unknown" means

The v2 design counts 38 of 217 commits as guard, hook or classifier work and
says "there will always be a next case". §2.4 is the next fourteen. v2's
triggers replace prose matching, but v2 keeps `shellcmd` normalization, the
read-only allowlist and the always-ask floor, so these misses carry over.

Three changes would end the pattern instead of extending it:

- **Make read-only a short positive list of exact forms**, and treat
  everything else as possibly writing. Today the allowlist names programs
  (`yq`, `fd`, `sort`, `git reflog`) and tries to enumerate their writing
  flags.
- **Unwrap before classifying.** Strip `sudo`, `env VAR=…`, `command`, `nice`,
  `timeout` and `xargs`, and recurse into `sh -c` strings, in one place, before
  any rule runs.
- **Test by property, not by case.** For example: for every command in a
  corpus, prefixing `sudo`, removing the space before `>`, or appending a
  second line must never lower the verdict. A few hundred generated variants
  would have caught most of §2.4. The existing eval suites are a ready corpus.

`docs/security.md` §2.x already says a `PROCEED` means "no relevant memory,
not safe". `README.md:667` ("A few actions always ask") is the sentence that
overpromises: until the floor survives a wrapper, it should say which
spellings it covers.

### 5.4 One implementation per rule

Several findings are the same shape: a rule implemented twice, with the two
copies disagreeing. The deferred review fixed this for git state and
timestamps; it recurs here.

| Rule | Copies that disagree | Finding |
|---|---|---|
| What ends a frontmatter line | writer rejects `\n`/`\r`; reader uses `splitlines()` | §2.1 |
| Who may supersede | `_admit` called in `tool_record` and `tool_verify`, not `tool_note` | §2.2 |
| Where the store is | CLI, hooks and MCP each resolve the root differently | §1.4 |
| How a title is clipped | prompt hook and transcript miner | §3.3 H2 |
| What a match is | full scan and indexed lookup | §2.8 |
| What is scanned for secrets | jot title and note, not evidence | §2.6 |
| Record order | decisions by recency, traps and questions by filename | §3.1 R1 |

The existing AST tests that refuse open-coded path conversion are the right
tool: add the same kind of test for "frontmatter is parsed in one function"
and "admission is checked in the `cli` layer, not per transport".

### 5.5 Test what the CLI writes, not what the test writes

1,565 tests pass while `crumb rename` destroys every real record, because the
fixture record was typed by hand without a field the CLI always writes. The
same gap let `remember --privacy local-private` ship unable to succeed.

- Build test records through `remember`, `note` and `verify`, so tests see the
  shape real stores have.
- Add one round-trip test per command: create through the CLI, run the
  command, `validate`, and check the record is still reachable by `show` and
  `search`.
- Keep the audit's crash harness (kill before the Nth rename or unlink, then
  `recover`, `reindex`, `validate`) as a test. It found §2.5 and confirmed the
  rest in minutes.

### 5.6 Deliver less, in the right order

- **Budget each channel in the unit the host enforces.** For Claude Code
  hooks that is 10,000 characters, not approximate tokens (§1.3).
- **Order everything by recency**, and let `--task` reorder questions and
  traps as it does decisions (§3.1 R1, R10).
- **Reconsider the trim order.** Warnings are trimmed last, so
  `resume --budget 500` on a large store shows four "open question … 22 days"
  lines and no decisions or traps.
- **Let the budget, not fixed caps, decide.** At 1,000 records the packet uses
  2,782 of 5,000 tokens while hiding 185 decisions; `--budget` cannot raise
  the caps.
- **Carry the reason an attempt failed.** The benchmark's own product finding
  is that the packet shows the do-not-retry condition but not the result,
  "one `crumb show` away". That lookup is the step an agent skips.
- **Look at what the packet spends on.** On this store about 30% of it is
  twelve verification lines (18%), twenty file names (6%) and twelve
  verification commands (6%), none of which say what to do next.

### 5.7 Performance: three places grow faster than the store

Measured by the audit on synthetic stores (seconds, one run):

| Command | 100 | 1,000 | 5,000 |
|---|---|---|---|
| `resume` | 0.27 | 1.40 | 8.7 |
| `reindex` | 0.20 | 1.09 | 7.5 |
| `audit` | 0.26 | 1.70 | 17.0 |
| `guard` | 0.11 | 0.20 | 0.59 |
| `search` | 0.07 | 0.29 | 1.00 |

- **`resume` rebuilds every projection on every call**, even when nothing
  changed: two unchanged runs each replaced `index/search.sqlite`. That is
  about two thirds of its wall time. Check the generation manifest against the
  current inputs digest first.
- **`audit` is quadratic** (`lifecycle.near_duplicate_pairs`: 2.1 million
  similarity calls at 5,000 records). `related.compute_related` and
  `find_contradictions` run on every reindex and grow the same way.
- **The path-token regex is quadratic in token length** (§3.2 W2).

This matters more under v2, where a curator writes many more records than
agents do today.

### 5.8 Make the surface smaller

- **37 top-level commands.** An agent pays tokens for every `--help` it
  reads. `repair`, `rename`, `recover`, `rollup`, `prune`, `migrate`,
  `consolidate`, `expired` and `usage` are operator maintenance and could sit
  under one `crumb admin` group, leaving about a dozen commands an agent
  needs.
- **The README is the 1,301-line reference**, and it is the PyPI page. 61 of
  its examples are written `python crumb.py …`, which fails for anyone who ran
  `pipx install crumb-kit`. Make it about 150 lines: what it is, install, the
  executed quickstart, links.
- **`cli-spec.md` is organised by when a feature was built** and carries 86
  internal ticket ids. Generate the command table from `cli_parser` and test
  it, as the flag check already does in spirit.
- **`CHANGELOG.md` is 202 KB**; 0.4.0 alone is 691 lines. Give each release a
  five-line "what you must do on upgrade" header and move the narrative to the
  review documents.
- **The hook command is a 700-character shell line repeated six times** in
  `settings.json`. A small launcher script, or the plugin packaging in v2
  §9.3, would make the file readable and the launcher testable.

### 5.9 Notes on the v2 design

The direction is right: the evidence in §5.2 is that an agent does not keep
memory current when asked to. Specific points:

- **Fix the gate before a model writes through it.** v2's safety rests on the
  deterministic gate: schema, secrets, injection, admission. Today that gate
  lets a line separator forge review fields (§2.1), misses common secret
  shapes (§2.3), passes invisible characters (§2.7), and checks jot evidence
  for nothing (§2.6). With an agent writing a few records these are edge
  cases. With a curator summarising transcripts that include web pages and
  tool output, they are the main path. I would make §2.1, §2.3, §2.6 and §2.7
  entry conditions for phase P2.
- **Triggers inherit the matching bugs.** Path triggers need §3.1 R4 (basename
  matching) and §1.4 (subdirectory `cwd`) fixed first, or they will fire on
  every `__init__.py` and go silent after a `cd`.
- **`claude -p` from a hook is the riskiest assumption**, and the design marks
  it unverified: how it counts against quota, whether a detached process
  survives `SessionEnd`, and which flag removes tools. Verify those before
  P1, since the spool and episode format depend on the answer.
- **Git-only episodes (§9.2) need no model and no host.** A reverted commit
  or a fix-up chain is a failed attempt v1 never records. That could ship in
  v1 as a deterministic source of attempt candidates, and would be the first
  entries in an empty section.
- **Automatic supersede (Q3):** start with proposals only. §2.5 and §2.2 show
  the supersede path is where the store's integrity bugs currently are.
- **The 10,000-character cap** applies to "Changed since last time" as well,
  which v2 adds on top of a packet that is already over.

---

## 6. Suggested order

**Status.** Items 1 to 6 are done on branch `ccr-5a263b6c-3gtzxn` (see
`CHANGELOG.md`, `[Unreleased]`). For item 1 the operator chose to drop Python
3.9 rather than pin the runner; the floor is now 3.10, which every runner
image provides. For item 3 the hooks are installed in this repository
(`.claude/settings.json`). One limit remains: the installed launcher's last
fallback, `python -m breadcrumbs`, imports this checkout's package only when
the hook process starts at the repository root. With crumb-kit not installed,
a hook process started in a subdirectory finds no `crumb` and prints `{}`.
Installing crumb-kit (`pip install -e .`) or a `.venv` in the checkout avoids
it.

1. **Unblock CI and releases:** pin the runner for the 3.9 leg (§1.1), make
   the gate fail closed and read the `push` run (§3.4 C1).
2. **Stop data loss:** `rename` (§1.2), the journal-discard window (§2.5),
   `prune sessions` ordering (§3.2 W1).
3. **Make delivery reach the agent:** the character cap (§1.3), one root
   resolver (§1.4), and merged branch handoffs (§5.2). Then install the hooks
   in this repo.
4. **Close the gate:** frontmatter separators (§2.1), `memory_note`
   supersede (§2.2), scanner patterns and file selection (§2.3), jot evidence
   (§2.6), invisible characters (§2.7).
5. **Guard:** the here-string and redirect parsing bugs now; the allowlist and
   wrapper redesign with property tests (§5.3) as its own piece of work;
   index parity (§2.8).
6. **Run the agent-outcome eval** (§5.1) before starting v2's P1. Done: see
   [`docs/benchmarks/agent-outcomes.md`](../benchmarks/agent-outcomes.md). Any
   memory stopped the repeat where the model did not already know better; a
   hand-kept notes file did as well as breadcrumbs at a third of the context;
   and guard's `ASK_HUMAN` on a correct migration plan stalled 5 of 6
   breadcrumbs runs in one scenario.
7. The tables in §3, in whatever order is convenient. Most are small.

Items 1 and 2 are a patch release. Items 3 and 4 change behaviour agents see
and belong in a minor release with decision records for the character budget
and the root resolver.
