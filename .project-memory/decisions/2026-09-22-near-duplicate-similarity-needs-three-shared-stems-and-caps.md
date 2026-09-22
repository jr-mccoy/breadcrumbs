---
id: dec_20260922_near-duplicate-similarity-needs-three-shared-stems-and-caps
type: decision
slug: near-duplicate-similarity-needs-three-shared-stems-and-caps
title: Near-duplicate similarity needs three shared stems and caps the file and tag bonus at 0.2
status: active
created_at: 2026-09-22T19:56:25+00:00
updated_at: 2026-09-22T19:56:25+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/agentic-memory-system-mybkpi
commit: 086fc4e
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
  - lifecycle
  - dedup
  - phase-3
  - wm-32
evidence:
  - type: file
    ref: breadcrumbs/lifecycle.py
---

## Context
WM-32 specified Jaccard over specific stems plus 0.15 per shared file and 0.1 per shared tag, threshold 0.6. On this repo's own store that flagged two related-but-distinct decisions at 0.24 text overlap (four shared files), and short texts matched on one word.

## Decision
similarity() returns 0 unless the pair shares at least DUP_MIN_SHARED=3 specific stems (or is identical), counts section content only (not headings), and caps the bonus at DUP_BONUS_MAX=0.2, so text must carry at least 0.4. Threshold 0.6, jots 0.9. The gate is off in note()/verify() by default and on in the CLI and MCP writers.

## Rationale
Records about the same files are related (related.json says so), not duplicates. A refusal that fires on related work teaches agents to pass --allow-duplicate by reflex.
