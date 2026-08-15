# CLI Specification

The CLI binary is `crumb` (installed via `pipx`/`pip`; from a source checkout the
equivalent is `python crumb.py <command>`, a shim over `breadcrumbs.cli`). Every
command supports the global flags below; capture/resume additionally support
`--fast`. New subcommands are added without changing established flag semantics.

---

## Global flags

Every command accepts:

```text
--json            machine-readable JSON output
--plain           plain-text output (no decoration)
--verbose         verbose output
--project <path>  project root (default: cwd)
--fast            capture/resume only: git-only, no prompts or LLM narrative
```

`crumb --version` (top level, not a subcommand) prints the package version and the
record `schema_version` — two independent numbers, see `README.md`.

`--stale-days N` is accepted by `resume`, `search`, `guard` and `audit`. It is one
cutoff with one meaning everywhere — *a record older than N days counts as aged*
(default: 21). What each command does with that differs: `resume`/`audit` raise a
warning on aged questions and decisions, `search`/`guard` score aged records lower.

Default output is human-readable Markdown / plain text.

---

## Command table

| Command | Reads | Writes | Purpose | Phase |
|---|---|---|---|---|
| `init` | project root | `.project-memory/`, `manifest.yml`, `.gitignore` edits | Install memory layout; record session + generated-projection policy in `manifest.yml`. | **1 (built)** |
| `validate` | all canonical files | validation output | Enforce schema and invariants (deterministic). Includes a projection-freshness check: fails on a `generated/` projection whose stamped `inputs_hash` no longer matches the live records. | **2 (built)** |
| `remember decision` | git state, user input | decision record | Capture a durable choice. | **3 (built)** |
| `remember attempt` | git state, user input | attempt record | Capture a tried path and its outcome. | **3 (built)** |
| `verify <subject>` | git state, user input | verification record | Record a verification result (a finding about reality): `--status fixed\|open\|regressed\|not_applicable\|inconclusive`, `--method static\|runtime\|test`. Reindexes on write. | **built** |
| `reindex` | all canonical files | `generated/` projections | Rebuild the generated projections from the records (mutations reindex automatically). | **built** |
| `capture session` | git state (log, status, diff --shortstat) | session record, handoff, current | Record session end; git-prefill body sections (Files Touched is a counts-only summary) over a bounded window (`since..HEAD`, capped at 20 commits) that the record names. `--fast` = git-only snapshot + one-line next action; `--next` + `--set` runs unattended without dropping narrative. | **3 (built)** |
| `schema [<type>]` | (none) | record contract | Print body sections / vocab / rules from source constants. `--template <type>` emits a `remember` skeleton. | **built** |
| `note question\|trap\|idea` | user input, git state | open-questions / known-traps / idea record | Write-surface for the three kinds with no `remember` type; refreshes the resume packet. | **built** |
| `resume` | current, handoff, records, git state | generated resume packet | Print a bounded resume packet (≤5k tokens) with computed staleness. `--fast` = git snapshot + focus + next action + staleness (print-only). `--task TEXT` scopes `likely_files` to matching records (print-only). | **4 (built)** |
| `search [<query>]` | decisions, attempts, verifications, ideas, traps, open questions | search output (read-only — `search` writes nothing) | Deterministic keyword/tag/file lookup over the records; the permissive layer `guard` builds on. Keyword and tag matching folds morphological variants — query and record tokens are stemmed by a small deterministic suffix-stripper (plus a tiny curated alias table: auth/config/db/repo), so "reconciliation" meets a record that says "reconciler"; `keyword_overlap` in `--json` output therefore contains stems. | **5 (built)** |
| `guard "<action>"` | decisions, attempts, traps, questions, unsettled verifications, handoff (**not** ideas) | a verdict + the matches behind it (read-only — `guard` writes nothing) | Warn before a repeated mistake (deterministic ranking). Exits with the verdict-mapped code — see `guard` section. | **5 (built)** |
| `audit` | all memory + adapters | health report | Find stale / unsafe / bloated memory (incl. secret + instruction-like heuristics). Heuristic — does NOT gate `validate`. | **6 (built)** |
| `scan-secrets` | committed memory | secret report | Scan committed memory for secret-like strings; non-zero on a hit. Run before committing memory. | **6 (built)** |
| `mark-status <id> <status>` | one record | status + `updated_at` (+ optional `superseded_by`) | Record lifecycle mutation (stale/disputed/superseded/…), validate-gated and reverted on failure; `--superseded-by ID` is the supersede flow. Reindexes on write. | **built** |
| `doctor` | adapters, `.mcp.json`, hooks, packet | integration-health report | Is memory wired up? Exit 1 if a store exists but no integration is active. | **built** |
| `mcp serve\|register\|doctor` | `.mcp.json` | running server / registration / health | Run the MCP server, merge its `.mcp.json` entry, or report MCP wiring (`[mcp]` extra + registration). | **built** |
| `hook session\|guard\|capture` | hook stdin payload | hook JSON on stdout | Claude Code hook translators (`init --with-hooks` installs them, as a `sh` resolver that falls back through `./.venv` and `python -m breadcrumbs` and reports memory inactive if none resolve). Installed entries are identified by a `breadcrumbsHook` key, not by command text, so a custom launcher stays visible to `doctor` and `--remove-integrations`. Removal keys on that marker alone: an unmarked entry that merely looks like a crumb hook is reported and left in place, never deleted (adopt it with `init --with-hooks` to make it removable). The event is validated before stdin is read, so a bare `crumb hook` reports usage (exit 2) instead of blocking on a terminal. `hook capture` runs the **extraction turn**: when the ending turn produced new commits since the last session record, it holds the stop once (`decision: block`) with an instruction to record durable decisions/attempts/verifications and finish with `capture session --next` (which is also what clears the prompt). Edit-only turns snapshot silently; a `stop_hook_active` continuation is never held again and falls back to the machine snapshot; the first firing in a store takes a silent baseline; `extraction_prompt: false` in `manifest.yml` disables the prompt entirely. | **built** |

