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

## Resources (14) — read-only

Seven static URIs and seven per-id templates (`STATIC_RESOURCES` /
`TEMPLATE_RESOURCES` in `mcp_core.py`; `tests/test_mcp.py` pins the count).

| URI | Returns | Backed by |
|---|---|---|
| `memory://current` | verbatim `current.md` | plain file |
| `memory://handoff` | verbatim `handoff.md` — always that file, not the current branch's `handoffs/<slug>.md`; the packet names the one it read | plain file |
| `memory://resume-packet` | rendered packet markdown (identical to `crumb resume`) | `build_resume_packet` + `render_packet_markdown` |
| `memory://decisions` | markdown index of **active** decisions (`` `id` — title``) | `active_decisions` |
| `memory://decisions/{id}` | verbatim text of one decision record | `find_record_by_id` |
| `memory://attempts/{id}` | verbatim text of one attempt record | `find_record_by_id` |
| `memory://records/{id}` | the text `crumb show <id>` prints, for **any** id: record, jot, trap or question | `find_item` |
| `memory://traps/{id}` | one trap (`trap_…`) | `find_item`, kind-checked |
| `memory://questions/{id}` | one question (`q_…`; `q:…` accepted) | `find_item`, kind-checked |
| `memory://verifications/{id}` | one verification record | `find_item`, kind-checked |
| `memory://inbox/{id}` | one jot, committed or machine-local | `find_item`, kind-checked |
| `memory://open-questions` | verbatim `open-questions.md` (at schema 3, the generated index of `questions/`) | plain file |
| `memory://known-traps` | verbatim `known-traps.md` (at schema 3, the generated index of `traps/`) | plain file |
| `memory://inbox` | rendered list of live jots, both inboxes | `inbox.jot_rows` |

The per-id templates are progressive disclosure: the packet, the hook
injections and the two indexes carry one line per item, and these fetch the
body. `memory://records/{id}` serves anything; the typed templates refuse an id
of the wrong kind (a decision id on `memory://traps/{id}` is an error, not the
decision), as `memory://decisions/{id}` and `memory://attempts/{id}` always
have. A trap or question file is served whole (frontmatter and body); one still
stored as a block is served as that block.

`memory://inbox` is the one resource that is *rendered* rather than a file: the
inbox is two directories (committed and machine-local) and the useful view is
both together with the id needed to promote or drop each one. It includes the
private half, which the committed resume packet deliberately excludes — this
resource is read live by the agent working in this checkout, not written to a
file somebody else will read.

Reading the other `memory://*` returns the same bytes the CLI / plain files show. An
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

## Tools (13) — wrap existing functions

| Tool | Signature | Wraps | Output |
|---|---|---|---|
| `memory_search` | `(query, filters?, files?)` | `cli.search` | `{ok, query, filters, count, matches[]}` |
| `memory_record` | `(type, payload)` | `cli.write_record` + validate gate, reindex | `{ok, id, type, path, confidence, supersedes?}` or `{ok:false, error}` |
| `memory_verify` | `(subject, status, method?, note?, evidence?, tags?, confidence?, allow_duplicate?, supersedes?, scope?)` | `cli.verify` + validate gate, reindex | `{ok, id, subject, outcome, method, confidence, expires_at, path, supersedes?}` or `{ok:false, error}` |
| `memory_note` | `(kind, text, fields?, tags?, allow_duplicate?, supersedes?)` | `cli.note` | `{ok, kind, ref|id, path, supersedes?}` or `{ok:false, error}` |
| `memory_jot` | `(text, tags?, files?, local?, allow_duplicate?, scope?)` | `inbox.write_jot` + validate gate, reindex | `{ok, id, path, local, expires_at, source}` or `{ok:false, error}` |
| `memory_inbox_promote` | `(id, target, title?, sections?, evidence?, tags?, confidence?)` | `inbox.promote_jot` | `{ok, jot, promoted_to, type, path}` or `{ok:false, error}` |
| `memory_reindex` | `()` | `cli.reindex_projections` | `{ok, path}` |
| `memory_guard_before_action` | `(action, files?)` | `cli.guard` | `{ok, verdict, matches, history, staleness, recommended_action, …}` |
| `memory_build_resume_packet` | `(task?)` | `cli.build_resume_packet` | `{ok, …packet}` (`task` is passed to the engine: scoped `likely_files`, echoed `requested_task`, `starting cold` label, list sections ordered by relevance with `ordering: "relevance"` — identical to `crumb resume --task`) |
| `memory_show` | `(id)` | `cli.find_item` + `generated/related.json` | `{ok, id, kind, status, path, text, related}` or `{ok:false, error}` |
| `memory_validate` | `()` | `cli.run_validate` | `{ok, fail_count, findings[]}` (includes the projection-freshness check) |
| `memory_mark_status` | `(id, status, reason, superseded_by?)` | `cli.set_record_status`, reindex | `{ok, id, from, to, path, demoted?}` or `{ok:false, error}` |
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
`title`, say), not just one the validate gate reverts. A near-duplicate refusal
adds two keys — `{ok:false, error:"near-duplicate", duplicates, message}`; see
*Near-duplicate refusal* below. A write refused because another writer holds
the store is `{ok:false, error}` as well; see *Store write lock*.

