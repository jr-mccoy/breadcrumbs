# Project Handoff

_Last updated: 2026-08-16T03:57:36+00:00_
_Branch: claude/trap-retirement-mark-status-o64qqs_
_Commit: b84ac9a_

## Current Focus
Field-test 0.1.10 in the Android app repo: install from PyPI, run crumb init --with-hooks, work a real session, judge extraction-prompt quality and fatigue

## Next Action
Branch claude/trap-retirement-mark-status-o64qqs is restarted from main at b84ac9a (CI fix only; the trap+question work already merged as PR #42). THREE things left, in order: (1) confirm CI run 31925269674 is green on b84ac9a — the guard exit-code fix was verified locally under bash -e but not yet in Actions; (2) open a PR for b84ac9a and merge it, then confirm main is green (main has been red since 5c861c4); (3) release 0.1.11 per RELEASING.md — bump __version__ in breadcrumbs/__init__.py (still 0.1.10), date the CHANGELOG Unreleased section (20 entries), merge to main, then run release.yml with mode=dry-run before mode=publish. Never hand-tag.

## Blockers / Open Questions


## Active Decisions To Respect


## Failed Attempts To Avoid


## Known Traps


## Likely Relevant Files


## Verification Commands


## Stale If
