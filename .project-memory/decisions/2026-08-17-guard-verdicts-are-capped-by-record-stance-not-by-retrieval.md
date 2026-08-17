---
id: dec_20260817_guard-verdicts-are-capped-by-record-stance-not-by-retrieval
type: decision
slug: guard-verdicts-are-capped-by-record-stance-not-by-retrieval
title: guard verdicts are capped by record stance, not by retrieval overlap
status: active
created_at: 2026-08-17T03:42:09+00:00
updated_at: 2026-08-17T03:42:09+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/crumb-kit-audit-review-x5b51n
commit: 37d032f
dirty_files:
  - CHANGELOG.md
  - README.md
  - breadcrumbs/cli.py
  - docs/mcp-spec.md
  - tests/test_guard.py
  - tests/test_hooks.py
  - tests/test_integrations.py
  - tests/test_note.py
  - tests/test_verify.py
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - guard
  - verdict
  - stance
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: test
    ref: python -m unittest tests.test_guard
---

## Context
0.1.11 field audit F-1/F-2: a trap documenting a hazard in ConversationDao.kt, whose Safe approach prescribed the fix, PAUSEd all five edits implementing that prescribed fix. Overlap answered 'is this about the same thing', never 'does this oppose the action'.

## Decision
A match's stance decides its verdict ceiling: blocking (an attempt with an explicit Do Not Retry Unless) may reach PAUSE; advisory (trap, decision, verification, open question) is capped at READ_FIRST. The score band is applied per match rather than once from the best score across all matches.

## Consequences
PAUSE now means a recorded do-not-retry attempt. To make a record hard-stop an action, write it as remember attempt --do-not-retry. High-impact action classes still escalate to ASK_HUMAN independently of stance.
