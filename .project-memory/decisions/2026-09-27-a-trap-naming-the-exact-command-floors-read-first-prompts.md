---
id: dec_20260927_a-trap-naming-the-exact-command-floors-read-first-prompts
type: decision
slug: a-trap-naming-the-exact-command-floors-read-first-prompts
title: A trap naming the exact command floors READ_FIRST; prompts are looked up unless they are acknowledgements
status: active
created_at: 2026-09-27T04:58:55+00:00
updated_at: 2026-09-27T04:58:55+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/new-session-9f1k6i
commit: 5210aa8
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
  - wp10
  - guard
  - retrieval
  - hooks
evidence:
  - type: file
    ref: breadcrumbs/retrieval.py
  - type: file
    ref: breadcrumbs/cli.py
  - type: file
    ref: docs/reviews/2026-09-27-breadcrumbs-wp10/README.md
---

## Decision
Guard gives a live trap whose summary or hazard text names the action's command (>=2 leading tokens, whole action or up to a flag; remedy spans excluded) the command signal and a READ_FIRST floor; the pre-filter lists named commands. The prompt hook looks up every non-acknowledgement prompt via breadcrumbs/retrieval.py, with no corpus pre-count or 500 cutoff, a bounded full scan (2,000) and a reported skip beyond it.

## Rationale
Audit F09/F10: memory vanished above 500 records and for prompts under 12 characters, and npm test got PROCEED from a trap about npm test.
