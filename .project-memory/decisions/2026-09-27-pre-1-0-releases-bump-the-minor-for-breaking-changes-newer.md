---
id: dec_20260927_pre-1-0-releases-bump-the-minor-for-breaking-changes-newer
type: decision
slug: pre-1-0-releases-bump-the-minor-for-breaking-changes-newer
title: Pre-1.0 releases bump the minor for breaking changes; newer stores are read with a warning and never written
status: active
created_at: 2026-09-27T20:38:05+00:00
updated_at: 2026-09-27T20:38:05+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/new-session-9f1k6i
commit: 22907a1
dirty_files: []
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - release
  - compatibility
  - migration
  - audit
evidence:
  - type: file
    ref: docs/compatibility.md
  - type: file
    ref: breadcrumbs/compat.py
  - type: file
    ref: tests/test_store_upgrade_contract.py
  - type: file
    ref: docs/reviews/2026-09-27-breadcrumbs-wp21/README.md
---

## Context
Audit WP21 (F05, F18, F24): 0.3.1 and the audit branch silently wrote into a schema_version 5 store; migration backups were unverified and could not be restored; the branch had forked before v0.3.1; get_version reported stale metadata. The operator chose all three options on 2026-09-27.

## Decision
Version policy (docs/compatibility.md): a schema_version change, a requires: feature or an incompatible compatibility-surface change is the next 0.MINOR; fixes and compatible additions are 0.x.PATCH; the next release from this branch is 0.4.0. A store newer than the build (schema or unknown requires: feature) is refused at lock.store_lock (IncompatibleStore) and read with a warning; migrate --restore is the one repair write. Migration backups are verified (backup-manifest.json), interrupted migrations resume against the original backup, and --restore puts the store back exactly. main (v0.3.1) was merged into the branch with a merge commit.

## Rationale
The lock is the one place every committed write already passes, and every caller already handles StoreLocked, so the refusal needs no per-writer code. Released readers (<=0.3.1) cannot be changed, so semantic changes must also be designed to fail safe for them (schema bump, meaning kept out of fields they interpret, a requires: feature). The suite, which the release workflow already runs, enforces the version table rather than a second release process.

## Consequences
Releases add a row to docs/compatibility.md section 3 besides __version__ and the CHANGELOG. WP14's review profiles must ship as a schema bump plus a requires: feature, never as a changed meaning of status: active. Backups from 0.3.1 and earlier have no manifest and are restored by hand.
