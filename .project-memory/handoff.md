# Project Handoff

_Last updated: 2026-08-16T04:48:11+00:00_
_Branch: main_
_Commit: 37d032f_

## Current Focus
Field-test 0.1.10 in the Android app repo: install from PyPI, run crumb init --with-hooks, work a real session, judge extraction-prompt quality and fatigue

## Next Action
Release 0.1.11: a human must run Actions -> release -> Run workflow from main (mode=dry-run first, then mode=publish). main is at 37d032f with __version__ 0.1.11, CHANGELOG dated 2026-08-16, and ci.yml green (run 142, 36/36). An agent session cannot dispatch it — see trap_agent-cannot-dispatch-workflows. Never hand-tag; the workflow cuts the tag and Release itself.

## Blockers / Open Questions


## Active Decisions To Respect


## Failed Attempts To Avoid


## Known Traps


## Likely Relevant Files


## Verification Commands


## Stale If
