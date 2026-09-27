---
id: dec_20260927_transcript-mining-uses-a-byte-cursor-carried-calls
type: decision
slug: transcript-mining-uses-a-byte-cursor-carried-calls
title: Transcript mining uses a byte cursor, carried calls and a durable backlog
status: active
created_at: 2026-09-27T03:58:21+00:00
updated_at: 2026-09-27T03:58:21+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/new-session-9f1k6i
commit: 9bdcd58
dirty_files: []
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - audit
  - wp09
  - transcript
  - hooks
evidence:
  - type: file
    ref: breadcrumbs/transcript.py
  - type: file
    ref: breadcrumbs/hooks_common.py
  - type: file
    ref: docs/reviews/2026-09-27-breadcrumbs-wp09/README.md
---

## Decision
Hooks mine transcripts through transcript.ingest under the store lock: a byte cursor at line boundaries with head/anchor identity digests, Bash/edit calls carried between firings, candidates saved to a per-session backlog in private/miner/ before any jot is written, and a cross-session ledger of acknowledged event ids for idempotency. Nothing is dropped without being counted.

## Rationale
Audit F02: an entry count over a sliding 8 MB tail froze once transcripts outgrew it, lost cross-firing call/result pairs, and discarded capped or failed candidates silently.
