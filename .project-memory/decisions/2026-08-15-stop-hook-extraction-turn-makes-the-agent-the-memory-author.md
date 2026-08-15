---
id: dec_20260815_stop-hook-extraction-turn-makes-the-agent-the-memory-author
type: decision
slug: stop-hook-extraction-turn-makes-the-agent-the-memory-author
title: Stop-hook extraction turn makes the agent the memory author
status: active
created_at: 2026-08-15T01:24:22+00:00
updated_at: 2026-08-15T01:24:22+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/system-audit-viability-e2sft7
commit: f981707
dirty_files:
  - .gitignore
  - CHANGELOG.md
  - CLAUDE.md
  - README.md
  - breadcrumbs/cli.py
  - docs/cli-spec.md
  - docs/record-schema.md
  - tests/test_guard.py
  - tests/test_hooks.py
  - tests/test_integrations.py
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - hooks
  - extraction
  - memory
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: command
    ref: python -m unittest tests.test_hooks
---

## Context
The store's high-value records (decisions, attempts, do-not-retry) were 100% human-authored; auto-capture only wrote git snapshots. That discipline tax is what kills tools of this shape.

## Options Considered
_(not recorded)_

## Decision
When the ending turn produced new commits, hook capture holds the stop once (decision: block) and instructs the agent to write records, ending with capture session --next which clears the prompt. Loop-guarded by stop_hook_active; machine snapshot is the floor; manifest extraction_prompt is the kill switch.

## Rationale
_(not recorded)_

## Consequences
Blocking behavior ships on by default to existing hook installs (changelog is the notice). Edit-only turns never prompt; first firing takes a silent baseline.

## What Not To Retry
_(not recorded)_

## Evidence
_(not recorded)_

## Stale / Review Conditions
_(not recorded)_
