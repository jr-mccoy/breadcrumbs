# crumb-kit (breadcrumbs) — System Review #5

> **Resolution status (added 2026-08-02): every finding in this document has
> shipped.** All five High, all thirteen Medium and every Low became MF-01 … MF-42
> across batches 1–6 — see [`fix-list.md`](fix-list.md) for the master ID each maps
> to, what was decided, and the two that were deliberately *not* implemented as
> written (M10 → MF-26, dropped by deleting the templates; §5 → **D4**, still
> deferred). The document is kept, unedited below this banner, because D4 is
> sourced from its §5.
>
> **Read the rest as a snapshot of 2026-07-18.** The `cli.py` line numbers no longer
> point at the code cited: the tree was reformatted in `d293796`.

**Reviewer:** Claude (Claude Code agent)
**Date:** 2026-07-18
**Version reviewed:** `crumb-kit` 0.1.7 (record `schema_version` 1), `main` @ `8fdb4cc`
**Basis:** Full read of `breadcrumbs/cli.py`, `mcp_core.py`, `mcp_server.py`, the
bundled template tree, both GitHub workflows, all docs, and the test suite —
performed by four parallel review passes, with **every reported finding
reproduced against the live code** (temp-dir stores, a live FastMCP server on
Python 3.11, a built wheel, real hook stdin payloads). Findings that could not
be reproduced were discarded. Test suite state at review time: 315 passed,
2 skipped.

This is the fifth review round. Reviews #1–#4 (and system review #3's R1–R26)
are resolved per `CHANGELOG.md`; nothing below duplicates a fixed finding.

---

## 1. Executive summary

The core engine remains in good shape: packaging is clean (wheel diffed against
the template tree — all 18 files ship), the MCP server registers exactly the
spec'd 10 tools / 8 resources / 6 prompts, fixtures are real and exercised twice
over, docs match the CLI surface on every spot-check of flags and defaults, and
the release workflow's tag-on-built-commit design holds.

The problems found this round cluster in three places:

1. **The 0.1.2 automaticity layer (hooks) has two high-severity behavioral bugs.**
   The PreToolUse guard emits `permissionDecision: "allow"` on its *warning*
   verdicts — which in the Claude Code hook contract **bypasses the permission
   prompt** and hides the warning from the model, the exact inverse of "memory
   informs, never decides." And the Stop hook fires on **every agent turn**, not
   once per session, flooding `sessions/` with near-empty records and
   overwriting a real `Next Action` with a placeholder. The integration layer
   was reviewed less than the engine in rounds #1–#4, and it shows.

2. **Two trust primitives fail open.** The secret scanner silently skips any
   file it cannot decode (one bad byte = zero findings), and `git_dirty_files`
   corrupts the first filename in the most common dirty state (unstaged
   modification), poisoning `dirty_files` in every record written from such a
   tree.

3. **The release process still has one unrecoverable failure mode**, and its
   own docs describe the recovery wrongly: if PyPI upload succeeds but the
   tag/Release step fails, a re-run hard-fails the "not already on PyPI"
   pre-flight forever. The stale `v0.1.5`/`v0.1.6` tags on GitHub (versions
   that never reached PyPI) are live evidence of the tag/PyPI invariant not yet
   being true.

Everything else is medium/low: a fence-awareness fix (R4) applied to only one
of two parallel section splitters, a rename-blind `inputs_hash`, several
integration-UX edges (`--with-hooks=typo` traceback, irreversible
`--with-adapter=<arbitrary file>`, Ctrl+C-as-consent), MCP envelope and doc
drift, and CI hardening. A short structural note (§6) argues the 5,942-line
`cli.py` has now produced two bug classes *because* of duplication and should be
split.

---

## 2. Findings — High

### H1. PreToolUse guard hook `"allow"` bypasses the permission system and hides warnings from the model
`breadcrumbs/cli.py:5416-5424`

