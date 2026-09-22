---
id: dec_20260922_traps-and-questions-are-one-file-each-the-singletons
type: decision
slug: traps-and-questions-are-one-file-each-the-singletons
title: Traps and questions are one file each; the singletons are generated indexes that adopt hand-written blocks
status: active
created_at: 2026-09-22T18:42:37+00:00
updated_at: 2026-09-22T18:42:37+00:00
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
  - traps
  - questions
  - schema
  - phase-2
  - wm-22
evidence:
  - type: file
    ref: breadcrumbs/blockfiles.py
  - type: command
    ref: python -m unittest tests.test_blockfiles
---

## Context
WM-22 (schema 3). known-traps.md reached 167 KB and 77 traps in a field store, parsed in full on every hook, and every writer spliced into the same file, which caused merge conflicts between branches. The two singletons are also what a cloud agent without the CLI reads.

## Decision
traps/<slug>.md and questions/<slug>.md with standard frontmatter; files are undated so ids stay trap_<slug> / q_<slug> (q: accepted on input). known-traps.md and open-questions.md become generated one-line-per-record indexes. Readers switch on the manifest schema_version (blockfiles.uses_files), never on disk contents. At schema 3 readers union files with any hand-written block (file wins on id clash); reindex adopts each block into its own file; a block whose id already has a different file is kept under the index and reported by audit as unadopted-block.

## Rationale
Ids are cited in records and commit messages, so they must not change and a dated filename would change them. Pure projections would silently delete blocks that humans, older tool versions or unmigrated branches still append; merging two versions of a trap is a judgement call the tool must not make. Readers return the same dict shapes as before so guard, search, the packet and the prefilter need no change, and results are identical across the migration.

## Consequences
Anything that writes a trap or question must branch on blockfiles.uses_files(). Loose prose and provenance lines from a block land in a Notes section; bookkeeping bullets (Status, Last confirmed, Superseded by, Opened) become frontmatter. The _(not recorded)_ stub render_body writes for an empty record must never be rendered back as a bullet.

## What Not To Retry
Do not regenerate the singletons without first adopting blocks (data loss). Do not decide the store shape from whether traps/ exists.
