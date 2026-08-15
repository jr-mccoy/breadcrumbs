---
id: dec_20260815_pypi-trusted-publisher-must-be-re-pointed-after-a-repo
type: decision
slug: pypi-trusted-publisher-must-be-re-pointed-after-a-repo
title: PyPI trusted publisher must be re-pointed after a repo owner rename
status: active
created_at: 2026-08-15T04:39:11+00:00
updated_at: 2026-08-15T04:39:11+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/release-run-failures-gcuil8
commit: 24878e5
dirty_files:
  - .github/workflows/release.yml
  - RELEASING.md
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - release
  - pypi
  - ci
  - trusted-publishing
evidence:
  - type: file
    ref: .github/workflows/release.yml:36
  - type: file
    ref: RELEASING.md:22
  - type: commit
    ref: 24878e5
---

## Context
The 0.1.10 release runs (31861720187, 31863777676, both on 24878e5) failed in publish-pypi at the Trusted Publishing OIDC exchange with 'invalid-publisher: valid token, but no corresponding publisher'. The build job and pre-flight passed; the version 0.1.10 was correct and free (PyPI latest 0.1.9, latest tag v0.1.9). Root cause: the repo moved from owner jumbodaddystack to jr-mccoy after 0.1.9 shipped (2026-08-06), and PyPI matches the trusted publisher against the repo's current owner/name without following GitHub redirects.

## Options Considered
_(not recorded)_

## Decision
Treat invalid-publisher as a PyPI-side config defect, never a workflow bug. The fix is to update the publisher entry at pypi.org/manage/project/crumb-kit/settings/publishing to match the OIDC claims the run prints (owner=jr-mccoy, repo=breadcrumbs, workflow=release.yml, environment=pypi), then re-run release.yml with mode=publish. Documented the failure mode in release.yml's header and in RELEASING.md (one-time setup callout + 'If a release fails' bullet), and corrected the stale owner=jumbodaddystack reference in both.

## Rationale
_(not recorded)_

## Consequences
Re-running unchanged cannot help: unlike the 0.1.8 ConnectTimeout, invalid-publisher is deterministic, so the workflow's built-in second attempt fails identically. Nothing is burned by these failures — the exchange happens before any upload, so no tag, no Release, and 0.1.10 is still free on PyPI. Once PyPI is updated, re-run at 0.1.10 with no version bump.

## What Not To Retry
_(not recorded)_

## Evidence
_(not recorded)_

## Stale / Review Conditions
_(not recorded)_
