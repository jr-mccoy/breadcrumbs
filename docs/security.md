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
9. A link committed into the store makes a reader serve, or a writer write,
   a file outside the project (audit F17).
10. Record text poses as tool framing: a control sequence, an invisible
    character, or a tag that closes the envelope an agent reads it in.

---

## 2. Required controls

- **Secret scan memory before commit.** Implemented as `crumb
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

  The URL case was missed until 0.1.8: a password after a bare `:` inside
  a URL carries no `password=`-style label for the keyword list to match, and it is
  usually too short and too word-like for the entropy heuristic. A "how to run
  this" note carrying a `DATABASE_URL` is among the likeliest secrets to be written
  into project memory, and `scan-secrets` reported OK on every form of it.
- **Treat memory content as data, not instruction.** `guard` treats matched record
  text as data, never as a command to execute.
- **Filesystem containment** (audit F17, WP13; `breadcrumbs/path_policy.py`).
  - *Threat model.* Whoever can write the repository can put a symbolic link
    in `.project-memory/`. A process that reads "its own memory" would then
    read whatever the link names, with its own permissions, and hand it to an
    agent or MCP client; a linked directory would redirect writes. This is
    not a remote exploit: it needs write access to the store's files. It
    matters when repository content is trusted less than the process reading
    it.
  - *Policy.* Nothing inside the store may be a link or junction: the store
    directory, its directories, and every file read, hashed, enumerated or
    written. `..` never appears in a store path. The project root is the one
    the person running the command chose (working directory or `--project`),
    never derived from store content.
  - *Enforcement.* On POSIX every store path is opened one component at a time
    from the store directory, each with `O_NOFOLLOW` relative to the previous
    descriptor, and writes create and rename their temporary file through that
    descriptor. A link swapped in mid-operation is refused, not followed; there
    is no window between check and use. Where descriptor-relative calls are
    missing (Windows), each component is checked with `lstat` (junctions and
    other reparse points count as links) before use, and a link swapped in
    between the check and the use is a documented residual race.
  - *Covered surfaces.* Record reads and enumeration, singletons, MCP
    resources and tools, `show`, search and the index, the packet and its
    input hash, the hook state files, usage events and the hook log, the
    store lock, projections, the mutation journal and its rollback, and
    migration. Migration refuses a store containing any link, before backing
    anything up, and the backup never follows one. `init --force` refuses
    to empty a store that is a link.
  - *Project files the tool writes* (`CLAUDE.md`, `AGENTS.md`, `.gitignore`,
    `.mcp.json`, `.claude/settings.json`) may be links that resolve inside
    the project (`AGENTS.md -> CLAUDE.md`). One resolving outside is refused.
  - *Diagnostics.* A refusal (`path_policy.Refused`, a `PermissionError`)
    names the store- or project-relative path and the rule. It never names the
    link's target, returns its bytes, or prints an absolute host path.
    `validate` lists every link as `path-link`.
  - *Out of scope.* Paths the host names outside the project (a hook's
    `transcript_path`) are read as given. Git's own files are read through
    git.
- **Record text is rendered as data** (audit F17, WP13;
  `breadcrumbs/safetext.py`). Hook context, the resume packet, guard reasons,
  MCP resources and tool results, and the CLI's human output escape control
  characters (ANSI, NUL, bare `\r`, U+2028) and invisible formatting (bidi
  overrides, zero-width), and neutralize closing tags and envelope-named
  opening tags (`&lt;/system-reminder>`).
  - A field that must be one line (a title in a hook line) has every line
    break flattened, so it cannot start a line posing as the tool's verdict.
  - MCP text is bounded at 200,000 characters.
  - Ordinary text, `<id>` placeholders and Markdown pass unchanged.
  - `--json` output carries exact values, since JSON is itself the escaping
    envelope, and the files on disk are never rewritten.
  - This keeps record text from impersonating framing. It does not make
    hostile *content* harmless, which is what "data, not instruction" and
    review are for.
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
- **Privacy labels enforced by validation**.

---

## 3. Validation posture (deterministic vs heuristic)

`validate` is **fully deterministic**. It checks structure and invariants:

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
