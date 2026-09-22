---
id: dec_20260922_the-search-index-is-a-plain-sqlite-inverted-index-of-our
type: decision
slug: the-search-index-is-a-plain-sqlite-inverted-index-of-our
title: The search index is a plain sqlite inverted index of our own stems, never FTS5, and must equal the full scan
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
  - search
  - index
  - phase-2
  - wm-23
evidence:
  - type: file
    ref: breadcrumbs/searchindex.py
  - type: command
    ref: python -m unittest tests.test_searchindex
---

## Context
WM-23. The plan specified an FTS5 index. FTS5 tokenises text itself and its tokens are not _specific's stems, so a record FTS5 missed could still score, and it is not compiled into every Python.

## Decision
breadcrumbs/searchindex.py stores postings(field, token, rid) of the same stems, tag stems and files search scores on, in index/search.sqlite (machine-local, disposable). Built at reindex from 200 records (reindex --search-index forces). It only narrows the candidate set; ubiquity is computed for the query stems from index document frequency. Freshness is a stat fingerprint first, then _inputs_hash. Stale, absent, unreadable or too small: full scan.

## Rationale
Equivalence is the one rule: indexed search must return exactly the full scan's matches and scores. Our own stems make that true by construction. Computing ubiquity over only the narrowed set changed scores. _inputs_hash reads every file, which cost as much as the scan the index saves.

## What Not To Retry
FTS5 MATCH over raw text (tokeniser mismatch). Ubiquity over narrowed candidates (scores drift). Hash-only freshness (too slow).
