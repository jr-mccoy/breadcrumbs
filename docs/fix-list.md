# crumb-kit — Master Fix List

**Living document.** Every unresolved finding from every review round, merged,
deduplicated, and ordered as a work queue. Delete an item when it ships; add a
`CHANGELOG.md` entry in the same commit.

**State as of 2026-07-25** (`main` @ `10cd505`, `crumb-kit` 0.1.7, record
`schema_version` 1): **17 open items** — 0 High, 2 Medium, 15 Low — plus 4
explicitly deferred. Batches 1–5 (MF-01 … MF-25) have shipped and are recorded in
`CHANGELOG.md` `[Unreleased]`; nothing else below has. **No High-severity item is
open**, and everything still open is in Batch 6.

## Sources

| Round | Document | Status of its findings |
|---|---|---|
| Agentic review #1 (2026-06-26) | `crumb-kit-agentic-review-2026-06-26.md.txt` (repo root) | Resolved in 0.1.2/0.1.3 — nothing open |
| Agentic review #2 (2026-06-27) | `docs/crumb-kit-agentic-review-2026-06-27.md` | Resolved except F9/F10/F11-partial → **D1–D3** |
| System review #3 (2026-07-01) | doc deleted in `a4da5c0` | R1–R26 resolved in 0.1.6 |
| System review #4 | folded into 0.1.6 | Resolved |
| System review #5 (2026-07-18) | `docs/crumb-kit-system-review-2026-07-18.md` | All five H shipped (H1–H5), plus M1–M9/M11/M12 (MF-01 … MF-25); M10/M13 **open**, and the Lows that Batch 5 did not cover |
| System audit #6 (2026-07-24) | `docs/crumb-kit-system-audit-2026-07-24.md` | N1–N6 all shipped (in MF-06/MF-07/MF-04/MF-14/MF-17/MF-18) — nothing open |

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

## Batch 3 — Multi-machine correctness — **SHIPPED** (`[Unreleased]`)

All five projection/freshness defects are fixed, and the missing fixture exists;
see `CHANGELOG.md`. Everything here was invisible on one machine and wrong the
moment a second one existed, which is exactly why the suite stayed green.

