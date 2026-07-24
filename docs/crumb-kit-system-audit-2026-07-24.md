# crumb-kit (breadcrumbs) — System Audit #6

**Reviewer:** Claude (Claude Code agent)
**Date:** 2026-07-24
**Version audited:** `crumb-kit` 0.1.7 (record `schema_version` 1), `main` @ `4790c4a`
**Test suite at audit time:** `python -m unittest discover -s tests` → 317 passed,
2 skipped.

**Scope.** This round is deliberately *differential*. Review #5 (`docs/crumb-kit-system-review-2026-07-18.md`,
six days old) is a thorough report; repeating it would waste the round. So this
audit does two things:

1. **Re-verifies review #5's findings against the current tree** — which are still
   open, and where review #5 got a detail wrong (§2).
2. **Adds new findings** in the areas review #5 covered least: cross-machine /
   multi-developer behavior of the freshness gate, host-path disclosure, and the
   failure modes of `audit` itself (§3).

Every finding below was reproduced against the live code in a temp git repo
before being written down. Nothing here duplicates a fixed finding.

---

## 1. Executive summary

**The single largest improvement available to this project is not another
finding — it is shipping the ones already found.** All five High and all
thirteen Medium findings from review #5 are still present in `main`, verbatim,
and `CHANGELOG.md`'s `[Unreleased]` section is empty. Reviews #1–#4 each ended
with a release that resolved them; round #5 did not. Spot-check reproductions
this round:

| #5 finding | Status today |
|---|---|
| H1 guard hook emits `"allow"` on warning verdicts | **Open** — `cli.py:5416` unchanged |
| H2 Stop hook fires every turn | **Open** — `cli.py:5428-5444` unchanged |
| H3 `git_dirty_files` corrupts first filename | **Open** — reproduced: one unstaged edit to `tracked.py` → `['racked.py']` |
| H4 secret scan fails open on undecodable file | **Open** — and worse than reported (see N3) |
| H5 partial publish unrecoverable | **Open** — workflow unchanged |
| M6 `--with-hooks=<typo>` → `KeyError` | **Open** — reproduced, and it leaves a half-built project (see N4) |
| M12 stale `v0.1.5`/`v0.1.6` tags | **Open** — confirmed against the GitHub tag list and the PyPI JSON API: tags `v0.1.5`, `v0.1.6` exist; PyPI has `0.1.0–0.1.4`, `0.1.7`; tag `v0.1.2` still missing |

Beyond that backlog, this round found **three new defects that only appear when
more than one machine or more than one developer touches a store** — the exact
scenario the product exists for, and the one no fixture covers:

- **N1 (High).** Under the documented `distillate` policy, the committed
  resume packet is stamped with a hash computed over *gitignored* session
  records, so `crumb validate` fails on every teammate's clone, permanently and
  irreconcilably. The trust primitive inverts: it reports drift that does not
  exist, forever.
- **N2 (High).** The committed resume packet embeds the **absolute host path**
  of the project. That publishes each developer's local directory layout into a
  shared repo, makes `crumb doctor` report a stale packet on any clone at a
  different path, and defeats the module's own "never leak a host path to the
  MCP client" rule via `memory://resume-packet`.
- **N3 (Medium).** `crumb audit` — the secret gate — **aborts entirely** on a
  single undecodable byte anywhere in committed memory, emitting one opaque
  error with no filename and *zero* secret findings, while `validate` and
  `scan-secrets` both stay green.

Also of note: review #5's M5 mis-states its own repro (§2.2). Fixing it as
written would produce the wrong fix.

---

## 2. Review #5 re-verification

### 2.1 Still open, unchanged

Every H- and M-tier finding from review #5 reproduces on `main` @ `4790c4a`.
The three whose repro is cheapest to re-run:

```
# H3 — one unstaged edit to a tracked file
$ python -c "from breadcrumbs import cli; from pathlib import Path;
             print(cli.git_dirty_files(Path('.')))"
['racked.py']            # <- 'tracked.py' with three chars eaten

# M6 — invalid hook event
$ crumb init --project . --with-hooks=bogus
    cc_event, matcher, command = _HOOK_SPECS[ev]
KeyError: 'bogus'

# M12 — tags vs PyPI
tags:  v0.1.0 v0.1.1 v0.1.3 v0.1.4 v0.1.5 v0.1.6 v0.1.7
PyPI:  0.1.0 0.1.1 0.1.2 0.1.3 0.1.4 0.1.7
```

### 2.2 Correction: review #5's M5 describes the wrong failure mode

M5 says `crumb resume` on an undecodable `handoff.md` "crashes with a raw
`UnicodeDecodeError` traceback". It does not. `UnicodeDecodeError` subclasses
`ValueError`, and `main()` (`cli.py:5933`) catches `(OSError, ValueError)`.
The actual behavior, reproduced:

