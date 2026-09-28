---
id: dec_20260927_transports-reach-the-store-through-breadcrumbs-service
type: decision
slug: transports-reach-the-store-through-breadcrumbs-service
title: Transports reach the store through breadcrumbs.service with an explicit Context
status: active
created_at: 2026-09-27T22:30:28+00:00
updated_at: 2026-09-27T22:30:28+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/new-session-9f1k6i
commit: c08c6be
dirty_files: []
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - architecture
evidence:
  - type: file
    ref: breadcrumbs/service.py
  - type: file
    ref: tests/test_application_parity.py
---

## Decision
CLI, MCP and hooks call service functions (record, mark_status, search, guard, resume_packet, prompt_lookup, admit) inside service.active(ctx); wording, exit codes and envelopes stay in the adapters. Parser lives in cli_parser.py. Aliases and clock are per-thread scoped state. Any further move out of cli.py must keep tests/fixtures/application_parity.json passing (audit WP16).
