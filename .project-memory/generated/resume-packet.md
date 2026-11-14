<!-- GENERATED PROJECTION — do not edit by hand. Rebuilt by `crumb resume`. -->
<!-- source_commit: e3f6036 | inputs_hash: bff747d86cae | generated_at: 2026-11-14T14:58:42+00:00 -->
<!-- view: markdown | budget: 3190/5000 approx_tokens (approx-tokens/2: ceil(ASCII chars / 4) + 1 per non-ASCII char — a heuristic, not a model tokenizer) | rules: portable -->

# Resume Packet

## Project
**breadcrumbs** — `.`  
branch `ccr-5a263b6c-3gtzxn` · commit `e3f6036` · 7 uncommitted file(s) · handoff: handoffs/ccr-5a263b6c-3gtzxn.md

## Current Focus
Review items 1 to 3 are done on ccr-5a263b6c-3gtzxn and the Claude Code hooks are installed in this repo. Not yet merged or released; the next release is 0.7.0.

## Next Action
Merge ccr-5a263b6c-3gtzxn (head after this capture) to main; confirm ci is green there; release 0.7.0 per CLAUDE.md. Then review item 4 (docs/reviews/2026-11-13-system-review.md section 6), and look at trap_miner-reads-hook-feedback-as-a-correction.

_(3 earlier entries in handoffs/ccr-5a263b6c-3gtzxn.md)_