```
$ crumb resume --project .
error: 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte
$ echo $?
1
```

The substance of M5 survives — the message **names no file**, so a user has no
way to know *which* of the store's files is bad, and `reindex_projections`
swallows the same exception (`cli.py:2067`) so projections silently stop
refreshing (`Reindex failed (projections left unchanged).`, no cause). But a fix
written to "stop the traceback" would be a no-op. The fix that is actually
needed is: name the unreadable path in the error, and surface the exception from
`cmd_reindex`.

The same correction applies to M5's sibling claims elsewhere in the report: the
undecodable-file family of bugs degrades to a *bare, path-less error*, not a
traceback. The one place that genuinely does traceback is M6 (`KeyError` is not
caught).

---

## 3. New findings

### N1 (High). Under `session_tracking: distillate`, the freshness gate fails on every clone — permanently
`breadcrumbs/cli.py:3112-3127` (`_inputs_hash`) vs `:208-227` (`gitignore_block`)

`_inputs_hash` hashes the core files, `manifest.yml`, **and every `*.md` under
each of `DIR_TYPES`** — which includes `sessions/`:

```python
for d in DIR_TYPES:                       # decisions, attempts, sessions, ideas
    dd = Path(memory_dir) / d
    if dd.is_dir():
        paths.extend(sorted(dd.glob("*.md")))
```

But when the user picks `session_tracking: distillate` — the policy `crumb init`
describes as *"keep sessions/ local; commit only decisions/attempts (lean team
repo)"* — `gitignore_block` adds `.project-memory/sessions/` to `.gitignore`.
Meanwhile `commit_generated_projections` defaults to **true**, so
`generated/resume-packet.md` *is* committed, stamped with a hash computed partly
from files that will never leave the author's machine.

Reproduced end to end:

```
$ crumb init --session-tracking distillate
$ crumb capture session --fast --next "wire the parser"
$ crumb validate                              # author's machine
validate: OK — 12 checks passed, 0 problems.

$ mv .project-memory/sessions /tmp/           # simulate a fresh clone
$ crumb validate
validate: 1 problem(s) found (10 checks passed)
  ✗ [freshness] generated/resume-packet.md: stale projection
    (built from inputs_hash 8f68bfd19b6a; live is 355bf6f629ef). Run `crumb reindex`.
```

The failure is not transient and not fixable by the instruction it prints:

- Every teammate who clones sees `validate` fail and `audit` warn
  (`packet-drift`) from the first second, on a store that is in fact perfectly
  in sync.
- If a teammate follows the advice and runs `crumb reindex`, the packet is
  restamped with *their* (session-less) hash and committed — and now the
  **author's** machine fails, because their local `sessions/` is back in the
  hash. It ping-pongs on every push, forever, generating a spurious diff each
  time.
- `validate` is the project's stated trust primitive ("it must not stay green
  while a projection silently desyncs — that would *certify* drift",
  `cli.py:1201-1205`). Here it does the opposite and cries drift that does not
  exist, which trains users to ignore the one check that is supposed to be
  believed.

No fixture covers a multi-developer store, and every fixture ships
`session_tracking: full`, which is why the suite is green.

**Fix.** Make the hash cover only what the store's own policy says is shared:
skip `sessions/` when `load_manifest(...)["session_tracking"] == "distillate"`
(and, for the same reason, skip any record directory the active `.gitignore`
excludes). Fold the policy itself into the hash so a policy flip invalidates
correctly. Add a fixture with `distillate` + no `sessions/` that must
`validate` clean.

### N2 (High). The committed resume packet embeds the absolute host path
`breadcrumbs/cli.py:3169` (`"path": str(root)`), rendered at `:3379`

`build_resume_packet` puts the fully-resolved project root into the packet, and
`render_packet_markdown` writes it into `generated/resume-packet.md` — a file
that is **tracked by default**:

```
## Project
**t1** — `/tmp/…/scratchpad/t1`
branch `master` · commit `21b2fe0` · 3 uncommitted file(s)

$ git check-ignore -v .project-memory/generated/resume-packet.md
(no output — the file is committed)
```

Three distinct consequences:

