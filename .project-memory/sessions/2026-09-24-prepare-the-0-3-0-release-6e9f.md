---
id: ses_20260924_prepare-the-0-3-0-release-6e9f
type: session
slug: prepare-the-0-3-0-release-6e9f
title: Prepare the 0.3.0 release
status: active
created_at: 2026-09-24T19:45:45+00:00
updated_at: 2026-09-24T19:45:45+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/release-prep-publish-dw1xzf
commit: 7a4a07f
dirty_files:
  - CHANGELOG.md
  - breadcrumbs/__init__.py
  - docs/roadmap-working-memory.md
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

## Work Completed
- 7a4a07f Merge pull request #51 from jr-mccoy/claude/agentic-memory-system-mybkpi
- ecde2fb Capture the Phase 6 session

_Prefill window: `89b94b9`..HEAD — 2 commit(s) since the last session record._

## Decisions Made
Version 0.3.0 for phases 0-6 together (dec_20260924_phases-0-6-ship-together-as-0-3-0-not-the-roadmap-s-per). CHANGELOG [Unreleased] became [0.3.0] with an upgrade note (crumb migrate 1->4, re-run init --with-hooks), verified against a real 0.2.0-built store. Tests, ruff, evals, build and twine check all pass.

## Files Touched
6 files changed, +66/-28 (vs `89b94b9`) — 3 uncommitted file(s), see `dirty_files`

## Next Action
Merge the 0.3.0 release-prep PR to main, then run release.yml from main: mode=dry-run first, then mode=publish. Never tag by hand.