### Store write lock (the seven writers)

`memory_record`, `memory_verify`, `memory_note`, `memory_jot`,
`memory_inbox_promote`, `memory_mark_status` and `memory_reindex` run under the
same store write lock as the writing CLI commands (`cli-spec.md` → *Store write
lock*). A call waits up to 2 seconds for another writer — a CLI command, a
hook, another MCP call in the same server — and then returns without writing:

```jsonc
{ "ok": false, "error": "store is locked by pid 4242; try again, or remove a stale lock" }
```

Retrying later is the answer. The read tools and every resource never wait.

### Branch scope (`memory_jot`, `memory_verify`)

`scope: "branch"` marks a jot or verification that holds only on the current
branch (`cli-spec.md` → *Branch scope*): on any other branch it leaves the
packet's lists and `memory_guard_before_action`'s live set (it is listed under
`history`), and it stays in `memory_search`, whose matches carry `scope`.
`memory_jot` defaults to `"project"`, as `crumb jot` does. A value other than
`"project"` or `"branch"` is ignored (the default applies) rather than refused.
`memory_record`'s `payload.scope` is free text as on `crumb remember`; the
value `"branch"` has the same effect there.

### Near-duplicate refusal (the four writers)

`memory_record`, `memory_verify`, `memory_note` and `memory_jot` apply the same
gate as `crumb remember` / `verify` / `note` / `jot` (`cli-spec.md` →
*Near-duplicate gate*): a new item whose similarity to a **live** item of the
same type (active and unexpired; for a question, `open`) reaches 0.6 — 0.9 for a
jot — is not written, and the call returns

```jsonc
{
  "ok": false,
  "error": "near-duplicate",
  "duplicates": [ { "id": "dec_…", "title": "…", "similarity": 0.71 } ],  // up to 3, most similar first
  "message": "looks like dec_… (0.71 similar) — pass --supersedes dec_… to replace it, or --allow-duplicate to write anyway"
}
```

The message is the CLI's, flag spellings included. Over MCP the answers are:

| Tool | Replace the duplicate | Write both |
|---|---|---|
| `memory_record` | `payload.supersedes: "<id>"` | `payload.allow_duplicate: true` |
| `memory_verify` | `supersedes: "<id>"` | `allow_duplicate: true` |
| `memory_note` | `supersedes: "<id>"` | `allow_duplicate: true` |
| `memory_jot` | — | `allow_duplicate: true` |

`supersedes` must name a live item of the same type; anything else is
`{ok:false, error}` before anything is written. On success the new record
carries `supersedes: [id]` (trap and question files do not carry the key), the
old one is marked `superseded` with `superseded_by` (a question: `closed`), and
the result echoes `supersedes`. An exact repeat of a question's text or a
trap's slug keeps its own error (reopen the existing one with
`memory_mark_status`). `memory_inbox_promote` is not gated: it goes through the
internal writers, which write what they are given.

