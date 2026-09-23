---
id: dec_20260922_related-records-use-a-pure-overlap-score-so-the-committed
type: decision
slug: related-records-use-a-pure-overlap-score-so-the-committed
title: Related records use a pure overlap score so the committed related.json is machine-independent
status: active
created_at: 2026-09-22T18:42:38+00:00
updated_at: 2026-09-22T18:42:38+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/agentic-memory-system-mybkpi
commit: 1f3ee4d
dirty_files:
  - .gitignore
  - CHANGELOG.md
  - breadcrumbs/blockfiles.py
  - breadcrumbs/cli.py
  - breadcrumbs/hooks_prompt.py
  - breadcrumbs/mcp_core.py
  - breadcrumbs/mcp_server.py
  - breadcrumbs/migrate.py
  - breadcrumbs/related.py
  - breadcrumbs/searchindex.py
  - breadcrumbs/templates/project-memory/known-traps.md
  - breadcrumbs/templates/project-memory/manifest.yml
  - breadcrumbs/templates/project-memory/open-questions.md
  - breadcrumbs/templates/project-memory/questions/
  - breadcrumbs/templates/project-memory/traps/
  - docs/roadmap-working-memory.md
  - tests/_schema2.py
  - tests/data/schema2/
  - tests/test_aliases.py
  - tests/test_blockfiles.py
  - tests/test_identity.py
  - tests/test_mcp.py
  - tests/test_note.py
  - tests/test_regressions.py
  - tests/test_resume.py
  - … +4 more
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - related
  - projections
  - phase-2
  - wm-25
evidence:
  - type: file
    ref: breadcrumbs/related.py
---

## Context
WM-25 said to relate records by _score_item. That score decays by age and by branch, so two machines compute different neighbours.

## Decision
related.pair_score = shared files x6 + shared tag stems x4 + shared non-ubiquitous specific stems x1, threshold GUARD_NOISE_FLOOR, live items only, top 3, ties broken by id. Written to generated/related.json stamped with inputs_hash; drift detection covers JSON projections with a top-level inputs_hash.

## Rationale
A committed projection that differs per machine churns on every reindex and every commit.
