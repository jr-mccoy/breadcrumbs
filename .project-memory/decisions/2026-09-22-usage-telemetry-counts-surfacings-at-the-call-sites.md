---
id: dec_20260922_usage-telemetry-counts-surfacings-at-the-call-sites
type: decision
slug: usage-telemetry-counts-surfacings-at-the-call-sites
title: Usage telemetry counts surfacings at the call sites and stays machine-local
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
  - telemetry
  - roadmap
  - wm-02
evidence:
  - type: file
    ref: breadcrumbs/usage.py
  - type: command
    ref: python -m unittest tests.test_usage
---

## Context
WM-02 needs to know which records actually get shown, to drive decay, ranking and promotion in later phases. The plan put the call inside build_resume_packet.

## Decision
Record at cmd_resume, _hook_session, cmd_guard and _hook_guard instead, into private/usage.json, keyed by record id, never committed.

## Rationale
Every mutation reindexes and every reindex builds a packet, so counting inside build_resume_packet would have measured writes rather than surfacings. Splitting guard between the command and the hook avoids double-counting every hook advisory, since the hook shows a filtered subset of the same result. Counters in frontmatter would churn every record on every guard call and break 'records are authored facts'; a committed counter file would conflict on every merge.

## Consequences
The counts are per machine, so a shared signal remains an open decision to be made with data from this. usage.json also carries a bounded per-record session list, which WM-42 needs and a raw count cannot provide.
