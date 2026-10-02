---
id: dec_20261001_guard-reads-shell-commands-by-segment-and-effect
type: decision
slug: guard-reads-shell-commands-by-segment-and-effect
title: Guard reads shell commands by segment and effect, with a short always-ask list
status: active
created_at: 2026-10-01T22:29:02+00:00
updated_at: 2026-10-01T22:29:02+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/zealous-hamilton-ba7e5m
commit: 3085c5d
dirty_files: []
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
evidence:
  - type: commit
    ref: 4e58737
  - type: file
    ref: breadcrumbs/shellcmd.py
---

## Decision
breadcrumbs/shellcmd.py splits commands into segments; read-only means every segment is; quoted text and heredocs never classify; crumb's own commands are classified by effect; force-push to a default branch, rm -rf outside build dirs and a real crumb migrate always ASK_HUMAN.

## Rationale
Field report issues 7/8/N4: 23 of 23 firings warned, and find | xargs rm -rf was capped as read-only. Operator decision D3 (built-in floor).
