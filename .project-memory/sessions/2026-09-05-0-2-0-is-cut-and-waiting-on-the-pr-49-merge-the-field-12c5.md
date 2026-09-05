---
id: ses_20260905_0-2-0-is-cut-and-waiting-on-the-pr-49-merge-the-field-12c5
type: session
slug: 0-2-0-is-cut-and-waiting-on-the-pr-49-merge-the-field-12c5
title: "0.2.0 is cut and waiting on the PR #49 merge; the field-review work is"
status: active
created_at: 2026-09-05T01:35:59+00:00
updated_at: 2026-09-05T01:35:59+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/artifact-388cc819-sm0ipj
commit: 9037d68
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

## Work Completed
Bumped __version__ to 0.2.0 and dated the CHANGELOG section. Chose 0.2.0 over 0.1.13 because four behaviour changes can surprise a 0.1.12 consumer (scan-secrets exit code, --set exit code, session id shape, dirty_files contents); they are collected under a Changed heading.

## Files Touched
13 files changed, +373/-32 (vs `a5de02b`)

## Commands / Verification
python -m unittest discover -s tests (775 pass); ruff check . && ruff format --check .; python crumb.py --version -> breadcrumbs 0.2.0

## Next Action
Merge PR #49 to main, then run release.yml from main: mode=dry-run first to confirm the artifact, then mode=publish. Do not hand-tag — the workflow cuts the tag and the Release on the commit it builds.
