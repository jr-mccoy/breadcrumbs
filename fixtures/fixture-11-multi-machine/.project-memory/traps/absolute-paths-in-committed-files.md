---
id: trap_absolute-paths-in-committed-files
type: trap
slug: absolute-paths-in-committed-files
title: a committed file must never carry a checkout path
status: active
created_at: 2026-09-22T18:29:19+00:00
updated_at: 2026-09-22T18:29:19+00:00
created_by: unknown
agent: migration
project: fixture-11-multi-machine
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
`.project-memory/generated/resume-packet.md`, `deploy/render.py`

## Symptom
the file rewrites itself on every machine, and review diffs fill with path churn

## Why
two developers check this repo out at different paths, so any absolute path is per-machine state committed into shared history

## Safe approach
store paths relative to the project root

## Verification
python -m unittest discover -s tests
