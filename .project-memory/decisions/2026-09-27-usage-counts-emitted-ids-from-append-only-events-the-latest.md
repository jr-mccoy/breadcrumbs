---
id: dec_20260927_usage-counts-emitted-ids-from-append-only-events-the-latest
type: decision
slug: usage-counts-emitted-ids-from-append-only-events-the-latest
title: Usage counts emitted ids from append-only events; the latest task is recorded before retrieval
status: active
created_at: 2026-09-27T05:46:01+00:00
updated_at: 2026-09-27T05:46:01+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/new-session-9f1k6i
commit: dca2a94
dirty_files: []
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - telemetry
  - hooks
  - audit
evidence:
  - type: file
    ref: breadcrumbs/usage.py
  - type: file
    ref: breadcrumbs/hooks_prompt.py
  - type: file
    ref: tests/test_emission_accounting.py
  - type: file
    ref: docs/reviews/2026-09-27-breadcrumbs-wp12/README.md
---

## Context
Audit F15/F16: compaction restored an older matched task because the task was saved only on a match; usage counted guard repeats the hook stayed silent on and prompt lines trimmed away; parallel writers lost 110-130 of 180 read-modify-write increments.

## Decision
The prompt hook records every substantive prompt as the session's latest task before the lookup, and keeps the lookup's selected/emitted ids apart, labelled by prompt digest. Usage counts only ids in printed output, after dedupe and budget trimming. Each emission is one event file under private/usage-events/, folded exactly once into usage.json under .usage.lock; hook state updates take a per-file side lock; the hook log rotates instead of being rewritten.

## Rationale
A count must mean the host received the record; anything else inflates decay/promotion signals. Event files make acknowledged increments durable without a shared read-modify-write, and the fold's folded_last makes a crash between write and delete harmless. Telemetry never takes the store lock, so it cannot delay writers.

## Consequences
Counts say shown, not read or useful; nothing acts on them alone. Drops are reported (usage_dropped, state_dropped, crumb usage accounting). The guard_usage_dedupe audit probe keeps flagging because its condition is counts-is-not-None; its recorded usage is now 1, not 2. Refines dec_20260922_usage-telemetry-counts-surfacings-at-the-call-sites (still call sites, still machine-local).
