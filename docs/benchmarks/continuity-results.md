# Continuity replays: what a later session is handed

Audit WP19, finding F26. These are **delivery** results: what a second session
is handed, and when. **No agent was run.** Whether a model acts on what it is
handed is a separate question, and these numbers do not answer it.

- **Reproduce:** `python evals/task_replays/run.py --json results.json`
  (about a minute). It is deterministic: no model and no randomness.
- **Raw rows:** [`evals/task_replays/results.json`](../../evals/task_replays/results.json).
- **Inputs:** [`scenarios.json`](../../evals/task_replays/scenarios.json).
- **Scoring:** [`oracle.py`](../../evals/task_replays/oracle.py) imports
  nothing from breadcrumbs.
- **Versions:** crumb-kit 0.3.1 source at this commit; Python 3.11; git 2.x.
  The scenario version is in `results.json`.

## Design

**Three baselines**, run on the same scenario, host and harness conditions:

- **`none`:** no memory. Session 2 has the repository and its git log, and
  nothing is delivered to it.
- **`notes`:** a hand-kept `NOTES.md`.
  - Session 1 appends the line a diligent person would write for each event.
  - Session 2's harness loads the file at start, as it loads
    `CLAUDE.md`/`AGENTS.md`, and reloads it after a compaction.
- **`breadcrumbs`:** session 1 records with `crumb`.
  - Under Claude Code, session 2 gets the `SessionStart` packet, the
    `UserPromptSubmit` injection, and the `PreToolUse` guard warning at its
    first action. These are the real hooks, fed the JSON Claude Code sends.
  - Under an MCP client (the cross-harness scenario), it gets
    `memory_build_resume_packet` at start and `memory_guard_before_action`
    at the action. Those are calls the agent must choose to make, so that row
    assumes compliance.

**Five scenarios:**

- **Repeated failure:** session 2 is asked to redo a failed approach.
- **Changed decision:** a decision was later superseded.
- **Compaction:** the key record, then 40 unrelated ones, then a compaction.
- **Branch switch:** guidance scoped to a feature branch; session 2 is on
  `main`, and memory was not yet committed.
- **Cross-harness:** recorded under Claude Code, resumed by an MCP client.

**Two hosts:**

- `fresh`: an empty repository.
- `this-repo`: a local clone of this repository, whose real store (79 decision, attempt, trap,
  verification, question and idea records) competes for the budget.

**Measures, per run:**

- **facts@start:** every fact the oracle requires was in the text handed over
  by the first prompt.
- **facts@action:** the same, in the text handed over at the first action.
- **pointer:** the title of the record holding the facts was handed over, so
  the facts are one `crumb show` away.
- **stale:** guidance that is no longer true (superseded, or another branch's)
  appeared as current.
- **tokens:** what was handed over, all moments summed (the package's
  approx-token heuristic).
- **capture cost:** memory commands run, bytes of memory written (a new
  store's one-time scaffolding reported separately), and prose authored.

## Results

Ten runs per baseline: 5 scenarios × 2 hosts.

| Baseline | facts@start | facts@action | pointer@start | pointer@action | stale as current | tokens (sum) | commands | bytes written |
|---|---|---|---|---|---|---|---|---|
| none | 2/10* | 2/10* | 2/10* | 2/10* | 0/10 | 0 | 0 | 0 |
| notes | **10/10** | 2/10* | 6/10 | 2/10* | **4/10** | 1,398 | 0 | 5,584 |
| breadcrumbs | 6/10 | 4/10 | **10/10** | **10/10** | **0/10** | 22,614 | 97 | 100,985 (+63,885 setup) |

\* The branch-switch scenario requires delivering nothing (only not
delivering the stale line), so every baseline passes its delivery columns
there. In `none`'s 2/10, those two branch-switch runs are the only passes.

The scenario facts appear in a commit message in 5/10 runs, and every
baseline has the git log. Nothing delivers it; an agent would have to read it.

### By scenario (both hosts agree unless noted)

| Scenario | notes | breadcrumbs |
|---|---|---|
| Repeated failure | Facts at start. Nothing at the action. | The attempt and its do-not-retry condition at start, and the attempt again at the edit (PAUSE: Claude Code asks). **Not** why it failed ("stale prices"): that is one `crumb show` away. |
| Changed decision | Facts at start, **and the superseded decision beside them as current**: the note file is append-only. | The current decision at start and at the edit. The superseded one is never presented. |
| Compaction | Facts at start (the file is reloaded whole; 576 tokens for 41 lines). | The attempt, with its do-not-retry condition, survives in the post-compaction packet, the prompt injection and the guard. **Not** why it failed ("9 seconds"). |
| Branch switch | **The feature branch's insecure-cookie note is handed to `main` as current** (an untracked file follows `git checkout`). | Nothing from the feature branch reaches `main`: the record is branch-scoped. |
| Cross-harness | Facts at start, if the second harness loads the file. | Facts at start in the portable packet, if the agent calls `memory_build_resume_packet`; the attempt at the action through `memory_guard_before_action`. |

## What this shows, and what it does not

**Where breadcrumbs did better here:**
- It never presented stale guidance as current: 0/10, against 4/10 for the
  hand-kept notes.
- It pointed at the relevant record at the moment of action in 10/10 runs,
  where the notes baselines relied on the agent remembering the file.

**Where the hand-kept notes did better here:**
- They delivered the full facts at start more often (10/10 against 6/10),
  in far fewer tokens (1,398 against 22,614).
- They need no commands and no store.

**Found by these replays:** the packet's *Failed Attempts To Avoid* line
carries the title and the do-not-retry condition, not the result. So the
reason an approach failed is one lookup away, in every scenario that needs it.
That is a product finding for a follow-up. This package changes no product
code.

**Cost.**
- In the real repository, breadcrumbs hands over 2,800–4,100 tokens at
  session start, because the packet carries the repository's own history.
  The fresh host needs about 300 (1,000 after 41 records).
- Capture is one command per record, plus a new store's 12.8 KB of
  scaffolding.
- The 40-record compaction scenario wrote 42–48 KB of memory, generated
  projections included, against 2.3 KB of notes.

**Not shown:**
- **No agent outcomes.** Whether a model heeds a PAUSE, runs `crumb show`, or
  reads `NOTES.md` is not measured. The roadmap's full three-baseline
  experiment with independent task oracles run by agents remains open.
- **One real repository, not three.** The acceptance criterion asks for at
  least three. Only this repository was available in this session. Other
  repositories were deliberately not cloned: the session's access is scoped
  to this one. The harness takes any repository path, so an outside rerun on
  other projects is one argument away.
- **Hand-written inputs.** The note lines are what a *diligent* person
  writes; real notes are often sparser or missing, which would favor
  breadcrumbs, and nothing here measures that. The breadcrumbs records are
  written with full fields, which favors it.
- **No uncertainty interval.** Each cell is one deterministic run, not a
  sample; the denominators are the whole population (10 runs per baseline).
  Varying the scenario wording would give a distribution; that is not done
  here.

## Rerun and inspect

```bash
python evals/task_replays/run.py --json /tmp/results.json
python evals/task_replays/demo.py            # the two-session demo, step by step
```

Each row of `results.json` records:
- a digest of every delivered text;
- for breadcrumbs, the id, file and content hash of each record that
  surfaced, so the exact revision can be inspected;
- whether the fact was in the git log.

`oracle.py` can be applied to saved text without breadcrumbs installed.
