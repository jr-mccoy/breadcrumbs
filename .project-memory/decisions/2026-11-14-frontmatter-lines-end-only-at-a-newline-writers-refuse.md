---
id: dec_20261114_frontmatter-lines-end-only-at-a-newline-writers-refuse
type: decision
slug: frontmatter-lines-end-only-at-a-newline-writers-refuse
title: Frontmatter lines end only at a newline; writers refuse every line-break character
status: active
created_at: 2026-11-14T15:15:52+00:00
updated_at: 2026-11-14T15:15:52+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-5a263b6c-3gtzxn
commit: 10f8a9d
dirty_files: []
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - security
  - frontmatter
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: test
    ref: tests/test_gate.py
  - type: commit
    ref: 10f8a9d
---

## Decision
cli.parse_frontmatter splits on \n only (after CRLF to LF); _render_scalar refuses any of FRONTMATTER_LINE_BREAKS (newline, CR, VT, FF, the information separators, NEL, U+2028, U+2029). Bodies keep such characters byte for byte.

## Rationale
With splitlines() on read and a two-character refusal on write, a U+2028 inside an evidence ref became keys on read and forged review fields past admission, which inspects payload keys only. Both sides now agree, and other tools reading the files cannot be fooled by a value crumb wrote.
