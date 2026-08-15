<!-- GENERATED PROJECTION — do not edit by hand. Rebuilt by `crumb resume`. -->
<!-- source_commit: ac8352c | inputs_hash: dd88f4a43cca | generated_at: 2026-08-15T03:14:19+00:00 -->

# Resume Packet

## Project
**breadcrumbs** — `.`  
branch `claude/system-audit-viability-e2sft7` · commit `ac8352c` · 7 uncommitted file(s)

## Current Focus
Field-test 0.1.10 in the Android app repo: install from PyPI, run crumb init --with-hooks, work a real session, judge extraction-prompt quality and fatigue

## Next Action
Field-test 0.1.10 in the Android app repo: install from PyPI, run crumb init --with-hooks, work a real session, judge extraction-prompt quality and fatigue

## Active Decisions
- `dec_20260815_cut-0-1-10-as-the-agent-authorship-release` — Bump __version__ to 0.1.10 (single source of truth) and date the CHANGELOG section. Headline is the Stop-hook extraction turn; the prefilter and stemming fixes make what it writes reachable. Version bump + changelog are the ONLY manual edits — release.yml cuts the tag and Release.
- `dec_20260815_the-tool-s-own-repo-commits-its-own-memory-store` — Remove the blanket ignore and commit .project-memory/ in this repo, exactly as a target project would (managed block still keeps private/ and index/ local). The store is the repo's continuity ledger and its live demo.
- `dec_20260815_stop-hook-extraction-turn-makes-the-agent-the-memory-author` — When the ending turn produced new commits, hook capture holds the stop once (decision: block) and instructs the agent to write records, ending with capture session --next which clears the prompt. Loop-guarded by stop_hook_active; machine snapshot is the floor; manifest extraction_prompt is the kill switch.
- `dec_20260815_guard-folds-morphology-with-a-deterministic-fixpoint` — Small suffix-stripper applied longest-first to a fixpoint (idempotent, so the prefilter can re-stem older on-disk indexes), plus a tiny curated alias table (auth/config/db/repo). No embeddings; vectors stay a later disposable accelerator per architecture.md.

## Failed Attempts To Avoid
_(none recorded)_

## Known Traps
- trap_hand-tagged-releases: Never create a git tag or GitHub Release by hand

## Open Questions / Blockers
- Should the extraction turn also fire on PreCompact (memory extraction at the moment context is about to be destroyed)? Needs a field test of prompt fatigue first.

## Likely Relevant Files
- breadcrumbs/__init__.py
- .gitignore
- breadcrumbs/cli.py

## Verifications
- `ver_20260815_hook-guard-escalates-on-edits-to-files-named-by-evidence` — hook guard escalates on edits to files named by --evidence file: **fixed** · test

## Verification Commands
- python -m build --wheel
- python crumb.py validate
- python -m unittest tests.test_hooks
- python -m unittest tests.test_guard

## Stale / Risk Warnings
_(ages below are measured; the cutoff is 21 days — set with `--stale-days`)_
- handoff is 0 day(s) old, written 0 commit(s) behind current HEAD.
