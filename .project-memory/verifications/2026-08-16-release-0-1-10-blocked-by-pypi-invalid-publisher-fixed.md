---
id: ver_20260816_release-0-1-10-blocked-by-pypi-invalid-publisher-fixed
type: verification
slug: release-0-1-10-blocked-by-pypi-invalid-publisher-fixed
title: release 0.1.10 blocked by PyPI invalid-publisher — fixed
status: active
created_at: 2026-08-16T04:04:28+00:00
updated_at: 2026-08-16T04:04:28+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/breadcrumbs-ci-release-fu0q13
commit: 491b544
dirty_files:
  - CHANGELOG.md
  - breadcrumbs/cli.py
  - tests/test_note.py
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
subject: release 0.1.10 blocked by PyPI invalid-publisher
outcome: fixed
method: static
tags: []
evidence:
  - type: command
    ref: curl -s https://pypi.org/pypi/crumb-kit/json
---

## Subject
release 0.1.10 blocked by PyPI invalid-publisher

## Outcome
fixed

## Method
static

## Notes
0.1.10 is on PyPI and v0.1.10 is tagged at 38f3e3d, so the trusted-publisher re-point landed and the release completed end to end. Supersedes ver_20260815_release-0-1-10-blocked-by-pypi-invalid-publisher-open, which still reads 'open' and made guard answer ASK_HUMAN on any release work.
