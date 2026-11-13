---
id: trap_crumb-rename-deletes-the-record
type: trap
slug: crumb-rename-deletes-the-record
title: crumb rename deletes the record it renames
status: active
created_at: 2026-11-13T05:05:30+00:00
updated_at: 2026-11-13T05:05:30+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-5a263b6c-3gtzxn
commit: b8c6066
dirty_files: []
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - data-loss
  - rename
evidence: []
---

## Area / files
breadcrumbs/rename.py; crumb rename on any record written by the CLI

## Symptom
crumb rename <id> --slug <new> exits 1 with 'failed validation ... nothing was changed', but the record file is gone and crumb recover finds nothing. An uncommitted record is lost.

## Why
rename.py sets meta id but not meta slug, so the validate gate fails for every record with a slug key; the old file is removed with a bare unlink, outside the journal, so the rollback cannot restore it. tests/test_rename.py uses a hand-written record with no slug key. Found 2026-11-13, at 0.6.2.

## Safe approach
Do not run crumb rename until rename.py sets the slug and deletes through mutations.delete. If a record must be renamed, commit the store first so git can restore it.

## Verification
python -m unittest tests.test_rename # after adding a test that renames a record created by crumb remember
