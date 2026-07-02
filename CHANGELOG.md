# Changelog

All notable changes to **crumb-kit** (the `breadcrumbs` package) are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/), and the project
uses semantic versioning. The package version is independent of the on-disk record
`schema_version` (still `1`); `crumb --version` prints both.

## [Unreleased]

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

Resolves the six high-severity findings from the third (full-system) review
(`docs/crumb-kit-system-review-2026-07-01.md`, R1–R6), and — in a second pass —
all twenty of its Medium/Low findings (R7–R26), completing the review.

### Added
- **`crumb mark-status <id> <status>` (R25)** — the record lifecycle mutation
  (stale/disputed/superseded/…) as a CLI command; it previously existed only as
  the MCP `memory_mark_status` tool despite README/docs describing the flow.
  `--superseded-by ID` sets the pointer validate requires when superseding
  (mirrored on the MCP tool as a new optional param) — this is the "supersede
  flow" mcp-spec referenced.
- **Trap-token guard pre-filter index (R9)** — reindex now also writes
  `generated/guard-prefilter.json`, a token/path index over known traps and
  do-not-retry attempts. The `PreToolUse` hook consults it (one small-file
  read; still no record walk on the common path), so a trap-shaped but
  routine-looking command (`pytest -n auto`) escalates to full guard scoring —
  the near-miss class that motivated hooks in review #1, previously covered
  only by a hardcoded regex.

### Fixed
- **`capture session` reindexes on write (R1)** — the session-end flow (and the
  `Stop → crumb hook capture` hook) mutates three packet inputs (session record,
  `handoff.md`, `current.md`) but was the one canonical mutation that never
  refreshed the `generated/` projections, so `crumb validate` failed on
  freshness immediately after the documented workflow.
- **Integrations-only `init` on an existing store (R2)** — `crumb init
  --with-adapter/--with-mcp/--with-hooks` against a project that already has a
  store now applies just those integrations and leaves the store untouched;
  previously it errored and steered users toward `--force`, which replaces the
  scaffold and deletes every record. The clobber-guard message now spells out
  that `--force` is destructive.
- **Round-trip-safe frontmatter re-rendering (R3)** — values containing both
  quote kinds are now emitted single-quoted with YAML `''` escaping (and parsed
  back), block lists render both scalar and map items under *any* key (scalar
  `evidence` items no longer crash; list-of-maps under generic keys no longer
  persist as Python `repr` strings), unrepresentable nesting raises instead of
  corrupting, and `set_record_status` refuses to write any rendering the parser
  would read back differently (fail-closed round-trip check).
- **Fence-aware markdown section splitting (R4)** — `## ` lines inside
  ``` / ~~~ code fences are content, not section boundaries, so `capture
  session` no longer structurally corrupts a `handoff.md`/`current.md` whose
  sections contain fenced command output.
- **MCP server on Python 3.10/3.11 (R5)** — tool schemas now use
  `typing_extensions.TypedDict` (with a stdlib fallback for SDK-less installs);
  pydantic rejects `typing.TypedDict` before Python 3.12, so `breadcrumbs-mcp`
  crashed at startup on two of the three advertised Python versions.
- **Release dry-run publishes to TestPyPI (R6)** — `release.yml` now routes
  `workflow_dispatch` to TestPyPI (environment `testpypi`) and only a published
  GitHub release to real PyPI, matching RELEASING.md; previously the documented
  "dry-run" performed an irreversible real publish.
- **Trust loop (R7, R8)** — `_inputs_hash` now covers `manifest.yml` (a packet
  input), so the freshness check can no longer certify a packet built from a
  since-edited manifest; the packet's `warnings` list is capped (20) with an
  omitted-count disclosure and is budget-trimmable *after* every substantive
  section, so the ≤5k-token bound holds even on warning-heavy stores.
- **MCP parity (R10, R11, R12)** — `memory_build_resume_packet(task=…)` passes
  `task` through to the engine (scoped `likely_files`, `starting cold` label —
  identical to `crumb resume --task`) instead of merely echoing it;
  `memory_record` returns the CLI's error for an explicit evidence-less
  medium/high confidence instead of silently downgrading it to low (unstated
  confidence still defaults to low); `crumb mcp serve --project PATH` actually
  serves that project (exports `BREADCRUMBS_PROJECT`) instead of silently
  serving cwd.
- **Hook robustness (R13)** — a truthy non-dict `tool_input` (and a valid but
  non-object JSON stdin payload) degrades to `{}` like every other malformed
  payload instead of crashing with a traceback.
- **Content preservation (R14)** — `update_handoff`/`update_current` keep user
  intro text between the header and the first `## `, and duplicate-heading
  bodies are merged instead of last-wins dropped (shared fence-aware ordered
  splitter).
