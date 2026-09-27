---
id: dec_20260927_projections-are-stamped-from-a-verified-snapshot
type: decision
slug: projections-are-stamped-from-a-verified-snapshot
title: Projections are stamped from a verified snapshot and published as one generation
status: active
created_at: 2026-09-27T02:17:00+00:00
updated_at: 2026-09-27T02:17:00+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/new-session-9f1k6i
commit: 89f5967
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
  - wp07
  - projections
  - guard
  - searchindex
evidence:
  - type: file
    ref: breadcrumbs/snapshots.py
  - type: file
    ref: breadcrumbs/projections.py
  - type: file
    ref: docs/reviews/2026-09-27-breadcrumbs-wp07/README.md
---

## Decision
Every generated projection is built inside snapshots.stable_build (hash before and after, 3 attempts, else stamp 'unstable'), published together with the search index staged until stable, and vouched for by the machine-local index/generation.json written last. The guard hook trusts its pre-filter only via projections.verified; otherwise it runs the full guard. Search-index freshness is the content hash only (INDEX_FORMAT 2).

## Rationale
Audit F07/F11/F12: a stamp taken after the read certified omitted records; an unusable pre-filter silenced real hazards; a size/mtime shortcut made indexed search diverge from the full scan. Re-hashing costs ~17 ms at 1000 records; the unverified hook path costs ~40-90 ms, never silence.
