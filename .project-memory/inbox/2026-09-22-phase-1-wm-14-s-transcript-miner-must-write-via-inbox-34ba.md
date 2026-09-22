---
id: jot_20260922_phase-1-wm-14-s-transcript-miner-must-write-via-inbox-34ba
type: jot
slug: phase-1-wm-14-s-transcript-miner-must-write-via-inbox-34ba
title: Phase 1 WM-14's transcript miner must write via inbox.write_jot(source='transcript', local=True) — the private/inbox split is load-bearing, not a default
status: active
created_at: 2026-09-22T16:54:33+00:00
updated_at: 2026-09-22T16:54:33+00:00
created_by: unknown
agent: claude-code
source: agent
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
confidence: low
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: 2026-10-06T16:54:33+00:00
tags:
  - wm-14
  - phase-1
evidence:
  - type: file
    ref: breadcrumbs/inbox.py
---

## Note
Phase 1 WM-14's transcript miner must write via inbox.write_jot(source='transcript', local=True) — the private/inbox split is load-bearing, not a default
