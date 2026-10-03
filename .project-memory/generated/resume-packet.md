<!-- GENERATED PROJECTION — do not edit by hand. Rebuilt by `crumb resume`. -->
<!-- source_commit: 7d941f4 | inputs_hash: 6205a8df8373 | generated_at: 2026-10-03T13:07:58+00:00 -->
<!-- view: markdown | budget: 3626/5000 approx_tokens (approx-tokens/2: ceil(ASCII chars / 4) + 1 per non-ASCII char — a heuristic, not a model tokenizer) | rules: portable -->

# Resume Packet

## Project
**breadcrumbs** — `.`  
branch `ccr-4e962709-tubaoe` · commit `7d941f4` · 2 uncommitted file(s) · handoff: handoffs/ccr-4e962709-tubaoe.md

## Current Focus
0.6.0 is bumped on the branch: the DoWhat retest fixes plus the Stop-hook snapshot settle fix. Next is merge and publish.

## Next Action
2.2 git half is on branch ccr-4e962709-tubaoe (breadcrumbs/git.py). Next for 2.2: one timestamp parser (cli._parse_iso vs validation.parse_timestamp), one lenient reader, path_policy for store-relative POSIX paths, one shell tokenizer; then 2.1 seam 1 (hooks_stop). 0.6.0 is still unpublished: run the release workflow on main (dry-run, then publish) after checking the native-full Windows job.