### Integration flags on `init`

```text
init --with-adapter[=CLAUDE.md,…] / --no-adapter   # signpost block in detected guidance files
init --with-mcp / --no-mcp                          # merge .mcp.json entry
init --with-hooks[=session,guard,capture] / --no-hooks
init --print-integrations                           # dry run
init --remove-integrations                          # reverse everything
```

On a TTY with none specified, `init` asks once per integration; non-interactive +
unspecified writes nothing (plus a one-line nudge). Every edit is fenced and
reversible.

Both lists are validated **before any filesystem mutation** — `--with-hooks` against
`session|guard|capture`, `--with-adapter` against the known guidance filenames —
and a typo exits 2 naming the valid values, with nothing written. `init` never
injects the signpost into a file outside that list, because `--remove-integrations`
would not know to look there. (For stores already in that state, removal scans the
project root for stray managed blocks and reverses them too.)

Ctrl+C at any `init` prompt aborts with exit 130 and writes nothing further; EOF
(piped input) still takes the prompt's default.

### Later commands (post-MVP)

**None of these exist**, and none is scheduled. They are recorded here as the shape
a later version might take, not as work in progress:

```text
supersede <old-id> <new-id>   # sugar over `mark-status --superseded-by` (which is built)
build-index                   # nothing builds an index today; see `index/` in the store
dashboard | recent | where-was-i
```

---

## `init` (built)

```bash
crumb init
crumb init --session-tracking <full|distillate>
crumb init --no-commit-generated
crumb init --project <path>
crumb init --force
```

Behavior:

- Refuses to clobber an existing `.project-memory/` unless `--force` (which
  replaces the scaffold and deletes all existing records). With any
  `--with-adapter`/`--with-mcp`/`--with-hooks` flag, an existing store is left
  untouched and just those integrations are applied (no `--force` needed).
- Copies the bundled `breadcrumbs/templates/project-memory/` tree (shipped as
  package data, resolved package-relative) into the target's `.project-memory/`.
- Auto-derives `project` (root dir name), `created_at` (ISO-8601 w/ tz), and sets
  `schema_version: 1`.
- **Session-tracking policy:** `--session-tracking <full|distillate>`, else prompt;
  non-interactive default is `full`. Recorded in `manifest.yml`.
