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
  Run it before any "commit memory" workflow. Coverage is conservative: the covered
  set is `SECRET_PATTERNS` in `breadcrumbs/cli.py` (AWS / GitHub / Slack / Google /
  OpenAI / Stripe key shapes, JWTs, PEM private-key headers, bearer tokens,
  `secret|token|password=`-style assignments, labeled hex secrets, and credentials
  embedded in a connection string — `postgres://app:<pw>@host/db`,
  `redis://:<pw>@…`, `https://user:<token>@host/repo.git`, with the real
  credential in place of the placeholder) plus a mixed-character-class high-entropy
  heuristic. **Known gaps, deliberately:** a bare lowercase-hex token is not
  flagged on its own — it is shape-identical to the commit SHAs and `inputs_hash`
  values that legitimately fill project memory, so it is caught only in a labeled
  credential context; path- or CamelCase-identifier-shaped tokens are allowlisted
  out of the entropy heuristic; and a URL credential is only flagged at six or more
  characters and is skipped for `$VAR` / `${VAR}` / `<placeholder>` interpolations
  and the obvious doc placeholders, so `postgres://user:password@localhost/db` in a
  README and `amqp://guest:guest@…` do not block a commit. A scanner that cried
  wolf on every commit ref would be turned off, and the check is only useful while
  it blocks. `tests/test_secrets.py` pins the covered shapes, these controls, and —
  for the URL pattern — a zero-false-positive sweep of this repository.

  The URL case was missed until 0.1.8 (MF-67): a password after a bare `:` inside
  a URL carries no `password=`-style label for the keyword list to match, and it is
  usually too short and too word-like for the entropy heuristic. A "how to run
  this" note carrying a `DATABASE_URL` is among the likeliest secrets to be written
  into project memory, and `scan-secrets` reported OK on every form of it.
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
- **No host paths in shared artifacts.** `generated/resume-packet.md` is committed
  under the default policy and served over MCP, so it records the project path as
  `.` — publishing the author's absolute directory layout (`/Users/<name>/…`,
  `/home/<user>/clients/<client>/…`) into a shared repo is the same disclosure the
  MCP layer already forbids for error messages.
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

**Enforcement is still an open question.** Nothing in the tool distinguishes a
high-impact record change from a routine one, so the list above is a review
convention, not a check. What exists today is narrower and blocking: `scan-secrets`
(and `audit`'s secret sub-check) fails the build on a committed secret, and `audit`
*warns* on instruction-like text — which catches the "says to skip the tests" row
and nothing else on this list. Whether the rest becomes a CI gate, a pre-commit
hook, or stays advisory is a dogfood decision that has not been made.

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
