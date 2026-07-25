# breadcrumbs / crumb-kit — Agentic Review #2 (MCP integration, write path, cloud portability)

**Date:** 2026-06-27
**Reviewer:** AI agent (Claude), as the primary *consumer* of the tool
**Evaluated build:** `crumb-kit` **0.1.3** (PyPI; `requires_python >=3.9`). CLI self-reports `breadcrumbs 0.1.3 (record schema_version 1)`. The bundled MCP server self-reports `breadcrumbs 1.28.1` (FastMCP server version, distinct from the package version — see F11).
**Surface exercised:** 8 MCP tools, 6 flat resources (+ templated `decisions/{id}`, `attempts/{id}`), 6 prompts, plus the `crumb` CLI.
**Environment:** Local Linux (Lubuntu, Python 3.14.4, PEP-668) consumed through **Claude Code** over a real stdio MCP connection; plus a static analysis of cloud portability to **Claude Code on the web** and **Codex cloud**.

> This document is the second-pass agentic review. The first-pass review it was
> transferred alongside (`crumb-kit-agentic-review-2026-06-26.md.txt`) has since
> been removed: its findings all shipped in 0.1.2/0.1.3, and this repo deletes a
> review doc once its findings are resolved. See the **Resolution status**
> section appended at the end for how each finding here was addressed.

---

## 0. Relationship to the 2026-06-26 review

The first review evaluated the **CLI** in isolation and predicted the roadmap. This pass actually **installed the package, stood up the MCP server, connected it to a real harness (Claude Code), and used it to do real work** (verifying a 3-finding Android performance audit against live code). That changes what's observable.

- ✅ **Confirmed live — `memory_note` now exists (0.1.3).** The §6.6 read/write asymmetry is **closed**. `memory_note(kind=question|trap|idea)` is the 8th MCP tool.
- ✅ **Confirmed live — automaticity is still the #1 gap (§5/§7.3).** The tools were loaded for an *entire* session and were never reached for until explicitly told to.
- 🔁 **Reproduced on a new surface — projection drift (§6.5/§6.6)** through the **MCP `memory_record` write path** (F2), and `validate` does not catch it (F3).
- 🆕 **New territory:** install/packaging of the MCP extra (F7), MCP registration UX + project-scope approval gate (F8), cloud-environment portability (F9), and a structural gap: **no record type for a verification result** (F1).

---

## 1. Executive summary

**Verdict: the engine and the MCP layer are solid; the gaps are in the *write→project→trust* loop and in *distribution*.**

| # | Severity | Finding | One-line fix |
|---|---|---|---|
| **F1** | High | No `verification` record type; `verification: []` resume slot has no writer | Add a first-class verification record + `crumb verify` / `memory_verify` |
| **F2** | High | MCP writes don't refresh `generated/` projections | Reindex-on-write (or explicit `crumb reindex` + auto-call) |
| **F3** | High | `validate` passes even when projections are stale → false confidence | Add a projection-freshness check (inputs-hash compare) |
| **F4** | Medium | `likely_files` is store-global, misleads on off-domain tasks | Scope it to task/keyword overlap; return empty + label when none |
| **F5** | Medium | Automaticity still absent (confirmed live) | `crumb init` bootstrapper: register MCP + install harness hooks |
| **F6** | Medium | Resume packet `current_focus`/`next_action` reflect last capture, not the requested task | Distinguish "store state" from "this task"; derive focus from `requested_task` |
| **F7** | Medium | `pip install crumb-kit` yields a **non-functional** MCP server (missing `[mcp]` extra) | Ship clearer packaging/guidance; fail louder at register time |
| **F8** | Medium | MCP registration friction: stdio-only + project-scope approval + bare-command PATH dependency | Document the flow; consider an HTTP transport; smarter `init` |
| **F9** | Medium | Cloud non-portability: Codex cloud has **no stdio MCP**; Claude web needs a setup-script bootstrap | Optional streamable-HTTP server + a documented cloud recipe |
| **F10** | Low | Confusing dual staleness numbers (`stale_days` vs "handoff N days old") | Clarify field semantics / name them distinctly |
| **F11** | Low | Server version (`1.28.1`) ≠ package version (`0.1.3`); MCP server still undiscoverable from `crumb --help` | Align versions; add `crumb mcp` subcommand |

---

## 3. Findings (abridged — see the full prose in the PR description / original review)

