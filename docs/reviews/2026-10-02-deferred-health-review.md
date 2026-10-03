# Deferred: code health, signal quality and verification gaps

Written 2026-10-02 on branch `ccr-e63a7edc-aluyzm`, after the 0.6.0 fixes for
the Stop-hook commit loop, the self-rewriting resume packet and the Stop-hook
lifecycle gaps. Those are fixed and tested in 0.6.0 (`CHANGELOG.md`). This
file is the part of the same review that was **not** acted on, written down so
it can be picked up later without redoing the survey.

Nothing here is a bug that loses data or loops. Each item says what was
found, the evidence, a proposed direction, and a rough size. Figures were
measured on this repo at the commit above unless marked otherwise.

## How to use this file

- Pick an item, re-check its evidence first (line numbers drift), then do it
  on its own branch.
- When an item is done or dropped, strike it here and say where it went
  (commit, decision id, or "dropped because …").
- The project memory has a pointer to this file; `crumb resume` lists it under
  open questions until the pointer is closed.

## 1. Signal quality

### 1.1 `crumb audit` is mostly age noise

**Found.** On this store, 17 of the 21 audit warnings were of one kind: an
active decision "is N days old with no update — is this still true?". A
decision staying unchanged for a month is the normal case, not a finding.
When most of the output is noise, people stop reading the one warning that
matters, and the same age lines appear in the resume packet's warnings.

**Direction.** Key staleness on evidence, not elapsed time:

- warn when a decision's evidence files changed after the decision was
  written (the commit range touching its `files`/`evidence` paths);
- warn when a newer record contradicts it (`conflicts.json` already computes
  candidates);
- keep a pure age warning only far past the cutoff, once per record, and
  never in the packet.

**Size.** Medium. Needs a decision record (it changes what `audit` and the
packet say) and an eval check that no true staleness case goes quiet.

### 1.2 One open question has aged past its own cutoff

**Found.** "Should the extraction turn also fire on PreCompact?" has been open
48 days. It is blocked on the field test in `docs/field-test.md`, which has
not been run.

**Direction.** Run the field test, or close the question with the reason it
is parked. An open question nobody owns is itself audit noise.

**Size.** Small to close; medium to run the field test.

## 2. Code structure

### 2.1 `breadcrumbs/cli.py` holds half the package

**Found.**

| Measure | Value |
|---|---|
| `cli.py` lines | 15,651 |
| Package lines | 32,856 |
| Functions in `cli.py` | 424 |
| Modules that import `cli` back | 18 |
| Functions over 150 lines | 13 (largest: `run_validate`, 391) |

