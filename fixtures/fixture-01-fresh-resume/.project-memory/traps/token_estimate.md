---
id: trap_token_estimate
type: trap
slug: token_estimate
title: the 5k bound uses a chars/4 token approximation
status: active
created_at: 2026-09-22T18:29:18+00:00
updated_at: 2026-09-22T18:29:18+00:00
created_by: unknown
agent: migration
project: fixture-01-fresh-resume
scope: project
branch: claude/agentic-memory-system-mybkpi
commit: 1f3ee4d
dirty_files:
  - .gitignore
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
  - tests/test_identity.py
  - tests/test_mcp.py
  - tests/test_note.py
  - tests/test_regressions.py
  - tests/test_search.py
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags: []
evidence: []
---

## Area / files
continuity.py resume packet bounding

## Symptom
a packet can run slightly over a real tokenizer's count

## Why
chars/4 is a heuristic, not a real BPE count

## Safe approach
keep section caps conservative; treat 5k as a soft ceiling

## Verification
python -m unittest discover -s tests
