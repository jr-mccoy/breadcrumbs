# Relevance evals

Measures whether retrieval gets better or worse (roadmap WM-61). A change to
the stemmer, a scoring weight or the packet's ordering can change what an agent
sees for a task without failing a unit test. These evals catch that.

```bash
python evals/run.py                    # table + compare with baseline.json (exit 1 on regression)
python evals/run.py --verbose          # also list each task's misses
python evals/run.py --write-baseline   # accept the current numbers
python evals/run.py --json             # everything, machine-readable
```

Standard library only, like the package. Nothing here is shipped in the wheel
or the sdist.

## What is measured

For every task, three things:

| system   | what runs                                        | ranked by                                   |
|----------|--------------------------------------------------|---------------------------------------------|
| `prompt` | `hooks_prompt.retrieve(prompt=task)`             | its own output order (at most 5)            |
| `packet` | `build_resume_packet(task=…)`                    | `cli.task_relevance_scores`, the score the packet orders by, over the records the bounded packet kept |
| `guard`  | `guard(task)`, only for tasks that set `verdict` | the verdict must be one of those listed     |

The packet's recency floor (the newest 3 entries of each section stay first) is
a reading-order rule, not relevance, so the packet is ranked by the score it
orders the rest by.

- **precision@5**: the share of the top 5 that is in `expect`. It is averaged
  over tasks that expect something. Showing nothing when something was expected
  scores 0.
- **recall@5**: the share of `expect` that made the top 5.
- **reject_hits**: `reject` ids that made a top 5, summed. Any increase is a
  regression.
- **quiet** (prompt only): the share of control tasks (`expect: []`) where the
  hook injected nothing.
- **guard_accuracy**: the share of `verdict` tasks guard answered as listed.

`run.py` exits 1 when a rate falls more than 0.05 below `baseline.json`, or
when a count rises. It exits 2 when a suite is malformed, such as an id in
`tasks.yml` that is not in the built store, or a store command that fails.

## Suites

Each directory under `suites/` is one store:

- `store.crumb`: the commands that build it. Each command starts on an
  `@YYYY-MM-DD` line, and indented lines continue it. Every command runs
  through `crumb.main` with the clock set to its date, so the store is written
  by the same code a user's is, and ids and ages are reproducible.
- `files/` (optional): copied into the store as-is, for example
  `aliases.txt`.
- `tasks.yml`: `as_of` (the clock the queries run at) and `tasks`. Each task
  has `task`, and optionally `expect`, `reject`, `verdict`, `files` and
  `note`. The file is a strict YAML subset: one-line values and one-line
  `[a, b]` lists.

Stores are built in a temporary directory on every run.

| suite     | what it is                                   | what it exercises |
|-----------|----------------------------------------------|-------------------|
| `webapp`  | TypeScript app, Playwright, npm              | the 0.2.0 field-review cases (screenshot trap vs a `json.load` script; `git status` vs `npm test`), a superseded decision, an expired verification |
| `service` | Python backend: auth, Postgres, Celery       | store aliases (`pg` → `database`), stale and superseded decisions, an answered question, the fixture 2/3 guard pair |
| `library` | pure-Python CLI on PyPI                      | one-word actions (`upgrade ruff`), release records that disagree on one area, an idea that must never surface |

## Changing things

- **You changed retrieval on purpose.** Run `--verbose`, check each moved task
  is better for a reason you can name, then `--write-baseline` and commit the
  new `baseline.json` with the change.
- **You added a task or a suite.** Write `expect` from what a person would want
  to see, not from what the tool shows today. Then `--write-baseline`. A task
  the tool gets wrong today is a measured gap, not a mistake in the task.
- **A suite errors (exit 2).** The message names the command or id. The
  near-duplicate gate (exit 3) refuses a record too close to an existing one:
  reword it, or add `--allow-duplicate` if the closeness is the point.