- **Shallow clones (R15)** — `capture session` diffs from the shallow boundary
  instead of the empty tree, so "Files Touched" no longer claims the entire
  repo in a depth-limited clone.
- **Validate robustness (R16, R17)** — a non-string verification `subject` and
  a non-UTF-8 `handoff.md`/`generated/*.md` are reported as findings instead of
  crashing the trust primitive; session done-markers are word-boundary matched
  ("done" no longer matches "abandoned").
- **CI blindness (R18)** — the test job runs a 3.9/3.11/3.12 matrix (3.9 is the
  documented floor); a new `mcp` job installs the `[mcp]` extra on 3.10–3.12,
  runs the suite (un-skipping the SDK registration test that would have caught
  R5) and asserts the server builds with all 10 tools + 6 prompts; the
  bundled-template guardrail compares the wheel against `git ls-files` identity
  instead of duplicated magic counts. Also repairs the "validate Fixtures 2-10"
  step, red on `main` since the 0.1.4 freshness check landed: fixture-08's
  projection is *deliberately* stale, so that step now asserts the freshness
  failure instead of tripping over it (the unit suite already pinned this).
- **Signal quality (R19, R20)** — template placeholder values in the handoff
  header are treated as absent, so a fresh store no longer warns "branch
  mismatch … '<branch>'" / "timestamp is not parseable" on every resume/guard
  until first capture; `audit` reports the unconditional handoff age/distance
  line as INFO unless it is actually cold (⚠), so a seconds-old store audits
  quietly.
- **Record integrity (R21, R23, R24)** — git's C-quoted porcelain paths
  (spaces/quotes/non-ASCII) are decoded before storage in `dirty_files`;
  recency ordering parses timestamps instead of comparing strings (mixed UTC
  offsets no longer pick the wrong "newest" record); unborn-HEAD repos record
  the real branch name; `load_manifest` no longer truncates values at a bare
  `#`; record/singleton/projection writes go through tmp+rename (no truncated
  files on interruption); a status-change `reason` containing `-->` can no
  longer escape the trailing HTML comment.
- **Note hygiene (R22)** — question/trap text and field values are flattened to
  one line (embedded `\n## …` can no longer forge headings) and comment markers
  are neutralized (a `<!--`/`-->` pair across two traps could comment-join
  everything between them out of every reader); duplicate trap slugs and
  duplicate questions are refused instead of accumulating shadowed blocks; the
  template-placeholder filter matches the exact template lines instead of any
  user line shaped like `_No … yet._`.
- **MCP envelope + docs (R25)** — every tool success now carries `ok`
  (search/guard/packet gained it; `scan_secrets` keeps `clean` alongside);
  the dead `fast` parameter is gone from the packet adapter;
  `breadcrumbs-mcp --help` prints usage instead of silently starting the stdio
  server; mcp-spec's tool table matches reality (incl. `files` on
  `memory_search`).
- **Heuristic coverage (R26)** — the instruction-like scan catches natural
  phrasings ("ignore failing tests", "ignore all prior instructions", "bypass
  the code review"); the secret scan adds `refresh_token`/`private_key`/
  `id_token`/`session_token`/`signing_key` labels, matches JSON-quoted keys,
  and scans `.yaml`/`.json`/`.txt` under memory, not just `.md`/`.yml`.

## [0.1.4] — 2026-06-29

Resolves the high-leverage findings from the second agentic review (MCP
integration, write path, cloud portability — `docs/crumb-kit-agentic-review-2026-06-27.md`).
The CLI remains the single source of behavior; the MCP layer stays a thin wrapper
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
