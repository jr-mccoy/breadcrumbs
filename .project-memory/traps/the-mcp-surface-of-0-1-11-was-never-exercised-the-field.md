---
id: trap_the-mcp-surface-of-0-1-11-was-never-exercised-the-field
type: trap
slug: the-mcp-surface-of-0-1-11-was-never-exercised-the-field
title: The MCP surface of 0.1.11 was never exercised: the field audit had to kill the server to allow the upgrade, so no mcp__breadcrumbs__* tool ran on that release at all
status: active
created_at: 2026-09-22T19:27:00+00:00
updated_at: 2026-09-22T19:27:00+00:00
created_by: unknown
agent: migration
project: breadcrumbs
scope: project
branch: claude/agentic-memory-system-mybkpi
commit: ce0d42f
dirty_files: []
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
breadcrumbs/mcp_server.py

## Symptom
MCP-only regressions can ship undetected; init, schema, prune, reindex, resume, hook and mcp serve were also untested in the field

## Why
an in-place upgrade on Windows requires stopping every running server, and the audit session never restarted one

## Safe approach
run a session that exercises the MCP tools specifically before the next release; the CLI-side test suite does not cover the SDK wiring (its MCP tests skip without the extra installed)

## Verification
python -m unittest tests.test_mcp with the [mcp] extra installed
