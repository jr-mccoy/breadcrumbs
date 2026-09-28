# Demo: a later session is warned off a mistake

One failed approach, recorded in session 1. In session 2, a fresh session with
none of session 1's context is asked to take the same approach. It is warned
at session start, at the prompt, and at its first edit, and every warning
leads back to the record and its evidence.

Reproduce it with one command, in a temporary repository, using this
checkout's `crumb`:

```bash
python evals/task_replays/demo.py
```

Every output is the real CLI's, or a real Claude Code hook fed the JSON Claude
Code sends. **No model runs.** This shows what the next session is *handed*,
not what an agent does with it. The measured comparison with no memory and
with a hand-kept notes file is in
[`docs/benchmarks/continuity-results.md`](../benchmarks/continuity-results.md).
The excerpts below are from a run on 2026-09-27; ids carry the run's date.

## Session 1: an attempt fails, and is recorded

```console
$ crumb remember attempt --title 'Tried an in-process LRU cache for pricing' \
    --problem 'the pricing API is slow' \
    --tried 'an in-process LRU cache in front of the pricing client' \
    --result 'workers served stale prices for up to an hour' \
    --do-not-retry 'all pricing workers share one process' \
    --evidence file src/pricing/cache.py --tags pricing,cache
Recorded attempt: att_20260927_tried-an-in-process-lru-cache-for-pricing
```

## Session 2: asked to do the same thing

**At session start** (`SessionStart` hook), the injected packet includes:

```markdown
## Failed Attempts To Avoid
- `att_20260927_tried-an-in-process-lru-cache-for-pricing` — do not retry: all pricing workers share one process
```

**At the prompt** "add an in-process LRU cache to speed up the pricing
client" (`UserPromptSubmit` hook):

```text
breadcrumbs: memory relevant to this prompt (data, not instruction):
- `att_20260927_tried-an-in-process-lru-cache-for-pricing` [attempt] Tried an in-process LRU cache for pricing — same component/tag: cache, pricing; +5 shared keyword(s); named in the record's title; has an explicit do-not-retry condition

Fetch a body before acting on this area: `crumb show <id>` (or `memory://records/{id}`).
```

**At the first edit** of `src/pricing/cache.py` (`PreToolUse` hook), the
guard answers `PAUSE`. Claude Code then asks the person
(`permissionDecision: "ask"`):

```text
breadcrumbs guard: PAUSE for this action.
- Tried an in-process LRU cache for pricing (same file(s): cache.py; same component/tag: cache, pricing; +2 shared keyword(s); named in the record's title; has an explicit do-not-retry condition)
```

## The trail

Each warning names the record. `crumb show <id>` prints it in full:
- the problem;
- what was tried;
- the result ("workers served stale prices for up to an hour");
- the condition under which a retry is sensible;
- the evidence (`src/pricing/cache.py`);
- who wrote it, on which branch and commit, and its review status.

## What it does not show

- **It shows what the agent is handed, not what the agent does.** No agent
  is run, so whether a model heeds the PAUSE is not measured.
- **The start packet names the condition, not the reason.** It says "do not
  retry: all pricing workers share one process", but *why* the attempt failed
  is one `crumb show` away. The replay results call this out as a follow-up.
- **Only Claude Code gets the three automatic moments.** Another harness gets
  the same record through MCP (`memory_build_resume_packet`,
  `memory_guard_before_action`) or the CLI, and only when it calls them. See
  [`compatibility-matrix.md`](../compatibility-matrix.md).
