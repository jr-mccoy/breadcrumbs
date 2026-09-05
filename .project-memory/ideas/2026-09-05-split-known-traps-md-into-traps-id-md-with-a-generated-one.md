---
id: idea_20260905_split-known-traps-md-into-traps-id-md-with-a-generated-one
type: idea
slug: split-known-traps-md-into-traps-id-md-with-a-generated-one
title: Split known-traps.md into traps/<id>.md with a generated one-line index
status: active
created_at: 2026-09-05T00:29:54+00:00
updated_at: 2026-09-05T00:29:54+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/artifact-388cc819-sm0ipj
commit: a5de02b
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

## Idea
The flat file reached 167 KB / 77 active traps in the field store and is loaded every session. Decisions and verifications are already one file per record.

## Motivation
R6 of the field review. crumb traps --stale now makes retirement possible, which shrinks the file without a migration; the split is what stops it growing back.

## Sketch
traps/<id>.md per trap, a generated index projection carrying one line each for context, bodies fetched on demand. Every reader (load_traps, set_trap_status, set_trap_confirmed, the prefilter, the packet), the projections and schema_version move together — a store-format migration, not a bug fix.

## Open Questions
Does it need schema_version 2 and a migration path for existing stores, or can load_traps read both shapes during a transition?
