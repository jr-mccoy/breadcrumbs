# Relevance and delivery evals

These evals measure whether retrieval gets better or worse (roadmap WM-61), and,
since audit WP18, what a reader is actually handed and a set of critical
assertions no baseline can approve. A change to the stemmer, a scoring weight,
a hook or the packet can change what an agent sees without failing a unit test.
These evals catch that.

```bash
python evals/run.py                     # tables + critical cases + compare with baseline.json
python evals/run.py --verbose           # also list each task's misses
python evals/run.py --release           # the release gate: known critical failures fail too
python evals/run.py --write-baseline --reason "why the numbers move"
python evals/run.py --json              # everything, with metric definitions
```

Standard library only, like the package. Nothing here is shipped in the wheel
or the sdist.

## Three layers

### 1. Ranking diagnostics (unchanged since WM-61)

| system   | what runs                                        | ranked by                                   |
|----------|--------------------------------------------------|---------------------------------------------|
| `prompt` | `hooks_prompt.retrieve(prompt=task)`             | its own output order (at most 5)            |
| `packet` | `build_resume_packet(task=…)`                    | `cli.task_relevance_scores`, over the records the bounded packet kept, zero-score entries dropped |
| `guard`  | `guard(task)`, only for tasks that set `verdict` | the verdict must be one of those listed     |

These say whether the *ranking* is right. They do not say what a reader sees:

- `prompt` calls retrieval directly, before the hook's length gate,
  deduplication and rendering.
- `packet` drops zero-relevance entries and re-ranks what is left, so the
  recency floor (the 3 newest entries of each section come first) and every
  other line of noise are invisible to it.

### 2. Delivery (audit WP18)

The real entry points run, and their output is scored as printed.

| system             | what runs | scored on |
|--------------------|-----------|-----------|
| `prompt_delivered` | `crumb hook prompt`, JSON in and out, a fresh session per task, then the same prompt again in the same session | the ids in the injected text; silence on controls; that the repeat is silent (`dedupe`); the injection's token cost |
| `packet_delivered` | `crumb resume --task TASK`, as printed | the first 5 entries **in reading order**, recency floor included (`precision_at_5`); every entry in the packet (`recall_in_view`, `reject_hits`); the whole printed text's token cost and declared budget (`within_budget`) |
| `hook_guard_accuracy` | `crumb hook guard` on the task as a tool call (an Edit of `files[0]` when `files` is set, else Bash) | a warning is delivered exactly when `PROCEED` is not listed |

Correction capture is switched off while the prompt hook runs. It is a write,
not delivery, and a jot from one task would change what later tasks see.

### 3. Critical cases (`critical/cases.yml`, audit WP18)

These are pass/fail assertions, each run against a suite's store:

- a recorded hazard does not get `PROCEED` (`guard_not`), and the guard hook
  warns (`hook_guard_warns`);
- guard cites none of a list of unrelated records (`guard_cites_none`), or
  shows nothing as blocking (`guard_no_blocking`);
- a superseded, retired or speculative record is never delivered
  (`never_delivered`);
- a relevant record is delivered (`delivered`);
- a control prompt is silent (`quiet`);
- every delivery is well-formed and within its declared budget
  (`delivery_bounded`).

**No baseline can approve a critical case.** It fails the run however the
aggregates compare, and `--write-baseline` refuses to write while one fails.

- **`known: <finding>`** marks a failure the repair program already tracks.
  - It is printed on every run (and annotated in GitHub Actions).
  - It does not fail an ordinary run, but it fails `--release`.
  - Once the case passes, the marker must be removed: a stale marker fails the
    run, so a fix cannot hide behind an old excuse.
- **`waiver: <reason>`** marks a capability the project does not claim. It is
  reported, never gated.

Adding either marker is a reviewed change to `cases.yml`, never a baseline
rewrite. The three cases once marked `known: F10` (`npm test` got `PROCEED`,
the guard hook was silent, and the 8-character prompt was never answered)
pass since audit WP10, and their markers were removed. `.github/workflows/release.yml`
runs `--release`, so a release needs every critical case to pass.

## Metrics: definitions and denominators

`METRIC_DEFINITIONS` in `run.py` states what each metric is and what it is
divided by. It is written into every `--json` run and every `baseline.json`,
and every summary carries `n`, the denominators. In short:

