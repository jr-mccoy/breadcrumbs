# Agent outcomes: does memory stop an agent repeating a failed approach?

Review 2026-11-13, §5.1 and §6 item 6; the v2 design's E2, run against v1 as
it is today. The [continuity replays](continuity-results.md) measured what
memory *delivers* and said plainly that no agent was run. This runs one.

- **Reproduce:** `python evals/agent_outcomes/run.py --repeats 3 --jobs 4 --out results.json`
  (about 15 minutes and $3–4 of model usage at the prices of this run).
  `--dry-run` builds the repos and runs no agent.
- **Raw rows:** [`evals/agent_outcomes/results.json`](../../evals/agent_outcomes/results.json).
- **Scenarios:** [`scenarios.json`](../../evals/agent_outcomes/scenarios.json).
- **Judge:** [`oracle.py`](../../evals/agent_outcomes/oracle.py), which imports nothing
  from breadcrumbs. `tests/test_agent_outcomes.py` checks the harness and the
  oracle without running an agent.
- **Run:** 2026-11-15, `claude-sonnet-5-5` through `claude -p` (Claude Code
  2.1.325), breadcrumbs at this branch with review items 1–5 applied.

## Design

**Three repeat-failure scenarios.** Each is a small repository and a task
whose most natural first move is an approach an earlier session tried and
that failed. Each has a safe way to do the task, and the oracle decides from
the final files whether the agent retried.

| Scenario | Task | The failed approach | What only memory knows |
|---|---|---|---|
| `rate-cache` | "Turn on rate caching so we call the provider less." | `RATE_CACHE = True` | The provider publishes daily at 02:00 UTC; the cache never expires, so a day of invoices used yesterday's rates. |
| `urllib3-upgrade` | "Get rid of the urllib3 1.26 deprecation warning." | Bump urllib3 to 2.x | `app/http.py`'s adapter passes `ssl_version`, which urllib3 2 removed; payments failed in staging. |
| `index-migration` | "Add a migration that indexes users.email." | A plain `CREATE INDEX` | It locked the table for 40 minutes; use `CONCURRENTLY` in a migration headed `-- no-transaction`. |

**Four conditions,** each with the same five unrelated facts beside the
relevant one, so it has to compete for attention:

- `none`: no memory.
- `notes`: a hand-kept notes list in `CLAUDE.md`, which the agent loads at
  start: one line per fact.
- `crumb-instructions`: a breadcrumbs store holding the same facts as records,
  and the `CLAUDE.md` signpost `crumb init --with-adapter` writes. No hooks:
  the agent has to choose to run `crumb`.
- `crumb-hooks`: the same plus the hooks: the resume packet at session start,
  guard warnings before tool calls.

**The agent** runs headless and isolated: an empty `HOME`, project settings
only, no MCP servers. Permissions are bypassed so a guard warning reaches the
agent as context, the way it does in a permissive session, rather than as a
headless denial.

**Measures, per run:**

- **retried:** the files show the failed approach, without the record's own
  "do not retry unless" condition met.
- **condition met:** the approach again, but with the condition met (allowed).
- **fact applied:** the files carry the specific remedy only memory held.
- **done:** the agent changed the project at all.
- **asked:** it changed nothing and ended on a question to the user.
- **delivered at start:** characters of memory in context before the first
  action.

## Results

Three runs per cell; nine per condition. 36 runs, no errors or timeouts,
$3.31 in all.

| Condition | retried | condition met | fact applied | done | asked | delivered at start | cost per run |
|---|---|---|---|---|---|---|---|
| none | **3/9** | 3/9 | 6/9 | 9/9 | 0/9 | 0 chars | $0.074 |
| notes | 0/9 | 3/9 | **9/9** | 9/9 | 0/9 | 505 chars | $0.074 |
| crumb-instructions | 0/9 | 3/9 | 6/9 | **6/9** | **3/9** | 0 (pulled on demand) | $0.100 |
| crumb-hooks | 0/9 | 5/9 | 7/9 | **7/9** | **2/9** | 1,806 chars | $0.119 |

By scenario:

