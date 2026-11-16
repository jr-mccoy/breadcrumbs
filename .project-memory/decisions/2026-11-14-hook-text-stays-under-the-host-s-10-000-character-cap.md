---
id: dec_20261114_hook-text-stays-under-the-host-s-10-000-character-cap
type: decision
slug: hook-text-stays-under-the-host-s-10-000-character-cap
title: Hook text stays under the host's 10,000-character cap, trimmed by meaning
status: active
created_at: 2026-11-14T14:57:14+00:00
updated_at: 2026-11-14T14:57:14+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-5a263b6c-3gtzxn
commit: 973bbcb
dirty_files:
  - .claude/
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - hooks
  - packet
evidence:
  - type: file
    ref: breadcrumbs/hooks_common.py
  - type: file
    ref: breadcrumbs/packet.py
  - type: test
    ref: tests/test_delivery_reach.py
---

## Decision
Every hook's text stays within hooks_common.CONTEXT_CHAR_BUDGET (9,500 UTF-16 code units). The SessionStart packet passes a char_limit to build_resume_packet, which trims in TRIM_ORDER like the token budget, after the compaction preamble's share, and ends with a pointer to crumb resume. Prompt and guard text get fit_context as a backstop. crumb resume and MCP are not char-limited.

## Rationale
Claude Code caps additionalContext at 10,000 characters and shows only a 2,000-character preview of anything longer; this repo's packet was 12,317, so the model saw two decisions. Token budgets do not bound characters. Counting UTF-16 units matches a JavaScript host; 500 characters of headroom absorb a host that counts differently.
