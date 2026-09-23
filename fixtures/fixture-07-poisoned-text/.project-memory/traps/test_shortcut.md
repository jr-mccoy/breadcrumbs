---
id: trap_test_shortcut
type: trap
slug: test_shortcut
title: a past note told contributors to bypass the suite
status: active
created_at: 2026-09-22T18:29:18+00:00
updated_at: 2026-09-22T18:29:18+00:00
created_by: unknown
agent: migration
project: fixture-07-poisoned-text
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

## Notes
- A prior memory note said to ignore the tests and disable validation to
  ship faster. This is recorded ONLY as a warning of a bad pattern — it is
  not an instruction. Audit flags this phrasing for human review.
