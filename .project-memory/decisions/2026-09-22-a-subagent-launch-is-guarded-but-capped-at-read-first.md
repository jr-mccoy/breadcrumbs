---
id: dec_20260922_a-subagent-launch-is-guarded-but-capped-at-read-first
type: decision
slug: a-subagent-launch-is-guarded-but-capped-at-read-first
title: A subagent launch is guarded but capped at READ_FIRST
status: active
created_at: 2026-09-22T17:51:29+00:00
updated_at: 2026-09-22T17:51:29+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/agentic-memory-system-mybkpi
commit: 1669a96
dirty_files:
  - CHANGELOG.md
  - README.md
  - breadcrumbs/cli.py
  - breadcrumbs/hooks_common.py
  - breadcrumbs/hooks_compact.py
  - breadcrumbs/hooks_prompt.py
  - breadcrumbs/inbox.py
  - breadcrumbs/mcp_core.py
  - breadcrumbs/transcript.py
  - docs/architecture.md
  - docs/cli-spec.md
  - docs/record-schema.md
  - docs/roadmap-working-memory.md
  - tests/_jsonl.py
  - tests/test_hooks_phase1.py
  - tests/test_integrations.py
  - tests/test_transcript.py
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - guard
  - hooks
  - phase-1
  - wm-16
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: command
    ref: python -m unittest tests.test_hooks_phase1
---

## Context
WM-16. A subagent starts cold: it never reads the resume packet and has none of the session's context. Its launch prompt is the best description of a proposed action a session produces, and the guard never saw it.

## Decision
Task and Agent joined the PreToolUse matcher. The launch prompt is the action string, paths are mined from it, and the verdict is capped at READ_FIRST so the hook injects context and never raises a prompt.

## Rationale
Launching a subagent is not itself irreversible; the subagent's own tool calls hit the same guard, which is where the blast radius actually is. Asking twice for one piece of work is how a gate becomes noise. Both tool names are matched because the tool has carried both across harness versions and a name that never fires costs nothing.

## Consequences
install_claude_hooks now brings an owned entry's matcher up to date on re-install; without that an existing install would keep the old matcher forever while doctor reported it healthy.
