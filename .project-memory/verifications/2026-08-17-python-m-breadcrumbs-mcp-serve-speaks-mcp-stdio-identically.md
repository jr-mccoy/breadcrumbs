---
id: ver_20260817_python-m-breadcrumbs-mcp-serve-speaks-mcp-stdio-identically
type: verification
slug: python-m-breadcrumbs-mcp-serve-speaks-mcp-stdio-identically
title: python -m breadcrumbs mcp serve speaks MCP stdio identically to the breadcrumbs-mcp console script — fixed
status: active
created_at: 2026-08-17T03:42:18+00:00
updated_at: 2026-08-17T03:42:18+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/crumb-kit-audit-review-x5b51n
commit: 37d032f
dirty_files:
  - .project-memory/generated/resume-packet.md
  - CHANGELOG.md
  - README.md
  - breadcrumbs/cli.py
  - docs/mcp-spec.md
  - tests/test_guard.py
  - tests/test_hooks.py
  - tests/test_integrations.py
  - tests/test_note.py
  - tests/test_verify.py
  - .project-memory/decisions/2026-08-17-guard-verdicts-are-capped-by-record-stance-not-by-retrieval.md
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
subject: python -m breadcrumbs mcp serve speaks MCP stdio identically to the breadcrumbs-mcp console script
outcome: fixed
method: runtime
tags:
  - mcp
  - windows
  - packaging
evidence:
  - type: file
    ref: breadcrumbs/cli.py
---

## Subject
python -m breadcrumbs mcp serve speaks MCP stdio identically to the breadcrumbs-mcp console script

## Outcome
fixed

## Method
runtime

## Notes
Driven with the real MCP SDK client against the exact dict mcp_server_entry(windows=True) returns: initialize handshake OK (breadcrumbs 0.1.11), 10 tools, 6 resources, 6 prompts, and a memory_search tool call returned data. Byte-identical surface to breadcrumbs-mcp. The 0.1.11 audit had confirmed only that the module entry point resolved.
