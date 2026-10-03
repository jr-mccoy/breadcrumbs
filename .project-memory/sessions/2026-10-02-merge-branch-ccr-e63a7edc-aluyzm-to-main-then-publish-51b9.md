---
id: ses_20261002_merge-branch-ccr-e63a7edc-aluyzm-to-main-then-publish-51b9
type: session
slug: merge-branch-ccr-e63a7edc-aluyzm-to-main-then-publish-51b9
title: Merge branch ccr-e63a7edc-aluyzm to main, then publish 0.6.0
status: active
created_at: 2026-10-02T20:38:28+00:00
updated_at: 2026-10-02T20:38:28+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-e63a7edc-aluyzm
commit: 1b26438
dirty_files:
  - CHANGELOG.md
  - breadcrumbs/cli.py
  - breadcrumbs/hooks_common.py
  - breadcrumbs/hooks_compact.py
  - breadcrumbs/inbox.py
  - breadcrumbs/mcp_core.py
  - breadcrumbs/migrate.py
  - docs/cli-spec.md
  - docs/compatibility.md
  - docs/operator-guide.md
  - docs/reviews/2026-10-02-deferred-health-review.md
  - docs/roadmap-working-memory.md
  - tests/test_hooks.py
  - tests/test_hooks_phase1.py
  - tests/test_multi_machine.py
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags: []
evidence: []
---

## Work Completed
- 1b26438 Release 0.6.0: bump the version, CHANGELOG section, compatibility row
- 095f908 Stop hook: committing the store is not new work; the snapshot settles

_Prefill window: `84633e4`..HEAD — 2 commit(s) since the last session record._

## Decisions Made
Reads keep a fresh committed projection (inputs_hash match); crumb reindex/migrate/MCP reindex force. The Stop hook treats a capture made in the extraction turn as covering that turn's commits; an ask is answerable only by the continuation right after it (ask_pending). SubagentStop mines agent_transcript_path only.

## Attempts / Failures
Sharing one parse cache across the whole Stop firing was measured and made no difference (about 300 ms per snapshot either way on this store), so it was removed. A first cut of the coalescing change used the wrong diff base and erased summarized work; an adversarial review caught it plus a stale-ask bug, both fixed with tests.

## Files Touched
13 files changed, +269/-36 (vs `84633e4`) — 15 uncommitted file(s), see `dirty_files`

## Next Action
Merge branch ccr-e63a7edc-aluyzm to main, then publish 0.6.0 (release.yml dry-run, then publish). It now also carries the packet-settles fix (dec_20261002_reads-never-rewrite-a-fresh-committed-projection-only-input) and the Stop lifecycle fixes (dec_20261002_the-stop-hook-treats-the-agent-s-answer-to-the-extraction). Deferred work with evidence: docs/reviews/2026-10-02-deferred-health-review.md.
