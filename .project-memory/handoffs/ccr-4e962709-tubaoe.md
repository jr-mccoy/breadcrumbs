# Project Handoff

_Last updated: 2026-10-03T13:37:11+00:00_
_Branch: ccr-4e962709-tubaoe_
_Commit: aedc62a_

## Current Focus
crumb-kit 0.5.0 is on PyPI. 0.6.0 (the DoWhat retest fixes: guard verdicts and speed, machine-local guard pre-filter, `min_crumb_version`, plus the Stop-hook snapshot settle fix) is version-bumped on branch ccr-e63a7edc-aluyzm, ready to merge and publish. docs/reviews/2026-10-02-dowhat-retest-plan.md and dec_20261002_a-head-that-moved-only-by-memory-store-commits-is-not-new are the record; do not redo them.

## Next Action
### 2026-10-03 · `aedc62a`
Item 2.2 of docs/reviews/2026-10-02-deferred-health-review.md is done on branch ccr-4e962709-tubaoe (git module, timestamps, reads, POSIX paths, command text; full suite 1519 OK, evals at baseline). Next: open a PR for the branch; then 2.1 seam 1 (extract the Stop hook into hooks_stop behind tests/fixtures/application_parity.json). 0.6.0 is still unpublished: check the native-full Windows job on main, then run the release workflow (dry-run, then publish).

### 2026-10-03 · `7d941f4`
2.2 git half is on branch ccr-4e962709-tubaoe (breadcrumbs/git.py). Next for 2.2: one timestamp parser (cli._parse_iso vs validation.parse_timestamp), one lenient reader, path_policy for store-relative POSIX paths, one shell tokenizer; then 2.1 seam 1 (hooks_stop). 0.6.0 is still unpublished: run the release workflow on main (dry-run, then publish) after checking the native-full Windows job.

## Blockers / Open Questions


## Active Decisions To Respect


## Failed Attempts To Avoid


## Known Traps


## Likely Relevant Files


## Verification Commands


## Stale If