- **Generated-projection policy:** default `commit_generated_projections: true`;
  `--no-commit-generated` flips it. Recorded in `manifest.yml`.
- Writes a managed `.gitignore` block matching the policies. `index/**` is always
  ignored (except `index/README.md`); `private/**` is always ignored;
  `--no-commit-generated` ignores `generated/*.md` (keeping the README);
  `distillate` ignores `sessions/`.
- **Non-git fallback:** detects whether the project is a git repo; if not, prints a
  notice that git-derived record fields will use the sentinels documented in
  [`record-schema.md`](record-schema.md) §7 (`branch: (no-git)`,
  `commit: (no-git)`, `dirty_files: []`).
- `--json` emits a machine summary of what was created and the chosen policies.

---

## `resume` (built)

```bash
crumb resume                  # full bounded packet; writes generated/resume-packet.md
crumb resume --fast           # reduced reorientation view (print-only)
crumb resume --json           # structured packet (sections + warnings + source header)
crumb resume --stale-days N   # age cutoff in days (default: 21)
crumb resume --task TEXT      # resume FOR this task: scope likely-files (print-only)
```

Behavior:

- Assembles the §12 packet from `current.md`, `handoff.md`, active `decisions/`,
  active `attempts/`, `known-traps.md`, `open-questions.md`, and live git state.
- **Bounding:** per-section caps, then a hard **5,000-token** ceiling (chars/4
  heuristic). Current/handoff/active-decisions outrank old session observations;
  lower-priority sections are trimmed first and an omission note is shown. Raw
  transcripts are never included.
