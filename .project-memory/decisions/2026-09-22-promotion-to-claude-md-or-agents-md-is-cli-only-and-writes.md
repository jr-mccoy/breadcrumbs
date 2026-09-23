---
id: dec_20260922_promotion-to-claude-md-or-agents-md-is-cli-only-and-writes
type: decision
slug: promotion-to-claude-md-or-agents-md-is-cli-only-and-writes
title: Promotion to CLAUDE.md or AGENTS.md is CLI-only and writes to a separate managed block
status: active
created_at: 2026-09-22T20:18:52+00:00
updated_at: 2026-09-22T20:18:52+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/agentic-memory-system-mybkpi
commit: 2581404
dirty_files:
  - CHANGELOG.md
  - docs/roadmap-working-memory.md
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - promote
  - long-term
  - phase-4
  - wm-40
evidence:
  - type: file
    ref: breadcrumbs/promote.py
  - type: command
    ref: python -m unittest tests.test_promote
---

## Context
Phase 4 (WM-40 to WM-43) connects breadcrumbs to the long-term tier: the agent instruction file every session loads whole.

## Decision
crumb promote writes one rule per source record into its own managed block (PROMOTED_BEGIN/END in breadcrumbs/promote.py), separate from the init signpost; the record stays active with promoted_to/promoted_at/promoted_rule. The packet leaves promoted records out of its lists; guard keeps scoring them. Any retirement demotes (hook in set_record_status). No MCP tool for promote/demote. --remove-integrations leaves the promoted block.

## Rationale
An agent writing its own permanent instructions through a tool call is the persistence step of a prompt injection. A separate block keeps the signpost's bloat and removal semantics. A retired rule must not stay in the file every session loads, so demotion cannot be a second manual step.

## What Not To Retry
Do not add a memory_promote MCP tool. Do not render drift against the default rule when a --rule override was used (store it as promoted_rule).