For any verdict that is not `PROCEED` and not `ASK_HUMAN`, `_hook_guard` does
`decision = "ask" if verdict == "ASK_HUMAN" else "allow"`. In the Claude Code
hook contract, `permissionDecision: "allow"` is not neutral — it **auto-approves
the tool call, skipping the permission prompt the user would otherwise get**,
and the `permissionDecisionReason` for `allow` is shown only to the user, never
to the model. So on `PAUSE`/`READ_FIRST` (a recorded failed attempt on this
exact area) the hook actively *removes* a safety prompt and the guard warning
never reaches the agent. Reproduced end-to-end: with a recorded force-push trap,
`echo '{"tool_name":"Bash","tool_input":{"command":"git push --force origin
main"}}' | crumb hook guard` emits `{"permissionDecision": "allow",
"permissionDecisionReason": "breadcrumbs guard: READ_FIRST …"}`.

**Fix:** for `READ_FIRST` emit `{}` (leave the normal permission flow untouched)
or surface the matched records via `additionalContext`; for `PAUSE` and
`ASK_HUMAN` emit `"ask"` with the reason. `tests/test_hooks.py:103` currently
blesses `"allow"` and must be updated with the fix.

### H2. Stop-hook auto-capture fires every turn, floods `sessions/`, and clobbers a real Next Action
`breadcrumbs/cli.py:5428-5444`

