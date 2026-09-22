---
id: dec_20260922_the-transcript-miner-is-deterministic-and-writes-only
type: decision
slug: the-transcript-miner-is-deterministic-and-writes-only
title: The transcript miner is deterministic and writes only candidates
status: active
created_at: 2026-09-22T17:51:29+00:00
updated_at: 2026-09-22T17:51:29+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/agentic-memory-system-mybkpi
commit: 1669a96
dirty_files:
  - CHANGELOG.md
  - README.md
  - breadcrumbs/cli.py
  - breadcrumbs/hooks_common.py
  - breadcrumbs/hooks_compact.py
  - breadcrumbs/hooks_prompt.py
  - breadcrumbs/inbox.py
  - breadcrumbs/mcp_core.py
  - breadcrumbs/transcript.py
  - docs/architecture.md
  - docs/cli-spec.md
  - docs/record-schema.md
  - docs/roadmap-working-memory.md
  - tests/_jsonl.py
  - tests/test_hooks_phase1.py
  - tests/test_integrations.py
  - tests/test_transcript.py
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - miner
  - hooks
  - phase-1
  - wm-14
evidence:
  - type: file
    ref: breadcrumbs/transcript.py
  - type: command
    ref: python -m unittest tests.test_transcript
---

## Context
WM-14 needed to turn a Claude Code transcript into memory. The alternatives were asking a model what was interesting, or writing durable records directly from what a regex noticed.

## Decision
Four deterministic regex rules (failed-then-fixed, passing test command, file churn, user correction) over the JSONL transcript, writing jots into private/inbox/ only. Never a decision, attempt or trap directly; promotion through the real writer is a separate act.

## Rationale
A model-driven miner would be unreproducible, would cost a round trip exactly when a session is ending, and could not run in PreCompact at all — that hook's output never reaches the model. Four narrow rules that are usually right beat one broad rule that cannot be tested. And what a regex noticed is not a finding: the miner cannot tell whether a file was edited four times because it is fragile or because a feature landed in it.

## Consequences
Candidates carry confidence: low, a TTL, and are excluded from every guard verdict. Secret redaction drops rather than masks, and consults only the blocking half of the table — the high-entropy heuristic is warn-only for scan-secrets and would drop candidates citing a build hash. Rules are tunable only with a fixture proving the new shape is real.
