<!-- GENERATED PROJECTION — do not edit by hand. Rebuilt by `crumb resume`. -->
<!-- source_commit: 06932b3 | inputs_hash: 2e9a4bc53e50 | generated_at: 2026-10-02T04:33:08+00:00 -->
<!-- view: markdown | budget: 3665/5000 approx_tokens (approx-tokens/2: ceil(ASCII chars / 4) + 1 per non-ASCII char — a heuristic, not a model tokenizer) | rules: portable -->

# Resume Packet

## Project
**breadcrumbs** — `.`  
branch `claude/sharp-hopper-g0wbvw` · commit `06932b3` · 12 uncommitted file(s) · handoff: handoffs/claude-sharp-hopper-g0wbvw-577848.md

## Current Focus
crumb-kit 0.4.0 is on PyPI. 0.5.0 (the DoWhat field-report fixes: Next Action log, migration safety, Stop-hook session cursor, guard rework and speed, repair/rename/handoff trim) is version-bumped and merged to main, ready to publish. docs/reviews/2026-10-01-dowhat-field-report-plan.md is the record; do not redo it.

## Next Action
Publish 0.6.0 when the operator says so: bump __version__ to 0.6.0, move CHANGELOG [Unreleased] to a [0.6.0] heading, add the docs/compatibility.md section 3 row, merge to main, then release.yml dry-run and publish. Before running crumb migrate on this repo's or DoWhat's store, upgrade every machine and the cloud setup: migrate sets min_crumb_version 0.5.0 with requires: min-crumb-version, so 0.4.x and 0.5.0 then refuse to write. On Windows, read crumb doctor --hook-log's p50 phases (import_ms, git_ms) to settle decision D7.

## Active Decisions
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
- `dec_20260927_nothing-inside-the-store-may-be-a-link-record-text-reaches` — No links at all is the simplest rule to audit and nothing in the tool creates one. Descriptor-relative no-follow opens close the check/use race on POSIX. Raising a sanitized PermissionError, rather than returning placeholder text, keeps a refusal from being mistaken for content. Batching reads per d… [excerpt: 300 of 356 chars; full text: crumb show dec_20260927_nothing-inside-the-store-may-be-a-link-record-text-reaches]
- `dec_20260927_usage-counts-emitted-ids-from-append-only-events-the-latest` — A count must mean the host received the record; anything else inflates decay/promotion signals. Event files make acknowledged increments durable without a shared read-modify-write, and the fold's folded_last makes a crash between write and delete harmless. Telemetry never takes the store lock, so it… [excerpt: 300 of 322 chars; full text: crumb show dec_20260927_usage-counts-emitted-ids-from-append-only-events-the-latest]
- `dec_20260927_the-guard-pre-filter-is-a-strict-superset-of-what-full` — Audit F11/WP11: the traps-only pre-filter made the hook silent on 27 of 193 warnings full guard gives on the eval stores; the superset costs ~0.3 ms median on routine commands.
- `dec_20260927_a-trap-naming-the-exact-command-floors-read-first-prompts` — Audit F09/F10: memory vanished above 500 records and for prompts under 12 characters, and npm test got PROCEED from a trap about npm test.
_(… 38 more omitted to stay within the per-section cap)_

## Failed Attempts To Avoid
_(none recorded)_

