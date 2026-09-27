---
id: dec_20260927_packets-are-bounded-on-the-delivered-view-and-promoted
type: decision
slug: packets-are-bounded-on-the-delivered-view-and-promoted
title: Packets are bounded on the delivered view and promoted records stay portable
status: active
created_at: 2026-09-27T03:17:20+00:00
updated_at: 2026-09-27T03:17:20+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/new-session-9f1k6i
commit: da542cd
dirty_files: []
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - audit
  - wp08
  - packet
  - budget
  - promote
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: file
    ref: breadcrumbs/promote.py
  - type: file
    ref: docs/reviews/2026-09-27-breadcrumbs-wp08/README.md
---

## Decision
Every packet view (markdown, markdown-fast, json, json-fast) is bounded on its final serialized text with marked excerpts and pointers; budget/estimator (approx-tokens/2) are reported in the packet. Promoted records stay in portable packets with their effective rule; only a consumer with verified loaded rules (Claude Code's SessionStart hook, via promote.loaded_rules on CLAUDE.md) leaves them out.

## Rationale
Audit F14: the bound covered lists only (7,333 tokens under a 5,000 ceiling). F13: a promoted decision vanished from every packet when CLAUDE.md was gone or unread by the consumer. Promotion is an extra delivery channel, not a reason for memory to disappear.
