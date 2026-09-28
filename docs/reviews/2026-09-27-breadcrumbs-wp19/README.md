# WP19: controlled continuity replays, results and a demo (2026-09-27)

This implements work package WP19 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), finding F26,
**in part**. The starting commit is `5e01027` (WP17 in progress; WP19
changes no product code). The operator authorized the remaining work on
2026-09-27.

Read this first: **the roadmap asks for an agent experiment on at least
three real repositories. This package delivers a delivery experiment on one.**
Both gaps are stated below and in the published results. The tracker records
the package as `review_required` with them.

## Cause

F26 says the evaluations are synthetic and single-session. Nothing
demonstrated that a later session is actually handed what an earlier one
learned, compared against no memory and against a small hand-kept notes file,
with cost counted. There was no demo someone outside the project could rerun.

## Change

Everything is under `evals/task_replays/` and `docs/`. No product code
changes.

- **`scenarios.json`.** Five two-session scenarios as sanitized, hand-written
  inputs: repeated failure, changed decision, compaction, branch switch and
  cross-harness. Each has:
  - session 1's events;
  - session 2's task and first action;
  - the note line a diligent person would write, and the commit message;
  - an oracle: facts that must be delivered, the record title (pointer), and
    stale guidance that must not be presented as current.
- **`oracle.py`.** Scores text only and imports nothing from breadcrumbs.
- **`run.py`.** Three baselines:
  - `none`;
  - a hand-kept `NOTES.md`;
  - breadcrumbs, through the real hooks under Claude Code and the real MCP
    tools for the cross-harness scenario.

  They run on two hosts: a fresh repository, and a local clone of this
  repository with its real store. Recorded per run:
  - the delivered text's digest;
  - facts and pointer at start and at the action;
  - stale presentation;
  - tokens;
  - commands, bytes and prose (store setup separate);
  - for breadcrumbs, each surfaced record's id, file and content hash.
- **`results.json`.** The published run.
- **`demo.py`.** The two-session handoff, step by step.
- **`docs/benchmarks/continuity-results.md`.** Design, results, what they show
  and do not show, and how to rerun.
- **`docs/demos/two-session-handoff.md`.** The demo, with excerpts from a run.

## Tests

- **`tests/test_task_replays.py`.**
  - `test_rerun_reproduces_the_published_verdicts` reruns the fresh-host
    replays and holds every oracle verdict to `results.json`; every surfaced
    record carries a file and a hash.
  - `test_the_oracle_needs_nothing_from_breadcrumbs`.
- **The roadmap's acceptance checks:**
  - *An independent rerun can reproduce the task oracle and inspect the
    surfaced record revision.* Yes: the test above, and each row's
    `surfaced[].sha256`.
  - *No-memory and minimal-Markdown baselines use comparable task/harness
    conditions.* Yes: the same scenario, host, git history and session-2
    moments. The notes file is loaded where an instruction file is. The one
    asymmetry, the guard hook's action-time moment, is breadcrumbs', and is
    reported as its own column.
  - *All reported cost includes maintenance and retries.* Commands, bytes
    (generated projections included) and prose are counted. There are no
    retries to count: the replays are deterministic and no command was
    retried.

## Results (from `results.json`, 10 runs per baseline)

| Baseline | facts@start | pointer@action | stale as current | tokens | commands |
|---|---|---|---|---|---|
| none | 2/10 | 2/10 | 0/10 | 0 | 0 |
| notes | 10/10 | 2/10 | 4/10 | 1,398 | 0 |
| breadcrumbs | 6/10 | 10/10 | 0/10 | 22,614 | 97 |

The full table, per scenario, is in
[continuity-results.md](../../benchmarks/continuity-results.md).

**A product finding for follow-up.** The packet's *Failed Attempts To Avoid*
line gives the title and the do-not-retry condition, but not why the attempt
failed. The replays show that reason is one `crumb show` away in every
scenario that needs it.

## Limits

- **Delivery, not outcomes.** No agent was run. Whether a model heeds a PAUSE
  or reads the notes file is not measured. The roadmap's agent experiment
  remains open.
- **One real repository, not three.** This session's access is scoped to this
  repository, and other projects were deliberately not cloned. The harness
  takes any repository, so this is a rerun, not a rewrite.
- **Hand-written inputs.** Both baselines are given diligent authors.
  Measuring sparse or missing notes is not done.
- **No uncertainty interval.** Each cell is one deterministic run. The
  denominators are the whole population.
- **Cross-harness assumes compliance.** The MCP client is assumed to call
  `memory_build_resume_packet` and `memory_guard_before_action`.