## Active Decisions
- `dec_20261003_git-state-has-one-owner-breadcrumbs-git-full-shas` — One implementation per question removes the class of drift that produced N8, and moving HEAD reads to the disk reader removes git spawns from the Stop hook path on Windows. Storing full shas in records would change a stored format, so it was kept out.
- `dec_20261002_the-stop-hook-treats-the-agent-s-answer-to-the-extraction` — The ask's instruction ends with the capture, so a capture after the ask is the answer, whatever else the turn committed. Amend and rebase preserve author time, which is what tells an already-asked commit from new work.
- `dec_20261002_reads-never-rewrite-a-fresh-committed-projection-only-input` — inputs_hash equality is already the definition of fresh that validate gates on. The kept file stays internally consistent: its commit, ages and dirty count all describe the store as of its own generated_at.
- `dec_20261002_a-head-that-moved-only-by-memory-store-commits-is-not-new` — The hook runs after the agent's last commit by construction, so any tracked file it writes is left uncommitted; the one-round cost is acceptable, an unbounded one is not. Reusing the commit counter's definition of work keeps one notion of 'this session's work' across the ask and the snapshot.
- `dec_20261002_guard-speed-remove-git-processes-first-remeasure-on-windows` — DoWhat retest of 0.5.0, item 7, operator decision D7: p50 764 ms on Windows; 24 of 29 firings took the full path with 5 git spawns each.
- `dec_20261002_a-store-names-its-oldest-allowed-writer-with-min-crumb` — DoWhat retest of 0.5.0, item 14, operator decision D14: a 0.4.x capture session replaced the Next Action log 0.5.0 keeps; the requires: bridge is the only way to stop builds that predate the field.
- `dec_20261002_the-guard-pre-filter-is-machine-local-in-index-compact` — DoWhat retest of 0.5.0, items 8-9, operator decision D8: the hook only trusts a copy this machine's generation manifest vouches for, so a committed copy bought nothing and was a 33,000-line diff that conflicted on merges.
- `dec_20261001_guard-reads-shell-commands-by-segment-and-effect` — Field report issues 7/8/N4: 23 of 23 firings warned, and find | xargs rm -rf was capped as read-only. Operator decision D3 (built-in floor).
- `dec_20261001_capture-session-next-adds-a-dated-entry-only-replace` — Field report 2026-10-01 issue 1: a one-line --next destroyed a 139-line hand-kept log with no copy. Operator decision D1 (append unless --replace); D1b: no requires: flag.
- `dec_20260928_the-native-full-suite-runs-on-main-weekly-and-on-demand` — Keeps per-push cost low while main and a weekly run still see platform regressions; run it by hand on a branch before merging platform-sensitive changes.
- `dec_20260928_store-relative-paths-are-posix-and-line-endings` — A store is shared across machines and platforms; a value that differs by OS makes stamps stale everywhere and made rollback and the write gate silently wrong on Windows.
- `dec_20260927_transports-reach-the-store-through-breadcrumbs-service` — CLI, MCP and hooks call service functions (record, mark_status, search, guard, resume_packet, prompt_lookup, admit) inside service.active(ctx); wording, exit codes and envelopes stay in the adapters. Parser lives in cli_parser.py. Aliases and clock are per-thread scoped state. Any further move out o… [excerpt: 300 of 379 chars; full text: crumb show dec_20260927_transports-reach-the-store-through-breadcrumbs-service]
- `dec_20260927_pair-generation-uses-postings-and-exact-prefix-filtering` — related, conflicts and the near-duplicate sweep score only pairs that can reach their thresholds; pairwise versions stay as test oracles. Past RELATED_PAIR_BUDGET the related map reports degraded (audit: related-degraded) instead of skipping. Parses are shared per operation via cli.operation() keyed… [excerpt: 300 of 332 chars; full text: crumb show dec_20260927_pair-generation-uses-postings-and-exact-prefix-filtering]
- `dec_20260927_review-profiles-solo-by-default-team-makes-agent-written` — Proportional: ordinary capture never waits for a person; only the writes that make memory authoritative are gated. Opt-in semantics use requires: instead of a store-wide schema bump.
- `dec_20260927_pre-1-0-releases-bump-the-minor-for-breaking-changes-newer` — The lock is the one place every committed write already passes, and every caller already handles StoreLocked, so the refusal needs no per-writer code. Released readers (<=0.3.1) cannot be changed, so semantic changes must also be designed to fail safe for them (schema bump, meaning kept out of field… [excerpt: 300 of 456 chars; full text: crumb show dec_20260927_pre-1-0-releases-bump-the-minor-for-breaking-changes-newer]
_(… 42 more omitted to stay within the per-section cap)_

## Failed Attempts To Avoid
_(none recorded)_

## Known Traps
- trap_a-bare-n-in-a-commit-message-links-an-issue-but-never: A bare (#N) in a commit message links an issue but never closes it
- trap_a-hand-written-version-literal-in-prose-drifts-silently: A hand-written version literal in prose drifts silently
- trap_a-hook-test-payload-without-cwd-fires-the-hook: A hook test payload without cwd fires the hook at the repository the suite runs in
- trap_a-record-s-remedy-fields-are-mined-for-file-paths: A record's remedy fields are mined for file paths and become its blast radius
- trap_a-test-that-runs-resume-or-reindex-on-a-checked-in-fixture: A test that runs resume or reindex on a checked-in fixture rewrites it
- trap_eval-baseline-after-retrieval-change: A retrieval change fails the evals CI job and test_evals until the baseline is rewritten
- trap_guard-exit-code-in-ci: A CI step that calls crumb guard dies on guard's own verdict exit code
- trap_hand-tagged-releases: Never create a git tag or GitHub Release by hand
- trap_linux-cannot-show-a-windows-path-separator-bug: Linux cannot show a Windows path-separator bug
- trap_the-mcp-surface-of-0-1-11-was-never-exercised-the-field: The MCP surface of 0.1.11 was never exercised: the field audit had to kill the server to allow the upgrade, so no mcp__breadcrumbs__* tool ran on that release at all

## Open Questions / Blockers
- Should the extraction turn also fire on PreCompact (memory extraction at the moment context is about to be destroyed)? Needs a field test of prompt fatigue first.
- Which items in docs/reviews/2026-10-02-deferred-health-review.md should be taken next: audit age noise, the cli.py split, duplicated git/timestamp helpers, Windows gating, coverage, or the Stop snapshot's publication cost?

## Inbox (unsorted, expires)
_(candidates, not findings — promote with `crumb inbox promote <id> <type>` or drop with `crumb inbox drop <id>`)_
- `jot_20260922_phase-1-wm-14-s-transcript-miner-must-write-via-inbox-34ba` (10d, agent) Phase 1 WM-14's transcript miner must write via inbox.write_jot(source='transcript', local=True) — the private/inbox sp…

## Likely Relevant Files
- breadcrumbs/git.py
- tests/test_git.py
- breadcrumbs/cli.py
- breadcrumbs/hooks_common.py
- breadcrumbs/hooks_compact.py
- breadcrumbs/gitrefs.py
- breadcrumbs/compat.py
- breadcrumbs/migrate.py
- docs/reviews/2026-10-02-dowhat-retest-plan.md
- breadcrumbs/shellcmd.py
- .github/workflows/ci.yml
- tests/test_platform_portability.py
- breadcrumbs/service.py
- tests/test_application_parity.py
- breadcrumbs/related.py
- breadcrumbs/lifecycle.py
- breadcrumbs/admission.py
- tests/test_admission_policy.py
- docs/reviews/2026-09-27-breadcrumbs-wp14/README.md
- docs/compatibility.md
_(… 43 more omitted to stay within the per-section cap)_

## Verifications
- `ver_20260817_f-5-guard-reprints-the-staleness-block-on-every-call` — F-5 (guard reprints the staleness block on every call) is already fixed on main and in 0.1.11: **not_applicable** · runtime
- `ver_20260925_ci-mcp-job-fails-stale-pinned-tool-resource-counts-in-ci` — CI mcp job fails: stale pinned tool/resource counts in ci.yml: **fixed** · test
- `ver_20260923_relevance-evals-hold-the-committed-baseline-prompt-p-5-0-66` — Relevance evals hold the committed baseline (prompt P@5 0.66, R@5 0.87, 1 reject hit): **fixed**
- `ver_20260922_phase-5-of-the-working-memory-roadmap-wm-50-to-wm-52` — Phase 5 of the working-memory roadmap (WM-50 to WM-52) is implemented and green: **fixed** · test
- `ver_20260922_phase-4-of-the-working-memory-roadmap-wm-40-to-wm-43` — Phase 4 of the working-memory roadmap (WM-40 to WM-43) is implemented and green: **fixed** · test
- `ver_20260922_phase-3-of-the-working-memory-roadmap-wm-30-to-wm-35` — Phase 3 of the working-memory roadmap (WM-30 to WM-35) is implemented and green: **fixed** · test
- `ver_20260922_phase-2-of-the-working-memory-roadmap-wm-20-to-wm-25` — Phase 2 of the working-memory roadmap (WM-20 to WM-25) is implemented and green: **fixed** · test
- `ver_20260922_phase-1-of-the-working-memory-roadmap-wm-10-to-wm-16` — Phase 1 of the working-memory roadmap (WM-10 to WM-16: capture hooks and the transcript miner): **fixed** · test
- `ver_20260922_phase-0-of-the-working-memory-roadmap-wm-01-migration-wm-02` — Phase 0 of the working-memory roadmap (WM-01 migration, WM-02 usage, WM-03 inbox): **fixed** · test
- `ver_20260905_the-16-findings-of-the-0-1-11-crumb-kit-field-review-re` — the 16 findings of the 0.1.11 crumb-kit field review, re-checked against 0.1.12: **fixed** · static
- `ver_20260903_resume-s-possible-drift-line-fires-on-incidental-two-word` — resume's possible-drift line fires on incidental two-word overlap and version fragments: **fixed** · test
- `ver_20260818_readme-status-blurb-no-longer-hard-codes-a-package-version` — README Status blurb no longer hard-codes a package version: **fixed** · static
_(… 8 more omitted to stay within the per-section cap)_

## Verification Commands
- tests/test_hooks.py::StopLifecycleTests
- tests/test_multi_machine.py::ResumeLeavesAFreshPacketTests
- tests/test_hooks.py::HookCaptureTests::test_committing_the_snapshot_is_not_new_work
- tests/test_gitrefs.py
- python -m unittest tests.test_handoffs tests.test_lock tests.test_scope
- python -m unittest tests.test_promote
- python -m unittest tests.test_lifecycle
- python -m unittest tests.test_searchindex
- python -m unittest tests.test_blockfiles
- python -m unittest tests.test_transcript
- python -m unittest tests.test_hooks_phase1
- python -m unittest tests.test_usage
_(… 11 more omitted to stay within the per-section cap)_

## Stale / Risk Warnings
_(ages below are measured; the cutoff is 21 days — set with `--stale-days`)_
- handoff is 0 day(s) old, written 0 commit(s) behind current HEAD.
- active decision dec_20260905_a-read-only-action-caps-at-read-first-and-entropy-warns is 28 days old with no update — is this still true?
- active decision dec_20260905_path-extraction-is-structural-and-a-mined-path is 28 days old with no update — is this still true?
- active decision dec_20260905_a-wrong-set-heading-parks-content-it-never-discards-the-call is 28 days old with no update — is this still true?
- active decision dec_20260903_branch-mismatch-is-judged-on-whether-the-file-reached-head is 30 days old with no update — is this still true?
- active decision dec_20260818_repo-presentation-is-a-release-artifact-no-hand-pinned is 45 days old with no update — is this still true?
- active decision dec_20260818_hook-guard-never-overrides-the-session-s-permission-mode is 46 days old with no update — is this still true?
- active decision dec_20260818_blast-radius-is-scored-separately-from-retrieval-overlap is 46 days old with no update — is this still true?
- active decision dec_20260817_guard-verdicts-are-capped-by-record-stance-not-by-retrieval is 47 days old with no update — is this still true?
- active decision dec_20260816_questions-get-their-own-status-vocabulary-not-the-record-one is 48 days old with no update — is this still true?
- active decision dec_20260816_traps-carry-a-lifecycle-status-and-mark-status-resolves-them is 48 days old with no update — is this still true?
- active decision dec_20260815_crumb-guard-exits-verdict-mapped-codes-0-10-15-20 is 48 days old with no update — is this still true?
- active decision dec_20260815_guard-verdict-floors-require-file-tag-specificity-keyword is 48 days old with no update — is this still true?
- active decision dec_20260815_pypi-trusted-publisher-must-be-re-pointed-after-a-repo is 49 days old with no update — is this still true?
- active decision dec_20260815_cut-0-1-10-as-the-agent-authorship-release is 49 days old with no update — is this still true?
- active decision dec_20260815_the-tool-s-own-repo-commits-its-own-memory-store is 49 days old with no update — is this still true?
- active decision dec_20260815_stop-hook-extraction-turn-makes-the-agent-the-memory-author is 49 days old with no update — is this still true?
- active decision dec_20260815_guard-folds-morphology-with-a-deterministic-fixpoint is 49 days old with no update — is this still true?
- open question "Should the extraction turn also fire on PreCompact (memory extraction at the moment context is about to be destroyed)? Needs a field test of prompt fatigue first." has been open 49 days — did this ever get resolved?
