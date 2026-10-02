---
id: dec_20261002_reads-never-rewrite-a-fresh-committed-projection-only-input
type: decision
slug: reads-never-rewrite-a-fresh-committed-projection-only-input
title: Reads never rewrite a fresh committed projection; only input changes or an explicit reindex do
status: active
created_at: 2026-10-02T20:25:18+00:00
updated_at: 2026-10-02T20:25:18+00:00
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
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - projections
  - resume-packet
  - doctor
  - release-0.6.0
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: test
    ref: tests/test_multi_machine.py::ResumeLeavesAFreshPacketTests
---

## Context
crumb resume and the SessionStart republish (every fresh clone, so every cloud session) rewrote generated/resume-packet.md on each run because the render embeds HEAD, generated_at and the dirty count. Every session started dirty, and committing the packet moved HEAD so the next read rewrote it again. doctor compared those same volatile lines and called the packet stale after every commit.

## Decision
_publish_projections_inner keeps a committed generated/ projection whose stamped inputs_hash equals the new digest (_keep_committed_projection) and records the on-disk bytes in the generation manifest. force=True (crumb reindex, migrate, MCP memory_reindex) always rewrites. doctor's _strip_packet_volatile ignores HEAD/clock/dirty-derived lines; Landed Since excludes memory-only commits.

## Rationale
inputs_hash equality is already the definition of fresh that validate gates on. The kept file stays internally consistent: its commit, ages and dirty count all describe the store as of its own generated_at.

## Consequences
The committed packet can show the branch view and git line of whoever last changed the store, not the current checkout; the live views (resume stdout, SessionStart context) are always current. A renderer upgrade reaches the committed file on the next store write or crumb reindex. Deferred: making the committed file branch-independent (docs/reviews/2026-10-02-deferred-health-review.md 4.2).
