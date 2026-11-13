---
id: dec_20261113_python-3-10-is-the-supported-floor-3-9-is-dropped
type: decision
slug: python-3-10-is-the-supported-floor-3-9-is-dropped
title: Python 3.10 is the supported floor; 3.9 is dropped
status: active
created_at: 2026-11-13T14:04:29+00:00
updated_at: 2026-11-13T14:04:29+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-5a263b6c-3gtzxn
commit: 52d3bfe
dirty_files: []
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - python
  - ci
  - release
evidence:
  - type: file
    ref: pyproject.toml
  - type: file
    ref: .github/workflows/ci.yml
  - type: test
    ref: tests/test_release_process.py
---

## Decision
requires-python >=3.10. The CI test matrix runs exactly the pyproject classifiers (3.10 to 3.14), and the native jobs run 3.10 and 3.13 on Windows and macOS. The [mcp] extra has no environment marker.

## Rationale
3.9 reached end of life in October 2025 and ubuntu-latest (Ubuntu 26.04) no longer provides it, which turned CI on main red from 2026-11-02 and blocked publishing. The operator chose dropping it over pinning the runner. Dropping a Python version is breaking, so it ships in a minor release (0.7.0).
