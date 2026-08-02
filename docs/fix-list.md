# crumb-kit — Master Fix List

**Living document.** Every finding from every review round, merged, deduplicated,
and worked as a queue. Add a `CHANGELOG.md` entry in the same commit as the fix,
and mark the batch SHIPPED here with a one-line summary per item — the shipped
sections stay, so the next reviewer can see what was decided and why rather than
re-reporting it.

**State as of 2026-08-02** (`main` @ `c4e31d9`, `crumb-kit` 0.1.7, record
`schema_version` 1): **0 open items.** Every finding from every review round
(MF-01 … MF-64) has shipped and is recorded in `CHANGELOG.md` `[Unreleased]`.
**O1 and O2 were both decided and closed** in Batch 8, along with a live
packaging break the earlier rounds could not have seen (MF-59). **D3 was taken
up** — the SDK now exposes the setter it was waiting for. **D2** closed in Batch
7. **D1 and D4 remain deferred**, each with a sharpened condition below.

*Two earlier stamps were wrong in the same way — a SHA that predated the batches
it claimed to cover. MF-52 fixed the first; this one is `c4e31d9`, the `main`
Batch 8 branched from.*

**Two maintainer decisions are outstanding** and are deliberately not acted on
here — see *Maintainer decisions* at the bottom. Neither is a bug; both change
what users get, so they are the maintainer's call:

1. Everything from MF-01 … MF-64 sits in `CHANGELOG.md` `[Unreleased]` against
   **0.1.7, which is already on PyPI**. Anyone installing `crumb-kit` today gets
   pre-fix behavior — including the MCP break in MF-59, which is now *actively*
   biting anyone whose resolver picks SDK 2.x.
2. `v0.1.5` / `v0.1.6` are dead tags and `0.1.2` is on PyPI untagged.

## Sources

| Round | Document | Status of its findings |
|---|---|---|
| Agentic review #1 (2026-06-26) | doc deleted in Batch 6 (MF-32) | Resolved in 0.1.2/0.1.3 — nothing open |
| Agentic review #2 (2026-06-27) | `docs/crumb-kit-agentic-review-2026-06-27.md` | Resolved except F9/F10/F11-partial → **D1–D3** |
| System review #3 (2026-07-01) | doc deleted in `a4da5c0` | R1–R26 resolved in 0.1.6 |
| System review #4 | folded into 0.1.6 | Resolved |
| System review #5 (2026-07-18) | `docs/crumb-kit-system-review-2026-07-18.md` | **Fully resolved** — all H, M and Low findings shipped as MF-01 … MF-42 (resolution banner added in Batch 7) |
| System audit #6 (2026-07-24) | `docs/crumb-kit-system-audit-2026-07-24.md` | N1–N6 all shipped (in MF-06/MF-07/MF-04/MF-14/MF-17/MF-18) — nothing open (resolution banner added in Batch 7) |
| Doc review #7 (2026-08-02) | this file, Batch 7 | Doc/code drift sweep: MF-43 … MF-55 shipped, D2 taken up as MF-56, two feature gaps filed as O1/O2 |
| Open-items round #8 (2026-08-02) | this file, Batch 8 | O1 and O2 decided and closed, D3 taken up, plus a fresh pass that found a live packaging break (MF-59) and three drift/test-gap items (MF-61 … MF-64) |

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

## Batch 7 — doc/code drift sweep + D2 — **SHIPPED** (`[Unreleased]`)

The first round with no reviewer behind it: a systematic read of every doc against
the code it describes. The through-line is that batches 1–6 changed behavior faster
than the prose describing it, plus a class of text nobody re-reads — a spec's
command table, a bundled template, an audit note — that quietly kept promising
things that were dropped, renamed, or never built.