## Active Decisions
- `dec_20261114_the-project-root-is-the-nearest-store-at-or-above-cwd` — Payload cwd follows every cd, so hooks went silent in subdirectories and crumb init from src/ made a nested store. Stopping at .git keeps an enclosing repo's store out of submodules and nested repos. Payload cwd comes before CLAUDE_PROJECT_DIR because inside a linked worktree it is the worktree, who… [excerpt: 300 of 419 chars; full text: crumb show dec_20261114_the-project-root-is-the-nearest-store-at-or-above-cwd]
- `dec_20261114_a-merged-branch-s-newer-handoff-is-shown-above-next-action` — Branch handoffs are committed on their branch, so presence in the checkout is the merge; no ancestry check or git spawn is needed. Nothing carried a branch's Next Action forward on merge, so main's handoff.md was 40 days stale in a pull-request workflow. Emitting the key only when non-empty kept the… [excerpt: 300 of 343 chars; full text: crumb show dec_20261114_a-merged-branch-s-newer-handoff-is-shown-above-next-action]
- `dec_20261114_hook-text-stays-under-the-host-s-10-000-character-cap` — Claude Code caps additionalContext at 10,000 characters and shows only a 2,000-character preview of anything longer; this repo's packet was 12,317, so the model saw two decisions. Token budgets do not bound characters. Counting UTF-16 units matches a JavaScript host; 500 characters of headroom absor… [excerpt: 300 of 333 chars; full text: crumb show dec_20261114_hook-text-stays-under-the-host-s-10-000-character-cap]
- `dec_20261113_the-release-ci-gate-fails-closed-and-ignores-scheduled-runs` — The shell gate published with a warning when it could not read CI, and it read the newest run of any kind, so a weekly scheduled run on a newer runner image made the green commit 4606001 unpublishable. A scheduled run measures runner drift, not the commit; the release job runs the suite and the crit… [excerpt: 300 of 318 chars; full text: crumb show dec_20261113_the-release-ci-gate-fails-closed-and-ignores-scheduled-runs]
- `dec_20261113_python-3-10-is-the-supported-floor-3-9-is-dropped` — 3.9 reached end of life in October 2025 and ubuntu-latest (Ubuntu 26.04) no longer provides it, which turned CI on main red from 2026-11-02 and blocked publishing. The operator chose dropping it over pinning the runner. Dropping a Python version is breaking, so it ships in a minor release (0.7.0).
- `dec_20261003_the-guard-hook-computes-no-staleness-and-answers-reached` — At a stable HEAD a full firing now starts 0 processes, including on a shallow blob-filtered clone; after HEAD moves at most 2 (rev-list, ls-tree), neither needing a blob.
- `dec_20261003_a-do-not-retry-line-objects-only-with-evidence-about` — Stance is what interrupts a human; ranking and labels are what find memory. Applying the rule to lookups changed crumb search's wire output (parity fixture) and, with the weight removed too, lost the service eval's logout/cookie attempt from the prompt hook.
- `dec_20261003_code-moves-out-of-cli-py-by-mechanical-ast-move-into` — A mechanical move behind the parity fixture, the evals and the full suite cannot change behaviour. A patch on cli no longer reaches a moved function's callers, so tests patch the owning module; tests/test_extracted_modules.py enforces the contract.
- `dec_20261003_audit-keys-decision-staleness-on-how-much-the-evidence` — Measured on this store: 6 warnings on main where the age rule gave 17 and 'touched since' gave 48, each a real candidate. Two git processes for the whole store. The staleness eval suite (split: checks) asserts every true staleness kind is questioned and an old untouched decision is not.
- `dec_20261003_one-owner-per-helper-concern-parse-timestamp-for-stamps` — A reader that accepts more than validate acts on stamps validate rejects, and differently per interpreter. One spelling for POSIX paths keeps the store-relative POSIX rule in one place. Exact and loose tokenizing serve different jobs; merging them would change guard verdicts and the eval baseline.
- `dec_20261003_git-state-has-one-owner-breadcrumbs-git-full-shas` — One implementation per question removes the class of drift that produced N8, and moving HEAD reads to the disk reader removes git spawns from the Stop hook path on Windows. Storing full shas in records would change a stored format, so it was kept out.
- `dec_20261002_the-stop-hook-treats-the-agent-s-answer-to-the-extraction` — The ask's instruction ends with the capture, so a capture after the ask is the answer, whatever else the turn committed. Amend and rebase preserve author time, which is what tells an already-asked commit from new work.
- `dec_20261002_reads-never-rewrite-a-fresh-committed-projection-only-input` — inputs_hash equality is already the definition of fresh that validate gates on. The kept file stays internally consistent: its commit, ages and dirty count all describe the store as of its own generated_at.
- `dec_20261002_a-head-that-moved-only-by-memory-store-commits-is-not-new` — The hook runs after the agent's last commit by construction, so any tracked file it writes is left uncommitted; the one-round cost is acceptable, an unbounded one is not. Reusing the commit counter's definition of work keeps one notion of 'this session's work' across the ask and the snapshot.
- `dec_20261002_guard-speed-remove-git-processes-first-remeasure-on-windows` — DoWhat retest of 0.5.0, item 7, operator decision D7: p50 764 ms on Windows; 24 of 29 firings took the full path with 5 git spawns each.
_(… 52 more omitted to stay within the per-section cap)_

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
- trap_miner-reads-hook-feedback-as-a-correction: The transcript miner files harness-injected Stop hook feedback as a user correction
- trap_the-mcp-surface-of-0-1-11-was-never-exercised-the-field: The MCP surface of 0.1.11 was never exercised: the field audit had to kill the server to allow the upgrade, so no mcp__breadcrumbs__* tool ran on that release at all

## Open Questions / Blockers
- Should the extraction turn also fire on PreCompact (memory extraction at the moment context is about to be destroyed)? Needs a field test of prompt fatigue first.
- Which items in docs/reviews/2026-10-02-deferred-health-review.md should be taken next: audit age noise, the cli.py split, duplicated git/timestamp helpers, Windows gating, coverage, or the Stop snapshot's publication cost?

