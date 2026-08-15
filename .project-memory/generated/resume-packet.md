<!-- GENERATED PROJECTION — do not edit by hand. Rebuilt by `crumb resume`. -->
<!-- source_commit: c34db39 | inputs_hash: acfe7aa9aade | generated_at: 2026-08-15T20:29:40+00:00 -->

# Resume Packet

## Project
**breadcrumbs** — `.`  
branch `claude/crumb-kit-0.1.10-triage-l3qo5a` · commit `c34db39` · 6 uncommitted file(s)

## Current Focus
Field-test 0.1.10 in the Android app repo: install from PyPI, run crumb init --with-hooks, work a real session, judge extraction-prompt quality and fatigue

## Next Action
Field-test triage branch claude/crumb-kit-0.1.10-triage-l3qo5a is complete through commit c34db39 (batches: guard signal d7c639e, packet truth e6bc1a6, capture hygiene c2d33da, polish c34db39). Next: open/merge the PR, then release 0.1.11 per RELEASING.md (bump __version__, run the release workflow from main).

## Active Decisions
- `dec_20260815_crumb-guard-exits-verdict-mapped-codes-0-10-15-20` — Callers could not script on verdicts at all (everything exited 0), and a Windows field-test harness rendered advisory verdicts as tool failures; documented spaced codes make 'block only on ASK_HUMAN' possible and any host-layer weirdness diagnosable.
- `dec_20260815_guard-verdict-floors-require-file-tag-specificity-keyword` — 0.1.10 field test: the unconditional trap keyword floor fired READ_FIRST on 13/13 edits with one relevant hit; an ignored alarm is worse than no alarm.
- `dec_20260815_pypi-trusted-publisher-must-be-re-pointed-after-a-repo` — Treat invalid-publisher as a PyPI-side config defect, never a workflow bug. The fix is to update the publisher entry at pypi.org/manage/project/crumb-kit/settings/publishing to match the OIDC claims the run prints (owner=jr-mccoy, repo=breadcrumbs, workflow=release.yml, environment=pypi), then re-run release.yml with mode=publish. Documented the failure mode in release.yml's header and in RELEASING.md (one-time setup callout + 'If a release fails' bullet), and corrected the stale owner=jumbodaddystack reference in both.
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
- .github/workflows/release.yml:36
- RELEASING.md:22
- breadcrumbs/__init__.py
- .gitignore
- breadcrumbs/cli.py

## Verifications
- `ver_20260815_release-0-1-10-blocked-by-pypi-invalid-publisher-open` — release 0.1.10 blocked by PyPI invalid-publisher: **open** · static
- `ver_20260815_hook-guard-escalates-on-edits-to-files-named-by-evidence` — hook guard escalates on edits to files named by --evidence file: **fixed** · test

## Verification Commands
- python -m build --wheel
- python crumb.py validate
- python -m unittest tests.test_hooks
- python -m unittest tests.test_guard

## Stale / Risk Warnings
_(ages below are measured; the cutoff is 21 days — set with `--stale-days`)_
- handoff is 0 day(s) old, written 0 commit(s) behind current HEAD.
- 5 record(s) written on other branches than 'claude/crumb-kit-0.1.10-triage-l3qo5a': dec_20260815_pypi-trusted-publisher-must-be-re-pointed-after-a-repo (on 'claude/release-run-failures-gcuil8'), dec_20260815_cut-0-1-10-as-the-agent-authorship-release (on 'claude/system-audit-viability-e2sft7'), dec_20260815_the-tool-s-own-repo-commits-its-own-memory-store (on 'claude/system-audit-viability-e2sft7'), dec_20260815_stop-hook-extraction-turn-makes-the-agent-the-memory-author (on 'claude/system-audit-viability-e2sft7'), dec_20260815_guard-folds-morphology-with-a-deterministic-fixpoint (on 'claude/system-audit-viability-e2sft7').
- possible drift: `ver_20260815_hook-guard-escalates-on-edits-to-files-named-by-evidence` recorded "hook guard escalates on edits to files named by --evidence file" as **fixed** on 2026-08-15, but Current Focus / Next Action still claims that work — re-check before redoing it.