Claude Code's `Stop` event fires every time the agent finishes responding —
every turn, not once per session. `_hook_capture` unconditionally runs a full
`capture session --fast` with `next_action="(session ended; see git log)"`.
Reproduced: three firings produced `2026-07-18-session.md`, `-2.md`, `-3.md`
(two containing only `_(no file changes detected)_` / `_(no new commits)_`),
and after a deliberate `crumb capture session --next "wire the parser into the
CLI"`, one Stop firing rewrote `handoff.md`'s Next Action to `(session ended;
see git log)` — destroying the one field §16.10 calls required and that
`resume` leads with. Each firing also rewrites `current.md` and runs a full
reindex.

**Fix:** dedupe — skip the write when the HEAD commit and dirty-file set are
unchanged since the newest session record; never overwrite an existing
non-placeholder Next Action/Focus with the placeholder; honor the payload's
`stop_hook_active` flag.

### H3. `git_dirty_files` corrupts the first filename on the most common dirty state
`breadcrumbs/cli.py:815` (`_git_out` returns `r.stdout.strip()`) + `:888` (`line[3:]`)

`git status --porcelain` emits worktree-only modifications as `" M path"` — a
leading space. `_git_out`'s whole-output `strip()` removes that space from the
*first* line, after which `line[3:]` chops three characters off the path
instead of the status columns. Reproduced: one unstaged edit to `tracked.py` →
`git_dirty_files(root)` returns `['racked.py']`. The mangled path lands in
every record's `dirty_files` frontmatter via `derive_fields` and feeds
guard/search file matching. Existing tests only cover staged/renamed/untracked
entries (no leading space), which is why the suite is green.

**Fix:** make `_git_out` strip only the trailing newline
(`r.stdout.rstrip("\n")` — safe for all other callers), or parse via
`git status --porcelain -z`.

### H4. Secret scan fails open: an undecodable file is skipped with zero findings
`breadcrumbs/cli.py:4453-4457`

`scan_secrets` does `except (OSError, UnicodeDecodeError): continue`. One
invalid UTF-8 byte (a note pasted from a Latin-1 editor, or a deliberately
poisoned file) silently exempts the entire file from scanning. Reproduced: a
`decisions/*.md` containing `password = abcdefghijKLMNOP1234` flags when clean
and yields `[]` after prepending a single `\xff` byte. For record directories,
`validate` at least reports "unreadable file"; for `known-traps.md` /
`current.md` / `open-questions.md` (validate only checks `is_file()`,
`cli.py:998-1002`) and stray `.txt`/`.json` files, the bypass is completely
silent — `audit`'s "secrets are blocking" posture is void for exactly those
files.

**Fix:** emit a blocking finding (e.g. `pattern: "unscannable-file"`) instead
of `continue`, or decode with `errors="replace"` and scan anyway.

### H5. A partial publish (PyPI ok, tag step failed) is unrecoverable by re-run, and RELEASING.md documents the wrong recovery
`.github/workflows/release.yml:82-93`, `:177-186`; `RELEASING.md:78-81`

The publish job uploads to PyPI first, then runs `gh release create`. If that
last step fails (transient API/network/token error), the version is permanently
on PyPI with no tag or Release — and a re-run now hard-fails in the build job's
pre-flight ("already on PyPI — bump the version"), so the run never reaches the
`skip-existing` upload or the tag step. The workflow comment ("a failed publish
leaves no tag/release to clean up — just fix and re-run") and RELEASING.md
("fix the cause and re-run; `skip-existing` tolerates any file that did make it
up") are both false for exactly this failure mode; the only escapes are
hand-tagging (explicitly forbidden by CLAUDE.md/RELEASING.md) or burning a
version, leaving the published version untagged forever.

**Fix:** make the pre-flight fail only when the version is on PyPI **and** tag
`v$VERSION` exists; when on PyPI but untagged in publish mode, warn and
continue so `skip-existing` no-ops the upload and the tag step completes the
release. Update both doc passages.

---

## 3. Findings — Medium

### M1. Verification records can never influence a guard verdict
`breadcrumbs/cli.py:3723-3727`, `:4086-4089`

`_item_from_record` replaces a verification's item status with its *outcome*
(`open`/`regressed`/…) so search filters work (review #4 F1), but `guard()`'s
liveness test is `status == "active" or (kind == "question" and status ==
"open")` — no verification outcome ever equals `"active"`, so every
verification lands in `history` and is excluded from `_decide_verdict`.
Reproduced: a `--status regressed` verification with a matching evidence file
scores **17.0** (well above the PAUSE band of 9) yet the verdict is `PROCEED`
with `matches: []`. A recorded "X is regressed" on the exact files being
touched should at least floor `READ_FIRST`. **Fix:** treat verification items
whose outcome is in the actionable set (`open`, `regressed`, `inconclusive` —
mirroring `active_verifications`) as live, or key liveness off the record's
lifecycle `status` and keep the outcome only for filtering/display.

### M2. `crumb resume` regenerates the packet without refreshing `guard-prefilter.json` — hook guard stays blind while audit's drift check goes green
`breadcrumbs/cli.py:3486-3489`

`cmd_resume` writes `generated/resume-packet.md` directly (plain `write_text`,
not the `write_text_atomic` used everywhere else) instead of calling
`reindex_projections`, so the trap-token index the PreToolUse hook depends on
is not rebuilt. Reproduced: after hand-appending a trap to `known-traps.md`,
`crumb resume` left `guard-prefilter.json` with `tokens: []`, and `crumb audit`
reported **zero** packet-drift findings — the freshly stamped `inputs_hash` now
matches, so the staleness is invisible until the next mutation, and `crumb hook
guard` will not escalate the newly recorded trap command. **Fix:** have
`cmd_resume` call `reindex_projections(memory_dir, root)` for the store-global
write path (it already writes both files atomically), keeping the direct render
only for the `--fast`/`--task` print-only views.

### M3. `Record.sections` is not fence-aware — the R4 fix was applied to only one of the two splitters
`breadcrumbs/cli.py:758-775` vs `:2573-2609`

A body whose fenced code block contains `## Next Action` produces sections
`['Tried', 'Next Action', 'Result']` from `Record.sections` while
`split_md_sections` correctly returns `['Tried', 'Result']` (reproduced).
Consequences: validate §16.10 false-passes a session with no real Next Action
if fenced output contains a `## next action` line; `_decision_rationale` /
`_attempt_do_not_retry` / `_build_guard_prefilter` read torn sections, so guard
can cite the wrong text; content after a fenced fake heading silently vanishes
from its section. Record bodies routinely carry fences (`--set 'Commands /
Verification' …`). **Fix:** implement `Record.sections` on top of
`split_md_ordered`, keeping one splitter.

### M4. `_inputs_hash` is rename-blind, so the freshness gate can certify a stale projection
`breadcrumbs/cli.py:3112-3127`

Record identity is filename-derived, so renaming `2026-01-01-foo.md` →
`2026-02-02-bar.md` changes the record's id everywhere in the resume packet —
but `_inputs_hash` (sorted paths, contents only, undelimited concatenation) is
unchanged (reproduced: hashes equal before/after rename). `detect_packet_drift`
/ validate §16.12b stay green on a projection full of ids that no longer exist.
**Fix:** fold each file's store-relative path plus separators into the hash
(`h.update(rel.encode()); h.update(b"\0"); h.update(p.read_bytes());
h.update(b"\0")`). Note: invalidates existing stamps once (one-time "stale
projection" finding).

### M5. `crumb resume` crashes with a raw traceback on an undecodable `handoff.md`; `reindex` then silently stops refreshing
`breadcrumbs/cli.py:3147-3157`, `:2067`

`build_resume_packet` calls `read_text(encoding="utf-8")` unguarded, while
every other reader is defensive. Reproduced: one `\xff` byte in `handoff.md` →
`UnicodeDecodeError` traceback. Side effect: `reindex_projections` swallows the
same exception (`except Exception: return False`), so every subsequent write
silently stops refreshing projections until the file is fixed, and `crumb
reindex` prints "Reindex failed" with no cause. **Fix:** read with `utf-8-sig`
+ catch `(OSError, UnicodeDecodeError)`, treat as empty, and append a packet
warning naming the unreadable file; make `reindex` surface the exception
message.

### M6. `crumb init --with-hooks=<typo>` crashes with a raw `KeyError` traceback
`breadcrumbs/cli.py:5040` via `_resolve_tristate_list` (`:5092-5103`)

Reproduced: `crumb init --project . --with-hooks=bogus` → `KeyError: 'bogus'`
from `install_claude_hooks`'s `_HOOK_SPECS[ev]`, uncaught because `main()` only
catches `OSError`/`ValueError`. **Fix:** validate the parsed event list against
`HOOK_EVENTS` in `resolve_integration_plan`; clean `_emit_error` + exit 2
naming the valid events.

### M7. `--with-adapter=<arbitrary file>` injects the managed block anywhere, but removal and doctor only know `ADAPTER_FILENAMES` — irreversible via the documented path
`breadcrumbs/cli.py:5103`, `:5157-5159` vs `:5172-5174`

Reproduced: `crumb init --with-adapter=README.md` injected the signpost block
into `README.md`; `crumb init --remove-integrations` printed "No integrations
to remove." and left the block in place (doctor doesn't see it either).
**Fix:** validate requested adapter names against `ADAPTER_FILENAMES` (clean
error otherwise), or make `remove_integrations`/`doctor` discover any file
containing `ADAPTER_BEGIN`.

### M8. `memory_record` breaks the documented `{ok:false, error}` envelope on frontmatter `ValueError`
`breadcrumbs/mcp_core.py:280`

Every other write path wraps `cli.write_record` in `try/except ValueError`
(`cmd_remember`, `cli.verify`, `cli.note`), but `tool_record` calls it bare —
a newline in `title` (raises at `cli.py:1421`) escapes as a raw `ToolError`
instead of the structured error `docs/mcp-spec.md:80,135-137` promises.
Reproduced against the live FastMCP server. **Fix:** wrap with `except
ValueError as exc: return {"ok": False, "error": str(exc)}`, matching the
other three writers.

### M9. `generated/guard-prefilter.json` escapes the `commit_generated_projections: false` policy and is undocumented
`breadcrumbs/cli.py:208-227` vs `:2061-2065`

The non-commit branch of `gitignore_block` only ignores `generated/*.md`, so
the JSON projection — rebuilt on every write — stays tracked even when the user
chose local-only projections (reproduced with `git check-ignore`). The file is
also absent from the `generated/README.md` template table and all of `docs/`.
**Fix:** add `generated/*.json` to the ignore branch (or always, like
`index/`), and document the file in the template README.

### M10. `generated/stale-report.md` and `memory-index.md` are never generated by anything, and their placeholder text lies about it
`breadcrumbs/templates/project-memory/generated/{stale-report,memory-index,README}.md`; `docs/record-schema.md:33-36,81-83`

Both templates say "Rebuilt by `crumb audit`" (stale-report even says "planned,
Phase 6" — long shipped), but the only projection writers target
`resume-packet.md` and `guard-prefilter.json`; after `init` + `audit`, both
files remain verbatim placeholders with `<!-- source: <commit-or-hash> -->`
headers (reproduced). Since projections are committed by default, every user
repo permanently carries placeholder files that misstate their provenance.
**Fix:** either have `cmd_audit` write `stale-report.md` (and reindex write
`memory-index.md`), or drop/reword the two templates and record-schema §2.

### M11. `mode: publish` never runs the test suite and doesn't gate on CI being green
`.github/workflows/release.yml` (build job); `RELEASING.md:53-54`

RELEASING.md says dry-run "builds and runs every check CI does", but the
release build job runs neither the unit suite nor fixture validation, and
publish mode has no check that the `ci` workflow succeeded on `$GITHUB_SHA`. A
commit that breaks the suite but survives the two-command smoke test (`init` +
`validate`) can be published permanently. **Fix:** add `python -m unittest
discover -s tests` to the build job (cheap; stdlib-only) or gate publish on the
commit's CI conclusion; correct the RELEASING.md sentence either way.

### M12. Stale remote tags `v0.1.5`/`v0.1.6` contradict the "tags == published releases" invariant
GitHub remote (verified via `git ls-remote --tags` + the PyPI JSON API)

`v0.1.5` and `v0.1.6` exist on GitHub while PyPI has no 0.1.5/0.1.6 (PyPI:
0.1.0–0.1.4 and 0.1.7); `v0.1.2` is missing although 0.1.2 *is* on PyPI. These
are precisely the confusing artifacts the rebuilt process exists to prevent —
`pipx install git+…@v0.1.6` yields a version PyPI never shipped. **Fix:**
delete the two dead tags (and any attached Releases), or document them as dead
in CHANGELOG/RELEASING; leave the v0.1.2 gap documented rather than hand-tagged.

### M13. No lint, formatter, or type-checker anywhere
No ruff/flake8/mypy config in the repo; no such job in `ci.yml`. For a single
~6k-line module, the entire static-analysis burden falls on tests and review
rounds (this review is round five). **Fix:** add a `lint` CI job running
`ruff check` + `ruff format --check` (config in `pyproject.toml`), optionally
`mypy breadcrumbs/` — the codebase already uses type annotations extensively.

---

## 4. Findings — Low

**Parser / validate**
- **Comment-only value parses as a literal string.** `key: # to be filled in`
  → `{'key': '# to be filled in'}` because `_strip_inline_comment`
  (`cli.py:537-541`) requires a space *before* `#`. YAML semantics make this
  null; here e.g. `superseded_by: # none yet` becomes truthy garbage that
  passes §16.6. Fix: unquoted value starting with `#` → `None`.
- **Filename canonicality accepts impossible dates and arbitrary slug
  characters.** `RECORD_STEM_RE` (`cli.py:124`) passes `9999-99-99-My
  Slug!.md`, yielding id `dec_99999999_My Slug!` — spaces/punctuation in an
  exact-match key. Writers always emit clean names; validate exists for
  hand-created files. Fix: validate month/day ranges, restrict slug to
  `[a-z0-9-]+` (or warn on near-misses).

**CLI UX**
- **Interactive `remember` prompts for sections already supplied via `--set`
  and discards the answer.** `sections.setdefault(heading, input(...).strip())`
  (`cli.py:1765-1768`) evaluates `input()` eagerly. Fix: `if heading not in
  sections:`.
- **`crumb hook` with no subcommand blocks on stdin before erroring.**
  `cmd_hook` (`cli.py:5447-5451`) reads stdin before validating `hook_event`;
  from a terminal it hangs until EOF. Fix: validate first.
- **Ctrl+C at an init consent prompt is recorded as consent.** `_prompt_yes`
  (`cli.py:5106-5114`) maps `KeyboardInterrupt` → `default`, and the
  adapter/MCP prompts default to yes, so an abort proceeds to edit
  `.mcp.json`. Fix: let `KeyboardInterrupt` abort init; keep `EOFError` →
  default for piped input.
- **`cmd_resume` writes the committed projection with plain `write_text`.**
  `cli.py:3489`; every other projection write is atomic (the R24 rationale).
  Folded into the M2 fix if `cmd_resume` delegates to `reindex_projections`.

**MCP layer**
- **CLI/MCP fork on omitted confidence with no evidence, and the parity
  comment is wrong.** Non-interactive CLI exits 2; the identical `tool_record`
  payload silently defaults to `low` (`mcp_core.py:264-278` vs
  `cli.py:1775-1792`; both reproduced). The mcp_core comment claims exact R11
  parity — it isn't. Fix: pick one behavior (defaulting to low is friendlier
  for agents) or correct the comment; docs/mcp-spec.md:126 documents the MCP
  side, so today the *code comment* is what lies.
- **`STATIC_RESOURCES`/`TEMPLATE_RESOURCES` are dead code with a false
  comment.** `mcp_core.py:150-162` says the server consumes them;
  `mcp_server.py:138-139` binds every resource explicitly and nothing
  references the registries. Fix: delete, or add a test asserting bound URIs ==
  registry keys.
- **`[mcp]` extra hint is a no-op loop on Python 3.9.** The extra's marker
  (`python_version >= '3.10'`) makes `pip install "crumb-kit[mcp]"` succeed
  installing nothing on 3.9, and `_INSTALL_HINT` (`mcp_server.py:107-112`)
  tells the user to run exactly that command without mentioning the floor.
  Fix: append "(the SDK needs Python >= 3.10)".
- **Missing-store envelope test covers 8 of 10 tools.**
  `tests/test_mcp.py:277-296` omits `tool_verify` and `tool_reindex`
  (currently correct but unpinned). Also untested: `tool_record`'s explicit
  medium/high-without-evidence error branch and `resource_attempt`'s
  unknown-id rejection. Fix: extend the tuple; add two small tests.

**Docs / templates / hygiene**
- **Bundled store README omits `verifications/`.**
  `templates/project-memory/README.md` never mentions the directory that
  `crumb verify` writes to. Fix: add a row.
- **`breadcrumbs/__init__.py` comment contradicts its code.** Lines 19-21
  claim importing the package avoids importing the CLI; line 26 unconditionally
  imports from `breadcrumbs.cli`. The static-read claim only holds for
  setuptools. Fix: reword, or make the re-exports lazy via module
  `__getattr__`.
- **Stray review file at repo root.**
  `crumb-kit-agentic-review-2026-06-26.md.txt` (34 KB, double extension) —
  review docs live in `docs/`, and its findings were resolved in 0.1.2/0.1.3;
  by the repo's own convention (review #3's doc was deleted once resolved) it
  should be removed or moved to `docs/` as `.md`.
  `docs/crumb-kit-agentic-review-2026-06-27.md:10` references it by the
  `.md.txt` name — update that line too.
- **Dangling CHANGELOG reference.** `CHANGELOG.md:34` cites
  `docs/crumb-kit-system-review-2026-07-01.md`, deleted in `a4da5c0`. Fix:
  annotate "(doc since removed)" or link the PR.
- **README install line still says "(future)".** `README.md:56`:
  `pipx install crumb-kit  # from a published artifact (future)` — 0.1.7 is
  live on PyPI. Fix: drop "(future)".
- **RELEASING.md Path B names the wrong PyPI project.** `RELEASING.md:91-92`
  says to scope a token to the `breadcrumbs` project; the project is
  `crumb-kit`. Also worth a one-line warning that Path B bypasses every
  guardrail Path A adds.
- **Two spec/behavior mismatches.** `docs/record-schema.md:307-308` says
  session Files Touched uses `git diff --stat` (actual since 0.1.2:
  `--shortstat` one-liner); `docs/cli-spec.md:41` says `guard` writes an
  optional session note (`cmd_guard` performs no writes).
- **Contributor tooling undeclared.** CLAUDE.md says `python -m pytest -q`,
  but pytest is declared nowhere (no dev extra, no requirements file) and CI
  runs `unittest discover`; there is no `[tool.pytest.ini_options]`, so a stray
  root `.pytest_cache` appears. Fix: add `[project.optional-dependencies]
  dev = ["pytest", "build", "twine"]` + `testpaths = ["tests"]`, or make
  `unittest discover` the documented canonical runner.

**CI / workflow hardening**
- Neither workflow sets a `permissions:` block (repo-default token scope);
  add top-level `permissions: contents: read`.
- Actions pinned to mutable refs — notably
  `pypa/gh-action-pypi-publish@release/v1`, a moving branch on the
  OIDC-publishing path; pin to commit SHAs at least in `release.yml`.
- `ci.yml` triggers on both `push` and `pull_request` with no `concurrency`
  group (doubled runs); `release.yml` also lacks one, so two simultaneous
  publish dispatches can race past both pre-flights.
- The mcp CI job asserts 10 tools + 6 prompts but not the 8 resources the
  README/mcp-spec advertise.
- The test matrix tops out at 3.12; 3.13/3.14 are current and untested despite
  unbounded `requires-python`.

---

## 5. Structural recommendation

`cli.py` is 5,942 lines / 183 top-level defs with at least five separable
units: frontmatter parser/renderer, record model + validate, capture/projection
writers, resume/search/guard, audit/secret-scan/hooks/integrations. This is no
longer only an aesthetic concern — two findings in this review are *duplication
bugs* that a split with shared utilities would have prevented: M3 (two parallel
`## `-section splitters, only one got the R4 fence fix) and M2/the atomic-write
low (two projection write paths, only one atomic and prefilter-refreshing). The
`crumb.py` shim already isolates the public import surface, so a split into a
package of modules is low-risk. Recommended as the vehicle for the M2/M3 fixes
rather than as a separate big-bang refactor.

---

## 6. Verified clean this round

Checked and explicitly *not* findings:

- **Packaging:** wheel built and diffed against the template tree — all 18
  files ship (every `.gitkeep`, `evidence/refs.yml`, the three dir READMEs);
  entry points work; `crumb.py` shim and `__main__.py` behave as documented.
- **MCP surface:** live FastMCP server (Python 3.11) registers exactly the
  spec'd 10 tools / 6 static + 2 template resources / 6 prompts; tool output
  shapes, missing-store envelope, verification outcome-as-status filtering,
  guard/resume/validate parity, and the `.mcp.json` registration shape match
  `docs/mcp-spec.md`.
- **Fixtures:** all ten real and exercised twice (CI end-to-end and
  `tests/test_fixtures.py`), including the deliberate fixture-08 staleness and
  fixture-09 cloud fallback; `fixtures/README.md` matches reality.
- **Docs vs CLI:** spot-checks of `init`/`resume`/`audit`/`search`/`verify`/
  `capture`/`note` help output against README/cli-spec/record-schema all match
  (flags, defaults, vocabularies, filename pattern).
- **Release mechanics:** `$GITHUB_SHA` is frozen per run and shared by build
  and publish jobs, so the tag lands on the exact built commit; version state
  is consistent (`__version__` == PyPI latest == CHANGELOG; empty
  `[Unreleased]` is correct).
- **Hook-guard cost:** pre-filter latency measured ~26-32 ms on escalated
  commands in a small store — the "no record I/O on the common path" promise
  holds.
- **Non-findings:** `"${CLAUDE_PROJECT_DIR:-.}"` in `mcp_server_entry` is
  valid Claude Code `.mcp.json` expansion; `--fast`/`--task` no-overwrite
  behavior, `_bound_packet` trimming disclosure, guard `by_id`/dedup paths,
  argparse global-flag backfill, and the secret-scan allowlists all behaved as
  documented under test.

---

## 7. Suggested fix order

1. **H1 + H2** — the hook layer is the product's automaticity story and both
   bugs actively harm users who enable it (H1 weakens the harness's own safety
   prompts; H2 corrupts the handoff). Small, local fixes.
2. **H3 + H4** — one-line-class fixes to trust primitives
   (`rstrip("\n")`; unscannable-file finding), plus regression tests for the
   leading-space porcelain line and the undecodable file.
3. **H5 + M11 + M12** — release: relax the pre-flight to (on PyPI AND tag
   exists), add the suite to the build job, delete the two dead tags, fix both
   doc passages.
4. **M1–M5** — the trust-loop cluster (guard blind spots, freshness-gate
   holes, splitter divergence, undecodable-handoff crash). M2/M3 are best done
   with the §5 module split.
5. **M6–M10, lows** — integration UX edges, MCP envelope, template/docs
   cleanup, CI hardening — mechanical, low-risk batch.

A future round should re-run the review-#1 style *live-usage* evaluation after
the hook fixes land, since H1/H2 mean the wired-up experience has not yet been
what reviews #1-#2 designed.
