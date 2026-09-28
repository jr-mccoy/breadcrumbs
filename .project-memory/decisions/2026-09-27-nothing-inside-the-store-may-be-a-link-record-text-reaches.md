---
id: dec_20260927_nothing-inside-the-store-may-be-a-link-record-text-reaches
type: decision
slug: nothing-inside-the-store-may-be-a-link-record-text-reaches
title: Nothing inside the store may be a link; record text reaches agents rendered as data
status: active
created_at: 2026-09-27T06:52:02+00:00
updated_at: 2026-09-27T06:52:02+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/new-session-9f1k6i
commit: a3e3f19
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
  - containment
  - audit
evidence:
  - type: file
    ref: breadcrumbs/path_policy.py
  - type: file
    ref: breadcrumbs/safetext.py
  - type: file
    ref: tests/test_path_containment.py
  - type: file
    ref: docs/reviews/2026-09-27-breadcrumbs-wp13/README.md
---

## Context
Audit F17: a symlinked current.md made memory://current serve a file outside the project; linked directories redirected writes, the store lock wrote its pid through a linked file, migration backups copied linked bytes, and init --force deleted the contents of a linked store's target. Record text carried ANSI escapes, bidi overrides and framing tags verbatim into hook, packet, guard and MCP output.

## Decision
breadcrumbs/path_policy.py refuses any symbolic link or junction inside .project-memory (store dir, directories, files) and '..'; on POSIX every store path is opened component by component with O_NOFOLLOW via directory descriptors and writes rename through the directory fd. Project files may be links only when they resolve inside the project. breadcrumbs/safetext.py renders record text as data (escaped controls and invisible characters, neutralized closing/envelope tags, one-line fields stay one line) everywhere it reaches an agent or terminal; --json and files keep exact values.

## Rationale
No links at all is the simplest rule to audit and nothing in the tool creates one. Descriptor-relative no-follow opens close the check/use race on POSIX. Raising a sanitized PermissionError, rather than returning placeholder text, keeps a refusal from being mistaken for content. Batching reads per directory keeps the checks within noise at 1,000 records.

## Consequences
A store that symlinks itself or a directory elsewhere fails closed and validate reports path-link; migrate refuses until links are replaced. Windows uses lstat checks with a documented residual race and is unqualified until WP17. Hard links are not detected. The symlink_read audit probe now records a probe error (the resource raises), since the audit script stays byte-identical.