- **MF-06** (audit #6 N1) — `_inputs_hash` hashes only what the store's own policy
  shares: `sessions/` is skipped under `session_tracking: distillate`, as is any
  record directory the **committed** `.gitignore` excludes (machine-local excludes
  like `.git/info/exclude` are deliberately not consulted — folding a personal
  exclude into a shared stamp would recreate the bug). The policy value is part of
  the hash, so a flip invalidates once. A clone with no `sessions/` and the
  author's checkout now agree, ending the permanent `validate` ping-pong.
- **MF-07** (audit #6 N2) — the packet records the project path as `.` in both the
  rendered file and `--json`, so nothing publishes the author's absolute host path
  into a shared repo, a byte-identical checkout at another path is no longer read
  as stale, and two developers stop rewriting that line at each other.
  `_strip_packet_volatile` also drops the project line, covering packets written by
  older versions.
- **MF-08** (review #5 M4) — each file's store-relative path plus separators are
  folded into the hash, so a rename (which changes every derived record id) and a
  move of text between records both invalidate the stamp. Invalidates existing
  stamps once — called out in `CHANGELOG.md` as required.
- **MF-09** (review #5 M2 + the `cmd_resume` atomic-write Low) — `cmd_resume`'s
  store-global write goes through `try_reindex_projections`, so
  `guard-prefilter.json` is rebuilt with the packet (guard no longer stays blind to
  a newly recorded trap) and both files are written atomically. `--fast`/`--task`
  stay print-only.
- **MF-10** (review #5 M9) — the local-only branch of the managed `.gitignore`
  block also ignores `generated/*.json`, and the pre-filter is documented in the
  bundled `generated/README.md`, `docs/record-schema.md` and `docs/cli-spec.md`.
- **Fixture 11** (`fixtures/fixture-11-multi-machine/`) — the multi-developer store
  the batch called for: `distillate`, no `sessions/`, committed packet + pre-filter,
  `AGENTS.md` signpost. `tests/test_multi_machine.py` checks it out at two paths and
  requires `validate`, `audit` and `doctor` clean at both, the committed packet
  accepted unchanged at either, and identical bytes from a reindex on either.

---

## Batch 4 — Release process — **SHIPPED** (`[Unreleased]`)

All three release-process items are fixed; see `CHANGELOG.md`. The workflow now
has tests — it had none, which is how a pre-flight that made a partial publish
permanent, and a publish path that never ran the suite, both shipped.

- **MF-11** (review #5 H5) — the pre-flight blocks on "already on PyPI" only when
  tag `v$VERSION` also exists. Published-but-untagged is a *recovery*: the run
  continues, the upload no-ops on `skip-existing`, and the tag + Release step
  completes the release. The recovery is refused when the version is not the
  newest on PyPI (so it can't re-tag an old version), and an existing tag for an
  unpublished version (a dead tag) still stops the run. The logic moved to
  `.github/scripts/release_preflight.py`, unit-tested in
  `tests/test_release_process.py`. The workflow comment, `RELEASING.md` and
  `CLAUDE.md` all describe the real recovery now.
- **MF-12** (review #5 M11) — the build job runs `python -m unittest discover -s
  tests` in **both** modes, and `publish` additionally requires the `ci` workflow
  to have concluded `success` on the exact commit (covering the fixture/guard/MCP
  checks and the Python matrix the release build doesn't repeat).
  `RELEASING.md`'s "runs every check CI does" is corrected to what dry-run
  actually runs.
- **MF-13** (review #5 M12) — `RELEASING.md` gained a *Tag / PyPI history* table
  recording the three entries that break the tags-equal-releases invariant:
  `v0.1.5` (tag only), `v0.1.6` (tag + Release, never published), and `0.1.2`
  (on PyPI, never tagged — left untagged deliberately rather than hand-tagged).
  Re-verified against the GitHub tag/release lists and the PyPI JSON API on
  2026-07-25; the audit's data was right except that `v0.1.5` has **no** attached
  Release. Deleting the two dead tags remains the maintainer's call — the
  workflow refuses to re-use them either way.

---

## Batch 5 — Input validation, correctness edges, MCP surface — **SHIPPED** (`[Unreleased]`)

All twelve are fixed; see `CHANGELOG.md`. The through-line is inputs the code
trusted without checking — a flag value, a fenced heading, a truncated slug, a
date-shaped filename — and three MCP payload contracts that did not match their
own spec.

- **MF-14** (review #5 M6 + M7 + audit #6 N4) — `crumb init` validates
  `--with-hooks` against `HOOK_EVENTS` and `--with-adapter` against
  `ADAPTER_FILENAMES` **before any filesystem mutation**, exiting 2 with the valid
  values named. `--with-hooks=bogus` no longer scaffolds the store, writes
  `.gitignore` and *then* dies on a raw `KeyError`, and `--with-adapter=README.md`
  no longer injects the managed block into a file removal cannot find.
  `resolve_integration_plan` raises `ValueError` on the same input as a backstop
  for non-`cmd_init` callers. For stores already in the bad state,
  `discover_adapter_blocks` scans the project root (bounded by size) so
  `--remove-integrations` reverses a stray block too. `doctor` was left reporting
  only the canonical files — removal is what made the injection irreversible.
- **MF-15** (review #5 M3) — `Record.sections` is `split_md_sections(self.body)`.
  One splitter; the fence-blind copy is gone, along with `_SECTION_RE`. Duplicate
  headings now merge rather than last-wins, matching the dict view's contract.
  **D4 was considered here and deferred again** — see the Deferred table.
- **MF-16** (review #5 M8) — `tool_record` wraps `cli.write_record` in
  `try/except ValueError` and returns `{ok: False, error}`, matching the other
  three writers and the spec.
- **MF-17** (audit #6 N5) — `_rel`/`_relativize` in `mcp_core` make every tool
  `path` store-relative (`decisions/2026-07-24-x.md`). `docs/mcp-spec.md` states
  the rule for the whole tool surface. Narrower than written: Batch 3's MF-07 had
  already made the resume packet's project path relative, so only the write-tool
  payloads remained. A sweep test asserts no tool result contains the host path.
- **MF-18** (audit #6 N6) — `question_item_id` appends a 6-hex digest of the full
  question when the slug is truncated; short ids are unchanged (fixture 11's
  `q:should-the-worker-own-its-own-schema-migrations` still resolves).
  `_disambiguate_item_ids` catches any residual duplicate from any source,
  including traps, which derive ids from a heading prefix.
- **MF-19** (review #5 Low) — `if heading not in sections:` instead of
  `setdefault(heading, input(...))`.
- **MF-20** (review #5 Low) — `cmd_hook` validates `hook_event` against
  `HOOK_EVENTS` before `_read_hook_stdin()`.
- **MF-21** (review #5 Low) — `_prompt_yes` and `prompt_session_tracking` let
  `KeyboardInterrupt` propagate (`EOFError` still takes the default); `main`
  catches it, prints `aborted.` and returns 130. `prompt_session_tracking` had the
  same defect and is fixed with it — it ran *before* the scaffold, so Ctrl+C there
  silently chose `full` and built a store.
- **MF-22** (review #5 Low) — an unquoted scalar that starts with `#` after
  inline-comment stripping parses as `None`.
- **MF-23** (review #5 Low) — `RECORD_STEM_RE` requires a `[a-z0-9-]` slug and
  `derive_identity` requires a real calendar date. `docs/record-schema.md` §5 and
  the §16.4 finding both state the rule. This *newly* fails validate on
  hand-created records with impossible dates or stray slug characters — the point
  of the check.
- **MF-24** (review #5 Low) — the fork is kept and stated rather than removed:
  the CLI's exit 2 names the flag a human forgot, and a tool call has no such
  conversation, so `low` is what "stated no confidence" records. The lying
  parity comment in `mcp_core` is corrected and `docs/mcp-spec.md` documents the
  divergence. Explicit `medium`/`high` without evidence stays an error on both.
- **MF-25** (review #5 Low) — `_INSTALL_HINT` says the SDK needs Python ≥ 3.10 and
  that the command installs nothing on 3.9.

## Batch 6 — Templates, docs, tests, CI hygiene

Mechanical and low-risk. Worth doing in one sweep.

| ID | Sev | Item | Location | Fix | Ver |
|---|---|---|---|---|---|
| **MF-26** | Med | `stale-report.md` and `memory-index.md` are never generated by anything, and their placeholder text claims otherwise ("Rebuilt by `crumb audit`"; stale-report even says "planned, Phase 6"). Projections are committed by default, so every user repo permanently carries placeholder files that misstate their provenance. | `templates/project-memory/generated/*.md`; `docs/record-schema.md:33-36,81-83` | Have `cmd_audit` write `stale-report.md` (and reindex write `memory-index.md`), **or** drop/reword both templates and record-schema §2 | `code` |
| **MF-27** | Med | No lint, formatter, or type-checker anywhere — the whole static-analysis burden falls on review rounds (this is the sixth) | no ruff/flake8/mypy config; no such job in `ci.yml` | Add a `lint` job: `ruff check` + `ruff format --check` (config in `pyproject.toml`); optionally `mypy breadcrumbs/` — the code is already well annotated | `repro` |
| **MF-28** | Low | `STATIC_RESOURCES`/`TEMPLATE_RESOURCES` are dead code with a false comment ("consumed by the server"); `mcp_server.py:141-169` binds all 8 resources explicitly and nothing references the registries | `mcp_core.py:177-189` | Delete them, or add a test asserting bound URIs == registry keys | `repro` (zero references outside the definition) |
| **MF-29** | Low | Missing-store envelope test covers 8 of 10 tools (omits `tool_verify`, `tool_reindex`); `tool_record`'s medium/high-without-evidence branch and `resource_attempt`'s unknown-id rejection are untested | `tests/test_mcp.py:414-433` | Extend the tuple; add two small tests | `inherited` |
| **MF-30** | Low | Bundled store README never mentions `verifications/` — the directory `crumb verify` writes to | `templates/project-memory/README.md` | Add a row | `repro` (0 occurrences) |
| **MF-31** | Low | `__init__.py:17-21` claims importing the package avoids importing the CLI; line 26 unconditionally does `from breadcrumbs.cli import …`. The static-read claim holds only for setuptools | `breadcrumbs/__init__.py` | Reword, or make the re-exports lazy via module `__getattr__` | `repro` |
| **MF-32** | Low | Stray review file at repo root: `crumb-kit-agentic-review-2026-06-26.md.txt` (34 KB, double extension). Review docs live in `docs/`, and its findings shipped in 0.1.2/0.1.3; by the repo's own convention (review #3's doc was deleted once resolved) it should go | repo root; referenced by `docs/crumb-kit-agentic-review-2026-06-27.md:10` | Remove or move to `docs/` as `.md`; update that reference line | `repro` |
| **MF-33** | Low | Dangling CHANGELOG reference to `docs/crumb-kit-system-review-2026-07-01.md`, deleted in `a4da5c0` | `CHANGELOG.md:267` | Annotate "(doc since removed)" or link the PR | `repro` |
| **MF-34** | Low | README install line still says `pipx install crumb-kit  # from a published artifact (future)` — 0.1.7 has been live on PyPI since 2026-07-02 | `README.md:56` | Drop "(future)" | `repro` |
| **MF-35** | Low | RELEASING.md Path B says to scope a PyPI token to the `breadcrumbs` project; the project is `crumb-kit` | `RELEASING.md:91-92` | Fix the name; add a one-line warning that Path B bypasses every guardrail Path A adds | `repro` |
| **MF-36** | Low | Two spec/behavior mismatches: record-schema says session Files Touched uses `git diff --stat` (actual since 0.1.2: `--shortstat`); cli-spec says `guard` writes an optional session note (`cmd_guard` performs no writes) | `docs/record-schema.md:325`; `docs/cli-spec.md:41` | Correct both | `repro` |
| **MF-37** | Low | Contributor tooling undeclared: `CLAUDE.md` says `python -m pytest -q`, but pytest is declared nowhere (no dev extra, no requirements file) and CI runs `unittest discover`; no `[tool.pytest.ini_options]`, so a stray root `.pytest_cache` appears | `CLAUDE.md`, `pyproject.toml` | Add `[project.optional-dependencies] dev = ["pytest", "build", "twine"]` + `testpaths = ["tests"]`, **or** make `unittest discover` the documented canonical runner | `repro` (pytest not importable in a clean env) |
| **MF-38** | Low | Neither workflow sets a **top-level** `permissions:` block, so anything without a job-level one runs with the repo-default token scope. `release.yml` now scopes both of its jobs (publish for OIDC, build for the MF-12 CI gate); `ci.yml` has none at all | `.github/workflows/*.yml` | Add top-level `permissions: contents: read` to both | `repro` (re-checked 2026-07-25, after Batch 4) |
| **MF-39** | Low | Actions pinned to mutable refs — notably `pypa/gh-action-pypi-publish@release/v1`, a moving branch on the OIDC-publishing path | `release.yml:227` (was `:168` before Batch 4) and both workflows | Pin to commit SHAs, at minimum in `release.yml` | `repro` |
| **MF-40** | Low | No `concurrency` group anywhere: `ci.yml` triggers on both `push` and `pull_request` (doubled runs), and two simultaneous publish dispatches can race past both pre-flights | both workflows | Add `concurrency` groups | `repro` |
| **MF-41** | Low | The `mcp` CI job asserts 10 tools + 6 prompts but not the 8 resources the README/mcp-spec advertise | `ci.yml` (mcp job) | Assert the resource count too | `repro` |
| **MF-42** | Low | Test matrix is 3.9/3.11/3.12 — 3.10 is exercised only in the `mcp` job, and 3.13/3.14 are current and untested despite unbounded `requires-python` | `ci.yml` (test matrix) | Add 3.10, 3.13, 3.14 | `repro` |

---

## Deferred — decide explicitly, don't let them rot

| ID | Item | Source | Why deferred | What would change the call |
|---|---|---|---|---|
| **D1** | Optional streamable-HTTP MCP transport (Codex cloud supports no stdio MCP; Claude web needs a setup-script bootstrap) | Agentic review #2 F9 | Depends on the optional MCP SDK and a real cloud harness to validate; out of scope for a stdlib-only change set | A user actually blocked on Codex cloud, or the HTTP transport becoming testable offline |
| **D2** | Confusing dual staleness numbers: `stale_days` (a threshold) vs "handoff N days old" (an age) | Agentic review #2 F10 | Cosmetic | Batch 3 shipped without renaming either field; the next change that touches one anyway |
| **D3** | FastMCP self-reports its own version (`1.28.1`), not the package version | Agentic review #2 F11 (partial) | The FastMCP version API is SDK-version-fragile and untestable in the stdlib-only suite; risking server startup wasn't worth it | The SDK exposing a stable way to set it |
| **D4** | Split `cli.py` (~6,300 lines, 180+ top-level defs) into modules | Review #5 §5, audit #6 §5 | Large, and best done *as* the vehicle for other fixes rather than as a big-bang refactor | **Deferred again at MF-15, explicitly.** MF-15 turned out to be a *deletion* — `Record.sections` became a one-line delegation to the splitter that already existed — so it carried no structural work to ride along with, and pairing a 6,000-line file move with a correctness fix would have made both unreviewable. The vehicle argument has now failed twice (MF-09, MF-15), which is itself the finding: no incidental fix is ever going to be large enough to justify the split, so it needs to be scheduled as its own change with its own review. The three separate notions of "is this projection current" (`_inputs_hash`, `_packet_is_stale`, `detect_packet_drift`) still all exist and remain the strongest argument for doing it |

---

## Traceability

Original review ID → master ID. Use this when reading an old review doc.

| Origin | Master |
|---|---|
| #5 H1, H2 | MF-01, MF-02 (shipped) |
| #5 H3 | MF-03 (shipped) |
| #5 H4 + #5 M5 + #6 N3 | **MF-04** (merged, shipped) |
| #5 H5 | MF-11 (shipped) |
| #5 M1 | MF-05 (shipped) |
| #5 M2 + #5 Low (`cmd_resume` non-atomic write) | **MF-09** (merged, shipped) |
| #5 M3 | MF-15 (shipped) |
| #5 M4 | MF-08 (shipped) |
| #5 M6 + #5 M7 + #6 N4 | **MF-14** (merged, shipped) |
| #5 M8 | MF-16 (shipped) |
| #5 M9 | MF-10 (shipped) |
| #5 M10 | MF-26 |
| #5 M11, M12 | MF-12, MF-13 (shipped) |
| #5 M13 | MF-27 |
| #5 Lows (parser/validate) | MF-22, MF-23 (shipped) |
| #5 Lows (CLI UX) | MF-19, MF-20, MF-21 (shipped) |
| #5 Lows (MCP) | MF-24, MF-25 (shipped); MF-28, MF-29 |
| #5 Lows (docs/templates/hygiene) | MF-30 … MF-37 |
| #5 Lows (CI) | MF-38 … MF-42 |
| #6 N1, N2 | MF-06, MF-07 (shipped) |
| #6 N5, N6 | MF-17, MF-18 (shipped) |
| Agentic #2 F9, F10, F11 | D1, D2, D3 |
| #5 §5 + #6 §5 (structural) | D4 |