## Likely Relevant Files
- breadcrumbs/cli.py
- breadcrumbs/handoffs.py
- breadcrumbs/packet.py
- breadcrumbs/hooks_common.py
- .github/scripts/ci_gate.py
- .github/workflows/release.yml
- pyproject.toml
- .github/workflows/ci.yml
- breadcrumbs/hooks_guard.py
- tests/test_retest_060.py
- breadcrumbs/scoring.py
- tests/test_extracted_modules.py
- docs/architecture.md
- breadcrumbs/audit.py
- tests/test_decision_staleness.py
- evals/suites/staleness/store.crumb
- breadcrumbs/shellcmd.py
- breadcrumbs/path_policy.py
- breadcrumbs/validation.py
- breadcrumbs/git.py
_(… 55 more omitted to stay within the per-section cap)_

## Verifications
- `ver_20260817_f-5-guard-reprints-the-staleness-block-on-every-call` — F-5 (guard reprints the staleness block on every call) is already fixed on main and in 0.1.11: **not_applicable** · runtime
- `ver_20261113_prune-sessions-keep-keeps-the-newest-sessions-not-the-last` — prune sessions --keep keeps the newest sessions, not the last by file name: **fixed** · test
- `ver_20261113_crumb-rename-deletes-the-record-it-renames-fixed` — crumb rename deletes the record it renames: **fixed** · test
- `ver_20261113_crumb-recover-apply-no-longer-undoes-half-of-a-finished` — crumb recover --apply no longer undoes half of a finished operation: **fixed** · test
- `ver_20260925_ci-mcp-job-fails-stale-pinned-tool-resource-counts-in-ci` — CI mcp job fails: stale pinned tool/resource counts in ci.yml: **fixed** · test
- `ver_20260923_relevance-evals-hold-the-committed-baseline-prompt-p-5-0-66` — Relevance evals hold the committed baseline (prompt P@5 0.66, R@5 0.87, 1 reject hit): **fixed**
- `ver_20260922_phase-5-of-the-working-memory-roadmap-wm-50-to-wm-52` — Phase 5 of the working-memory roadmap (WM-50 to WM-52) is implemented and green: **fixed** · test
- `ver_20260922_phase-4-of-the-working-memory-roadmap-wm-40-to-wm-43` — Phase 4 of the working-memory roadmap (WM-40 to WM-43) is implemented and green: **fixed** · test
- `ver_20260922_phase-3-of-the-working-memory-roadmap-wm-30-to-wm-35` — Phase 3 of the working-memory roadmap (WM-30 to WM-35) is implemented and green: **fixed** · test
- `ver_20260922_phase-2-of-the-working-memory-roadmap-wm-20-to-wm-25` — Phase 2 of the working-memory roadmap (WM-20 to WM-25) is implemented and green: **fixed** · test
- `ver_20260922_phase-1-of-the-working-memory-roadmap-wm-10-to-wm-16` — Phase 1 of the working-memory roadmap (WM-10 to WM-16: capture hooks and the transcript miner): **fixed** · test
- `ver_20260922_phase-0-of-the-working-memory-roadmap-wm-01-migration-wm-02` — Phase 0 of the working-memory roadmap (WM-01 migration, WM-02 usage, WM-03 inbox): **fixed** · test
_(… 11 more omitted to stay within the per-section cap)_

## Verification Commands
- tests/test_delivery_reach.py
- tests/test_release_process.py
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
_(… 13 more omitted to stay within the per-section cap)_

## Stale / Risk Warnings
_(ages below are measured; the cutoff is 21 days — set with `--stale-days`)_
- handoff is 0 day(s) old, written 0 commit(s) behind current HEAD.
- open question "Should the extraction turn also fire on PreCompact (memory extraction at the moment context is about to be destroyed)? Needs a field test of prompt fatigue first." has been open 91 days — did this ever get resolved?
- open question "Which items in docs/reviews/2026-10-02-deferred-health-review.md should be taken next: audit age noise, the cli.py split, duplicated git/timestamp helpers, Windows gating, coverage, or the Stop snapshot's publication cost?" has been open 43 days — did this ever get resolved?