- **F1 — No record type for a verification result (High).** The task produced "I checked findings 1/2a/2b/3 against current code; all already fixed." breadcrumbs had only `memory_record` (decision/attempt) and `memory_note` (question/trap/idea). A verification is neither a *choice* nor a *failed attempt* — it is a *finding about reality*. The resume packet exposed an empty `verification: []` slot with no writer.
- **F2 — MCP writes don't refresh the generated projections (High).** After a successful `memory_record`, the canonical record was absent from every `generated/` projection until a manual `crumb resume`.
- **F3 — `validate` passes while projections are stale (High).** `validate` only asserted the projection *marker* was present, not that the projection *reflected current records* — so it certified drift.
- **F4 — `likely_files` is store-global, not task-scoped (Medium).** On an off-domain task, `search` honestly returned 0 hits, but `likely_files` confidently listed store-wide defaults.
- **F5 — Automaticity still absent (Medium).** MCP availability ≠ use. Only harness-level wiring (hooks) converts "may consult" into "always consults".
- **F6 — Resume packet conflates "store state" with "this task" (Medium).** `current_focus`/`next_action` reflected the last capture, not the requested task.
- **F7 — `pip install crumb-kit` ships a non-functional MCP server (Medium).** The `[mcp]` extra is discoverable only by running the server and reading the error.
- **F8 — MCP registration friction (Medium).** stdio-only + project-scope approval gate + bare-command PATH dependency.
- **F9 — Cloud non-portability (Medium).** Claude web can reach MCP via a setup script; Codex cloud supports only streamable-HTTP MCP, not stdio.
- **F10 — Confusing staleness fields (Low).** `stale_days` (a threshold) vs "handoff N days old" (an age).
- **F11 — Versioning & discoverability nits (Low).** FastMCP self-reports its own version; align with the package and surface `crumb mcp`.

---

## Resolution status (added on transfer)

Implemented in the same change set that lifted this review into the repo (see
`CHANGELOG.md` → *Unreleased*):

- **F1 — done.** New `verification` durable record type (`verifications/`, id prefix
  `ver`). `crumb verify <subject> --status <outcome> --method <static|runtime|test>
  --evidence …` and the `memory_verify` MCP tool. The record-level `status` stays
  the lifecycle value; the finding-about-reality lives in an `outcome` frontmatter
  field. Validated (subject + valid outcome/method + the §16.9 evidence-or-low
  rule), searchable (`--type verification --status open`, where `--status` filters
  on the outcome), and surfaced in the resume packet's **Verifications** section
  (actionable outcomes first). The legacy `verification` packet field (verification
  *commands*) is unchanged; the new results live under a distinct `verifications`
  key to avoid breaking it.
- **F2 — done.** `reindex_projections` runs after every canonical mutation
  (`remember`, `note`, `verify`, `mark-status`, and the `memory_record` /
  `memory_verify` / `memory_mark_status` / `memory_note` MCP tools). Added
  `crumb reindex` and `memory_reindex` for explicit/batch refresh.
- **F3 — done.** `run_validate` now includes a projection-freshness check (reusing
  `detect_packet_drift`): a `generated/` projection whose stamped `inputs_hash` no
  longer matches the live records **fails** validate with a `Run \`crumb reindex\``
  hint. `fixture-08-packet-stale` now fails validate's freshness check by design.
- **F4 / F6 — done.** `build_resume_packet(task=…)` (and `crumb resume --task`,
  `memory_build_resume_packet(task=…)`) scopes `likely_files` to records that match
  the task via the existing `search` scoring, labels an empty result `starting
  cold`, and echoes the `requested_task` above the last-session focus/next-action so
  the two are not conflated.
- **F11 — partial.** Added `crumb mcp doctor` (the `[mcp]` extra + `.mcp.json`
  registration check) so the MCP path is discoverable from the CLI. Aligning the
  FastMCP-advertised server version with the package version is deferred: the
  FastMCP version API is SDK-version-fragile and not testable in the stdlib-only
  suite, so it was left rather than risk breaking server startup for installed users.
- **F5 / F7 / F8 — already present (confirmed), documentation reinforced.**
  `crumb init --with-hooks` already installs `SessionStart→resume`,
  `PreToolUse→guard`, `Stop→capture`; `crumb doctor` already reports the `[mcp]`
  extra; `crumb mcp register` already writes `.mcp.json` (now also printing the
  expected "Pending approval" note).
- **F9 — deferred.** An optional streamable-HTTP transport is the right fix for
  Codex cloud, but it depends on the optional MCP SDK and a real cloud harness to
  validate; it is out of scope for a stdlib-only change set and tracked as
  follow-up.
- **F10 — deferred (cosmetic).** Field-name clarity for the dual staleness numbers.
