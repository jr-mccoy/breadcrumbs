---
id: trap_hand-tagged-releases
type: trap
slug: hand-tagged-releases
title: Never create a git tag or GitHub Release by hand
status: active
created_at: 2026-09-22T19:27:00+00:00
updated_at: 2026-09-22T19:27:00+00:00
created_by: unknown
agent: migration
project: breadcrumbs
scope: project
branch: claude/agentic-memory-system-mybkpi
commit: ce0d42f
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

## Area / files
.github/workflows/release.yml, RELEASING.md

## Symptom
a tag pointing at a pre-bump commit; dead tags (v0.1.5/v0.1.6); PyPI versions with no tag

## Why
the workflow cuts the tag and Release on the exact commit it builds; a hand tag races it and caused nearly every past failed release

## Safe approach
bump __version__, merge to main, run the release workflow (mode=publish); if a publish fails, re-run it — never hand-tag

## Verification
gh run view on the release workflow; the workflow refuses tag reuse and version regressions
