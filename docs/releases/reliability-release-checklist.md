# Reliability release checklist: crumb-kit 0.4.0 (prepared, not released)

This is audit work package WP22
([roadmap](../reviews/2026-09-26-breadcrumbs-audit-and-roadmap.md#wp22)). It
collects what a release of the audit remediation would stand on, so the person
who releases it can check each item instead of trusting a summary.

**Status: prepared, not released.** Nothing here has been published. At the
operator's request, the branch carries the version bump to `0.4.0` (section
7, step 3). Merging to `main` and running the release workflow are the
operator's steps, and neither has been taken.

## 1. Source

| Item | Value |
|---|---|
| Branch | `claude/new-session-9f1k6i` |
| Revision this checklist describes | `529356e`. The commit that adds this checklist changes documentation only. |
| Last released version | 0.3.1 (tag `v0.3.1`) |
| Commits since `v0.3.1` | 66 |
| Version on the branch | **0.4.0** (bumped at the operator's request): a minor, see below |
| `schema_version` | 4, unchanged since 0.3.0 |

**Why 0.4.0 and not 0.3.2.** Under the pre-1.0 policy
([compatibility.md](../compatibility.md) §1), a minor is required when the
manifest gains a `requires` feature or a compatibility surface changes
incompatibly. Both happen:
- a store under `crumb policy set team` declares `requires: review-profiles`
  (WP14), which an older build refuses to write;
- the write lock is now an OS lock on `private/.store.lock` (WP05). An older
  version does not see it, so the CHANGELOG says to run one version per
  checkout.

**Build hashes.** The release workflow builds its own artifacts on the tagged
commit, and those are the ones that matter. A local build of `8242861` (the
version bump) with `build` (`pyproject-build`), for reference. A build is not
byte-reproducible, because archive timestamps differ:

| File | SHA-256 |
|---|---|
| `crumb_kit-0.4.0-py3-none-any.whl` | `2d90410d3da88b70c8095cd3a3561c8f44a2130edf08716bac5485fdfc286bfc` |
| `crumb_kit-0.4.0.tar.gz` | `67261ccd1cf4f345ea5e0e858ca096dd3957bb18b7dbb77c3f5084b5d40f18ed` |

`crumb-kit==0.4.0` was not on PyPI when this was written, so the release
pre-flight will not stop with "already released".

## 2. Acceptance matrix

Every gate below is required by `ci.yml` or `release.yml` unless it says
"reported".

| Gate | Where it runs | Evidence | Status |
|---|---|---|---|
| Full unit suite, Linux, Python 3.9–3.14 | CI `test` job | run 249 (`529356e`) | green |
| MCP server, SDK `<2` and `>=2,<3`, Python 3.10–3.14 | CI `mcp` job | run 249 (`529356e`) | green |
| Installed-wheel smoke test, Windows and macOS, Python 3.9 and 3.13 | CI `native` job (gating) | run 249 (`529356e`) | green |
| Adapter and MCP contract tests, Windows and macOS | CI `native` job (gating) | run 249 (`529356e`) | green |
| Full unit suite, Windows and macOS | CI `native-full` job (reported) | the `native-full` job (on `main`, weekly and on demand); run 248 (`9b55822`): 1,365 run, 0 failures on all four combinations | green, reported |
| Packaging: wheel, sdist, `twine check`, bundled templates, installed binary, the quickstart as written | CI `package` job; `release.yml` | run 249 (`529356e`) | green |
| Fixture, guard and MCP checks | CI | run 249 (`529356e`) | green |
| Lint (`ruff check`, `ruff format --check`) | CI `lint` job | run 249 (`529356e`) | green |
| Critical eval gate: every case in `evals/critical/cases.yml` passes, `known:` included | `release.yml` (`evals/run.py --release`); CI reports | local, on `529356e`: 20 of 20 pass | green locally |
| Relevance and delivery evals against the baseline | CI `evals` job | run 249 (`529356e`) | green |
| Continuity replays reproduce the published verdicts | `tests/test_task_replays.py` | in the suite | green |
| Audit regression probes | `tools/audit/regression_probes.py` | section 4 | 2 signals, both explained |

## 3. Separate reviews

These are listed apart because a green suite does not review them.

- **Evaluation baselines.** `evals/baseline.json` changed twice since
  0.3.1, both through the reviewed path. `--write-baseline` needs a
  `--reason`, refuses while a critical case fails, and appends the reason and
  the task-level deltas to the baseline's `changes`:
  - WP18 (`b7f37ce`) added the delivery measurements. Every earlier value
    kept its definition and its number
    ([WP18 record](../reviews/2026-09-27-breadcrumbs-wp18/README.md)).
  - WP10 (`725eb76`) recorded three task-level improvements and no
    regressions, all on webapp `npm test`
    ([WP10 record](../reviews/2026-09-27-breadcrumbs-wp10/README.md)).
  - `evals/critical/cases.yml` is new (WP18). Three `known: F10` markers came
    off in WP10 when their cases passed.
- **Dependencies.** None added. The package has no runtime dependencies.
  `pyproject.toml` changed only to exclude `tools/audit/` from ruff (the
  audit's scripts are evidence, kept byte-identical).
- **Sensitive memory.** This repository's own `.project-memory/` changed in
  38 files since 0.3.1. `crumb scan-secrets` reports no secret-like strings.
  The default `handoff.md` was reconciled in WP20.
- **Publication artifacts.** `release.yml` runs `twine check`, compares the
  bundled templates with the source, and runs the installed binary. The CI
  `package` job also runs the quickstart against the installed wheel.
- **Audit evidence.** `docs/reviews/2026-09-26-breadcrumbs-evidence/`,
  `tools/audit/*.py` and the roadmap are unchanged since they arrived.

## 4. What is not claimed (explicit exclusions)

- **Seven work packages await a person's review.** The tracker
  ([work-packages.json](../reviews/2026-09-26-breadcrumbs-work-packages.json))
  marks WP14, WP15, WP16, WP17, WP19, WP20 and WP22 `review_required`. They
  were implemented and checked by an AI coding agent. The operator authorized
  the work; no person has reviewed those seven yet.
- **F21 is not finished (WP16).** `cli.py` still holds most domain
  functions, and 18 modules import it.
- **The continuity replays measure delivery, not outcomes (WP19).** No agent
  was run, one real repository was used rather than three, the inputs are
  hand-written, and there is no uncertainty interval.
- **The native full unit suite.** It is reported, not gating, and runs on `main`, weekly and on
  demand. It was green on every combination in run 248. `release.yml` does
  not re-run it, so before publishing, check the `native-full` jobs of the
  `ci` run on the merge commit (a push to `main` runs them).
- **Two probe signals are recorded false positives.** The audit's scripts
  are kept byte-identical, so the probes are not edited.
  - `guard_usage_dedupe`: its condition flags any non-`None` count after one
    emission. Its own output shows the fix: `surfaced` is 1, where it was 2
    ([WP12 record](../reviews/2026-09-27-breadcrumbs-wp12/README.md)).
  - `resume_ignores_lock`: it fakes a lock holder by writing a pid into the
    lock file. Under an OS lock that holds nothing, so `resume` correctly takes
    the free lock. `test_resume_does_not_publish_under_foreign_writer` runs
    the scenario with a process that really holds it
    ([WP05 record](../reviews/2026-09-27-breadcrumbs-wp05/README.md)).

  Three probes error, each recorded as an error and not as "fixed". Their
  properties are held by ordinary tests:
  - `recheck_scope_and_claim` dereferences a record that the new recheck
    contract no longer writes for a diagnostic command (WP04);
  - `live_lock_stale` patches a staleness rule that no longer exists (WP05);
  - `symlink_read` has no handler for the refusal the resource now raises
    (WP13).
- **Hooks are Claude Code only.** Other agents get files, the CLI and MCP
  ([compatibility-matrix.md](../compatibility-matrix.md)).
- **The Windows hook-log fix is inferred.** The race it closes did not
  reproduce on Linux; the native telemetry test is the evidence
  (it passed on every native combination in runs 247 and 248).

## 5. Published material

- The bounded demo: [two-session-handoff.md](../demos/two-session-handoff.md)
  (`python evals/task_replays/demo.py`).
- The benchmark report:
  [continuity-results.md](../benchmarks/continuity-results.md), with its
  scripts, inputs, results file and limits.
- Contribution instructions: `CONTRIBUTING.md` (a first contribution from a
  failing scenario).
- The operating contract: [quickstart.md](../quickstart.md),
  [operator-guide.md](../operator-guide.md),
  [continuity-contract.md](../continuity-contract.md).
- Per-package records: `docs/reviews/2026-09-27-breadcrumbs-wpNN/`.

## 6. Draft release notes (for the GitHub Release)

> **crumb-kit 0.4.0: the reliability release**
>
> This release implements the remediation of an external audit of
> breadcrumbs (findings F01–F26, work packages WP00–WP22). The work was done
> by an AI coding agent, with every package checked by tests. Each package
> has a public review record under `docs/reviews/`, stating what changed,
> the evidence and the limits. Seven packages still await a person's review
> at the time of writing; the tracker says which.
>
> What changes for you:
> - **Writes are all-or-nothing and recoverable** (`crumb recover`). A failed
>   supersession no longer leaves two live decisions.
> - **One writer at a time**, with an OS lock that a crash cannot wedge. Run
>   one crumb-kit version per checkout.
> - **Team review profiles** (`crumb policy set team`). Agent-written guidance
>   is a proposal until a person reviews it.
> - **Guard sees PowerShell and notebook edits.** Re-run
>   `crumb init --with-hooks` to update the installed matcher.
> - **Windows and macOS are tested in CI**, and the defects that found are
>   fixed. Line endings and path spellings no longer change hashes or
>   rollback.
> - **A versioned MCP contract**, with advisory tool annotations.
> - **An executed quickstart, an operator guide, and a continuity
>   contract.**
>
> What is measured, and what is not: `docs/benchmarks/continuity-results.md`
> reports what a second session is handed under three baselines, with the
> costs. It measures delivery, not agent outcomes, on one repository.
>
> Upgrading: `schema_version` is unchanged (4). A store that declares
> `requires: review-profiles` is refused for writing by older versions. The
> full list is in `CHANGELOG.md`.

## 7. Steps for the operator (in order)

1. Review the `review_required` packages in the tracker, and record the
   outcome there.
2. Merge the branch to `main`.
3. **Done on the branch** (the operator asked for it before the merge):
   - `__version__` is `0.4.0` in `breadcrumbs/__init__.py`;
   - `CHANGELOG.md` has `## [0.4.0] — 2026-09-28`, with an empty
     `## [Unreleased]` above it;
   - `docs/compatibility.md` §3 has the `0.4.0 | 4` row.

   `tests/test_store_upgrade_contract.py` checks that all three agree. If
   the release happens on a later day, the date in the heading can be
   corrected on `main` first.
4. Run `release.yml` with `mode: dry-run`, then `mode: publish`
   ([RELEASING.md](../../RELEASING.md)). Never tag by hand.
5. After publishing, reconcile `.project-memory/handoff.md` on `main`
   ([operator guide](../operator-guide.md) §6).
