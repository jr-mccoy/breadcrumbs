# Project Handoff

_Last updated: 2026-10-02T19:30:00+00:00_
_Branch: ccr-e63a7edc-aluyzm_
_Commit: 84633e4_

## Current Focus
crumb-kit 0.5.0 is on PyPI. 0.6.0 (the DoWhat retest fixes: guard verdicts and speed, machine-local guard pre-filter, `min_crumb_version`, plus the Stop-hook snapshot settle fix) is version-bumped on branch ccr-e63a7edc-aluyzm, ready to merge and publish. docs/reviews/2026-10-02-dowhat-retest-plan.md and dec_20261002_a-head-that-moved-only-by-memory-store-commits-is-not-new are the record; do not redo them.

## Next Action
### 2026-10-02 · `84633e4`
Merge branch ccr-e63a7edc-aluyzm to main, then publish 0.6.0: Actions -> release -> Run workflow on main, mode dry-run, then mode publish (RELEASING.md). Before migrating this repo's or DoWhat's store with 0.6.0, upgrade every machine that shares the store: migrate sets min_crumb_version and 0.4.x/0.5.0 then refuse to write. Open after 0.6.0: an ask-time guard so a code+memory commit after the extraction turn does not stack a machine snapshot beside the agent's capture, and whether the Stop hook should write only under private/.

### 2026-10-01 · `54eeaab`
Publish 0.5.0: Actions -> release -> Run workflow on main, mode dry-run, then mode publish (RELEASING.md). Before publishing, run the native Windows job of the ci workflow on main to confirm the long-path migration backup/restore, UTF-8 output under Git Bash and `crumb mcp register --local`, which were only tested on Linux.

### Earlier, as written
A person reviews the work packages the tracker marks `review_required`, then merges the branch to main. The branch already carries the 0.4.0 bump (version, CHANGELOG, compatibility row); the release runs through release.yml with a dry-run first (RELEASING.md). docs/releases/reliability-release-checklist.md lists the gates, exclusions and the operator's steps; read the native-full jobs on the merge commit before publishing. After the merge, reconcile this file on main (docs/operator-guide.md §6).

## Blockers / Open Questions
Publishing 0.6.0 needs the operator: release.yml runs only from main and only by hand.

## Active Decisions To Respect
See the resume packet (`crumb resume`); the durable decisions are the records, not this file.

## Failed Attempts To Avoid


## Known Traps
Never tag or create a GitHub Release by hand (CLAUDE.md); release.yml owns both.

## Likely Relevant Files
docs/reviews/2026-09-26-breadcrumbs-work-packages.json, docs/releases/reliability-release-checklist.md, RELEASING.md, docs/compatibility.md

## Verification Commands
python -m unittest discover -s tests -p "test_*.py"; python evals/run.py --release

## Stale If
the branch has merged and 0.4.0 is released, or the tracker's statuses have changed.
