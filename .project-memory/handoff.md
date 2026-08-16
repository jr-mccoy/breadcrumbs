# Project Handoff

_Last updated: 2026-08-16T04:14:39+00:00_
_Branch: claude/trap-retirement-mark-status-o64qqs_
_Commit: 12287e9_

## Current Focus
Field-test 0.1.10 in the Android app repo: install from PyPI, run crumb init --with-hooks, work a real session, judge extraction-prompt quality and fatigue

## Next Action
Branch claude/trap-retirement-mark-status-o64qqs is green in CI at HEAD (runs 31925269674 on b84ac9a and 31925481738 on 12287e9, 18/18 jobs). TWO things left: (1) open a PR for this branch and merge it — that is what makes main green again, main has been red since 5c861c4; (2) release 0.1.11 per RELEASING.md — bump __version__ in breadcrumbs/__init__.py (still 0.1.10), date the CHANGELOG Unreleased section (21 entries), merge to main, run release.yml mode=dry-run then mode=publish. Never hand-tag.

## Blockers / Open Questions


## Active Decisions To Respect


## Failed Attempts To Avoid


## Known Traps


## Likely Relevant Files


## Verification Commands


## Stale If