**No lifecycle-command tools.** `crumb verify --recheck` has no MCP
equivalent, on purpose: it runs shell commands taken from the store, which is a
human-confirmed, CLI-only act. `crumb expired`, `crumb questions`, `crumb
consolidate` and `crumb rollup sessions` are CLI-only too. What they surface
reaches an MCP client through the packet: `memory_build_resume_packet` and
`memory://resume-packet` carry the lifecycle warnings (old actionable
verifications, unconfirmed traps, an untouched `current.md`, cited files
missing from HEAD, possible contradictions) and leave expired records out of
their lists. `memory_search` matches carry an `expired` boolean, and
`memory_guard_before_action` lists an expired match under `history`.

**No promote or demote tool.** `crumb promote` writes a rule into `CLAUDE.md` /
`AGENTS.md`, the file the harness loads into every session. An agent writing
its own permanent instructions through a tool call is the persistence step of a
prompt injection: text planted in a record, a file or a web page could ask for
exactly that call. So promotion is CLI-only — a person runs it, or an agent
runs it where a person can see the command — and `crumb demote` is CLI-only
with it. What promotion changes is visible over MCP:
`memory_build_resume_packet` leaves promoted decisions, attempts and traps out
of its lists and counts them under `promoted` (`{active_decisions,
failed_attempts, known_traps}`, non-zero sections only), and the rendered
`memory://resume-packet` ends each of those sections with `_(N promoted to the
instruction file — see its "Project rules promoted from memory")_`;
`memory_search` matches carry a `promoted` boolean; `memory_guard_before_action`
scores a promoted record at full weight. Retiring one through
`memory_mark_status` does demote it (below).

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

The handoff measured is the one the packet read: at schema 4, the current
branch's `handoffs/<slug>.md` when it exists, else `handoff.md`.
`project.handoff` names it — `handoffs/<slug>.md`, `handoff.md`, or
`handoff.md (no branch handoff)` (`cli-spec.md` → *Branch handoffs*).

The staleness pair was one field named `stale_days` until the round that added the
ages: the threshold was data and the age was English inside
a warning string. The `verification`/`verifications` pair is kept as-is — those keys
are section names driving the packet's cap and trim order, so renaming them changes
the bounding machinery, not just a label.

### `memory_show`

`crumb show` for clients without resource support: the same resolver
(`cli.find_item`) and the same text as `memory://records/{id}`, plus `related`
— up to three ids from `generated/related.json` that share files, tags or
specific vocabulary with this item (`[]` when there are none or the projection
is missing). `path` is store-relative, like every tool path. An unknown or
ambiguous id is `{ok:false, error}`.

### `memory_verify`

The home for a verification result — "I checked X; here is its state" (review
F1) — instead of mis-filing it as a decision/attempt. `status` is the **outcome**
(`fixed|open|regressed|not_applicable|inconclusive`); `method` is
`static|runtime|test`. The record-level lifecycle `status` stays `active`; the
outcome lives in an `outcome` frontmatter field. Searchable via
`{type:"verification", status:"open"}` (the `status` filter matches the outcome)
and surfaced in the resume packet's **Verifications** section. Goes through the
same validate gate as `memory_record`, and reindexes on write. A settled outcome
(`fixed`, `not_applicable`) comes back with an `expires_at`
(`ttl_verification_days`, default 90); an actionable one with `null`.
Re-verifying a subject that already has a live verification is often refused
as a near-duplicate: pass `supersedes` with the old verification's id so the new
result replaces it.

### `memory_note`

Write-surface for the three record kinds that have no `memory_record` type:
`kind` is `"question"`, `"trap"`, or `"idea"`. `fields` mirrors the `crumb note`
flags per kind (question: `why`/`needs`/`status`; trap: `slug`/`area`/`symptom`/
`why`/`safe`/`verify`; idea: `sections{heading:text}`). At schema 3 question/trap
write their own file (`questions/<slug>.md` / `traps/<slug>.md`, id `q_<slug>` /
`trap_<slug>`) through the same validate gate as `memory_record`, and the
singleton index is rebuilt; on a schema-2 store they append a parse-verified
block to the singleton file. idea passes the same validate gate as
`memory_record`. Each call refreshes `generated/resume-packet.md`. Invalid writes
are reverted. `allow_duplicate` and `supersedes` answer a near-duplicate
refusal as on the other writers; superseding a question closes the old one.

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
  "scope": "project",        // optional; free text, "branch" = applies on this branch only
  "status": "active",        // optional
  "agent": "agent",          // optional; recorded in created_by/agent
  "supersedes": "dec_…",     // optional; the live record of this type it replaces
  "allow_duplicate": false   // optional; write despite a near-duplicate
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

