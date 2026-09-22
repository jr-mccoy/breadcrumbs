---
id: dec_20260922_automatic-memory-writes-land-in-private-inbox-and-earn
type: decision
slug: automatic-memory-writes-land-in-private-inbox-and-earn
title: Automatic memory writes land in private/inbox and earn a commit by promotion
status: active
created_at: 2026-09-22T16:54:27+00:00
updated_at: 2026-09-22T16:54:27+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/agentic-memory-system-mybkpi
commit: d71a7e3
dirty_files:
  - .gitignore
  - CHANGELOG.md
  - README.md
  - breadcrumbs/cli.py
  - breadcrumbs/inbox.py
  - breadcrumbs/mcp_core.py
  - breadcrumbs/mcp_server.py
  - breadcrumbs/migrate.py
  - breadcrumbs/templates/project-memory/README.md
  - breadcrumbs/templates/project-memory/inbox/
  - breadcrumbs/templates/project-memory/manifest.yml
  - breadcrumbs/templates/project-memory/private/inbox/
  - breadcrumbs/usage.py
  - docs/cli-spec.md
  - docs/mcp-spec.md
  - docs/record-schema.md
  - docs/roadmap-working-memory.md
  - pyproject.toml
  - tests/test_inbox.py
  - tests/test_init.py
  - tests/test_mcp.py
  - tests/test_migrate.py
  - tests/test_usage.py
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - inbox
  - privacy
  - roadmap
  - wm-03
evidence:
  - type: file
    ref: breadcrumbs/inbox.py
  - type: file
    ref: breadcrumbs/cli.py
  - type: command
    ref: python -m unittest tests.test_inbox
---

## Context
WM-03 adds a jot tier. Phase 1 will write jots automatically from user prompts, transcripts and subagent runs. A hook cannot know whether what it just saw is publishable.

## Decision
Two inbox directories. inbox/ is committed and holds what a human or agent chose to write. private/inbox/ is gitignored and is where every automatic writer must put things. Promotion through 'crumb inbox promote' is what moves content into committed memory; the jot file itself stays private. The committed resume packet lists committed jots only.

## Rationale
A machine-local jot in a committed projection makes that file differ between two checkouts of one store while _inputs_hash calls both fresh, since the hash cannot read gitignored input without the same problem. That is the cross-machine ping-pong _hashed_input_dirs already exists to prevent. Excluding private jots from the packet keeps the projection machine-independent by construction.

## Consequences
WM-12 and WM-15 must surface private jots explicitly (compaction marker, extraction prompt); they will not arrive via the packet. The local-private validate rule became path-aware because private/inbox/ is the first record directory that is not committed.
