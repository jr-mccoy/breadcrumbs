# crumb-kit — Master Fix List

**Living document.** Every finding from every review round, merged, deduplicated,
and worked as a queue. Add a `CHANGELOG.md` entry in the same commit as the fix,
and mark the batch SHIPPED here with a one-line summary per item — the shipped
sections stay, so the next reviewer can see what was decided and why rather than
re-reporting it.

**State as of 2026-07-25** (`main` @ `10cd505`, `crumb-kit` 0.1.7, record
`schema_version` 1): **0 open items** — every finding from every review round
(MF-01 … MF-42) has shipped and is recorded in `CHANGELOG.md` `[Unreleased]`.
Four items remain **explicitly deferred** (D1–D4), each with the condition that
would reopen it. Nothing is queued: the next entry in this file will come from the
next review round, or from D1–D4 being taken up.

## Sources

| Round | Document | Status of its findings |
|---|---|---|
| Agentic review #1 (2026-06-26) | doc deleted in Batch 6 (MF-32) | Resolved in 0.1.2/0.1.3 — nothing open |
| Agentic review #2 (2026-06-27) | `docs/crumb-kit-agentic-review-2026-06-27.md` | Resolved except F9/F10/F11-partial → **D1–D3** |
| System review #3 (2026-07-01) | doc deleted in `a4da5c0` | R1–R26 resolved in 0.1.6 |
| System review #4 | folded into 0.1.6 | Resolved |
| System review #5 (2026-07-18) | `docs/crumb-kit-system-review-2026-07-18.md` | **Fully resolved** — all H, M and Low findings shipped as MF-01 … MF-42 |
| System audit #6 (2026-07-24) | `docs/crumb-kit-system-audit-2026-07-24.md` | N1–N6 all shipped (in MF-06/MF-07/MF-04/MF-14/MF-17/MF-18) — nothing open |

**Verification legend** (historical — every item below has since shipped, and each
was independently reproduced against a throwaway store immediately before its fix):

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

## Batch 6 — Templates, docs, tests, CI hygiene — **SHIPPED** (`[Unreleased]`)

All seventeen are fixed; see `CHANGELOG.md`. Mechanical and low-risk, done in one
sweep, with one exception: MF-27 introduced the repo's first static analysis and
is the reason nine of the others will not recur silently.

