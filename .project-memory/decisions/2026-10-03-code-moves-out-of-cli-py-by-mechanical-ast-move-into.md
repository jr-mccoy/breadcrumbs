---
id: dec_20261003_code-moves-out-of-cli-py-by-mechanical-ast-move-into
type: decision
slug: code-moves-out-of-cli-py-by-mechanical-ast-move-into
title: Code moves out of cli.py by mechanical AST move into modules cli imports last; the package names the module, cli forwards moved names
status: active
created_at: 2026-10-03T14:55:13+00:00
updated_at: 2026-10-03T14:55:13+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-4e962709-tubaoe
commit: 78f6691
dirty_files:
  - docs/reviews/2026-10-02-deferred-health-review.md
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - architecture
  - refactor
evidence:
  - type: file
    ref: tests/test_extracted_modules.py
  - type: file
    ref: docs/architecture.md
---

## Context
Health review 2.1: cli.py held half the package. Seams moved out one at a time: hooks_stop/guard/session, packet, textmatch, scoring, validate, audit, secretscan (15,651 to 9,694 lines).

## Decision
Each extracted module imports cli for the core that stays; cli imports it at the end of the file and lists it in cli.EXTRACTED_MODULES, so the cycle is harmless either way. Package code and tests name the module (underscore alias, e.g. _packet, since 'packet' is a common local name); cli.__getattr__ forwards a moved name only for code outside the package (the byte-identical tools/audit probes); crumb.py re-exports moved names. Moves keep each node's source and the text between moved neighbours verbatim.

## Rationale
A mechanical move behind the parity fixture, the evals and the full suite cannot change behaviour. A patch on cli no longer reaches a moved function's callers, so tests patch the owning module; tests/test_extracted_modules.py enforces the contract.

## What Not To Retry
Do not reach a moved name as cli.NAME inside the package, and do not patch cli for one in tests: the patch silently stops applying (test_evals' false-safe gate failed exactly that way).
