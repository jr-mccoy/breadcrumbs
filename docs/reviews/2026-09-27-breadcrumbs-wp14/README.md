# WP14: review profiles, and who may make memory authoritative (2026-09-27)

This implements work package WP14 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), finding F18.
The starting commit is `5f5566c`, after WP21. The operator authorized the
remaining work on 2026-09-27 ("continue with the remaining work, whatever
needs to be done"). The roadmap asks WP14 to implement "the approved"
profiles, but no profile design had been approved separately. The design here
is proposed by this package: `solo` is the default and changes nothing, and
`team` is opt-in. The review is where it gets approved or changed.

## Cause

- **Identity was a payload claim.**
  - `memory_record` accepted `agent: human` from an MCP payload, so a record
    written by an agent could say a person wrote it.
  - Review fields in a payload were silently dropped, neither refused nor
    reported.
  - A record committed with `review_status: reviewed` and `reviewed_by:`
    looked exactly like a person's review. Nothing tied a review to what was
    reviewed.
- **No authority boundary.** Nothing separated routine capture from the
  writes that make memory authoritative:
  - `crumb promote` wrote a standing rule into `CLAUDE.md` without any review;
  - MCP could supersede, reject or quarantine any record;
  - there was no way to make MCP read-only or proposal-only.
- **security.md §4 said so.** "Enforcement is still an open question … a
  review convention, not a check."

## Change

**`breadcrumbs/admission.py` (new).**
- **Profiles**, in `manifest.yml` (`review_profile`, `mcp_mode`), set by `crumb
  policy set solo|team [--mcp-mode write|propose|read-only]`:
  - `solo` (default): nothing changes.
  - `team`:
    - guidance (decision, attempt, verification, trap) written through MCP, a
      hook, or the CLI inside an agent session is written unattended as a
      proposal, `review_status: needs-review`;
    - routine capture (jots, sessions, questions, ideas) is unchanged;
    - superseding, rejecting, quarantining or un-quarantining through MCP is
      refused;
    - `crumb promote` requires a valid review;
    - MCP defaults to `propose`, and the store declares
      `requires: review-profiles`.
  - `mcp_mode: propose` works in `solo` too. `read-only` refuses every MCP
    write, and the server does not list the writing tools.
  - An unknown profile reads as `team`, and an unknown mode as `read-only`.
- **The channel is set by the transport:**
  - MCP tools, in `mcp_core._data_tree`;
  - hooks, in `cmd_hook`;
  - the CLI is the default.

  A payload may not set `review_status` beyond `unreviewed`/`needs-review`, or
  `reviewed_by`, `reviewed_at` or `reviewed_hash`, and an MCP or hook payload
  may not claim `agent: human`. Such calls return `{ok: false, error,
  refused_by: "policy"}`.
- **Review stamps.** `crumb review <id>` records `reviewed_by` (`--reviewer`,
  else git's `user.email`, else the OS user), `reviewed_at`, and
  `reviewed_hash`: a digest of the record's claim, excluding bookkeeping
  (review, promotion, `updated_at`, `last_confirmed`).
  - `review_state` is one of `valid`, `stale` (edited since), `claimed` (says
    `reviewed`, no matching stamp) or `none`.
  - Text in a record ("approved by the lead") is never read as a review.
  - Under `team`, `crumb review` and `crumb policy set` are refused inside an
    agent session. That is friction, and it is documented as such.
- **Integration.** `cli.write_record` and the trap-file writer take the new
  record's `review_status` from the policy. `promote._promote` calls
  `check_promote`. The MCP writers call `_admit`: payload checks,
  `supersedes` counted as a high-impact change, and read-only through
  `_locked`. `tool_mark_status` calls `check_status_change`. `mcp_server`
  registers the writing tools through `write_tool`, which omits them under
  read-only.
- **Compatibility.** `compat.KNOWN_FEATURES` gains `review-profiles`.
  `docs/compatibility.md` §4 now distinguishes a store-wide change (schema
  bump) from an opt-in one (`requires:` on the stores that enable it). WP21's
  old-reader test now uses a genuinely unknown feature name.
- **Private to shared** was already disclosed (`from_private` on `inbox
  promote`). Under `team`, the record it creates is a proposal like any other
  agent write.

**Docs.**
- `security.md` §4: the authority model (4.1) and, plainly, what it does not
  protect against (4.2).
- `mcp-spec.md` safety posture; `record-schema.md` (the manifest keys and the
  review fields); `cli-spec.md` (`review`, `policy`); `compatibility.md` §4 and
  §6.
- `architecture.md`, `README.md` and `CHANGELOG.md`.

**Test changed.** `test_release_process`'s tool-count check counts
`@write_tool()` registrations as well as `@mcp.tool()`. The CI job's count is
unchanged at 13, because a writable store serves every tool.

## Tests

`tests/test_admission_policy.py` has 7 tests, including the four the roadmap
names.

- **`test_payload_cannot_forge_trusted_review_identity`.**
  - MCP payloads with `review_status: reviewed`, `reviewed_by`,
    `reviewed_hash`, `agent: human` or `agent: Human` are refused by policy,
    and nothing is written.
  - An honest MCP write is admitted, unreviewed, and not attributed to a
    human.
  - A record edited by hand to say `reviewed` / `reviewed_by: alice` is
    `claimed`, and under `team` its promotion is refused ("only claimed").
  - A record whose title says "approved by the lead" is refused ("has not been
    reviewed").
- **`test_delegated_routine_capture_stays_unattended`.**
  - Under solo, an agent's CLI write is unreviewed, as before.
  - Under team, the MCP decision and verification are admitted as
    `needs-review`, with no interaction. The MCP jot is admitted.
  - A CLI write from an agent session is `needs-review`; a person's is
    `unreviewed`.
  - The prompt hook's correction and the capture hook run without blocking.
  - The proposal is searchable, and `validate` passes.
- **`test_high_impact_promotion_requires_profile_authority`.** Under team:
  - Promotion: unreviewed is refused. Review inside an agent session is
    refused; a person's review stamps `reviewed_by` from git. An edit makes it
    `stale` and promotion is refused ("changed after it was reviewed");
    re-review, then promotion succeeds and the rule is in `CLAUDE.md`.
  - MCP `superseded`, `rejected` and `quarantined` are refused, and so is MCP
    `supersedes`. A routine `stale` succeeds.
  - `policy set` from an agent session is refused.
  - Under read-only, record, jot, mark-status and note all refuse, and the
    store is byte-identical afterwards.
- **`test_legacy_reader_policy_mismatch_is_detected_or_excluded`.**
  - A team store carries `requires: review-profiles` and `review_profile:
    team`.
  - A build without the feature (simulated by emptying `KNOWN_FEATURES`)
    refuses the lock (`IncompatibleStore`), refuses `remember` naming
    `review-profiles`, and warns on `resume`; the store is unchanged.
  - Switching back to solo removes the requirement and leaves every other
    manifest line exactly as it was.
- **Also covered:**
  - solo with `--mcp-mode propose`;
  - solo promotion needs no review, as before;
  - unknown policy values fail closed;
  - under the real MCP SDK (2.2.0), a read-only store's server lists
    `memory_search` and none of the writing tools (skipped without the SDK).

The behavioral comparison is [behavior.txt](behavior.txt), from
[behavior.py](behavior.py): each tree runs in a subprocess, with the team
policy written into the manifest.

| Check (store with `review_profile: team`) | Before (`5f5566c`) | After |
|---|---|---|
| MCP `agent: human` accepted | yes | no (refused) |
| MCP review fields not refused (before: silently dropped) | yes | no (refused) |
| MCP guidance written as a proposal | no | yes |
| MCP quarantine allowed | yes | no |
| Unreviewed promotion allowed | yes | no |
| MCP write allowed under `mcp_mode: read-only` | yes | no |
| **Defects observed** | **6** | **0** |

One informational row: a store with `requires: review-profiles` is refused by
the WP21 build, which lacks the feature, and written by this one. That is the
WP21 gate working, not a defect.

## Results

| Command | Exit | Result |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` (3.11.15) | 0 | 1326 run, 0 failures, 7 skipped |
| admission, mcp, promote, upgrade-contract, release-process, remember, note, inbox, verify and hooks tests on 3.9.23 | 0 | 318 OK |
| `test_mcp` and `test_admission_policy` with MCP SDK 2.2.0 | 0 | OK (2 skipped) and OK (0 skipped) |
| `python evals/run.py --verbose` | 0 | Identical to WP21 apart from timings ([evals.txt](evals.txt)) |
| `python evals/run.py --release` | 0 | 20 critical cases pass |
| `regression_probes.py … --fail-on-observed` | 2 | Unchanged: 3 defect signals, 3 probe errors ([probe-results.json](probe-results.json)) |
| CI `test` job fixture steps, replayed | 0 | All 7 pass |
| `ruff check . && ruff format --check .` (0.16.1) | 0 | Clean |

## Compatibility

- **`solo` is the default and behaves as before**, with one exception: an MCP
  or hook payload that sets review fields or claims `agent: human` is now
  refused where it used to be dropped or accepted.
- **New commands:** `crumb review <id> [--reviewer]` and `crumb policy [show |
  set solo|team [--mcp-mode …]]`.
- **New data:**
  - manifest keys `review_profile` and `mcp_mode`;
  - frontmatter `reviewed_at` and `reviewed_hash`;
  - MCP error field `refused_by: "policy"`.
- **A team store requires `review-profiles`.** Builds without the feature
  (including this branch before WP14) read it with a warning and refuse to
  write it. crumb-kit 0.3.1 and earlier ignore the policy entirely (below).
- **`SCHEMA_VERSION` stays 4.** The profile is opt-in, so it is declared per
  store with `requires:` rather than forcing every store through a migration
  (`compatibility.md` §4).

## Limits

- **It binds MCP clients and hooks, not an agent with a shell.** A full-shell
  agent can edit records, the manifest and `CLAUDE.md` directly, and clear the
  environment that marks an agent session. For those actors, Git review
  (CODEOWNERS or branch protection on `.project-memory/`, `CLAUDE.md` and
  `AGENTS.md`) is the boundary (`security.md` §4.2).
- **Agent detection is an environment claim.** It only ever adds caution: it
  makes writes proposals and refuses `review`. It never grants anything.
- **The reviewer label** is what the person running `crumb review` supplies
  (git `user.email`). It is not authentication.
- **The review hash proves consistency, not authority.** Anyone can compute
  it; it stops stale and accidental approvals, not a malicious committer.
- **Old releases.** crumb-kit 0.3.1 and earlier treat proposals as ordinary
  guidance and promote without review in a team store.
- **Readers do not yet mark proposals.** Packet and guard output do not flag
  `needs-review` records: a proposal is guidance with a pending review, and
  warnings from it stay useful.
- **Review covers one-file records.** Schema-2 trap blocks cannot be reviewed
  or, under team, promoted; migrate first.
