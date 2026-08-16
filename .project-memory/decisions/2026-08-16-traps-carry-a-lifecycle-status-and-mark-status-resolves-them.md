---
id: dec_20260816_traps-carry-a-lifecycle-status-and-mark-status-resolves-them
type: decision
slug: traps-carry-a-lifecycle-status-and-mark-status-resolves-them
title: Traps carry a lifecycle status and mark-status resolves them
status: active
created_at: 2026-08-16T00:30:33+00:00
updated_at: 2026-08-16T00:30:33+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/trap-retirement-mark-status-o64qqs
commit: 5c861c4
dirty_files:
  - .project-memory/generated/resume-packet.md
  - CHANGELOG.md
  - README.md
  - breadcrumbs/cli.py
  - breadcrumbs/mcp_server.py
  - breadcrumbs/templates/project-memory/known-traps.md
  - docs/cli-spec.md
  - docs/mcp-spec.md
  - tests/test_note.py
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - traps
  - lifecycle
  - guard
  - alarm-fatigue
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: file
    ref: tests/test_note.py
---

## Context
Traps live as ## trap_<slug> blocks inside one aggregate file while decisions/attempts/verifications are one file each, and mark-status only resolved the per-file types. note trap printed an id, search listed it [active], mark-status answered 'no record with id'. No trap could ever be retired through the CLI, so every trap stayed active forever and kept firing in guard and search — the compounding half of the alarm-fatigue finding P0-2 tuned the other half of.

## Options Considered
A separate retire-trap command (a second identity/lifecycle surface for one concept); deleting the block (loses the history a superseded decision keeps); a new 'resolved' status value (widens the schema vocabulary for every record type).

## Decision
A trap block in known-traps.md carries an optional '- Status:' bullet using the same VALID_STATUS vocabulary as records (absent = active). mark-status resolves trap_<slug> ids and edits that bullet in place; a retired trap leaves the resume packet and the guard prefilter and stops driving a verdict, but stays in search and in guard's context-only history.

## Rationale
Reusing VALID_STATUS through the existing mark-status entry point keeps one vocabulary and one writer, and gives the MCP memory_mark_status tool the same reach with no new code. search already printed [active] for traps, so the vocabulary was implied by the UI before it existed in the file.

## Consequences
The block is edited in place — only the Status bullet and a provenance comment change — so hand-written traps survive byte for byte. Lifecycle bullets are stripped from the text that feeds keyword matching (_trap_content): '- Status: active' tokenizes to statu/activ, so indexing the raw body would have added new prefilter noise from the fix meant to remove noise. Open questions still have no writer for their status — same aggregate-file class, not fixed here.
