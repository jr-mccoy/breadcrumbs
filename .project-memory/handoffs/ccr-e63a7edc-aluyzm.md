# Project Handoff

_Last updated: 2026-10-02T20:38:28+00:00_
_Branch: ccr-e63a7edc-aluyzm_
_Commit: 1b26438_

## Current Focus
0.6.0 is bumped on the branch: the DoWhat retest fixes plus the Stop-hook snapshot settle fix. Next is merge and publish.

## Next Action
### 2026-10-02 · `1b26438`
Merge branch ccr-e63a7edc-aluyzm to main, then publish 0.6.0 (release.yml dry-run, then publish). It now also carries the packet-settles fix (dec_20261002_reads-never-rewrite-a-fresh-committed-projection-only-input) and the Stop lifecycle fixes (dec_20261002_the-stop-hook-treats-the-agent-s-answer-to-the-extraction). Deferred work with evidence: docs/reviews/2026-10-02-deferred-health-review.md.

### 2026-10-02 · `84633e4`
Publish 0.6.0: Actions -> release -> Run workflow on main, mode dry-run, then mode publish (RELEASING.md). The branch ccr-e63a7edc-aluyzm carries the Stop-hook settle fix (tests/test_hooks.py: test_committing_the_snapshot_is_not_new_work) and the 0.6.0 bump; merge it to main first. Before migrating this repo's or DoWhat's store with 0.6.0, upgrade every machine (min_crumb_version). Open: the ask-time guard for a code+memory commit after the extraction turn, and whether Stop should write only under private/.

## Blockers / Open Questions


## Active Decisions To Respect


## Failed Attempts To Avoid


## Known Traps


## Likely Relevant Files


## Verification Commands


## Stale If
