---
id: ver_20260816_crumb-mark-status-can-answer-an-open-question-fixed
type: verification
slug: crumb-mark-status-can-answer-an-open-question-fixed
title: crumb mark-status can answer an open question — fixed
status: active
created_at: 2026-08-16T02:22:49+00:00
updated_at: 2026-08-16T02:22:49+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/trap-retirement-mark-status-o64qqs
commit: 4d7c69a
dirty_files:
  - .project-memory/generated/resume-packet.md
  - CHANGELOG.md
  - README.md
  - breadcrumbs/cli.py
  - breadcrumbs/mcp_server.py
  - breadcrumbs/templates/project-memory/open-questions.md
  - docs/cli-spec.md
  - docs/mcp-spec.md
  - tests/test_note.py
  - .project-memory/decisions/2026-08-16-questions-get-their-own-status-vocabulary-not-the-record-one.md
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
subject: crumb mark-status can answer an open question
outcome: fixed
method: test
tags: []
evidence:
  - type: file
    ref: tests/test_note.py
---

## Subject
crumb mark-status can answer an open question

## Outcome
fixed

## Method
test

## Notes
QuestionLifecycleTests: answering drops the question from the packet, from guard's open-blocker floor and from the aged-question staleness warning, while search still finds it as [answered]; digest-suffixed ids resolve; reopening works; the record and question vocabularies are rejected across kinds by name; only the target block is edited. 627 tests pass.
