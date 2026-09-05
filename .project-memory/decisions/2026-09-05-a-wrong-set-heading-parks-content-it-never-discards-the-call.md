---
id: dec_20260905_a-wrong-set-heading-parks-content-it-never-discards-the-call
type: decision
slug: a-wrong-set-heading-parks-content-it-never-discards-the-call
title: A wrong --set heading parks content; it never discards the call
status: active
created_at: 2026-09-05T00:29:33+00:00
updated_at: 2026-09-05T00:29:33+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/artifact-388cc819-sm0ipj
commit: a5de02b
dirty_files: []
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags: []
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: test
    ref: tests/test_sections.py
---

## Context
Field review C1: --set Summary '...800 words...' --set Findings '...600 words...' exited 2 and wrote nothing, because one of four section vocabularies did not know 'Summary'.

## Decision
Matching is case-, space- and punctuation-blind with a short synonym table; anything still unmatched is written under ## Unsorted tagged with the heading the caller used, warned on stderr, and normalize_sections runs inside write_record so non-CLI writers get the same guarantee.

## Rationale
The error was accurate and the cost was everything else on the command line. Content an agent has already synthesised is the most expensive thing in the system to reproduce, and the moment it is lost is the moment the agent has least context left. A guess that lands content under the wrong heading is worse than parking it, so the synonym table stays short.

## Consequences
An unknown heading is no longer an exit-2 signal; callers that relied on that see success plus a CRUMB-WARN line and a warnings key in --json. render_body emits Unsorted last so it never displaces the vocabulary.
