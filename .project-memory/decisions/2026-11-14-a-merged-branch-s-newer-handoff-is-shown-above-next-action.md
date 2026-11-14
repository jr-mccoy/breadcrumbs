---
id: dec_20261114_a-merged-branch-s-newer-handoff-is-shown-above-next-action
type: decision
slug: a-merged-branch-s-newer-handoff-is-shown-above-next-action
title: A merged branch's newer handoff is shown above Next Action, with no git
status: active
created_at: 2026-11-14T14:57:15+00:00
updated_at: 2026-11-14T14:57:15+00:00
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
  - handoff
  - packet
evidence:
  - type: file
    ref: breadcrumbs/handoffs.py
  - type: file
    ref: breadcrumbs/packet.py
  - type: test
    ref: tests/test_delivery_reach.py
---

## Decision
handoffs.newer_merged lists branch handoffs in the checkout written after the handoff a resume reads, excluding the current branch's own and .history.md files. The packet shows up to 3 above Next Action, labelled with branch, file and date; JSON merged_handoffs only when non-empty.

## Rationale
Branch handoffs are committed on their branch, so presence in the checkout is the merge; no ancestry check or git spawn is needed. Nothing carried a branch's Next Action forward on merge, so main's handoff.md was 40 days stale in a pull-request workflow. Emitting the key only when non-empty kept the application-parity wire fixture unchanged.