1. **Disclosure into a shared repo.** Every commit of the packet publishes the
   author's local directory layout — in practice `/Users/<real-name>/…` or
   `/home/<username>/clients/<client-name>/…`. That is exactly the class of
   host-path leak `mcp_core.py:41-46` calls out and fixes for the *error*
   message ("never embed the absolute host path of the project parent — that
   leaked a filesystem path to the MCP client", issue #7). The same leak flows
   straight through `resource_resume_packet` on every `memory://resume-packet`
   read, so the issue-#7 posture is defeated by the packet body.
2. **`crumb doctor` reports a false staleness on any clone.**
   `_packet_is_stale` (`cli.py:5257-5272`) compares rendered text and strips
   only the `generated_at:` line, so a *byte-identical copy at a different path*
   is read as stale. Reproduced:

   ```
   $ cp -r t1 t1_clone
   $ crumb doctor --project t1        →  ✓ [resume_packet] fresh
   $ crumb doctor --project t1_clone  →  ✗ [resume_packet] stale vs HEAD — run `crumb resume`
   ```

   Combined with N1, a teammate's first three commands after cloning
   (`validate`, `audit`, `doctor`) all report problems that do not exist.
3. **Churn.** Two developers at different paths rewrite that line against each
   other on every reindex.

The fixtures dodge all of this because their packets were hand-written with
`` `.` `` as the path — i.e. the fixtures already encode the correct behavior
that the code does not implement.

**Fix.** Store the project path project-relative (`"."`) or drop it from the
rendered packet, keeping the absolute path (if wanted) only in the
`--json`/in-memory view that never lands in git. Add `project.path` to
`_strip_packet_volatile` as a belt-and-braces measure for `doctor`.

### N3 (Medium). `crumb audit` aborts on one undecodable byte — the secret gate produces nothing
`breadcrumbs/cli.py:4498` (`scan_instruction_like`), `:4661` (`run_audit` handoff read), `:4560` (`_audit_bloat`)

Review #5's H4 established that `scan_secrets` skips an undecodable file
(fail-open). The situation is worse than that: three *other* readers inside
`audit` are unguarded, so the whole command dies. Reproduced by prepending a
single `\xff` byte to `known-traps.md` of an otherwise-clean store:

```
$ crumb audit --project .
error: 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte   (exit 1)
$ crumb validate --project .
validate: OK — 10 checks passed, 0 problems.
$ crumb scan-secrets --project .
scan-secrets: OK — no secret-like strings in committed memory.
```

So the store's own tooling reports, in order: *fatal error with no filename*,
*structurally perfect*, and *no secrets* — for a file that was never scanned at
all. `run_validate` handles exactly this case correctly for `handoff.md`
(`cli.py:1160-1165`) and `generated/*.md` (`:1188-1193`) with an explicit
"unreadable file" finding; `audit` never got the same treatment, and `audit` is
the command documented as the gate before committing memory.

**Fix.** Give `run_audit`, `scan_instruction_like`, `_audit_bloat` and
`doctor_report` (`cli.py:5195`, same unguarded pattern on adapter files) the
same defensive read `run_validate` already uses, and emit an
`unscannable-file` **blocking** finding rather than a silent skip (this is H4's
fix; the two belong in one change). Every failure must name the path.

### N4 (Medium). `--with-hooks=<typo>` leaves a half-configured project, not just a traceback
`breadcrumbs/cli.py:5040` via `_resolve_tristate_list` (`:5092-5103`) — refines review #5 M6

Review #5 reports the `KeyError`. What it misses is *when* it fires. In
`cmd_init` the ordering is: build the scaffold → swap it in (`:434-436`) → write
`.gitignore` (`:438-439`) → **then** `apply_integrations` (`:444-445`). So a
typo'd hook name crashes *after* the store and `.gitignore` already exist:

```
$ crumb init --project . --with-hooks=bogus     # KeyError traceback
$ ls .project-memory/                           # …but the store is there
decisions/ attempts/ sessions/ ideas/ manifest.yml …
```

The user is now in the state `cmd_init` explicitly refuses to touch again
(`"{MEMORY_DIRNAME}/ already exists"`), with no hooks installed and no
indication of how far the command got.

**Fix.** Validate the parsed `--with-hooks` / `--with-adapter` lists inside
`resolve_integration_plan` — i.e. *before* any filesystem mutation — and exit 2
with a clean message naming the valid events. This also subsumes review #5's M7
(arbitrary `--with-adapter=<file>`), since both are the same missing
input-validation step on the same code path.

### N5 (Medium). MCP write tools return absolute host paths, contradicting the module's own issue-#7 rule
`breadcrumbs/mcp_core.py:308`; `breadcrumbs/cli.py:2119`, `:2143`, `:2160`, `:2296`

`mcp_core.py:41-46` states the rule — never hand the MCP client an absolute host
path — and applies it to the missing-store error. Forty lines later, the success
payloads do exactly that. Reproduced against the adapter:

```python
>>> mcp_core.tool_record('decision', {...}, root='.')
{'ok': True, 'id': 'dec_20260724_x', 'type': 'decision',
 'path': '/tmp/…/scratchpad/t1/.project-memory/decisions/2026-07-24-x.md', …}
>>> mcp_core.tool_reindex(root='.')
{'ok': True, 'path': '/tmp/…/scratchpad/t1/.project-memory/generated/resume-packet.md'}
```

Same for `memory_note`, `memory_verify` and `memory_mark_status` (the `path`
key originates in `cli.note` / `cli.verify` / `set_record_status`).
`docs/mcp-spec.md:80-87` documents `path` in all five return shapes without
saying whether it is absolute, so the spec does not settle it either.

Severity is bounded — the client is usually local — but it is a real disclosure
for any hosted or shared MCP client, and it is the project's own stated policy
being violated in the same file.

**Fix.** Return store-relative paths from the MCP layer (the CLI can keep
absolute paths in its human output), and state the choice in `docs/mcp-spec.md`.

### N6 (Low). Open-question ids collide when two questions share a 48-char prefix
`breadcrumbs/cli.py:3762`

`_item_from_question` derives `id = "q:" + slugify(q["question"])[:48]`. Two
questions whose slugs agree on the first 48 characters produce the same id, so
`search`'s `by_id` map (`cli.py:3927`) keeps only the last — and `guard`'s
`_next_safest_action` resolves matches through that map. Reproduced: two
distinct questions — *"Should we migrate the reporting pipeline to the new
columnar store this quarter"* and *"… to the new row store next quarter"* —
both yield `q:should-we-migrate-the-reporting-pipeline-to-the-`, and `by_id`
retains one. Records are immune (filename-canonical, duplicate-checked by
validate §16.4); only questions and traps derive ids by truncation.

**Fix.** Suffix with a short hash of the full question text, or detect
collisions in `_candidate_items` the way `_unique_record_path` does.

---

## 4. Verified clean this round

Checked and explicitly *not* findings:

- **Test suite / CI mechanics.** 317 tests pass on this Python; the fixture
  loops, the wheel-vs-git template identity check, the installed-binary smoke
  test and the MCP tool/prompt count assertions all do what they claim.
- **Frontmatter round-trip.** The renderer/parser pair (quote-flip handling,
  doubled `''` escapes, map-vs-scalar list items, the fail-closed round-trip
  refusal in `set_record_status`) held under every value I threw at it.
- **Atomic writes.** `write_text_atomic` is correct (same-dir tmp + `os.replace`,
  tmp cleaned on failure) and is used by every writer except the one review #5
  already flagged (`cmd_resume`).
- **`init` scaffold swap.** The staging-dir build (`.project-memory.new` →
  build → `rmtree` → `rename`) genuinely prevents a half-written or deleted
  store on template failure.
- **Hook payload hardening.** `_read_hook_stdin` / `_hook_guard` degrade
  correctly on malformed JSON, non-object JSON and non-dict `tool_input`.
- **Packaging metadata.** Single-source dynamic version, `[mcp]` extra marker,
  console scripts and package-data globs are all consistent; PyPI latest
  (`0.1.7`) matches `__version__` and `CHANGELOG.md`.
- **Guard scoring internals.** File-overlap counting (full path vs bare
  basename), the anti-noise gate, branch/age/distance de-weighting and the
  verdict-floor logic behave as documented; the review #5 findings against guard
  are about *what reaches* the scorer, not the scorer itself.

---

## 5. Suggested order of work

1. **Ship review #5's H-tier.** H1/H2 (hook layer), H3/H4 (trust primitives),
   H5 (release recovery). These are small, local, and every day they sit open is
   a day the wired-up product misbehaves. Nothing in this round outranks them.
2. **N1 + N2 together.** Both are "the store is wrong as soon as a second
   machine exists", both live in the packet/hash path, and both need the same new
   fixture: a `distillate`, multi-checkout store that must come up clean.
3. **N3 with H4.** One change: defensive reads plus an `unscannable-file`
   blocking finding, applied to `audit`, `scan_secrets` and `doctor` at once.
4. **N4 + review #5's M6/M7.** One input-validation step in
   `resolve_integration_plan`, before any mutation.
5. **N5, N6, and review #5's remaining M/Low tier.** Mechanical batch.

### One process recommendation

This is the sixth review of a 6,000-line CLI, and the fifth produced no code
change. The bottleneck is no longer *finding* problems. Before commissioning a
seventh round, convert the open backlog into tracked issues (or a single
checklist in `CHANGELOG.md`'s `[Unreleased]`) and land the H-tier — and add
`ruff` to CI (review #5 M13), which would have caught nothing in this report but
raises the floor so future rounds can spend their budget on behavior instead of
hygiene. Review #5's §5 recommendation to split `cli.py` still stands, and N1/N2
add a third duplication-shaped defect class to its evidence: three separate
notions of "is this projection current" (`_inputs_hash`, `_packet_is_stale`,
`detect_packet_drift`), each with a different blind spot.
