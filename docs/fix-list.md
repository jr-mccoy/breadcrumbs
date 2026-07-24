# crumb-kit — Master Fix List

**Living document.** Every unresolved finding from every review round, merged,
deduplicated, and ordered as a work queue. Delete an item when it ships; add a
`CHANGELOG.md` entry in the same commit.

**State as of 2026-07-24** (`main` @ `4790c4a`, `crumb-kit` 0.1.7, record
`schema_version` 1): **37 open items** — 3 High, 11 Medium, 23 Low — plus 4
explicitly deferred. Batches 1 and 2 (MF-01 … MF-05) have shipped and are
recorded in `CHANGELOG.md` `[Unreleased]`; nothing else below has.

## Sources

| Round | Document | Status of its findings |
|---|---|---|
| Agentic review #1 (2026-06-26) | `crumb-kit-agentic-review-2026-06-26.md.txt` (repo root) | Resolved in 0.1.2/0.1.3 — nothing open |
| Agentic review #2 (2026-06-27) | `docs/crumb-kit-agentic-review-2026-06-27.md` | Resolved except F9/F10/F11-partial → **D1–D3** |
| System review #3 (2026-07-01) | doc deleted in `a4da5c0` | R1–R26 resolved in 0.1.6 |
| System review #4 | folded into 0.1.6 | Resolved |
| System review #5 (2026-07-18) | `docs/crumb-kit-system-review-2026-07-18.md` | H1–H4 + M1/M5 shipped (MF-01 … MF-05); H5 and the rest of M **open**, most Lows open |
| System audit #6 (2026-07-24) | `docs/crumb-kit-system-audit-2026-07-24.md` | N3 shipped (in MF-04); N1/N2/N4/N5/N6 **open** |

**Verification legend** — how each item's current status was established:

- `repro` — reproduced against `main` @ `4790c4a` on 2026-07-24.
- `code` — the cited code/config was re-read on 2026-07-24 and is unchanged
  since the review that reported it; not re-run at runtime.
- `inherited` — carried from review #5 without independent re-verification this
  round. Re-check before writing the fix.

---

## Batch 1 — Hook layer — **SHIPPED** (`[Unreleased]`)

Both 0.1.2 automaticity-layer bugs are fixed; see `CHANGELOG.md`.

