---
id: dec_20261002_the-stop-hook-treats-the-agent-s-answer-to-the-extraction
type: decision
slug: the-stop-hook-treats-the-agent-s-answer-to-the-extraction
title: The Stop hook treats the agent's answer to the extraction turn as covering that turn's commits
status: active
created_at: 2026-10-02T20:25:19+00:00
updated_at: 2026-10-02T20:25:19+00:00
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
  - stop-hook
  - extraction
  - subagent
  - release-0.6.0
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: file
    ref: breadcrumbs/hooks_common.py
  - type: file
    ref: breadcrumbs/hooks_compact.py
  - type: test
    ref: tests/test_hooks.py::StopLifecycleTests
---

## Context
After the extraction ask, an agent that committed its uncommitted code together with its capture got a machine snapshot stacked beside its record and was asked again about that commit. Rewritten history (amend, rebase) re-baselined silently and dropped the work. Subagent jots alone earned the ask, and SubagentStop mined the parent's transcript_path instead of agent_transcript_path.

## Decision
The baseline entry stamps asked_at. In the continuation, an authored session record created at or after asked_at means the agent answered: the baseline moves to HEAD and the tree is recorded as settled, so the next Stop is redundant while the tree is unchanged. A non-ancestor baseline counts from merge-base, skipping commits authored at or before asked_at. Subagent-tagged jots are listed but never earn the ask. SubagentStop reads only agent_transcript_path. Hook snapshots coalesce per host session and order by updated_at.

## Rationale
The ask's instruction ends with the capture, so a capture after the ask is the answer, whatever else the turn committed. Amend and rebase preserve author time, which is what tells an already-asked commit from new work.

## Consequences
One more private state field (settled) per session; the baseline file keeps 64 sessions. A payload without session_id is keyed by transcript path; only one with neither uses the shared bucket, which restarts at SessionStart.