A `trap_<slug>` or `q_<slug>` id (legacy `q:<slug>` accepted) resolves here too.
At schema 3 each is its own file and its frontmatter `status` is edited like any
record's. On a schema-2 store — or for a block typed into a singleton since the
last reindex — the block's `- Status:` bullet is edited in place (every other
byte preserved) instead; a block with no such bullet counts as `active` (trap) /
`open` (question). Retiring a trap drops it from `memory://resume-packet` and the hook
pre-filter and stops it driving a `memory_guard_before_action` verdict;
answering a question drops it from the packet, from that verdict's open-blocker
floor and from the aged-unresolved staleness warning. Both stay in the verdict's
context-only history and stay findable through `memory_search` under their new
status.

**Retiring a promoted record demotes it.** Setting a decision, attempt or trap
that `crumb promote` made a standing rule to `superseded`, `stale`, `rejected`,
`disputed` or `quarantined` also removes its line from `CLAUDE.md`/`AGENTS.md` and clears its
`promoted_*` keys, and the result carries `demoted: {ok, id, removed_from,
reason}` (`removed_from` lists file names, e.g. `["CLAUDE.md"]`). A rule nobody
believes any more must not stay in the file every session loads. The writers'
`supersedes` retires the old record the same way, so it demotes too, and
their results carry `demoted: [id]`. These are the only ways an MCP call changes the
instruction file, and they only ever take a rule out.

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
  the static snapshots never desync from the records. The four writers also
  share the CLI's near-duplicate gate.
- **One writer at a time.** The writing tools take the store's write lock and
  refuse with `{ok:false, error}` after 2 seconds rather than interleave with
  a CLI command or hook writing the same store.
- **Nothing runs a command.** No tool executes recorded evidence; rechecking a
  verification's commands is `crumb verify --recheck`, CLI-only.
- **Nothing writes the agent's instructions.** No tool adds a rule to
  `CLAUDE.md`/`AGENTS.md`; `crumb promote` is CLI-only. `memory_mark_status`
  can only take a promoted rule out, by retiring its record.
- **Secret-scan before commit.** `memory_scan_secrets` is available so an agent
  can check before any "commit memory" step (§2.6, §15, Fixture 6).
- **No new identity scheme.** `find_record_by_id` and `find_item` use the same
  filename-canonical ids ([`record-schema.md`](record-schema.md) §5) the CLI,
  search, guard and resume already use; `find_item` is also what `crumb show`
  resolves through.

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

**On Windows `crumb mcp register` writes the module form instead**, because a
running server holding `Scripts\breadcrumbs-mcp.exe` open makes
`pip install --upgrade` fail with `WinError 32` (and the shim is opened without
`FILE_SHARE_DELETE`, so rename-aside is refused too):

```jsonc
{
  "mcpServers": {
    "breadcrumbs": {
      "type": "stdio",
      "command": "C:\\path\\to\\python.exe",
      "args": ["-m", "breadcrumbs", "mcp", "serve"],
      "env": { "BREADCRUMBS_PROJECT": "${CLAUDE_PROJECT_DIR:-.}" }
    }
  }
}
```

Both forms reach the same server — `crumb mcp serve` is one branch of `cmd_mcp`
and calls `mcp_server.main`, so there is no second implementation to drift.

Equivalently `python -m breadcrumbs.mcp_server`. The server requires the
`[mcp]` extra to be installed; without it the command exits non-zero with an
install hint (graceful degradation), so a missing optional dependency never
breaks a project that opts into the registration. `crumb doctor` reports whether
the entry is present and whether the `[mcp]` extra is importable. Remove the
entry with `crumb init --remove-integrations`.