- **MF-26** (review #5 M10) — **dropped, not implemented.** `generated/stale-report.md`
  and `generated/memory-index.md` are removed from the bundled template, and
  `docs/record-schema.md` §1/§2 plus the bundled `generated/README.md` no longer
  list them. Generating them was the alternative; it was rejected because `audit`
  is a read-only health check that CI runs, writing a committed report on every
  run would add diff churn plus a third staleness surface, and neither file carried
  information `audit`/`search` do not already produce. Decisive evidence: not one
  of the eleven fixtures ships either file — only `init` created them.
- **MF-27** (review #5 M13) — a `lint` job runs `ruff check` + `ruff format --check`;
  config lives in `pyproject.toml` (`line-length = 100`, `target-version = "py39"`,
  E501 off because the formatter owns layout). The ten findings the first run
  surfaced are fixed. `ruff format` was applied to the tree in a **separate,
  mechanical commit** so this batch stayed reviewable. `mypy` was not added — the
  optional-`mcp`-SDK import dance and the dict-shaped record/finding payloads would
  need either stubs or a wall of `ignore`s to pass, which is a change worth its own
  decision rather than a rider on a hygiene sweep.
- **MF-28** (review #5 Low) — the registries are kept as the *declared* resource
  surface (the "8 resources" the docs advertise), the false "consumed by the
  server" comment is corrected, and `tests/test_mcp.py` pins the bound URIs to the
  registry keys by reading `build_server`'s decorators from the AST — so the check
  runs without the optional SDK. The CI `mcp` job asserts the live count (MF-41).
- **MF-29** (review #5 Low) — the missing-store envelope test enumerates all ten
  tools by name and fails if `mcp_core` grows an eleventh that is not listed.
  `tool_record`'s explicit medium/high-without-evidence branch is covered by
  MF-24's test; the templated resources' unknown-id rejection has its own (and
  shows a traversal-shaped id is just another miss — lookup is by record id, never
  by path).
- **MF-30** (review #5 Low) — `verifications/` has a row in the bundled store README.
- **MF-31** (review #5 Low) — the re-exports are lazy (PEP 562 `__getattr__`), so
  "importing the package does not import the CLI" is true for a real
  `import breadcrumbs`, not only for setuptools' static read.
- **MF-32** (review #5 Low) — `crumb-kit-agentic-review-2026-06-26.md.txt` is deleted
  and the one reference to it (in the 06-27 review) explains where it went.
- **MF-33** (review #5 Low) — the dangling `CHANGELOG.md` link is annotated
  "doc since removed in `a4da5c0`, once every finding had shipped".
- **MF-34** (review #5 Low) — the README install line reads `# from PyPI`.
- **MF-35** (review #5 Low) — Path B scopes its token to `crumb-kit`, explains that
  `breadcrumbs` is the import package and the repo, and opens with a warning that
  Path B has no pre-flight, no test run, no CI gate, and no tag or Release.
- **MF-36** (review #5 Low) — `docs/record-schema.md` says `git diff --shortstat`
  and `docs/cli-spec.md`'s `guard` row says read-only, `guard` writes nothing.
- **MF-37** (review #5 Low) — `unittest discover -s tests` is documented as the
  canonical runner (it needs nothing installed, which is the point of a
  zero-dependency package); a `[dev]` extra declares pytest/ruff/build/twine and
  `[tool.pytest.ini_options] testpaths` stops the stray root `.pytest_cache`.
- **MF-38** (review #5 Low) — both workflows floor at top-level `permissions:
  contents: read`.
- **MF-39** (review #5 Low) — every action is pinned to a 40-hex commit SHA with
  its version in a trailing comment. Resolved on 2026-07-25: `actions/checkout`
  v4.4.0, `actions/setup-python` v5.6.0, `actions/upload-artifact` v4.6.2,
  `actions/download-artifact` v4.3.0, and `pypa/gh-action-pypi-publish` at the head
  of the `release/v1` **branch** — which is what made it the worst offender.
- **MF-40** (review #5 Low) — `ci` supersedes stale runs of the same ref (never on
  `main`); `release` serializes with `cancel-in-progress: false`, because
  cancelling mid-publish is how a version lands on PyPI with no tag.
- **MF-41** (review #5 Low) — the `mcp` job asserts the 8 resources against the
  `mcp_core` registries, not just a count.
- **MF-42** (review #5 Low) — the test matrix is 3.9, 3.10, 3.11, 3.12, 3.13, 3.14.

`tests/test_release_process.py` gained a `WorkflowHygieneTests` class covering
MF-27 and MF-38 … MF-42 across **both** workflows, so none of them can regress
into a workflow nobody reads.

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
| #5 M10 | MF-26 (shipped — dropped the templates) |
| #5 M11, M12 | MF-12, MF-13 (shipped) |
| #5 M13 | MF-27 (shipped) |
| #5 Lows (parser/validate) | MF-22, MF-23 (shipped) |
| #5 Lows (CLI UX) | MF-19, MF-20, MF-21 (shipped) |
| #5 Lows (MCP) | MF-24, MF-25, MF-28, MF-29 (shipped) |
| #5 Lows (docs/templates/hygiene) | MF-30 … MF-37 (shipped) |
| #5 Lows (CI) | MF-38 … MF-42 (shipped) |
| #6 N1, N2 | MF-06, MF-07 (shipped) |
| #6 N5, N6 | MF-17, MF-18 (shipped) |
| Agentic #2 F9, F10, F11 | D1, D2, D3 |
| #5 §5 + #6 §5 (structural) | D4 |
