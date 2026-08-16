---
id: dec_20260816_questions-get-their-own-status-vocabulary-not-the-record-one
type: decision
slug: questions-get-their-own-status-vocabulary-not-the-record-one
title: Questions get their own status vocabulary, not the record one
status: active
created_at: 2026-08-16T02:22:49+00:00
updated_at: 2026-08-16T02:22:49+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/trap-retirement-mark-status-o64qqs
commit: 4d7c69a
dirty_files:
  - .project-memory/generated/resume-packet.md
  - CHANGELOG.md
  - README.md
  - breadcrumbs/cli.py
  - breadcrumbs/mcp_server.py
  - breadcrumbs/templates/project-memory/open-questions.md
  - docs/cli-spec.md
  - docs/mcp-spec.md
  - tests/test_note.py
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - questions
  - lifecycle
  - guard
  - vocabulary
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: file
    ref: tests/test_note.py
---

## Context
Closing the other half of the aggregate-file gap. Every question reader already honored the '- Status:' bullet — the packet lists only open ones, guard's open-blocker floor needs open, compute_staleness nags only about open ones aging out — but the bullet was write-once at note question time, so an answered question counted as a live blocker forever.

## Options Considered
Reuse VALID_STATUS for questions (one vocabulary everywhere); add 'answered' to VALID_STATUS (every record type gains a word that only fits questions); a per-kind vocabulary.

## Decision
mark-status resolves q:<slug> ids through the same in-place block editor traps use, but questions take open/answered/closed rather than VALID_STATUS. note question --status is constrained to the same vocabulary, on the CLI and the MCP writer alike. Only 'open' is live.

## Rationale
The record words do not fit. The dominant way a question retires is that somebody answered it, and no lifecycle value says that — marking an answered question 'stale' records the opposite of what happened. The codebase already has this shape: a verification's outcome is deliberately not its status, for the same reason. The id decides which vocabulary applies and a mismatch is rejected by name, so the two never silently cross.

## Consequences
mark-status's status check now runs after id resolution, since which vocabulary applies depends on what the id names; an unknown id with a bad status now reports the unknown id first. note question --status was free text and is now constrained — a typo used to silently hide the question from every reader. load_open_questions returns all questions with an id and a content view; open_questions() is the live filter.