- **precision@5**: the share of the top 5 that is in `expect`, divided by the
  number actually shown (up to 5), **not** by 5. It is averaged over tasks that
  expect something. Showing nothing when something was expected scores 0.
- **recall@5** / **recall_in_view**: the share of `expect` in the top 5, or
  anywhere in the delivered packet.
- **reject_hits**: `reject` ids that made a top 5 (ranking) or were delivered
  (delivery), summed. Any increase is a regression.
- **quiet**: the share of control tasks (`expect: []`) that got nothing.
- **dedupe**: of the tasks the prompt hook spoke on, the share where the
  repeated prompt was silent.
- **guard_accuracy** / **hook_guard_accuracy**: the share of `verdict` tasks
  answered as listed. There are eight such tasks in the development suites, so
  one miss is 0.125.
- **within_budget**: the share of printed packets within the budget their
  header declares.
- **tokens_mean** / **tokens_max** (`approx_tokens`): reported, never gated.

`run.py` exits 1 when a rate falls more than 0.05 below `baseline.json`, a count
rises, or a critical case fails. It exits 2 when a suite or a critical case is
malformed.

## Suites

Each directory under `suites/` is one store:

- `store.crumb`: the commands that build it. Each command starts on an
  `@YYYY-MM-DD` line, and indented lines continue it. Every command runs
  through `crumb.main` with the clock set to its date, so the store is written
  by the same code a user's is, and ids and ages are reproducible.
- `files/` (optional): copied into the store as-is, for example
  `aliases.txt`.
- `tasks.yml`: `as_of` (the clock the queries run at), optionally
  `split: holdout`, and `tasks`. Each task has `task`, and optionally `expect`,
  `reject`, `verdict`, `files` and `note`. The file is a strict YAML subset:
  one-line values and one-line `[a, b]` lists.

Stores are built in a temporary directory on every run.

| suite         | split   | what it is                              | what it exercises |
|---------------|---------|-----------------------------------------|-------------------|
| `webapp`      | dev     | TypeScript app, Playwright, npm         | the 0.2.0 field-review cases (screenshot trap vs a `json.load` script; `git status` vs `npm test`), a superseded decision, an expired verification |
| `service`     | dev     | Python backend: auth, Postgres, Celery  | store aliases (`pg` → `database`), stale and superseded decisions, an answered question, the fixture 2/3 guard pair |
| `library`     | dev     | pure-Python CLI on PyPI                 | one-word actions (`upgrade ruff`), release records that disagree on one area, an idea that must never surface |
| `holdout-ops` | holdout | Terraform, Kubernetes, a deploy workflow | destructive infra commands, a superseded secrets decision, an idea, controls |

### Holdout

`overall` covers the development suites only, as it always has. A `split:
holdout` suite is reported as its own `holdout` scope.

**Its tasks are fixed.** They were written once, from what an operator would
need, before the tool was run against them. Do not edit them to match the
tool: a task it scores badly is a measured gap. A change that moves a holdout
number goes through the same reviewed baseline write as any other.

## Changing things

**The baseline is rewritten only with a reason, and task by task.**

- `--write-baseline` needs `--reason`.
- It prints every task-level change against the old baseline: tasks that now
  miss an expected record, now show a rejected one, lost a guard answer, or
  speak on a control; tasks that improved; tasks added or removed.
- If any task regressed, it refuses to write until you rerun with
  `--accept-regressions`, after reviewing each one.
- The reason and the listed changes are appended to `changes` in
  `baseline.json`, which also keeps a per-task snapshot (`tasks`) for the next
  comparison.

Common cases:

- **You changed retrieval on purpose.** Run `--verbose`, check each moved task
  is better for a reason you can name, then write the baseline with that reason.
- **You added a task or a suite.** Write `expect` from what a person would want
  to see, not from what the tool shows today. A task the tool gets wrong today
  is a measured gap, not a mistake in the task.
- **A critical case fails.** Fix the product. If the failure is real and
  already tracked, a reviewed `known:` marker keeps it visible without
  blocking development. It still blocks `--release`.
- **A suite errors (exit 2).** The message names the command or id. The
  near-duplicate gate (exit 3) refuses a record too close to an existing one:
  reword it, or add `--allow-duplicate` if the closeness is the point.
