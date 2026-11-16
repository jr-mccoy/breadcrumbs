---
id: dec_20261114_safetext-escapes-format-characters-blank-fillers
type: decision
slug: safetext-escapes-format-characters-blank-fillers
title: safetext escapes format characters, blank fillers and variation-selector runs
status: active
created_at: 2026-11-14T15:15:53+00:00
updated_at: 2026-11-14T15:15:53+00:00
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
  - safetext
evidence:
  - type: file
    ref: breadcrumbs/safetext.py
  - type: test
    ref: tests/test_gate.py
  - type: commit
    ref: 10f8a9d
---

## Decision
Escaped wherever record text is shown: category Cf (Unicode tags, soft hyphen, bidi and zero-width), blank fillers (U+034F, Hangul fillers, braille blank, Mongolian selectors), every supplementary variation selector, and any FE00-FE0F selector except one FE0E/FE0F directly after a visible character. audit flags records holding them as hidden-characters.

## Rationale
Tag characters spell an instruction a diff does not show and reached hook output; a run of variation selectors carries one byte each. A single presentation selector is ordinary emoji text, so keeping it leaves normal titles unchanged.
