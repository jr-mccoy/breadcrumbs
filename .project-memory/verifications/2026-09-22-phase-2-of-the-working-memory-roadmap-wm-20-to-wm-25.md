---
id: ver_20260922_phase-2-of-the-working-memory-roadmap-wm-20-to-wm-25
type: verification
slug: phase-2-of-the-working-memory-roadmap-wm-20-to-wm-25
title: Phase 2 of the working-memory roadmap (WM-20 to WM-25) is implemented and green — fixed
status: active
created_at: 2026-09-22T18:43:56+00:00
updated_at: 2026-09-22T18:43:56+00:00
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
  - docs/cli-spec.md
  - docs/roadmap-working-memory.md
  - tests/_schema2.py
  - tests/data/schema2/
  - tests/test_aliases.py
  - tests/test_blockfiles.py
  - tests/test_identity.py
  - tests/test_mcp.py
  - tests/test_note.py
  - tests/test_regressions.py
  - … +5 more
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
subject: Phase 2 of the working-memory roadmap (WM-20 to WM-25) is implemented and green
outcome: fixed
method: test
tags:
  - phase-2
  - roadmap
evidence:
  - type: command
    ref: python -m unittest discover -s tests
  - type: file
    ref: tests/test_blockfiles.py
  - type: file
    ref: tests/test_searchindex.py
---

## Subject
Phase 2 of the working-memory roadmap (WM-20 to WM-25) is implemented and green

## Outcome
fixed

## Method
test

## Notes
994 unit tests pass (python -m unittest discover -s tests), ruff check and format clean. Indexed search equals the full scan on a 500-record synthetic store and on fixture-10. Migrating schema-2 stores with trap/question blocks leaves guard verdicts, search results and reader output unchanged (tests/test_blockfiles.py; fixtures 01/07/11 checked by hand). All 12 fixtures migrated to schema 3; CI fixture steps pass locally. The repo's own .project-memory is still schema 2: guard returned ASK_HUMAN for migrating it.
