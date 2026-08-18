---
id: dec_20260818_repo-presentation-is-a-release-artifact-no-hand-pinned
type: decision
slug: repo-presentation-is-a-release-artifact-no-hand-pinned
title: Repo presentation is a release artifact: no hand-pinned versions, no stale owner URLs
status: active
created_at: 2026-08-18T18:34:06+00:00
updated_at: 2026-08-18T18:34:06+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/resume-portfolio-readiness-ywdfiw
commit: 10d55da
dirty_files:
  - .project-memory/generated/resume-packet.md
  - CHANGELOG.md
  - README.md
  - breadcrumbs/templates/project-memory/README.md
  - pyproject.toml
  - CONTRIBUTING.md
  - SECURITY.md
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - pypi
evidence:
  - type: file
    ref: README.md
  - type: file
    ref: pyproject.toml
  - type: file
    ref: breadcrumbs/templates/project-memory/README.md
  - type: command
    ref: python -m unittest discover -s tests
---

## Context
Portfolio-readiness review. The engineering was already strong (673 tests green on 3.9-3.14, pinned-SHA CI, MCP matrix over both SDK majors, packaging smoke test, ruff clean), but the reader-facing surface had drifted: README's Status blurb hand-pinned '0.1.8' while __version__ was 0.1.12, [project.urls] and the shipped templates/project-memory/README.md still named the pre-rename owner jumbodaddystack, classifiers claimed only a bare 'Programming Language :: Python :: 3', and there was no CONTRIBUTING.md or SECURITY.md.

## Decision
Treat README/packaging metadata under the same single-source-of-truth rule the version already follows: the Status blurb names no version and points at 'crumb --version' plus CHANGELOG.md; project URLs and the template link name the current owner directly rather than lean on GitHub's rename redirect; classifiers enumerate the six Pythons CI actually proves. Added CONTRIBUTING.md and SECURITY.md, and five badges sourced from shields.io with absolute link targets.

## Rationale
A hand-maintained version literal in prose is the same defect the project already removed from pyproject.toml and cli.py; it went four releases stale precisely because nothing checked it. Badge link targets must be absolute because README.md is also the PyPI long description, where a relative href resolves to nothing. GitHub's native badge.svg endpoint could not be verified from this environment (403 through the proxy), so every badge URL used was one that returned 200 and the expected aria-label.

## Consequences
The PyPI page for 0.1.12 will carry correct owner links, Changelog/Issues entries, and an accurate support matrix; every project that runs 'crumb init' from 0.1.12 onward gets a store README pointing at the live repo. Release of 0.1.12 is still a manual workflow run - the version was bumped and CHANGELOG dated on 2026-08-18 but PyPI latest is still 0.1.11.
