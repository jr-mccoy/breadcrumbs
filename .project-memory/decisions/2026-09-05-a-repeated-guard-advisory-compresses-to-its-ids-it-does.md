---
id: dec_20260905_a-repeated-guard-advisory-compresses-to-its-ids-it-does
type: decision
slug: a-repeated-guard-advisory-compresses-to-its-ids-it-does
title: A repeated guard advisory compresses to its ids, it does not go silent
status: active
created_at: 2026-09-05T03:23:04+00:00
updated_at: 2026-09-05T03:23:04+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/guard-context-bloat-wcle08
commit: 53b5dac
dirty_files:
  - CHANGELOG.md
  - breadcrumbs/cli.py
  - breadcrumbs/templates/project-memory/known-traps.md
  - tests/test_hooks.py
  - tests/test_traps.py
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - guard
  - hooks
  - context-budget
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: file
    ref: tests/test_hooks.py
---

## Context
The PreToolUse guard's dedupe key was <file-or-action>|<record-ids>. It only recognizes a repeat when the command repeats byte-for-byte, so for Bash — where every command differs — it essentially never fired. One measured session: 52 distinct records, 215 injections, 41,961 bytes of guard text where one body each would have been 8,214. 81% verbatim repetition.

## Decision
Key the session dedupe on the record id alone, and on a repeat emit a single line naming the ids ('breadcrumbs guard: READ_FIRST — already shown this session: trap_a, trap_b') instead of the bodies. PAUSE/ASK_HUMAN are untouched and never dedupe.

## Rationale
Suppressing the repeat entirely was the alternative and it is cheaper by ~50 bytes a call, but the record still applies to the call being made: an advisory that vanishes on the second edit of a file is one the agent cannot act on, and the agent has no way to ask for it back. Naming the ids keeps the warning addressable (crumb search <id>) at a bounded cost. The tension this design has always had — dedupe so the agent does not learn to skim, repeat so the warning is present when it matters — is resolved by dropping the body, not the mention.

## Consequences
Measured A/B, 20 Bash calls against the same two traps: 28,500 -> 2,246 bytes, a 92% cut, with an advisory still emitted on all 20 calls. First firing 422 bytes, each repeat 96. The Edit path (which the old key did dedupe correctly) pays ~96 bytes per repeat where it used to pay nothing.
