# MCP Specification (implemented)

> **Status: built.** The Python MCP server ships in
> [`breadcrumbs/mcp_server.py`](../breadcrumbs/mcp_server.py), a thin binding
> over the adapter core in [`breadcrumbs/mcp_core.py`](../breadcrumbs/mcp_core.py).
> Every resource/prompt/tool wraps the **same** core functions the CLI calls
> ([`breadcrumbs/cli.py`](../breadcrumbs/cli.py)) — one source of behavior,
> no fork.

MCP is an **optional** interop layer above the plain files and the CLI. It is
never required for baseline functionality: a read-only agent with no MCP must
still resume from the plain files (see [`architecture.md`](architecture.md) §4)
and every MCP capability has a manual CLI / plain-file equivalent.

---

## Install & run

The SDK is an **optional extra** (the core package stays standard-library-only):

```bash
pip install "crumb-kit[mcp]"     # adds the `mcp` SDK (1.x or 2.x; needs Python >=3.10)
```

Run the server (stdio transport):

```bash
breadcrumbs-mcp                         # console script
python -m breadcrumbs.mcp_server    # equivalent module form
```

**Root resolution.** The server operates on the project in `$BREADCRUMBS_PROJECT`
if set, otherwise the current working directory. `crumb init --with-mcp` (or
`crumb mcp register`) writes a `.mcp.json` that sets this env (see
[Registration](#registration)).

**Graceful degradation.** If the `mcp` SDK is not installed, importing
`breadcrumbs.mcp_server` still succeeds; `build_server()` raises a clear
install hint and `breadcrumbs-mcp` prints that hint — plus the underlying import
error, so "installed but unimportable" is distinguishable from "missing" — and
exits non-zero. Nothing about the CLI or plain files depends on the SDK.

**Supported SDK majors: 1.x and 2.x.** SDK 2.0 renamed the high-level server class
from `mcp.server.fastmcp.FastMCP` to `mcp.server.mcpserver.MCPServer`;
`mcp_server` tries both, newest first. The two are drop-in for everything this
server uses — the `resource`/`prompt`/`tool` decorators, `run()` (stdio by
default), and the `list_*` inspection methods.

**One difference is visible to an MCP client:**

| | SDK 1.x | SDK 2.x |
|---|---|---|
| Server version advertised over MCP | the **SDK's** version (no way to set it) | the **package** version, via the constructor's `version=` |

**The other is not a protocol difference at all**, though it reads like one: SDK
2.0 renamed the camelCase *Python attributes* on its model classes to snake_case.
The serialized form is unchanged — every one of these keeps its camelCase alias on
the wire, verified by dumping both majors' models — so an MCP client sees
identical JSON either way, and only in-process code reading the model objects
(this repo's tests and the CI `mcp` job) has to care:

| Model | SDK 1.x attribute | SDK 2.x attribute | JSON key on both |
|---|---|---|---|
| `Tool` | `inputSchema` | `input_schema` | `inputSchema` |
| `Tool` | `outputSchema` | `output_schema` | `outputSchema` |
| `Resource` | `mimeType` | `mime_type` | `mimeType` |
| `ResourceTemplate` | `mimeType` | `mime_type` | `mimeType` |
| `ResourceTemplate` | `uriTemplate` | `uri_template` | `uriTemplate` |

This table used to list only `uriTemplate` — the one attribute the code happened
to touch — which read as an exhaustive list of a two-item difference and would
have made the next attribute read (say `mimeType`) look safe. Code that
must read one of these should go through the alias-tolerant accessor in
`tests/test_mcp.py`, or dump the model with `by_alias=True` and read the JSON key,
which is stable across both majors.

The extra is bounded (`mcp>=1.2,<3`) because an unbounded range is how 2.0 arrived
unannounced: it installed cleanly, the hardcoded 1.x import failed, and the server
reported itself as "not installed". The CI `mcp` job runs the full suite and a live
server build against **both** majors on Python 3.10–3.14 — the full range the SDK
declares support for, since stopping at 3.12 left the extra untested on two
Pythons it installs on.

---

## Resources (8) — read-only

| URI | Returns | Backed by |
|---|---|---|
| `memory://current` | verbatim `current.md` | plain file |
| `memory://handoff` | verbatim `handoff.md` | plain file |
| `memory://resume-packet` | rendered packet markdown (identical to `crumb resume`) | `build_resume_packet` + `render_packet_markdown` |
| `memory://decisions` | markdown index of **active** decisions (`` `id` — title``) | `active_decisions` |
| `memory://decisions/{id}` | verbatim text of one decision record | `find_record_by_id` |
| `memory://attempts/{id}` | verbatim text of one attempt record | `find_record_by_id` |
| `memory://open-questions` | verbatim `open-questions.md` | plain file |
| `memory://known-traps` | verbatim `known-traps.md` | plain file |

Reading `memory://*` returns the same bytes the CLI / plain files show. An
unknown `{id}` raises (surfaced to the client as a resource error). A missing
`.project-memory/` is a clear `FileNotFoundError`, not a crash.

## Prompts (6) — flows mapping to CLI

| Prompt | Mirrors | Purpose |
|---|---|---|
| `resume_project` | `crumb resume` | orient from the resume packet before acting |
| `capture_session` | `crumb capture session` | wind a session down into durable memory |
| `remember_decision` | `crumb remember decision` | record a durable decision (evidence-backed) |
| `remember_attempt` | `crumb remember attempt` | record a failed attempt + "do not retry" |
| `guard_before_action` | `crumb guard` | check memory before a risky action |
| `audit_project_memory` | `crumb audit` | validate + secret-scan health check |

Prompts return guidance text only. They carry **no authority** over the user's
current instruction, the code, the tests, or authoritative docs.

## Tools (10) — wrap existing functions

| Tool | Signature | Wraps | Output |
|---|---|---|---|
| `memory_search` | `(query, filters?, files?)` | `cli.search` | `{ok, query, filters, count, matches[]}` |
| `memory_record` | `(type, payload)` | `cli.write_record` + validate gate, reindex | `{ok, id, type, path, confidence}` or `{ok:false, error}` |
| `memory_verify` | `(subject, status, method?, note?, evidence?, tags?, confidence?)` | `cli.verify` + validate gate, reindex | `{ok, id, subject, outcome, method, confidence, path}` or `{ok:false, error}` |
| `memory_note` | `(kind, text, fields?, tags?)` | `cli.note` | `{ok, kind, ref|id, path}` or `{ok:false, error}` |
| `memory_reindex` | `()` | `cli.reindex_projections` | `{ok, path}` |
| `memory_guard_before_action` | `(action, files?)` | `cli.guard` | `{ok, verdict, matches, history, staleness, recommended_action, …}` |
| `memory_build_resume_packet` | `(task?)` | `cli.build_resume_packet` | `{ok, …packet}` (`task` is passed to the engine: scoped `likely_files`, echoed `requested_task`, `starting cold` label — identical to `crumb resume --task`) |
| `memory_validate` | `()` | `cli.run_validate` | `{ok, fail_count, findings[]}` (includes the projection-freshness check) |
| `memory_mark_status` | `(id, status, reason, superseded_by?)` | `cli.set_record_status`, reindex | `{ok, id, from, to, path}` or `{ok:false, error}` |
| `memory_scan_secrets` | `()` | `cli.scan_secrets` | `{ok, clean, count, findings[]}` (pattern names + locations only) |

**`recommended_action` (guard) and `next_action` (resume packet) are not the same
field.** `memory_guard_before_action`'s **`recommended_action`** is *synthesized by
this code* from the match kinds behind the verdict — advice about the action you
just proposed, always a non-empty string. `memory_build_resume_packet`'s
**`next_action`** is *recorded state*: the `## Next Action` a session handoff left
behind, and `""` when nobody set one. Both were called `next_action` until 0.1.9,
and a reader who saw the empty resume value naturally concluded guard returns
null. Do not treat one as a fallback for the other.

**`memory_search` and `memory_guard_before_action` read different corpora.** The
search tool includes `ideas/`; the guard tool does not, exactly as `crumb search`
and `crumb guard` differ (see `cli-spec.md` → `search`). An idea is a proposal
exempt from the §16.9 evidence rule, so it may be *retrieved* but must never reach
a verdict. Do not "fix" the asymmetry by passing `include_ideas=True` into
`cli.guard`; `tests/test_guard.py::SpeculativeIdeaTests` fails if you do.

**Envelope.** Every tool success carries `ok`; a missing store is always
`{ok:false, error}`. For `memory_validate` and `memory_scan_secrets`, `ok`
additionally means "healthy/safe" (`false` when problems/findings exist);
`clean` is kept on the scan result for compatibility. A rejected write is
`{ok:false, error}` too — including one the writer refuses outright (a newline in
`title`, say), not just one the validate gate reverts.

**Paths are store-relative.** Every `path` a tool returns is relative to
`.project-memory/` — `decisions/2026-07-24-x.md`, `open-questions.md`,
`generated/resume-packet.md` — the same form validate/audit/doctor findings use.
Never an absolute host path: the MCP client has no filesystem, only the store's
namespace, and the project's absolute location is not the client's business
(issue #7). The CLI still prints absolute paths, because a human's shell can use
them.

### `memory_build_resume_packet` — two pairs of look-alike keys

The packet has two names that differ by one letter and two staleness numbers that
are not the same kind of thing. Both pairs are deliberate:

| Key | What it holds |
|---|---|
| `verifications` | verification **records** (`{id, subject, outcome, method}`) |
| `verification` | verification **commands** — the lines under the handoff's *Verification Commands* heading |
| `stale_after_days` | the **threshold** in force (default 21) |
| `handoff_age_days` / `handoff_commit_distance` | the **measured** handoff age and commit distance; `null` when the timestamp is unparseable or there is no git repo |

The staleness pair was one field named `stale_days` until the round that added the
ages: the threshold was data and the age was English inside
a warning string. The `verification`/`verifications` pair is kept as-is — those keys
are section names driving the packet's cap and trim order, so renaming them changes
the bounding machinery, not just a label.

### `memory_verify`

The home for a verification result — "I checked X; here is its state" (review
F1) — instead of mis-filing it as a decision/attempt. `status` is the **outcome**
(`fixed|open|regressed|not_applicable|inconclusive`); `method` is
`static|runtime|test`. The record-level lifecycle `status` stays `active`; the
outcome lives in an `outcome` frontmatter field. Searchable via
`{type:"verification", status:"open"}` (the `status` filter matches the outcome)
and surfaced in the resume packet's **Verifications** section. Goes through the
same validate gate as `memory_record`, and reindexes on write.

### `memory_note`

Write-surface for the three record kinds that have no `memory_record` type:
`kind` is `"question"`, `"trap"`, or `"idea"`. `fields` mirrors the `crumb note`
flags per kind (question: `why`/`needs`/`status`; trap: `slug`/`area`/`symptom`/
`why`/`safe`/`verify`; idea: `sections{heading:text}`). question/trap append a
parse-verified block to the singleton file; idea passes the same validate gate as
`memory_record`. Each call refreshes `generated/resume-packet.md`. Invalid writes
are reverted.

### `memory_record` payload

Mirrors the `remember` CLI surface:

```jsonc
{
  "title": "Use markdown as the source of truth",     // required
  "sections": { "Decision": "…", "Rationale": "…" },  // {heading: text}
  "evidence": [ { "type": "commit", "ref": "abc1234" } ],
  "tags": ["storage"],
  "confidence": "high",      // optional; omitted ⇒ "low" when no evidence; explicit
                             // medium/high without evidence is an error (validate §16.9)
  "privacy": "repo-safe",    // optional
  "scope": "repo",           // optional
  "status": "active",        // optional
  "agent": "agent"           // optional; recorded in created_by/agent
}
```

`type` must be `"decision"` or `"attempt"`. The write passes the **same**
post-write validate gate as the CLI; an invalid record is reverted (no
half-written file) and `{ok:false, error}` is returned.

**Omitted `confidence` differs from the CLI, deliberately.** Without evidence,
non-interactive `crumb remember` exits 2 and names the flag the human forgot; a
tool call has no such conversation, so an omitted `confidence` is recorded as
`low` — which is exactly what "the caller stated no confidence" means. An
*explicit* `medium`/`high` without evidence is an error on both surfaces:
silently downgrading a stated confidence would misrepresent the caller.

### `memory_mark_status`

Changes a record's `status` (e.g. `stale`, `disputed`, `rejected`) and stamps
`updated_at`, recording `reason` as a trailing non-instruction comment. The edit
is **validate-gated**: e.g. marking `superseded` without a `superseded_by` is
rejected (§16.6) and reverted. When superseding, pass `superseded_by` (the
replacing record's id) — the same flow as `crumb mark-status <id> superseded
--superseded-by <new-id>` on the CLI.

A `trap_<slug>` or `q:<slug>` id resolves here too. Traps and open questions are
blocks inside an aggregate file rather than one file each, so the block's
`- Status:` bullet is edited in place (every other byte preserved) instead of
frontmatter; a block with no such bullet counts as `active` (trap) / `open`
(question). Retiring a trap drops it from `memory://resume-packet` and the hook
pre-filter and stops it driving a `memory_guard_before_action` verdict;
answering a question drops it from the packet, from that verdict's open-blocker
floor and from the aged-unresolved staleness warning. Both stay in the verdict's
context-only history and stay findable through `memory_search` under their new
status.

Questions take their own vocabulary — `open`, `answered`, `closed` — for the
same reason a verification's `outcome` is not its `status`: no lifecycle value
says "somebody answered this". The id decides which vocabulary applies, and a
mismatch (`superseded` on a question, `answered` on a decision) is rejected by
name rather than silently written.

---

## Safety posture

- **Data, not instruction.** Memory content returned over MCP is context about
  prior work; it never overrides the user's current instruction, the code, the
  tests, or authoritative docs. `guard` already treats matched text as data;
  the server changes nothing about that.
- **Writes go through validate.** `memory_record`, `memory_verify`, and
  `memory_mark_status` reuse the exact validate gate `remember` uses — one
  write-behavior — and each refreshes the `generated/` projections on success so
  the static snapshots never desync from the records.
- **Secret-scan before commit.** `memory_scan_secrets` is available so an agent
  can check before any "commit memory" step (§2.6, §15, Fixture 6).
- **No new identity scheme.** `find_record_by_id` uses the same filename-canonical
  id ([`record-schema.md`](record-schema.md) §5) the CLI, search, guard and resume
  already use.

## Design constraints (carried forward)

- MCP tools/resources are thin wrappers over the same canonical records and CLI
  logic — no separate source of truth.
- Executable MCP/hook configuration checked into a repo is a threat surface
  ([`security.md`](security.md)); the generated `.mcp.json` / hook templates are
  opt-in, reviewable, and reversible with `crumb init --remove-integrations`.
- Every MCP capability has a manual CLI / plain-file fallback.

---

## Registration

`crumb init --with-mcp` (or the standalone `crumb mcp register`) merges an
opt-in, reviewable entry into the project `.mcp.json`, preserving any other
servers:

```jsonc
{
  "mcpServers": {
    "breadcrumbs": {
      "type": "stdio",
      "command": "breadcrumbs-mcp",
      "args": [],
      "env": { "BREADCRUMBS_PROJECT": "${CLAUDE_PROJECT_DIR:-.}" }
    }
  }
}
```

Equivalently `python -m breadcrumbs.mcp_server`. The server requires the
`[mcp]` extra to be installed; without it the command exits non-zero with an
install hint (graceful degradation), so a missing optional dependency never
breaks a project that opts into the registration. `crumb doctor` reports whether
the entry is present and whether the `[mcp]` extra is importable. Remove the
entry with `crumb init --remove-integrations`.
