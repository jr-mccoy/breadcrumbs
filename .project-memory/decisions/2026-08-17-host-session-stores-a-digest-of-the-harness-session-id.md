---
id: dec_20260817_host-session-stores-a-digest-of-the-harness-session-id
type: decision
slug: host-session-stores-a-digest-of-the-harness-session-id
title: host_session stores a digest of the harness session id, never the raw id
status: active
created_at: 2026-08-17T15:49:32+00:00
updated_at: 2026-08-17T15:49:32+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/crumb-kit-audit-review-x5b51n
commit: 973a352
dirty_files:
  - breadcrumbs/cli.py
  - docs/cli-spec.md
  - docs/record-schema.md
  - tests/test_hooks.py
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - capture
  - secrets
  - schema
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: test
    ref: python -m unittest tests.test_hooks.HostSessionDigestTests
---

## Context
Storing the raw id made the tool fail its own gating check: harness session ids are opaque high-entropy tokens, session records are committed under the default full policy, and scan-secrets flags any 32+ char separator-free alphanumeric run as a possible secret. A harness whose ids carry no underscore or hyphen would have blocked every commit in the user's store, with the cause in a generated field nobody inspects. Claude Code's session_<24 chars> form escaped only because the underscore breaks the scanner's word boundary.

## Decision
Session snapshots store sha256(session_id)[:12] in host_session. Only equality is ever tested, so the raw id is never needed.

## Consequences
Do not 'simplify' this back to the raw id — tests/test_hooks.py HostSessionDigestTests pins both halves: that the raw id trips _looks_high_entropy, and that the digest does not. Keeping the harness token out of committed git history is a secondary benefit.