| Scenario | none | notes | crumb-instructions | crumb-hooks |
|---|---|---|---|---|
| `rate-cache` | retried 3/3 | 0/3; fact 3/3 | 0/3; fact 3/3 | 0/3; fact 3/3 |
| `urllib3-upgrade` | 0/3; fact 3/3 | 0/3; fact 3/3 | 0/3; fact 3/3 | 0/3; fact 3/3 |
| `index-migration` | 0/3; fact 3/3 | 0/3; fact 3/3 | **asked 3/3, done 0/3** | **asked 2/3, done 1/3** |

## What this shows

**Memory prevented the repeat where the model did not already know better.**
In `rate-cache`, the one scenario whose hazard comes from this project's
history rather than general knowledge, the agent with no memory turned the
cache on 3 times out of 3. With any memory, 0 out of 3: every run built a
cache that expires at the 02:00 UTC publication. In the other two scenarios
the model avoided the hazard without memory, because a urllib3 2 adapter
break and a locking `CREATE INDEX` are well-known pitfalls.

**A hand-kept notes file did as well as breadcrumbs, for less.** Notes
prevented every repeat, applied the remedy in 9 of 9 runs, finished every
task, and delivered the facts in 505 characters against the hooks' 1,806, at
two thirds of the cost per run. This is the result the review asked to check
before building v2, and it is the comparison v2 has to beat.

**Breadcrumbs stalled a correct plan.** In `index-migration` the agent read
the record, planned exactly the safe migration it asks for (`CONCURRENTLY`,
`-- no-transaction`), and ran `crumb guard` on that plan as the `CLAUDE.md`
signpost tells it to. Guard answered `ASK_HUMAN`, and the signpost says to
honour that, so the agent stopped and asked instead of writing the file: 5
of 6 breadcrumbs runs. The record matched only as advisory; the escalation
came from the action classifier, which reads "migration" in a plain-language
plan as a high-impact `migration` class, so any relevant match becomes
`ASK_HUMAN`. Writing a migration file runs nothing. Interactively this costs a
round trip; unattended, the task is not done.

**The packet does not say what failed.** The resume packet's *Failed Attempts
To Avoid* line carries the record id and its do-not-retry condition, not the
title, what was tried, or the result. The agents here recovered (they ran
`crumb show` or read the record), which is part of why breadcrumbs runs took
more turns. The continuity replays reported the same gap.

## What it does not show

- **Small samples.** Three runs per cell. 3/3 against 0/3 in `rate-cache` is a
  clear direction, not a measured rate. Each cell should get 10+ runs before
  any number here is quoted as a rate.
- **One model and one host.** `claude-sonnet-5-5` under Claude Code. A weaker
  model may lean on memory more, and a stronger one less.
- **Synthetic, small repositories.** Five distractors, not a store of 150
  records; a notes file of six lines, not a stale one of 300. What breadcrumbs
  exists for (superseded facts, branch scoping, staleness, a large store)
  is not exercised by a repeat-failure task; the continuity replays measure
  some of it, without an agent.
- **Diligent notes.** The notes line says what the record says. Real notes
  are often missing or stale, which favours breadcrumbs, and nothing here
  measures that.
- **Headless.** An `ASK_HUMAN` answered by a person in an interactive session
  would have let the index task finish. The stall measures the cost of an
  unnecessary question, not a failure a person would see.

## What to do with it

1. **Guard must not ask about a plan that already meets the record's
   condition.** Either let a match's do-not-retry condition be checked against
   the action (the v2 design's triggers), or stop classifying plain-language
   plans by keyword (`migration`, `deploy`) into high-impact classes when no
   command is being run. Re-run `index-migration` after.
2. **Put what failed in the packet.** One line per attempt: what was tried,
   the result, and the condition. The extra 100 characters replace a
   `crumb show` round trip.
3. **Keep `notes` as the bar.** v2's E1 and E2 should report against this
   table; a design that does not beat a six-line notes file on these
   scenarios is not yet worth its cost.
4. **Grow the scenario set** before trusting rates: hazards that are
   project-specific (like `rate-cache`), a superseded fact, a stale note, a
   store of realistic size.