- **Computed staleness** (not just authored): handoff **age + commit-distance**,
  **aged-unresolved** questions/decisions (> `--stale-days`), **branch mismatch**
  (incl. detached HEAD), and **expired**/**low-confidence** records.
- **The focus claims are falsifiable (0.1.11, P1-5).** Age and distance say how
  *old* the handoff is, never whether its claims still hold — the field test's
  packet told a fresh session to redo two items that had already landed. Two
  checks close that gap: the packet lists the commit subjects landed since the
  handoff was written (`commits_since_handoff`, bounded, rendered as *Landed
  Since The Handoff Was Written*) so the reader can check the work-list against
  history; and a **fixed** verification whose subject overlaps the Current
  Focus / Next Action claims adds a warn-only `possible drift:` line. Citing a
  commit sha or file in `--next` (the extraction prompt now asks for one) keeps
  the claim checkable.
- **Current Focus never mirrors Next Action.** `capture session` no longer
  defaults an unset `--focus` to the Next Action text, and packets from stores
  written before 0.1.11 render the verbatim duplicate as
  `_(same as Next Action)_` instead of printing ~1.4k chars twice (P1-6).
- **The threshold and the ages are separate, separately named fields.** `--json`
  carries `stale_after_days` (the cutoff in force) alongside `handoff_age_days` and
  `handoff_commit_distance` (what was measured; `null` when the timestamp is
  unparseable or there is no git repo), and the rendered packet names the cutoff
  above the warnings. One number is a policy, the others are facts — a distinction
  the old single `stale_days` field hid.
- **`next_action` here is recorded state, not advice.** The packet's
  `next_action` is the `## Next Action` a session handoff left behind — `""` when
  nobody set one. `guard --json` has no `next_action`: its synthesized advice is
  **`recommended_action`**, and it is always a non-empty string. The two were one
  name until 0.1.9, which made an unset handoff look like a broken guard.
- The **committed** projection is always written with the default cutoff, not the
  one a given invocation passed: a shared artifact must not change because one
  developer preferred `--stale-days 7`. `--stale-days` affects what *you* see.
- **Source header:** every packet carries `source_commit` / `inputs_hash` /
  `generated_at` (carrying the `GENERATED PROJECTION` marker so `validate` accepts
  it and `audit` can later detect drift).
- **Project path is project-relative** (`.`) in both the rendered packet and
  `--json`: the packet is a committed, shared artifact, so it never carries the
  author's absolute host path.
- Refreshes the store-global projections through the same reindex every mutation
  uses — `generated/resume-packet.md` (the committed cloud-fallback artifact under
  the default policy) **and** `generated/guard-prefilter.json`, both written
  atomically. `--fast` and `--task` are **print-only** and never overwrite them.
- Exit codes: `0` on success, `2` when no `.project-memory/` store is present.

---

## `search` (built)

```bash
crumb search "auth middleware"      # keyword search over the records
crumb search --tag auth             # filter by tag/component
crumb search --file src/auth/x.ts   # filter by referenced file path
crumb search --type verification --status open    # filter-only lookup (no query)
crumb search "session" --type decision --json
```

```text
--type {decision,attempt,verification,idea,trap,question}
--status <value>     record status; for a verification, its outcome (open, fixed, …)
--tag <value>        tag / component
--file <path>        a file path referenced by the record
--stale-days N       age cutoff in days (default: 21) — aged records score lower
```

Behavior:

- **Deterministic and dependency-free.** Exact/keyword text, tag/component and file
  path; no embeddings, no index (see `index/` in the store — nothing builds one).
  Same input → same output.
- The **corpus** is decisions, attempts, verifications, **ideas**, known traps and
  open questions. `sessions/` is deliberately out: sessions are narrative, and a
  `session_tracking: distillate` clone may not have them at all, so including them
  would make results depend on which checkout you ran in.
- **`ideas/` is searchable here and invisible to `guard`.** That asymmetry is the
  point, not an oversight. An idea is a proposal — exempt from the §16.9 evidence
  rule — and `guard`'s score band does not care what kind of record it is scoring,
  so a speculative note naming the right files would otherwise gate a real edit on
  the strength of nobody having done the work. `crumb search --type idea` finds it;
  a `guard` verdict never sees it. Fixture 12 is the control.
- A query with no filters ranks by overlap; filters with no query list every
  matching record instead of returning nothing.
- **Search can return zero, and that is an answer.** A pure-text match needs the
  same shared-keyword floor as `guard` (`GUARD_MIN_KEYWORD_OVERLAP`, relaxed to
  the query's own specific-token count so a one-word lookup like "libsignal"
  still works). Before 0.1.11 a single generic shared token ("version") counted
  as a match, which made weak queries return confident noise.
- **Ubiquity gate (shared with `guard`).** Once the corpus holds at least
  `GUARD_DF_MIN_CORPUS` items, a stem present in more than `GUARD_DF_UBIQUITY`
  of them (package prefixes shed by cited paths, the project's own domain noun)
  carries zero keyword weight and no gate credit. File and tag matches are
  exempt — both are author-curated signal.
- `guard` is this same engine with a verdict on top plus a noise floor,
  so a `search` hit is the permissive case of a `guard` match.
- Exit codes: `0` on success (including zero matches), `2` when no
  `.project-memory/` store is present.

---

## `guard` (built)

```bash
crumb guard "<proposed action>" [--files F ...] [--json] [--stale-days N]
```

The judging layer on top of `search`: classify the action, rank the overlapping
records, emit one deterministic verdict (`PROCEED` / `READ_FIRST` / `PAUSE` /
`ASK_HUMAN`) plus the matches behind it.

Behavior (deltas from `search` — everything there applies here too):

- **Verdict floors need author-curated specificity.** A matched decision,
  unsettled verification, or trap floors the verdict at `READ_FIRST` (a
  do-not-retry attempt at `PAUSE`) only when the match carries a **file or tag**
  signal. A keyword-only match — however the tokens overlap — can escalate only
  through the score bands (`GUARD_READ_FIRST_SCORE` / `GUARD_PAUSE_SCORE`).
  Until 0.1.11 a keyword-only *trap* match floored `READ_FIRST` unconditionally;
  in a store whose vocabulary overlaps the codebase that made one trap fire on
  every edit of a session (the 0.1.10 field test's 13-for-13).
- **Staleness on the guard path is risks-only.** Only abnormal states — cold
  handoff (`⚠`), detached HEAD, handoff branch mismatch — ride along with a
  verdict. The routine store facts (fresh handoff age, aged records, low
  confidence, other-branch record lists) are read once per session in
  `resume`/`doctor`/`audit`, not once per edit.
- **Exit codes are verdict-mapped** so callers can script on the verdict
  without parsing output: `PROCEED` = 0, `READ_FIRST` = 10, `PAUSE` = 15,
  `ASK_HUMAN` = 20 (`>= 15` means a human belongs in the loop); `2` = usage
  error / no store. Deliberately clear of 1, 2, and the shell's 126+ range.
  The hook translator (`crumb hook guard`) always exits 0 — hook protocols
  treat nonzero as a hook failure.

The `PreToolUse` hook path adds two behaviors of its own:

- **Edits carry content.** The guard action for an `Edit`/`Write`/`MultiEdit`
  is `edit <path>: <bounded snippet of the new content>`, so successive edits
  of one file stop producing byte-identical guard input and a content-shaped
  trap ("this API is banned") can actually match.
- **Advisories dedupe per host session.** A `READ_FIRST` for the same file and
  the same matched records fires once per session (state in
  `private/hook-guard-seen.json`, machine-local, bounded); a new record, a
  different file, or a new session speaks again. `PAUSE`/`ASK_HUMAN` are never
  deduplicated.

---

## `audit` (built)

```bash
crumb audit                  # human health report
crumb audit --json           # structured findings (check/severity/path/message)
crumb audit --plain          # one line per finding
crumb audit --stale-days N   # age cutoff in days (default: 21)
```

`audit` is the **heuristic** safety net that `validate`'s determinism intentionally
excludes (see the determinism note). It never gates `validate`; it advises. Findings
carry a severity:

- **fail** — blocks (non-zero exit). The *only* fail-severity check is a **secret
  leak**: a token-like string in committed memory (see `scan-secrets`). This must be
  resolved before any "commit memory" workflow.
- **warn** — flag for human review; never changes the exit code. Covers: stale
  handoff (age + commit-distance), branch mismatch (incl. detached HEAD),
  aged-unresolved questions/decisions, expired + low-confidence records,
  **instruction-like text** (override phrasing such as "ignore the tests" — flagged,
  never executed: matched memory is data, not command), **generated-packet drift**
  (a committed projection whose stamped `inputs_hash` no longer matches the canonical
  inputs → regenerate), bloat (adapter files duplicating memory; over-budget packet),
  and the validate-failing health conditions re-surfaced for one health view (missing
  evidence, invalid status, private-path violation, id/frontmatter disagreement).
- **info** — context note (e.g. `sessions/` growth → consider a rollup).

Exit codes: `1` when any **fail** finding is present (a secret), else `0`; `2` when no
`.project-memory/` store is present.

---

## `scan-secrets` (built)

```bash
crumb scan-secrets           # human report; non-zero on any hit
crumb scan-secrets --json    # {ok, count, hits:[{pattern, path, line}]}
```

The secret sub-check of `audit`, exposed standalone so it can run as a pre-commit /
pre-push gate before memory is committed (§2.6, §15). Scans committed memory only —
`private/`, `index/`, and `generated/` are skipped. Reports the matched pattern
**name** and location, never the secret value. Coverage is deliberately conservative
(AWS/GitHub/Slack/Google/OpenAI-style keys, JWTs, PEM private-key headers, bearer
tokens, `secret/token/password=`-style assignments, and mixed-class high-entropy
blobs). The covered set is `SECRET_PATTERNS` in `breadcrumbs/cli.py`, and the
false-positive controls (git SHAs, record ids, path- and CamelCase-shaped tokens)
are pinned by `tests/test_secrets.py`; known gaps are listed in
[`security.md`](security.md) §2. Exit codes: `1` on any hit, `0` when clean, `2`
when no store is present.

---

## `--fast` semantics

For `capture` and `resume` (Phases 3–4): skip all prompts and any LLM narrative and
operate from git state only. `capture --fast` writes a git-only snapshot plus a
one-line next action (~15-second path for a tired human). `resume --fast` prints the
git snapshot, current focus, next action, and computed staleness warnings only —
skipping the fuller record summaries.

---

## Determinism note

`validate` is fully deterministic. Heuristics (secret scan, instruction-like text
detection) live in `audit`, never in `validate`. See
[`security.md`](security.md).
