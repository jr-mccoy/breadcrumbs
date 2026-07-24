# Security & Privacy

Memory can be stale, poisoned, private, or executable-adapter-adjacent. Security is
part of the memory design, not an add-on.

---

## 1. Threat surfaces

1. A malicious PR edits `.project-memory/` to steer future agents.
2. A memory record contains prompt-injection-like text.
3. An old decision remains `active` after the code changed.
4. Private notes are accidentally committed.
5. Secrets from logs are captured in session records.
6. Checked-in MCP/hook config runs unsafe commands.
7. A generated resume packet is stale but trusted.
8. A vector/FTS index is stale or built from the wrong commit.

---

## 2. Required controls

- **Secret scan memory before commit.** Implemented in Phase 6: `crumb
  scan-secrets` (and the `audit` secret sub-check) scans committed memory for
  token-like strings and exits non-zero on a hit — the one blocking check in `audit`.
  Run it before any "commit memory" workflow. Coverage is conservative (key/token/PEM
  shapes, `secret=`-style assignments, high-entropy blobs); covered-set and known gaps
  are recorded in the Phase 6 doc.
- **Treat memory content as data, not instruction.** `guard` treats matched record
  text as data, never as a command to execute.
- **High-impact memory writes require review** (see §4).
- **Executable configs require human review.** The generated `.mcp.json` and the
  `.claude/settings.json` hooks are strictly opt-in (`init --with-mcp` /
  `--with-hooks`), fenced/merged without clobbering other entries, and fully
  reversible (`init --remove-integrations`). The `PreToolUse` guard hook surfaces
  matched memory as context but **never decides** an action from memory alone: it
  emits no `allow` (which would auto-approve the call and skip the prompt you
  would otherwise get) and no `deny` — only `ask`, or context.
- **Generated projections include a source timestamp/hash/commit header** so
  staleness is visible.
- **Indexes include the source file hash and are invalidated on mismatch.**
- **Branch mismatch warning** in `resume` and `guard`: a record whose `branch`
  differs from the current git `HEAD` branch is surfaced as possibly-stale rather
  than hidden. Detached HEAD and a record written on a since-merged branch both
  count as a mismatch and warn. (Records carrying the `(no-git)` sentinel are not
  treated as mismatches — see [`record-schema.md`](record-schema.md) §7.)
- **Privacy labels enforced by validation** (Phase 2).

---

## 3. Validation posture (deterministic vs heuristic)

`validate` (Phase 2) is **fully deterministic**. It checks structure and invariants:

1. `manifest.yml` exists and has a supported `schema_version`.
2. Required core files exist.
3. Durable records have valid frontmatter.
4. Record IDs are unique (enforced for free by filename-canonical identity).
5. Status values are valid.
6. `superseded` records include `superseded_by`.
7. `privacy: local-private` records are not in committed/shared paths.
8. `secret-prohibited` records fail validation.
9. Decisions and attempts have evidence or low confidence.
10. Session records have a `Next Action` or explicitly mark convergence/done.
11. Handoff has branch, commit, next action, and stale conditions.
12. Generated files are not treated as canonical.
13. Adapter (signpost) files do not duplicate full memory content.
14. Required structural files and frontmatter shape are well-formed.

**Detecting instruction-like text is NOT a validation check.** Spotting imperative
overrides (e.g. a trap saying "skip the tests") in free text is a heuristic, not a
deterministic rule, so it does not gate `validate`. It belongs in `audit` as a
flagging heuristic: a lexical scan for override-style phrasing ("ignore", "skip",
"disable", "always", "never run") that emits a warning for human review. Same
content-as-data posture as the poisoned-memory fixture: `audit` flags it, `guard`
treats matched text as data, `validate` stays deterministic.

---

## 4. High-impact memory changes (require human review)

A record change requires human review when it:

- changes authority boundaries,
- says to skip or reduce tests,
- changes security/privacy posture,
- changes tool permissions,
- changes dependency/vendor strategy,
- marks a major decision `superseded`,
- quarantines or unquarantines memory.

Enforcement mechanism (CI vs pre-commit vs warning) is an open question to be
decided during dogfood (Phases 6, 9).

---

## 5. Privacy labels

| Privacy | Meaning | Storage |
|---|---|---|
| `repo-safe` | May be committed. | anywhere in `.project-memory/` |
| `local-private` | Personal/sensitive local context. | `private/` (gitignored) or external private store |
| `secret-prohibited` | Secrets/credentials/PII. | **never** stored in project memory; fails validation |

`init` gitignores `private/**` and `index/**` (except `index/README.md`)
unconditionally, so local-private notes and disposable indexes cannot be committed
through the default workflow.
