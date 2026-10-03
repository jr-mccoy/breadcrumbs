# Project Handoff

_Last updated: 2026-10-03T18:00:00+00:00_
_Branch: claude/charming-sagan-9o911q_
_Commit: 11ae6d6_

## Current Focus
crumb-kit 0.6.0 is on PyPI. 0.6.1 (the DoWhat retest of 0.6.0: no git processes on the guard hook, lighter hook imports, objections need evidence about the action, generated indexes are memory, scratch cleanup and heredoc data not destructive, Stop-hook timings) is version-bumped on branch claude/charming-sagan-9o911q and being released. docs/reviews/2026-10-03-dowhat-0.6.0-retest-plan.md is the record; do not redo it.

## Next Action
### 2026-10-03 · `11ae6d6`
Release 0.6.1: merge claude/charming-sagan-9o911q to main (fast-forward), run release.yml on main in dry-run mode, then publish. Then the operator remeasures the guard hook on Windows (crumb doctor --hook-log now prints import, git, mine and snapshot timings and each hook's slowest firing) and decides on a lighter launcher (python -m breadcrumbs hook guard, or a shell pre-check) and whether the Stop snapshot's projection rebuild moves off the hook path.

### 2026-10-02 · `84633e4`
Merge branch ccr-e63a7edc-aluyzm to main, then publish 0.6.0: Actions -> release -> Run workflow on main, mode dry-run, then mode publish (RELEASING.md). Before migrating this repo's or DoWhat's store with 0.6.0, upgrade every machine that shares the store: migrate sets min_crumb_version and 0.4.x/0.5.0 then refuse to write. Open after 0.6.0: an ask-time guard so a code+memory commit after the extraction turn does not stack a machine snapshot beside the agent's capture, and whether the Stop hook should write only under private/.

### 2026-10-01 · `54eeaab`
Publish 0.5.0: Actions -> release -> Run workflow on main, mode dry-run, then mode publish (RELEASING.md). Before publishing, run the native Windows job of the ci workflow on main to confirm the long-path migration backup/restore, UTF-8 output under Git Bash and `crumb mcp register --local`, which were only tested on Linux.

### Earlier, as written
A person reviews the work packages the tracker marks `review_required`, then merges the branch to main. The branch already carries the 0.4.0 bump (version, CHANGELOG, compatibility row); the release runs through release.yml with a dry-run first (RELEASING.md). docs/releases/reliability-release-checklist.md lists the gates, exclusions and the operator's steps; read the native-full jobs on the merge commit before publishing. After the merge, reconcile this file on main (docs/operator-guide.md §6).

## Blockers / Open Questions
release.yml runs only from main and only by hand; the operator approved the 0.6.1 release on 2026-10-03.

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