- **MF-01** (review #5 H1) — the `PreToolUse` guard hook no longer emits
  `permissionDecision: "allow"` on a warning verdict. `PROCEED` → silent,
  `READ_FIRST` → `additionalContext` with no decision, `PAUSE`/`ASK_HUMAN` →
  `"ask"`. `tests/test_hooks.py` asserts the mapping for all four verdicts.
- **MF-02** (review #5 H2) — the `Stop` capture hook dedupes on
  HEAD + dirty-file set, treats its stand-in Next Action as placeholder text so
  it cannot clobber a real one, and honors `stop_hook_active`.

---

## Batch 2 — Trust primitives — **SHIPPED** (`[Unreleased]`)

All three fail-open / corrupt-data defects are fixed; see `CHANGELOG.md`.

- **MF-03** (review #5 H3) — `_git_out` strips only the trailing newline, so a
  ` M path` porcelain line keeps its status columns and `git_dirty_files` no
  longer returns `['racked.py']` for one unstaged edit to `tracked.py`.
- **MF-04** (review #5 H4 + M5 + audit #6 N3) — one lenient decode
  (`read_text_lenient`) behind every memory reader. `scan-secrets` and `audit`
  now *block* on an unreadable file with the path in the message instead of
  failing open / aborting, `validate` reports it, `resume` warns, `doctor`
  surfaces an unreadable adapter, and `reindex` names the cause it used to
  swallow.
- **MF-05** (review #5 M1) — guard's liveness test accepts a verification whose
  record is active and whose outcome is unsettled, so a `regressed` finding on
  the files being touched reaches the verdict (and floors `READ_FIRST`) instead
  of being filed as history.

---

## Batch 3 — Multi-machine correctness (the projection/freshness cluster)

Everything here is invisible on one machine and wrong the moment a second one
exists. There is no fixture for a multi-developer store, which is why the suite
is green. **Add one as part of this batch:** `distillate` policy, no
`sessions/`, checked out at two different paths, must come up clean on
`validate`, `audit` and `doctor`.

### MF-06 · High · `distillate` policy makes `validate` fail on every clone, permanently
*(audit #6 N1 · `repro`)*

`cli.py:3112-3127` (`_inputs_hash`) hashes every `*.md` under each of
`DIR_TYPES` — including `sessions/`. But `session_tracking: distillate` (the
policy `crumb init` recommends for a "lean team repo") gitignores
`.project-memory/sessions/`, while `commit_generated_projections` defaults to
**true**. So the committed packet is stamped with a hash no clone can reproduce.

```
$ crumb validate                       # author's machine
validate: OK — 12 checks passed, 0 problems.
$ mv .project-memory/sessions /tmp/    # simulate a fresh clone
$ crumb validate
  ✗ [freshness] generated/resume-packet.md: stale projection … Run `crumb reindex`.
```

Following the printed advice does not help: a teammate's `reindex` restamps with
*their* session-less hash, and now the author fails. It ping-pongs on every push
forever. `validate` is the project's stated trust primitive; here it cries drift
that does not exist, training users to ignore the one check meant to be believed.

**Fix.** Hash only what the store's own policy says is shared: skip `sessions/`
when the manifest says `distillate` (and any record directory the active
`.gitignore` excludes). Fold the policy value itself into the hash so a policy
flip invalidates correctly.

### MF-07 · High · The committed resume packet embeds the absolute host path
*(audit #6 N2 · `repro`)*

`cli.py:3169` (`"path": str(root)`), rendered at `:3379` into
`generated/resume-packet.md` — a file tracked by default. Three consequences:

1. **Disclosure into a shared repo** — every commit publishes the author's local
   directory layout (`/Users/<real-name>/…`, `/home/<user>/clients/<client>/…`).
   This is the exact leak `mcp_core.py:41-46` forbids for the error message
   (issue #7), and it flows straight out through `memory://resume-packet`.
2. **False staleness on any clone** — `_packet_is_stale` (`:5257-5272`) compares
   rendered text and strips only `generated_at:`, so a byte-identical copy at a
   different path reads as stale:
   ```
   crumb doctor --project t1        →  ✓ [resume_packet] fresh
   crumb doctor --project t1_clone  →  ✗ [resume_packet] stale vs HEAD
   ```
3. **Churn** — two developers at different paths rewrite that line against each
   other on every reindex.

The fixtures hand-write `` `.` `` as the path, i.e. they already encode the
correct behavior the code does not implement.

**Fix.** Store the path project-relative (`"."`), or drop it from the rendered
packet and keep the absolute path only in the `--json`/in-memory view that never
lands in git. Add `project.path` to `_strip_packet_volatile` as belt-and-braces.

### MF-08 · Medium · `_inputs_hash` is rename-blind, so the freshness gate certifies a stale projection
*(review #5 M4 · `code`)*

`cli.py:3112-3127` hashes sorted paths' *contents* only, undelimited. Record
identity is filename-derived, so renaming `2026-01-01-foo.md` →
`2026-02-02-bar.md` changes the record's id everywhere in the packet while the
hash is unchanged. `detect_packet_drift` / validate §16.12b stay green on a
projection full of ids that no longer exist.

**Fix.** Fold each file's store-relative path plus separators into the hash:
`h.update(rel.encode()); h.update(b"\0"); h.update(p.read_bytes()); h.update(b"\0")`.
Note: invalidates existing stamps once (a one-time "stale projection" finding —
say so in the CHANGELOG).

### MF-09 · Medium · `crumb resume` writes the packet without refreshing the prefilter, non-atomically
*(review #5 M2 + the `cmd_resume` atomic-write Low — merged · `code`)*

`cli.py:3486-3489` — `cmd_resume` writes `generated/resume-packet.md` directly
with plain `write_text` (every other projection write is atomic, the R24
rationale) instead of calling `reindex_projections`. So the trap-token index the
PreToolUse hook depends on is not rebuilt, **and** the freshly stamped
`inputs_hash` makes `audit` report zero packet-drift findings — the staleness
becomes invisible until the next mutation, and `crumb hook guard` stays blind to
the newly recorded trap.

**Fix.** Have `cmd_resume` call `reindex_projections(memory_dir, root)` for the
store-global write path (it already writes both files atomically); keep the
direct render only for the print-only `--fast`/`--task` views.

### MF-10 · Medium · `guard-prefilter.json` escapes the `commit_generated_projections: false` policy and is undocumented
*(review #5 M9 · `code`)*

`cli.py:208-227` — the non-commit branch of `gitignore_block` only ignores
`generated/*.md`, so the JSON projection (rebuilt on every write) stays tracked
even when the user chose local-only projections. The file is also absent from the
`generated/README.md` template table and from all of `docs/`.

**Fix.** Add `generated/*.json` to the ignore branch (or always, like `index/`),
and document the file in the template README.

---

## Batch 4 — Release process

### MF-11 · High · A partial publish is unrecoverable by re-run, and the docs describe the wrong recovery
*(review #5 H5 · `code`)*

`.github/workflows/release.yml:82-93` and `:177-186`. The publish job uploads to
PyPI **first**, then runs `gh release create`. If that last step fails
(transient API/network/token error), the version is permanently on PyPI with no
tag and no Release — and a re-run now hard-fails the build job's pre-flight
("already on PyPI — bump the version"), so the run never reaches the
`skip-existing` upload or the tag step. Both the workflow comment (`:23-25`, "a
failed publish leaves no tag/release to clean up — just fix and re-run") and
`RELEASING.md:78-81` are false for exactly this failure mode. The only escapes
are hand-tagging (forbidden by `CLAUDE.md` and `RELEASING.md`) or burning a
version, leaving the published one untagged forever.

**Fix.** Make the pre-flight fail only when the version is on PyPI **and** tag
`v$VERSION` exists. When on PyPI but untagged in publish mode, warn and continue
so `skip-existing` no-ops the upload and the tag step completes the release.
Correct both doc passages.

### MF-12 · Medium · `mode: publish` never runs the test suite and doesn't gate on CI
*(review #5 M11 · `repro` — no `unittest`/`pytest` string exists anywhere in `release.yml`)*

The build job runs `twine check`, the template-identity check, and a two-command
installed-binary smoke test (`crumb init` + `crumb validate`) — but never the
317-test suite, and publish mode has no check that the `ci` workflow succeeded on
`$GITHUB_SHA`. A commit that breaks the suite but survives the smoke test can be
published permanently. `RELEASING.md:53-54` claims dry-run "builds and runs every
check CI does" — it does not.

**Fix.** Add `python -m unittest discover -s tests` to the build job (cheap,
stdlib-only), or gate publish on the commit's CI conclusion. Correct the
RELEASING.md sentence either way.

### MF-13 · Medium · Stale remote tags contradict the "tags == published releases" invariant
*(review #5 M12 · `repro` — GitHub tag list + PyPI JSON API, 2026-07-24)*

```
tags:  v0.1.0 v0.1.1 v0.1.3 v0.1.4 v0.1.5 v0.1.6 v0.1.7
PyPI:  0.1.0  0.1.1  0.1.2  0.1.3  0.1.4         0.1.7
```

`v0.1.5`/`v0.1.6` exist on GitHub but never reached PyPI; `v0.1.2` is missing
though 0.1.2 *is* published. `pipx install git+…@v0.1.6` yields a version PyPI
never shipped — precisely the confusing artifact the rebuilt process exists to
prevent.

**Fix.** Delete the two dead tags and any attached Releases, or document them as
dead in `CHANGELOG.md`/`RELEASING.md`. Leave the `v0.1.2` gap documented rather
than hand-tagged.

---

## Batch 5 — Input validation, correctness edges, MCP surface

### MF-14 · Medium · Integration flags are applied without validation, after the store is already written
*(review #5 M6 + M7 + audit #6 N4 — merged, one change · `repro`)*

`cli.py:5040` via `_resolve_tristate_list` (`:5092-5103`). Two bad inputs, one
missing validation step:

- `crumb init --with-hooks=bogus` → raw `KeyError: 'bogus'` from
  `install_claude_hooks`'s `_HOOK_SPECS[ev]`, uncaught because `main()` only
  catches `OSError`/`ValueError`. And it fires *after* the scaffold is swapped in
  (`:434-436`) and `.gitignore` written (`:438-439`), so the user is left with a
  store the command will now refuse to touch again, no hooks, and no idea how far
  it got.
- `crumb init --with-adapter=README.md` injects the managed block into an
  arbitrary file; `--remove-integrations` then prints "No integrations to
  remove." and leaves it there, because removal and `doctor` only know
  `ADAPTER_FILENAMES`. Irreversible via the documented path.

**Fix.** Validate both parsed lists inside `resolve_integration_plan` — i.e.
**before any filesystem mutation** — against `HOOK_EVENTS` and
`ADAPTER_FILENAMES`, and exit 2 with a clean message naming the valid values.
(Optionally also make `remove_integrations`/`doctor` discover any file
containing `ADAPTER_BEGIN`, for stores already in the bad state.)

### MF-15 · Medium · `Record.sections` is not fence-aware — the R4 fix reached only one of two splitters
*(review #5 M3 · `code`)*

`cli.py:758-775` vs `:2573-2609`. A body whose fenced code block contains
`## Next Action` yields sections `['Tried', 'Next Action', 'Result']` from
`Record.sections` while `split_md_sections` correctly returns `['Tried',
'Result']`. Consequences: validate §16.10 false-passes a session with no real
Next Action; `_decision_rationale` / `_attempt_do_not_retry` /
`_build_guard_prefilter` read torn sections so guard can cite the wrong text; and
content after a fenced fake heading silently vanishes. Record bodies routinely
carry fences (`--set 'Commands / Verification' …`).

**Fix.** Implement `Record.sections` on top of `split_md_ordered`. One splitter.

### MF-16 · Medium · `memory_record` breaks the documented `{ok:false, error}` envelope
*(review #5 M8 · `code`)*

`mcp_core.py:280` calls `cli.write_record` bare, while every other write path
(`cmd_remember`, `cli.verify`, `cli.note`) wraps it in `try/except ValueError`.
A newline in `title` (raises at `cli.py:1421`) escapes as a raw `ToolError`
instead of the structured error `docs/mcp-spec.md:80,135-137` promises.

**Fix.** `except ValueError as exc: return {"ok": False, "error": str(exc)}`,
matching the other three writers.

### MF-17 · Medium · MCP write tools return absolute host paths
*(audit #6 N5 · `repro`)*

`mcp_core.py:308`; `cli.py:2119`, `:2143`, `:2160`, `:2296`.
`mcp_core.py:41-46` states the rule — never hand the MCP client an absolute host
path (issue #7) — and applies it to the missing-store error. Forty lines later
the success payloads do exactly that:

```python
>>> mcp_core.tool_record('decision', {...}, root='.')
{'ok': True, 'path': '/tmp/…/t1/.project-memory/decisions/2026-07-24-x.md', …}
```

Same for `memory_note`, `memory_verify`, `memory_mark_status`, `memory_reindex`.
`docs/mcp-spec.md:80-87` documents `path` without saying whether it is absolute,
so the spec doesn't settle it either.

**Fix.** Return store-relative paths from the MCP layer (the CLI keeps absolute
paths in human output) and state the choice in `docs/mcp-spec.md`.

### MF-18 · Low · Open-question ids collide on a shared 48-character slug prefix
*(audit #6 N6 · `repro`)*

`cli.py:3762` — `id = "q:" + slugify(q["question"])[:48]`. Two distinct
questions ("Should we migrate the reporting pipeline to the new **columnar store
this quarter**" / "… to the new **row store next quarter**") both yield
`q:should-we-migrate-the-reporting-pipeline-to-the-`, and `search`'s `by_id`
map (`:3927`) keeps only the last — which `guard`'s `_next_safest_action`
resolves through. Records are immune (filename-canonical, duplicate-checked by
validate §16.4); only questions and traps derive ids by truncation.

**Fix.** Suffix with a short hash of the full text, or detect collisions in
`_candidate_items` the way `_unique_record_path` does.

### MF-19 · Low · Interactive `remember` prompts for sections already given via `--set`, then discards the answer
*(review #5 Low · `code` — `cli.py:1767`)*

`sections.setdefault(heading, input(f"{heading}: ").strip())` evaluates
`input()` eagerly. **Fix:** `if heading not in sections:`.

### MF-20 · Low · `crumb hook` with no subcommand blocks on stdin before erroring
*(review #5 Low · `code` — `cli.py:5447-5451`)*

`cmd_hook` reads stdin before validating `hook_event`; from a terminal it hangs
until EOF. **Fix:** validate first.

### MF-21 · Low · Ctrl+C at an init consent prompt is recorded as consent
*(review #5 Low · `code` — `cli.py:5106-5114`)*

`_prompt_yes` maps `KeyboardInterrupt` → `default`, and the adapter/MCP prompts
default to yes, so an abort proceeds to edit `.mcp.json`. **Fix:** let
`KeyboardInterrupt` abort init; keep `EOFError` → default for piped input.

### MF-22 · Low · A comment-only frontmatter value parses as a literal string
*(review #5 Low · `repro`)*

`cli.py:537-541` — `_strip_inline_comment` requires a space *before* `#`, so
`superseded_by: # none yet` parses as `{'superseded_by': '# none yet'}`. YAML
semantics make that null; here it becomes truthy garbage that passes validate
§16.6. **Fix:** an unquoted value starting with `#` → `None`.

### MF-23 · Low · Filename canonicality accepts impossible dates and arbitrary slug characters
*(review #5 Low · `code`)*

`RECORD_STEM_RE` (`cli.py:124`) passes `9999-99-99-My Slug!.md`, yielding id
`dec_99999999_My Slug!` — spaces and punctuation in an exact-match key. Writers
always emit clean names; validate exists for hand-created files. **Fix:**
validate month/day ranges and restrict the slug to `[a-z0-9-]+` (or warn on
near-misses).

### MF-24 · Low · CLI/MCP fork on omitted confidence, and the parity comment is wrong
*(review #5 Low · `code`)*

Non-interactive CLI exits 2; the identical `tool_record` payload silently
defaults to `low` (`mcp_core.py:264-278` vs `cli.py:1775-1792`). The
`mcp_core` comment claims exact R11 parity — it isn't. `docs/mcp-spec.md:126`
documents the MCP side, so today the *code comment* is what lies. **Fix:** pick
one behavior (defaulting to low is friendlier for agents) or correct the comment.

### MF-25 · Low · The `[mcp]` extra hint is a no-op instruction on Python 3.9
*(review #5 Low · `code`)*

The extra's marker (`python_version >= '3.10'`) makes `pip install
"crumb-kit[mcp]"` succeed while installing nothing on 3.9, and `_INSTALL_HINT`
(`mcp_server.py:107-112`) tells the user to run exactly that command without
mentioning the floor. **Fix:** append "(the SDK needs Python ≥ 3.10)".

---

## Batch 6 — Templates, docs, tests, CI hygiene

Mechanical and low-risk. Worth doing in one sweep.

| ID | Sev | Item | Location | Fix | Ver |
|---|---|---|---|---|---|
| **MF-26** | Med | `stale-report.md` and `memory-index.md` are never generated by anything, and their placeholder text claims otherwise ("Rebuilt by `crumb audit`"; stale-report even says "planned, Phase 6"). Projections are committed by default, so every user repo permanently carries placeholder files that misstate their provenance. | `templates/project-memory/generated/*.md`; `docs/record-schema.md:33-36,81-83` | Have `cmd_audit` write `stale-report.md` (and reindex write `memory-index.md`), **or** drop/reword both templates and record-schema §2 | `code` |
| **MF-27** | Med | No lint, formatter, or type-checker anywhere — the whole static-analysis burden falls on review rounds (this is the sixth) | no ruff/flake8/mypy config; no such job in `ci.yml` | Add a `lint` job: `ruff check` + `ruff format --check` (config in `pyproject.toml`); optionally `mypy breadcrumbs/` — the code is already well annotated | `repro` |
| **MF-28** | Low | `STATIC_RESOURCES`/`TEMPLATE_RESOURCES` are dead code with a false comment ("consumed by the server"); `mcp_server.py:141-169` binds all 8 resources explicitly and nothing references the registries | `mcp_core.py:150-162` | Delete them, or add a test asserting bound URIs == registry keys | `repro` (zero references outside the definition) |
| **MF-29** | Low | Missing-store envelope test covers 8 of 10 tools (omits `tool_verify`, `tool_reindex`); `tool_record`'s medium/high-without-evidence branch and `resource_attempt`'s unknown-id rejection are untested | `tests/test_mcp.py:277-296` | Extend the tuple; add two small tests | `inherited` |
| **MF-30** | Low | Bundled store README never mentions `verifications/` — the directory `crumb verify` writes to | `templates/project-memory/README.md` | Add a row | `repro` (0 occurrences) |
| **MF-31** | Low | `__init__.py:17-21` claims importing the package avoids importing the CLI; line 26 unconditionally does `from breadcrumbs.cli import …`. The static-read claim holds only for setuptools | `breadcrumbs/__init__.py` | Reword, or make the re-exports lazy via module `__getattr__` | `repro` |
| **MF-32** | Low | Stray review file at repo root: `crumb-kit-agentic-review-2026-06-26.md.txt` (34 KB, double extension). Review docs live in `docs/`, and its findings shipped in 0.1.2/0.1.3; by the repo's own convention (review #3's doc was deleted once resolved) it should go | repo root; referenced by `docs/crumb-kit-agentic-review-2026-06-27.md:10` | Remove or move to `docs/` as `.md`; update that reference line | `repro` |
| **MF-33** | Low | Dangling CHANGELOG reference to `docs/crumb-kit-system-review-2026-07-01.md`, deleted in `a4da5c0` | `CHANGELOG.md:34` | Annotate "(doc since removed)" or link the PR | `repro` |
| **MF-34** | Low | README install line still says `pipx install crumb-kit  # from a published artifact (future)` — 0.1.7 has been live on PyPI since 2026-07-02 | `README.md:56` | Drop "(future)" | `repro` |
| **MF-35** | Low | RELEASING.md Path B says to scope a PyPI token to the `breadcrumbs` project; the project is `crumb-kit` | `RELEASING.md:91-92` | Fix the name; add a one-line warning that Path B bypasses every guardrail Path A adds | `repro` |
| **MF-36** | Low | Two spec/behavior mismatches: record-schema says session Files Touched uses `git diff --stat` (actual since 0.1.2: `--shortstat`); cli-spec says `guard` writes an optional session note (`cmd_guard` performs no writes) | `docs/record-schema.md:308`; `docs/cli-spec.md:41` | Correct both | `repro` |
| **MF-37** | Low | Contributor tooling undeclared: `CLAUDE.md` says `python -m pytest -q`, but pytest is declared nowhere (no dev extra, no requirements file) and CI runs `unittest discover`; no `[tool.pytest.ini_options]`, so a stray root `.pytest_cache` appears | `CLAUDE.md`, `pyproject.toml` | Add `[project.optional-dependencies] dev = ["pytest", "build", "twine"]` + `testpaths = ["tests"]`, **or** make `unittest discover` the documented canonical runner | `repro` (pytest not importable in a clean env) |
| **MF-38** | Low | Neither workflow sets a top-level `permissions:` block, so both run with the repo-default token scope (`release.yml` sets it only on the publish job, for OIDC) | `.github/workflows/*.yml` | Add top-level `permissions: contents: read` | `repro` |
| **MF-39** | Low | Actions pinned to mutable refs — notably `pypa/gh-action-pypi-publish@release/v1`, a moving branch on the OIDC-publishing path | `release.yml:168` and both workflows | Pin to commit SHAs, at minimum in `release.yml` | `repro` |
| **MF-40** | Low | No `concurrency` group anywhere: `ci.yml` triggers on both `push` and `pull_request` (doubled runs), and two simultaneous publish dispatches can race past both pre-flights | both workflows | Add `concurrency` groups | `repro` |
| **MF-41** | Low | The `mcp` CI job asserts 10 tools + 6 prompts but not the 8 resources the README/mcp-spec advertise | `ci.yml` (mcp job) | Assert the resource count too | `repro` |
| **MF-42** | Low | Test matrix is 3.9/3.11/3.12 — 3.10 is exercised only in the `mcp` job, and 3.13/3.14 are current and untested despite unbounded `requires-python` | `ci.yml` (test matrix) | Add 3.10, 3.13, 3.14 | `repro` |

---

## Deferred — decide explicitly, don't let them rot

| ID | Item | Source | Why deferred | What would change the call |
|---|---|---|---|---|
| **D1** | Optional streamable-HTTP MCP transport (Codex cloud supports no stdio MCP; Claude web needs a setup-script bootstrap) | Agentic review #2 F9 | Depends on the optional MCP SDK and a real cloud harness to validate; out of scope for a stdlib-only change set | A user actually blocked on Codex cloud, or the HTTP transport becoming testable offline |
| **D2** | Confusing dual staleness numbers: `stale_days` (a threshold) vs "handoff N days old" (an age) | Agentic review #2 F10 | Cosmetic | A field rename lands anyway during the Batch 3 work |
| **D3** | FastMCP self-reports its own version (`1.28.1`), not the package version | Agentic review #2 F11 (partial) | The FastMCP version API is SDK-version-fragile and untestable in the stdlib-only suite; risking server startup wasn't worth it | The SDK exposing a stable way to set it |
| **D4** | Split `cli.py` (5,942 lines, 183 top-level defs) into modules | Review #5 §5, audit #6 §5 | Large, and best done *as* the vehicle for other fixes rather than as a big-bang refactor | Do it while fixing MF-09/MF-15 — both are duplication bugs a split with shared utilities would have prevented. Audit #6 adds a third: **three** separate notions of "is this projection current" (`_inputs_hash`, `_packet_is_stale`, `detect_packet_drift`), each with a different blind spot |

---

## Traceability

Original review ID → master ID. Use this when reading an old review doc.

| Origin | Master |
|---|---|
| #5 H1, H2 | MF-01, MF-02 (shipped) |
| #5 H3 | MF-03 (shipped) |
| #5 H4 + #5 M5 + #6 N3 | **MF-04** (merged, shipped) |
| #5 H5 | MF-11 |
| #5 M1 | MF-05 (shipped) |
| #5 M2 + #5 Low (`cmd_resume` non-atomic write) | **MF-09** (merged) |
| #5 M3 | MF-15 |
| #5 M4 | MF-08 |
| #5 M6 + #5 M7 + #6 N4 | **MF-14** (merged) |
| #5 M8 | MF-16 |
| #5 M9 | MF-10 |
| #5 M10 | MF-26 |
| #5 M11, M12, M13 | MF-12, MF-13, MF-27 |
| #5 Lows (parser/validate) | MF-22, MF-23 |
| #5 Lows (CLI UX) | MF-19, MF-20, MF-21 |
| #5 Lows (MCP) | MF-24, MF-25, MF-28, MF-29 |
| #5 Lows (docs/templates/hygiene) | MF-30 … MF-37 |
| #5 Lows (CI) | MF-38 … MF-42 |
| #6 N1, N2, N5, N6 | MF-06, MF-07, MF-17, MF-18 |
| Agentic #2 F9, F10, F11 | D1, D2, D3 |
| #5 §5 + #6 §5 (structural) | D4 |
