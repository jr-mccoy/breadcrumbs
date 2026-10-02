---
id: dec_20261002_a-store-names-its-oldest-allowed-writer-with-min-crumb
type: decision
slug: a-store-names-its-oldest-allowed-writer-with-min-crumb
title: A store names its oldest allowed writer with min_crumb_version, set by migrate
status: active
created_at: 2026-10-02T04:33:01+00:00
updated_at: 2026-10-02T04:33:01+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/sharp-hopper-g0wbvw
commit: 06932b3
dirty_files: []
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - compat
  - migrate
  - manifest
evidence:
  - type: file
    ref: breadcrumbs/compat.py
  - type: file
    ref: breadcrumbs/migrate.py
---

## Decision
compat refuses writes (warns reads) when the build is older than manifest min_crumb_version. crumb migrate raises it to compat.MIN_SAFE_WRITER (0.5.0), never lowers it, and adds requires: min-crumb-version so 0.4.x and 0.5.0 refuse too. Raise MIN_SAFE_WRITER in a release that changes how a store must be written.

## Rationale
DoWhat retest of 0.5.0, item 14, operator decision D14: a 0.4.x capture session replaced the Next Action log 0.5.0 keeps; the requires: bridge is the only way to stop builds that predate the field.