- **MF-43** (doc review #7) — `docs/cli-spec.md` had **no `search` row and no
  `search` section**: a command shipped in Phase 5 was missing from the document
  whose job is the command surface, so its flags (`--type`, `--status`, `--tag`,
  `--file`, `--stale-days`) were specified nowhere. Added both, including the
  corpus limit the omission hid — `ideas/` and `sessions/` are not searchable
  (see **O1**).
- **MF-44** (doc review #7) — the same file's drift: `--version` missing from the
  global flags, `--task` missing from the `resume` synopsis (it was in the table
  three sections earlier), and a Phase column that marked built commands `2`/`3`/`5`
  while their neighbors said `**built**`. "Later commands (post-MVP)" now says
  outright that none of them exists and none is scheduled.
- **MF-45** (doc review #7) — `docs/security.md` and `docs/cli-spec.md` both sent
  the reader to "the Phase 6 doc" for the secret scanner's covered set and known
  gaps. **No phase doc exists** (same class as MF-33). The record now lives where it
  is actually kept — `SECRET_PATTERNS` in `cli.py`, the controls in
  `tests/test_secrets.py` — and `security.md` §2 states the two deliberate gaps
  (bare hex is only caught in a labeled context; path/CamelCase tokens are
  allowlisted) instead of pointing at nothing.
- **MF-46** (doc review #7) — `docs/architecture.md`, untouched since the June
  rebrand and the only doc where the string "verification" never appeared: the
  taxonomy gained a **Verification** row and a **guard pre-filter** row, "stale
  reports" left the projection list (dropped by MF-26), and the layering diagram
  stopped labelling shipped layers `(Ph8)`/`(Ph9)` as if pending. It also now says
  which two rows are reserved space rather than machinery — `evidence/refs.yml` and
  `index/` (see **O2**).
- **MF-47** (doc review #7) — `docs/record-schema.md` §2 omitted
  `verifications/` from the committed-by-default list although §1 creates it, so
  whether verification records are shared was unanswerable; and §1 listed
  `generated/guard-prefilter.json` under "`crumb init` creates this tree" when
  `init` does not create it (the first `resume`/`reindex` does — as the bundled
  `generated/README.md` already said, contradicting the spec).
- **MF-48** (doc review #7) — `docs/mcp-spec.md` cited "§7" for filename-canonical
  identity (that is §5; §7 is the non-git fallback) and called the hook templates
  "(Phase 9)". It also now documents the packet's two look-alike key pairs:
  `verification` (commands from the handoff) vs `verifications` (records), and the
  threshold vs the measured ages. **Renaming `verification`/`verifications` was
  considered and rejected** — those keys are section names driving `SECTION_CAPS`
  and `TRIM_ORDER`, so a rename edits the bounding machinery, not a label.
- **MF-49** (doc review #7) — the bundled `index/README.md` promised the SQLite FTS
  and vector index "in a later phase", "regenerated by a build command (planned)".
  Nothing builds one; `search` scans records directly. This text ships into every
  user's repo, so the template is what was wrong — it now says the directory is a
  reserved, always-gitignored slot with no writer.
- **MF-50** (doc review #7) — the bundled `generated/README.md` advertised a
  "3k–5k tokens" packet; the bound is `TOKEN_BUDGET_MAX = 5000` with no floor. The
  lower number was invented.
- **MF-51** (doc review #7) — `audit`'s sessions-growth note told users to "consider
  a periodic rollup (forward-ref Phase 10)" — advice to wait for a command that
  does not exist. It now says what a human can do today: promote with `remember`,
  prune the rest.
- **MF-52** (doc review #7) — this file's own state header claimed "0 open items"
  at `main @ 10cd505`, three merges before batches 4–6 landed. Restamped, with the
  error recorded rather than quietly overwritten.
- **MF-53** (doc review #7) — reviews #5 and #6 carried no resolution banner, so
  both still read as live: audit #6's summary asserts "All five High and all
  thirteen Medium findings from review #5 are still present in `main`, verbatim",
  which stopped being true six commits later. Both now open with a resolution
  banner pointing here, and both say their `cli.py` line numbers predate the
  `d293796` reformat. **Kept, not deleted** — the repo's delete-when-resolved policy
  does not apply while D4 is sourced from `#5 §5` + `#6 §5`, exactly as the 06-27
  review is kept for D1/D3.
- **MF-54** (doc review #7) — `fixtures/README.md` opened with "these are populated
  in later phases" above a table where all eleven rows say **built** and a closing
  line saying all eleven run in CI.
- **MF-55** (doc review #7) — release/version honesty, four places: `RELEASING.md`
  Path B said `cd breadcrumbs` before `python -m build`, which from the repo root
  lands in the *package* directory where the build fails (the doc itself explains
  that both are named `breadcrumbs`); `CHANGELOG.md` jumped 0.1.6 → 0.1.4 with no
  word on the missing 0.1.5 and presented 0.1.6 as a release although it never
  reached PyPI; `README.md`'s Status table described this checkout while readers
  install 0.1.7, which predates every fix in `[Unreleased]`; and `security.md` §4
  deferred the high-impact-change enforcement decision to "Phases 6, 9", both long
  shipped — it now states plainly that the decision has not been made and names the
  one mechanism that does block today.
- **MF-56 — D2, taken up** (agentic review #2 F10) — the packet carried exactly one
  staleness number, `stale_days`, which was the **threshold**; the **age** it was
  compared against existed only as English inside a warning string ("handoff is 6
  day(s) old"), so a consumer had the policy as data and the fact as prose. The
  threshold is now `stale_after_days` and the measurements are their own fields,
  `handoff_age_days` / `handoff_commit_distance` (`null` when the timestamp is
  unparseable or there is no git repo). The rendered packet names the cutoff above
  the warnings, and `--stale-days` has one help string everywhere instead of being
  an "aged-unresolved threshold" on `resume`/`audit` and a "recency de-weighting
  threshold" on `guard` — one cutoff described as two things, which was half the
  confusion. `tests/test_resume.py` pins the split, the agreement between
  `handoff_age_days` and the prose, and the `None` path.

---

## Batch 8 — the two open items, decided; D3 taken up; a live packaging break — **SHIPPED** (`[Unreleased]`)

Batch 7 left two product questions and three deferrals. This batch answers both
questions, takes up one deferral because the SDK finally exposed what it was
waiting for, and — from the fresh pass the round was also asked to do — finds a
**break that had already shipped**: the optional `[mcp]` extra installs an SDK the
server cannot import.

The through-line is dependencies and lists that moved while nothing was watching:
an unbounded version range, a CI glob that counted, a fixture roster kept in two
places, a doc pointer left behind in the one copy that was code.

- **MF-57 — O1, decided and closed** (doc review #7) — `ideas/` records are
  **searchable, and still invisible to `guard`**. `crumb note idea` wrote a real,
  validated record that `_candidate_items` never loaded, so `search --type idea`
  was not offered and an idea could only be found by opening the directory. The
  corpus now forks by **who is asking**, not by record type: lookup
  (`crumb search`, the `memory_search` MCP tool) passes `include_ideas=True`;
  judging (`guard`, the `PreToolUse` hook path, `resume --task`'s likely-file
  scoping) does not. The default is the narrow corpus, so a caller that forgets
  the flag makes the safe mistake. The reason for the split is not hypothetical:
  scored in the lookup corpus, **Fixture 12's** idea — an untried hunch whose own
  text says nobody measured it — reaches **8.96** against a `READ_FIRST` band of
  5, i.e. a speculative note would have gated a real edit purely by naming the
  right file. `tests/test_guard.py::SpeculativeIdeaTests` pins the `PROCEED`
  *and* that counterfactual score, so the fixture cannot decay into one that
  would have passed anyway. `sessions/` deliberately stays out of both corpora:
  a `distillate` clone may not have them, so including them would make results
  depend on which checkout you ran in.
- **MF-58 — O2, decided and closed: `evidence/refs.yml` is dropped, not given a
  writer** (doc review #7) — it was scaffolded for the entire life of the package
  and no released version ever read or wrote it. Deciding factors, in order: the
  question it would answer is already answered by the per-record `evidence:`
  frontmatter, which **is** consumed (`resume`'s Likely Relevant Files and
  Verification Commands, `guard`'s next-safest-action, `search`'s path matching);
  a hand-maintained second copy would have had no validator, no consumer, and no
  way to notice a dangling `ref_*` id; and there is no YAML *emitter* in this
  codebase at all — the parser is a deliberate read-only subset — so "give it a
  writer" was a larger change than it sounds. This is MF-26's precedent applied
  again, with MF-26's decisive evidence present too: **not one of the twelve
  fixtures ships an `evidence/` directory.** Note the asymmetry with `index/`,
  which MF-49 *kept*: `index/` is gitignored and costs a user nothing, while
  `refs.yml` shipped **committed**, with example entries and an instruction to
  delete them. Docs updated in all four places (`architecture.md` §3,
  `record-schema.md` §1/§2 and the frontmatter section, the bundled
  `.project-memory/README.md`, and fixture 11's copy of it); old stores can
  delete the file, and nothing looks for it.
- **MF-59 (new, and already shipped broken) — the `[mcp]` extra installs an SDK
  the server cannot import.** `mcp = ["mcp>=1.2; …"]` had no upper bound. MCP SDK
  **2.0 renamed `mcp.server.fastmcp.FastMCP` to `mcp.server.mcpserver.MCPServer`**,
  so a fresh `pip install "crumb-kit[mcp]"` resolves to 2.x, the single hardcoded
  import raises `ModuleNotFoundError`, the module's own graceful-degradation path
  swallows it, and every SDK-present surface — `crumb mcp serve`, `crumb mcp
  doctor`, `crumb doctor` — reports the SDK as **"not installed — run: pip install
  'crumb-kit[mcp]'"**, i.e. tells the user to re-run the command that just
  succeeded. The CI `mcp` job installs the extra unpinned and asserts
  `sdk_available()`, so it fails on this too. Fixed three ways: `mcp_server` tries
  both spellings newest-first (verified against real installs of **mcp 1.29.0 and
  2.0.0** — 10 tools, 6 prompts, 8 resources register identically on both); the
  extra is bounded `mcp>=1.2,<3`; and the CI job gained an `mcp-version` matrix
  axis so a future rename cannot pass unnoticed. `main()` now also prints the
  underlying import error, so "installed but unimportable" stops looking like
  "missing". One SDK-visible difference is documented rather than papered over:
  `list_resource_templates()` returns `uriTemplate` on 1.x and `uri_template` on
  2.x, which CI and `tests/test_mcp.py` both read leniently.
- **MF-60 — D3, taken up** (agentic review #2 F11) — the deferral's condition was
  "the SDK exposing a stable way to set it", and SDK 2.x does:
  `MCPServer(name, version=...)`. The server now advertises the **package**
  version. Whether to pass it is read from `inspect.signature(...)`, not guessed
  from a version string — SDK 1.x has no such parameter and raises `TypeError` on
  one, which is exactly the SDK-version fragility that justified deferring twice.
  On 1.x the old behavior stands (the SDK reports its own version), because there
  is still no way to change it there. Verified live: `0.1.7` on 2.0.0, unset on
  1.29.0.
- **MF-61 (new) — MF-45 missed the one copy that was code.** MF-45 replaced the
  "see the Phase 6 doc" pointers in `security.md` and `cli-spec.md` — no phase doc
  has ever existed — but the same dead reference sat above `SECRET_PATTERNS` in
  `cli.py`, which is where a reader looking for the covered set actually lands. It
  now names the real record: this tuple, `docs/security.md` §2, and
  `tests/test_secrets.py`.
- **MF-62 (new) — the only test of the `init` tree omitted `verifications/`.**
  `EXPECTED_TREE` in `tests/test_init.py` listed `decisions/`, `attempts/`,
  `sessions/` and `ideas/` but not `verifications/.gitkeep`, although the template
  has shipped it since the record type landed and `record-schema.md` §1 documents
  it — so deleting it from the scaffold would have gone unnoticed. Fixed, plus the
  root cause: an inclusion list only catches deletions of the entries someone
  remembered to add, so the tree is now also compared **against the bundled
  template itself**, which catches both directions.
- **MF-63 (new) — a new fixture was invisible to CI and to half the suite.** CI
  looped over `fixtures/fixture-0[2-9]-* fixtures/fixture-1[01]-*`; a
  `fixture-12-*` would simply not have been globbed, and `validate`/`audit` would
  have reported success over eleven of twelve. `tests/test_mcp.py` kept a *second*
  hand-maintained copy of the fixture roster, independent of the one in
  `test_fixtures.py`. Both now derive from the directory (CI globs
  `fixtures/fixture-*/`), and `test_fixtures.py` asserts the registered list
  equals what is on disk — so a fixture that nothing runs is a red suite, not a
  silent gap.
- **MF-64 (new, and it defuses part of D4) — the three "competing" notions of
  projection freshness are one primitive and two complementary detectors.** The
  D4 entry cites `_inputs_hash` / `_packet_is_stale` / `detect_packet_drift` as
  its strongest argument. Reading them: `_inputs_hash` is the primitive that
  *defines* "unchanged"; `detect_packet_drift` asks "is the stamp stale?" (cheap,
  no rebuild — the `validate`/`audit` gate); `_packet_is_stale` asks "would a
  rebuild produce different bytes?" (expensive — `doctor`'s advisory second
  opinion). They disagree in **both** directions, and both were reproduced
  against a throwaway store: an edit to a section the *bounded* packet never
  renders makes the stamp stale while the bytes are identical, and a change to
  the **renderer** changes the bytes while no hash over inputs can see it.
  Neither subsumes the other. A map is now written above `_inputs_hash` and
  `tests/test_audit.py::FreshnessComplementarityTests` pins both directions, so a
  future split — or a well-meant "deduplicate these" — cannot quietly collapse
  them.

---

## Open — not blocking, not forgotten

**None.** O1 and O2 were the last two, and both were decided in Batch 8 (MF-57,
MF-58). New findings go here; a claim of "0 open" is only worth anything if the
next reviewer re-derives it from the code rather than from this line — the last
two state headers were wrong in exactly that way (MF-52).

---

## Deferred — decide explicitly, don't let them rot

| ID | Item | Source | Why deferred | What would change the call |
|---|---|---|---|---|
| **D1** | Optional streamable-HTTP MCP transport (Codex cloud supports no stdio MCP; Claude web needs a setup-script bootstrap) | Agentic review #2 F9 | **Re-examined in Batch 8, still deferred — but the reason has changed.** The transport is *not* the hard part: `run(transport="streamable-http")` exists on both SDK majors, so switching it is one argument. What is missing is everything around it. (a) A `--http` flag needs host/port/path and a documented default. (b) **It binds a network listener that serves the whole project memory with no authentication** — that is a security decision, not a flag, and this repo has a `docs/security.md` that would have to answer it. (c) The stdlib-only suite cannot cover it (needs the SDK plus uvicorn/starlette), so it would live only in the `mcp` CI job. (d) The actual requirement — that a given cloud harness accepts it — is still unverifiable here | An authentication posture decided (even "localhost-only, no auth, documented as such"), **or** a user actually blocked on Codex cloud who can validate the round trip |
| ~~**D2**~~ | ~~Confusing dual staleness numbers~~ | Agentic review #2 F10 | ~~Cosmetic~~ | **Closed — taken up in Batch 7 as MF-56.** Deferred twice as cosmetic; it was not. The threshold was the only one of the two numbers a machine could read, so every consumer that wanted the age had to parse a warning sentence to get it |
| ~~**D3**~~ | ~~FastMCP self-reports its own version (`1.28.1`), not the package version~~ | Agentic review #2 F11 (partial) | ~~SDK-version-fragile~~ | **Closed — taken up in Batch 8 as MF-60.** The stated condition was met: SDK 2.x takes `version=` on the constructor. The fragility that justified deferring is real and is handled by reading `inspect.signature` rather than a version string — 1.x raises `TypeError` on the same kwarg, and keeps the old behavior |
| **D4** | Split `cli.py` (~6,800 lines, 190+ top-level defs — it grows every round) into modules | Review #5 §5, audit #6 §5 | Large; needs its own change and its own review | **Deferred a third time, and the case for it is now weaker than it looked.** The "ride along with another fix" plan failed at MF-09 and MF-15, which was the finding: no incidental fix will ever be big enough to justify it, so it must be scheduled standalone. Batch 8 did not become that vehicle either — pairing a 6,800-line move with a live packaging break (MF-59) and two product decisions would have made all four unreviewable, which is the exact mistake this row already records twice. What *did* change: **MF-64 examined the freshness trio this row cites as its strongest argument and found it is not one.** `_inputs_hash` is the primitive; the other two are complementary detectors that each catch a class the other cannot, reproduced in both directions and now pinned by a test. So the remaining argument is plain size, not tangled semantics. Batch 8 paid down the precondition instead: the map lives above `_inputs_hash`, and a splitter must keep all three together or carry that comment with `_inputs_hash`. **Anyone taking this up:** do it as a pure move, no behavior change, in a commit that does nothing else; `tests/test_release_process.py` asserts workflow guarantees by grepping YAML as text, and several tests import through the `crumb.py` shim, which re-exports `breadcrumbs.cli`'s module namespace flatly (tests that monkeypatch must patch the real module — see `test_guard.py` / `test_audit.py`) |

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
| Agentic #2 F9 | D1 (still deferred — condition sharpened in Batch 8) |
| Agentic #2 F10 | D2 → **MF-56** (shipped, Batch 7) |
| Agentic #2 F11 | D3 → **MF-60** (shipped, Batch 8) |
| #5 §5 + #6 §5 (structural) | D4 (still deferred; its freshness-trio argument answered by MF-64) |
| Doc review #7 (docs vs code) | MF-43 … MF-55 (shipped) |
| Doc review #7 (feature gap: unsearchable ideas) | O1 → **MF-57** (shipped, Batch 8) |
| Doc review #7 (feature gap: `evidence/refs.yml`) | O2 → **MF-58** (shipped, Batch 8 — dropped, not written) |
| Round #8 fresh pass (packaging) | **MF-59** (shipped — a live break, not from any review) |
| Round #8 fresh pass (drift + test gaps) | MF-61 … MF-64 (shipped) |

---

## Maintainer decisions — raised, deliberately not acted on

Neither is a bug. Both change what users get, so they are not an agent's call.

### 1. Cut 0.1.8?

Every fix from **MF-01 … MF-64** sits in `CHANGELOG.md` `[Unreleased]`, against a
`__version__` of **0.1.7 — which is already on PyPI**. So `pip install crumb-kit`
today gives pre-fix behavior: the fail-open guard hook (MF-01), the porcelain
path-truncation bug (MF-03), the release pre-flight that made a partial publish
permanent (MF-11), and now **MF-59**, which is the one actively getting worse —
every day makes it likelier that a user's resolver picks MCP SDK 2.x, and the
released `crumb-kit` then reports its own MCP server as "not installed".

Cutting the release is two edits and a workflow run: bump `__version__` in
`breadcrumbs/__init__.py` (the single source of truth — do not add a literal
anywhere else), date the `[Unreleased]` section, merge to `main`, then *Actions →
release → Run workflow* with `mode=dry-run` and, once clean, `mode=publish`. The
workflow cuts the tag and the GitHub Release itself, on the commit it builds.

**Not done here, because choosing a version number and publishing to an immutable
index is the maintainer's decision.** (A PyPI version is permanent; there is no
re-publish.)

### 2. Delete the dead tags?

`v0.1.5` (tag only, no Release, never published) and `v0.1.6` (tag + Release,
never published) both break the tags-equal-releases invariant, and `0.1.2` is on
PyPI with no tag. All three are documented in `RELEASING.md` → *Tag / PyPI
history*, re-verified against the GitHub tag/release lists and the PyPI JSON API
on 2026-07-25.

The release workflow refuses to re-use a tag either way, so nothing is blocked by
leaving them. Deleting a published git ref is the maintainer's call.
