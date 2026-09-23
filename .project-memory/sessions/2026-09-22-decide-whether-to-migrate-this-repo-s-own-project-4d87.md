---
id: ses_20260922_decide-whether-to-migrate-this-repo-s-own-project-4d87
type: session
slug: decide-whether-to-migrate-this-repo-s-own-project-4d87
title: Decide whether to migrate this repo's own .project-memory to schema 3
status: active
created_at: 2026-09-22T18:53:06+00:00
updated_at: 2026-09-22T18:53:06+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/agentic-memory-system-mybkpi
commit: c367b90
dirty_files:
  - README.md
  - breadcrumbs/blockfiles.py
  - breadcrumbs/cli.py
  - breadcrumbs/mcp_core.py
  - breadcrumbs/searchindex.py
  - breadcrumbs/templates/project-memory/README.md
  - breadcrumbs/templates/project-memory/index/README.md
  - docs/architecture.md
  - docs/cli-spec.md
  - docs/mcp-spec.md
  - docs/record-schema.md
  - tests/test_traps.py
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
- c367b90 Document Phase 2 in the CLI spec and record schema
- 8bdc4bd Implement Phase 2 of the working-memory roadmap (WM-20 to WM-25)
- 1f3ee4d feat: phase 1 of the working-memory roadmap (capture everywhere)

_Prefill window: `1669a96`..HEAD — 3 commit(s) since the last session record._

## Decisions Made
Phase 2 (WM-20..25) shipped: relevance-ordered packet, crumb show + per-id MCP resources, traps/questions as files (schema 3) with block adoption, plain sqlite search index equal to the full scan, store aliases, related.json from a machine-independent overlap score. Eight departures from the plan recorded in roadmap section 0.7.

## Files Touched
122 files changed, +7959/-358 (vs `1669a96`) — 12 uncommitted file(s), see `dirty_files`

## Next Action
Decide whether to migrate this repo's own .project-memory to schema 3 (guard said ASK_HUMAN; one `crumb migrate`). Then cut the 0.5.0 release per CLAUDE.md, or start Phase 3 (WM-30 typed TTL) from docs/roadmap-working-memory.md; read roadmap section 0.7 first.
