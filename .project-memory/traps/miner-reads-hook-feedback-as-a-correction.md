---
id: trap_miner-reads-hook-feedback-as-a-correction
type: trap
slug: miner-reads-hook-feedback-as-a-correction
title: The transcript miner files harness-injected Stop hook feedback as a user correction
status: active
created_at: 2026-11-14T14:58:42+00:00
updated_at: 2026-11-14T14:58:42+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-5a263b6c-3gtzxn
commit: e3f6036
dirty_files: []
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - hooks
  - miner
evidence: []
---

## Area / files
breadcrumbs/transcript.py, breadcrumbs/hooks_prompt.py (correction capture)

## Symptom
A user-role transcript turn that is a Stop hook's blocking message ('Stop hook feedback: [command hook]: There are uncommitted changes ...') was mined as a [correction] jot on 2026-11-14.

## Why
Claude Code delivers hook feedback as a user-role turn; the correction rule matches its wording, not its origin.

## Safe approach
Drop such jots; a fix should skip user turns that start with 'Stop hook feedback:' or carry the harness's hook-feedback marker.
