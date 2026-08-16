---
id: ver_20260815_release-0-1-10-blocked-by-pypi-invalid-publisher-open
type: verification
slug: release-0-1-10-blocked-by-pypi-invalid-publisher-open
title: release 0.1.10 blocked by PyPI invalid-publisher — open
status: superseded
created_at: 2026-08-15T04:39:19+00:00
updated_at: 2026-08-16T04:04:42+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/release-run-failures-gcuil8
commit: 24878e5
dirty_files:
  - .github/workflows/release.yml
  - .project-memory/generated/resume-packet.md
  - RELEASING.md
  - .project-memory/decisions/2026-08-15-pypi-trusted-publisher-must-be-re-pointed-after-a-repo.md
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: ver_20260816_release-0-1-10-blocked-by-pypi-invalid-publisher-fixed
expires_at: null
subject: release 0.1.10 blocked by PyPI invalid-publisher
outcome: open
method: static
tags:
  - release
  - pypi
evidence:
  - type: file
    ref: breadcrumbs/__init__.py:24
  - type: file
    ref: RELEASING.md:88
---

## Subject
release 0.1.10 blocked by PyPI invalid-publisher

## Outcome
open

## Method
static

## Evidence
_(not recorded)_

## Notes
Diagnosed and documented, but NOT fixed: the remaining action is on PyPI (re-point the trusted publisher to owner=jr-mccoy), which cannot be done from this repo. Version 0.1.10 verified correct and unpublished: breadcrumbs/__init__.py has 0.1.10, PyPI latest is 0.1.9, latest tag is v0.1.9, no v0.1.10 tag exists. Suite green (565 tests, 6 skipped).

<!-- status: active -> superseded (0.1.10 published to PyPI and tagged v0.1.10 at 38f3e3d; the trusted-publisher re-point landed) by claude-code at 2026-08-16T04:04:42+00:00 -->