The audit counted 13,272 lines in September; the roadmap says new code goes
in new modules (`docs/roadmap-working-memory.md`). WP16 ("finish extracting
the application layer") is `review_required` and its own README says the goal
is not yet true (`docs/reviews/2026-09-27-breadcrumbs-wp16/README.md`).

**Direction.** Extract by seam, one per change, each behind the existing
parity fixture (`tests/fixtures/application_parity.json`):

1. hooks (`_hook_*`, extraction prompt, snapshot) into a `hooks_stop` module
   next to `hooks_prompt`/`hooks_compact`;
2. resume packet build and render;
3. guard scoring and verdicts;
4. validate and audit.

Keep the freshness comment block (cli.py, "Projection freshness — three
functions, one primitive") with whichever module gets `_inputs_hash`.

**Size.** Large in total; each seam is medium.

### ~~2.2 Duplicated helpers, where the field bugs came from~~

**Done** on branch `ccr-4e962709-tubaoe` (2026-10-03), one commit per
concern; each bullet says where it went.

**Found.**

- ~~**Git state is read two ways.** `cli._git_out` spawns `git`, while
  `breadcrumbs/gitrefs.py` reads `.git` directly. `cli.git_commit` returns a
  short sha from a subprocess and `gitrefs.head_sha` a full one; the
  short-versus-full mismatch is what field-report item N8 was. Five other
  modules call the private `cli._git_out`.~~ **Done** on branch
  `ccr-4e962709-tubaoe`: `breadcrumbs/git.py` owns every git spawn and is the
  only importer of `gitrefs` (`tests/test_git.py::OwnershipTests` enforces
  both). HEAD identity is the full sha (`git.head`); the record's `commit`
  field keeps git's short form (`git.short_head`), compared with
  `git.same_commit`. Storing full shas in records was left out: it changes a
  stored format and needs its own decision.
- ~~**Timestamps are parsed by two near-identical functions:**
  `cli._parse_iso` and `validation.parse_timestamp`.~~ **Done:** `_parse_iso`
  is gone and every reader uses `validation.parse_timestamp`. They were not
  identical: `_parse_iso` took whatever the interpreter's `fromisoformat`
  accepts, so on 3.11 readers acted on stamps `validate` rejects.
- ~~**Text is read by three helpers:** `cli.read_text_lenient`,
  `path_policy.read_text`, `handoffs.read_text`.~~ **Not duplicates:** they
  are layers (strict primitive; lenient reader built on it; "find this
  branch's handoff, then read leniently"). The real gap was a read that
  bypassed all three: the fresh-projection check read the committed file
  with a plain `read_bytes`, so a link passed as fresh. It now goes through
  `path_policy` (`tests/test_path_containment.py`).
- ~~**POSIX path conversion** is open-coded about 23 times in `cli.py` and in
  11 other modules, although `path_policy` exists and a decision says
  store-relative paths are POSIX.~~ **Done:** `path_policy.posix_rel` and
  `path_policy.to_posix` replace 45 open-coded conversions (34
  `relative_to(…).as_posix()`, 11 `replace("\\", "/")`) in 12 modules; an
  AST test in `tests/test_platform_portability.py` refuses new ones.
- ~~**Shell commands are tokenized twice:** `cli._command_tokens` and
  `shellcmd.segments`/`words`; guard uses both.~~ **Kept as two tokenizers,
  one owner:** `words` is exact argv (what a command does); the other is
  loose, because guard matches it against prose trap titles, and merging them
  would change verdicts. It moved to `shellcmd.match_tokens`, with
  `normalize_command` from `transcript`.

**Direction.** One owner per concern: a `git` module (public functions, full
shas everywhere, short only for display), one timestamp parser, one lenient
reader, `path_policy` for every store-relative path. Each is a mechanical
change behind the existing tests.

**Size.** Medium; best done as part of 2.1's first seam.

## 3. Verification gaps

### 3.1 Nothing is verified on Windows

**Found.** The `.git` reader, the Stop hook's reflog filter, long-path
(`\\?\`) migration backups, UTF-8 output under Git Bash and
`crumb mcp register --local` were only tested on Linux. Decision D7 says to
re-measure guard speed on Windows. The native full suite runs weekly or on
demand with `continue-on-error: true` (`.github/workflows/ci.yml`), so a
Windows regression cannot block a merge.

**Direction.** Run the native full-suite job on `main` before each publish
(the 0.6.0 handoff already says so). Then make the Windows job gating for
changes under `breadcrumbs/` once it has been green for two weeks.

**Size.** Small to run; small to gate.

### 3.2 No coverage measurement

**Found.** No coverage step in either workflow and no coverage config. The
suite is 1,500 tests and takes about 4.5 minutes; several tests spawn
30-second child processes to exercise timeouts.

**Direction.** Add `coverage run -m unittest discover -s tests` as a
non-gating CI job that publishes the report, keeping the runtime dependency
policy (coverage is a `dev` extra only). Shorten the timeout tests with an
injectable clock where the code allows it.

**Size.** Small for coverage; medium for the slow tests.

### 3.3 Seven work packages are waiting on review

**Found.** In `docs/reviews/2026-09-26-breadcrumbs-work-packages.json`:
WP14, WP15, WP16, WP17, WP19, WP20 and WP22 are `review_required`. WP19's
continuity benchmark ran on one repo instead of three, and no agent was run.

**Direction.** A person reviews them, or the tracker says which ones are
superseded by later work (WP22 by the 0.5.0 and 0.6.0 releases, for example).

**Size.** Small per package, but it needs the operator.

## 4. Left over from the 0.6.0 fixes

These came out of the same review and were deliberately not taken in 0.6.0.

### 4.1 Publication cost on every Stop snapshot

**Found.** A Stop turn whose work moved writes a snapshot, and the snapshot
validates the store and republishes every projection. On this store (about
150 records) a snapshot firing takes about 300 ms, before and after 0.6.0;
about two thirds of it is the publication. Sharing one parse cache across the
firing was tried in 0.6.0 and made no measurable difference, so it was not
kept. The audit measured a full reindex at 2.8 seconds for 1,000 records,
and it grows linearly. WP15's README lists "publications are not coalesced"
and "capture still validates the whole store" as limits.

**Direction.** A per-projection inputs hash, so a snapshot (which changes only
the session record, the handoff and `current.md`) re-renders the packet and
restamps `related.json`/`conflicts.json` without recomputing them. That
changes what the stamps mean, so it needs a decision record and the
freshness tests (`tests/test_audit.py::FreshnessComplementarityTests`).

**Size.** Medium to large.

### 4.2 The committed packet shows the branch that last wrote it

**Found.** The packet's Current Focus and Next Action come from the current
branch's handoff, and records scoped to another branch are left out, but the
inputs hash covers neither the branch nor the clock. Since 0.6.0 a read never
rewrites a fresh packet, so after a feature branch merges, `main`'s committed
packet shows the feature branch's handoff and its branch-scoped records until
the next store write on `main` or a `crumb reindex`. Before 0.6.0 any
`crumb resume` repaired that, at the cost of dirtying every session.
`crumb resume` and SessionStart always show the live, correct view; only the
committed file lags, and `crumb doctor` reports it ("renders differently
now — run `crumb reindex`").

**Direction.** Either render the committed file from the default branch's
handoff whatever branch writes it, or drop the handoff-derived sections from
the committed file and keep them in the live view. Either way the committed
file stops depending on which branch wrote it.

**Size.** Medium; changes the cloud-fallback artifact, so it needs a decision
record.

### 4.3 The id-less session bucket

**Found.** Claude Code always sends `session_id` (hooks reference). For
other harnesses 0.6.0 falls back to the transcript path, and only a payload
with neither shares one bucket, which now restarts at each SessionStart. Two
id-less sessions running at once in one checkout still share it.

**Direction.** Nothing until another harness is wired up; then key on
whatever stable id it sends.

**Size.** Small, when needed.
