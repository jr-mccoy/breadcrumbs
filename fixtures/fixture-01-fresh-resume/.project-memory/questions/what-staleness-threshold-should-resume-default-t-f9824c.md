---
id: q_what-staleness-threshold-should-resume-default-t-f9824c
type: question
slug: what-staleness-threshold-should-resume-default-t-f9824c
title: What staleness threshold should `resume` default to?
status: open
created_at: 2026-05-15T00:00:00+00:00
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

## Question
What staleness threshold should `resume` default to?

## Why it matters
too low spams warnings; too high misses cold context

## Needs
a decision