## Known Traps
- trap_a-bare-n-in-a-commit-message-links-an-issue-but-never: A bare (#N) in a commit message links an issue but never closes it
- trap_a-hand-written-version-literal-in-prose-drifts-silently: A hand-written version literal in prose drifts silently
- trap_a-record-s-remedy-fields-are-mined-for-file-paths: A record's remedy fields are mined for file paths and become its blast radius
- trap_a-test-that-runs-resume-or-reindex-on-a-checked-in-fixture: A test that runs resume or reindex on a checked-in fixture rewrites it
- trap_eval-baseline-after-retrieval-change: A retrieval change fails the evals CI job and test_evals until the baseline is rewritten
- trap_guard-exit-code-in-ci: A CI step that calls crumb guard dies on guard's own verdict exit code
- trap_hand-tagged-releases: Never create a git tag or GitHub Release by hand
- trap_linux-cannot-show-a-windows-path-separator-bug: Linux cannot show a Windows path-separator bug
- trap_the-mcp-surface-of-0-1-11-was-never-exercised-the-field: The MCP surface of 0.1.11 was never exercised: the field audit had to kill the server to allow the upgrade, so no mcp__breadcrumbs__* tool ran on that release at all

## Open Questions / Blockers
- Should the extraction turn also fire on PreCompact (memory extraction at the moment context is about to be destroyed)? Needs a field test of prompt fatigue first.

## Inbox (unsorted, expires)
_(candidates, not findings — promote with `crumb inbox promote <id> <type>` or drop with `crumb inbox drop <id>`)_
- `jot_20260922_phase-1-wm-14-s-transcript-miner-must-write-via-inbox-34ba` (9d, agent) Phase 1 WM-14's transcript miner must write via inbox.write_jot(source='transcript', local=True) — the private/inbox sp…

## Likely Relevant Files
- breadcrumbs/gitrefs.py
- breadcrumbs/compat.py
- breadcrumbs/migrate.py
- breadcrumbs/cli.py
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
- tests/test_store_upgrade_contract.py
- docs/reviews/2026-09-27-breadcrumbs-wp21/README.md
- breadcrumbs/path_policy.py
- breadcrumbs/safetext.py
_(… 40 more omitted to stay within the per-section cap)_

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
- tests/test_gitrefs.py
- python -m unittest tests.test_handoffs tests.test_lock tests.test_scope
- python -m unittest tests.test_promote
- python -m unittest tests.test_lifecycle
- python -m unittest tests.test_searchindex
- python -m unittest tests.test_blockfiles
- python -m unittest tests.test_transcript
- python -m unittest tests.test_hooks_phase1
- python -m unittest tests.test_usage
- python -m unittest tests.test_inbox
- tests/test_secret_precision.py
- tests/test_guard_precision.py
_(… 8 more omitted to stay within the per-section cap)_

## Stale / Risk Warnings
_(ages below are measured; the cutoff is 21 days — set with `--stale-days`)_
- handoff is 0 day(s) old, written 0 commit(s) behind current HEAD.
- active decision dec_20260905_a-read-only-action-caps-at-read-first-and-entropy-warns is 27 days old with no update — is this still true?
- active decision dec_20260905_path-extraction-is-structural-and-a-mined-path is 27 days old with no update — is this still true?
- active decision dec_20260905_a-wrong-set-heading-parks-content-it-never-discards-the-call is 27 days old with no update — is this still true?
- active decision dec_20260903_branch-mismatch-is-judged-on-whether-the-file-reached-head is 29 days old with no update — is this still true?
- active decision dec_20260818_repo-presentation-is-a-release-artifact-no-hand-pinned is 44 days old with no update — is this still true?
- active decision dec_20260818_hook-guard-never-overrides-the-session-s-permission-mode is 44 days old with no update — is this still true?
- active decision dec_20260818_blast-radius-is-scored-separately-from-retrieval-overlap is 44 days old with no update — is this still true?
- active decision dec_20260817_guard-verdicts-are-capped-by-record-stance-not-by-retrieval is 46 days old with no update — is this still true?
- active decision dec_20260816_questions-get-their-own-status-vocabulary-not-the-record-one is 47 days old with no update — is this still true?
- active decision dec_20260816_traps-carry-a-lifecycle-status-and-mark-status-resolves-them is 47 days old with no update — is this still true?
- active decision dec_20260815_crumb-guard-exits-verdict-mapped-codes-0-10-15-20 is 47 days old with no update — is this still true?
- active decision dec_20260815_guard-verdict-floors-require-file-tag-specificity-keyword is 47 days old with no update — is this still true?
- active decision dec_20260815_pypi-trusted-publisher-must-be-re-pointed-after-a-repo is 47 days old with no update — is this still true?
- active decision dec_20260815_cut-0-1-10-as-the-agent-authorship-release is 48 days old with no update — is this still true?
- active decision dec_20260815_the-tool-s-own-repo-commits-its-own-memory-store is 48 days old with no update — is this still true?
- active decision dec_20260815_stop-hook-extraction-turn-makes-the-agent-the-memory-author is 48 days old with no update — is this still true?
- active decision dec_20260815_guard-folds-morphology-with-a-deterministic-fixpoint is 48 days old with no update — is this still true?
- open question "Should the extraction turn also fire on PreCompact (memory extraction at the moment context is about to be destroyed)? Needs a field test of prompt fatigue first." has been open 48 days — did this ever get resolved?
