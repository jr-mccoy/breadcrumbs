# Field-test protocol

How to run one real working session with every hook on, what to count, and how
to turn the counts into answers (roadmap WM-62). The relevance evals
(`evals/`) measure retrieval on synthetic stores. This protocol measures what
the hooks do to a real session: what they cost, how often they speak, and
whether what they say is used.

It exists to answer three questions the code cannot settle by itself:

1. **Does the extraction turn cause fatigue?** The Stop hook can block once per
   unit of work and ask the agent to record what it learned. Asked too often,
   or with nothing worth recording, an agent learns to answer with nothing.
2. **Should SubagentStop block too?** WM-13 only mines a finished subagent's
   transcript. Holding the subagent for its own extraction turn adds a second
   prompt per subagent (roadmap §3, open decision 2).
3. **Should the extraction turn also fire on PreCompact?** This is open
   question `q_should-the-extraction-turn-also-fire-on-precompa-ebd583`. It
   waits on the answer to question 1.

## What gets recorded

Every hook firing appends one line to `.project-memory/private/hook-log.jsonl`:

```json
{"event":"guard","at":"2026-09-23T10:02:11+00:00","ms":3.1,"outcome":"context","session":"…","tool":"Bash","verdict":"READ_FIRST"}
```

- `event`: which hook fired: `session`, `guard`, `prompt`, `capture` (Stop),
  `compact` (PreCompact) or `subagent` (SubagentStop).
- `ms`: how long the hook took.
- `outcome`: what the host received. `silent` is `{}`. `context` means records
  were injected. `ask` is a permission prompt. `block` is the Stop hook's
  extraction turn. `locked` means a writing hook skipped because another
  session held the store lock.
- Detail the hook noted: guard's `verdict`, `tool` and `skipped: prefilter`,
  the prompt hook's `matches`, `deduped` and `correction`, and capture's
  `mined`, `snapshot`, `redundant` and `offered`.

The log holds **no content**: no prompt, command, path or transcript text. Its
output is safe to paste into a report. It is under `private/`, so it is
gitignored and local to one machine. It keeps the latest 5000 lines at most.

## Before the session

1. Pick a real project with a store that has been used for a while, with at
   least 20 decisions, attempts and traps. An empty store tests nothing.
2. Install every hook: `crumb init --with-hooks` (the bare flag installs all
   six). Check with `crumb doctor`.
3. Start clean counters so the report covers this session only:
   ```bash
   mv .project-memory/private/hook-log.jsonl{,.before} 2>/dev/null
   crumb inbox --all --json > /tmp/inbox-before.json
   ```
4. Keep a tally sheet next to you (see the template below). The log counts what
   the hooks did. Only a person can say whether it helped.

## During the session

Work normally for at least two hours, or at least 30 prompts. Let the agent
launch subagents if the work calls for it, and let the context compact if it
gets there. Do not steer toward or away from the hooks.

Each time a hook's output is visible, mark one line on the tally:

- **helped**: it named something the agent then used, or stopped a mistake.
- **noise**: irrelevant, or something the agent already knew.
- **ignored**: relevant, but the agent went ahead without it.

For every extraction turn (the Stop hook blocking), also note what the agent
did: wrote a record, dismissed it with a reason, or produced an empty or
boilerplate answer.

## After the session

```bash
crumb doctor --hook-log            # per hook: firings, outcomes, spoke rate, ms p50/p95, verdicts
crumb doctor --hook-log --json     # the same, for the report
crumb usage --sessions             # which records reached how many sessions
crumb inbox --all --json > /tmp/inbox-after.json
```

From the two inbox snapshots, count the jots this session added. Mined jots
carry the `mined` tag, and a subagent's also carry `subagent`. A correction
captured from a prompt carries `correction`. Then count how many of them ended
`promoted`, how many `dropped`, and how many are still `active` at the end.
The inbox cannot tell Stop-mined jots from PreCompact-mined ones, but the hook
log can: `doctor --hook-log` sums `mined` per event.

## What to count

| measure | where from | what it says |
|---|---|---|
| firings per hook | `doctor --hook-log` | how often each hook runs |
| spoke rate per hook | `doctor --hook-log` | how often it spent the agent's context |
| guard verdicts | `doctor --hook-log` | PROCEED / READ_FIRST / PAUSE / ASK_HUMAN spread |
| p95 ms per hook | `doctor --hook-log` | whether any hook is slow enough to feel |
| extraction turns (`capture` outcome `block`) | `doctor --hook-log` | how often Stop asked |
| extraction answers: record / reasoned no / empty | tally | whether asking was worth it |
| helped / noise / ignored per hook | tally | whether speaking was worth it |
| mined jots: promoted / dropped / left | inbox snapshots | whether mining finds anything |
| mined jots per hook | `doctor --hook-log` (`mined`) | which hook's mining finds anything |
| subagent jots promoted | inbox snapshots, tag `subagent` | question 2's evidence |
| `locked` firings | `doctor --hook-log` | parallel-session contention (skipped, not lost) |

## Turning counts into answers

**Question 1 (fatigue).** Fatigue shows up in the answers, not in the count.
Treat it as present when either is true:

- more than half of the extraction turns got an empty or boilerplate answer;
- an extraction turn fired after a turn with no commit and no new attempt jot,
  and the answer was empty. That means the `earned` rule in `_hook_capture`
  let a turn through that it should not have.

If neither is true, the extraction turn pays for itself at its current rate.

**Question 2 (SubagentStop blocking).** Blocking is worth trying only if
subagent-mined jots get promoted at a rate close to Stop-mined ones, **and**
those findings did not reach a record some other way. If subagent jots are
mostly dropped, mining alone is the right amount.

**Question 3 (PreCompact extraction).** Only if question 1 found no fatigue
and at least one compaction happened. The test: after the compaction, did the
post-compaction packet (the `session` hook, `outcome: context`) carry what the
session was doing? If yes, a second extraction turn at PreCompact buys little.

Also note anything the tally shows about guard. The relevance evals found that
`npm test` against a trap titled for it stays at PROCEED. A trap that matches
only on text cannot raise a verdict since the 0.1.10 field test. Whether that
cost a warning someone needed is a field question.

## Recording the result

- One decision record per question answered, with the numbers as its evidence
  (`crumb remember decision … --evidence note "field test <date>: …"`).
- `crumb mark-status q_should-the-extraction-turn-also-fire-on-precompa-ebd583
  answered --reason "field test <date>: …"` when question 3 has an answer.
- A session capture with the report attached under `--set "Decisions Made"`.

## Report template

```markdown
### Field test — <date>, <project>, <hours> h, <prompts> prompts

| hook | firings | spoke | p95 ms | helped | noise | ignored |
|---|---|---|---|---|---|---|
| session  | | | | | | |
| prompt   | | | | | | |
| guard    | | | | | | |
| capture  | | | | | | |
| compact  | | | | | | |
| subagent | | | | | | |

Guard verdicts: PROCEED _ / READ_FIRST _ / PAUSE _ / ASK_HUMAN _
Extraction turns: _ (record _ / reasoned no _ / empty _)
Mined jots: stop _ / compact _ / subagent _ / corrections _ → promoted _ / dropped _ / left _
Locked skips: _

Answers: (1) fatigue … (2) SubagentStop … (3) PreCompact …
```
