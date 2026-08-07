# fixtures

Sample `.project-memory/` stores and expected outputs for the evaluation suite.

All twelve are built and run in CI on every push (see the bottom of this file):

| Fixture | Exercises |
|---|---|
| 1 — Fresh resume | `resume` answers project/active/decided/failed/next/do-not-retry |
| 2 — Guard true positive | `guard` returns `PAUSE`/`READ_FIRST` on a real match |
| 3 — Guard false-positive control | `guard` returns `PROCEED` on a generic-word-only overlap |
| 4 — Stale handoff | staleness warning on aged / wrong-branch handoff |
| 5 — Superseded decision | superseded decision not treated as active |
| 6 — Secret leak | `audit` / `scan-secrets` fails on token-like string |
| 7 — Poisoned memory text | `audit` flags instruction-like text; `guard` treats it as data |
| 8 — Generated packet stale | `audit` flags resume packet older than its source records |
| 9 — Cloud fallback | plain files + generated packet support manual resume, no CLI |
| 10 — Many sessions | resume packet stays bounded with 100 session records |
| 11 — Multi-machine | a `distillate` store with no `sessions/` stays clean from two checkout paths |
| 12 — Speculative idea | `search` finds an `ideas/` record; `guard` still returns `PROCEED` on it |

**Fixture 1** (`fixture-01-fresh-resume/`) is a hand-authored sample
`.project-memory/` store that `validate` passes and `resume` reduces to a packet
answering the six reorientation questions. **Fixtures 2–5**
(`fixture-02-guard-true-positive/`, `fixture-03-guard-false-positive/`,
`fixture-04-stale-handoff/`, `fixture-05-superseded-decision/`) each `validate`
clean and pin one `guard` behaviour (true positive → `PAUSE`/`READ_FIRST`;
false-positive control → `PROCEED`; stale handoff → staleness warning;
superseded → history-only).

**Fixtures 6–10** cover the trust surface. Every fixture `validate`s clean —
structure stays well-formed even where `audit` objects, which is the whole point of
the deterministic/heuristic split:

- **6 — Secret leak** (`fixture-06-secret-leak/`): a session record holds token-like
  strings (an AWS-style key id and a `password=` assignment). `validate` passes (no
  content scanning); `audit` and `scan-secrets` **block** (non-zero).
- **7 — Poisoned memory text** (`fixture-07-poisoned-text/`): a trap and an attempt
  body carry override phrasing ("ignore the tests", "never run …"). `audit` flags it
  as instruction-like (warning); `guard` surfaces the record as **data** and never
  lifts the imperative into its recommended action; `validate` stays clean.
- **8 — Generated packet stale** (`fixture-08-packet-stale/`): a committed
  `generated/resume-packet.md` carries a deliberately wrong `inputs_hash`, so `audit`
  flags drift / regeneration. (Its packet is committed via a `.gitignore` negation.)
- **9 — Cloud fallback** (`fixture-09-cloud-fallback/`): an accurate committed packet
  plus plain files answer the six reorientation questions with **no CLI**. Its packet
  is committed (negation) and its `inputs_hash` matches, so it is *not* drift-flagged.
- **10 — Many sessions** (`fixture-10-many-sessions/`): 100 session records; the
  resume packet stays within the 5,000-token budget, prioritises
  current/handoff/active-decisions, and never inlines a session transcript. `audit`
  emits a sessions-growth note.

**11 — Multi-machine** (`fixture-11-multi-machine/`) was added with the
multi-machine fixes. It is the store the suite had no example of: `session_tracking:
distillate`, so `sessions/` is gitignored and **absent**, with a committed
`generated/resume-packet.md` and `guard-prefilter.json`, an `AGENTS.md` signpost, and
records that only reference project-relative paths. It exists to be checked out at two
different paths at once: `tests/test_multi_machine.py` copies it to two temp paths and
requires `validate`, `audit` and `doctor` to come up clean at both, the committed
packet to be accepted unchanged at either path, and a reindex on either machine to
reproduce the same bytes. Before those fixes every one of those failed.

**12 — Speculative idea** (`fixture-12-speculative-idea/`) was added when `ideas/`
became searchable. Its only record is an untried hunch — "cache parsed sessions in the auth middleware", explicitly *not measured* — that
names `src/auth/middleware.ts` and carries the `auth`/`session` tags. That makes it
the control for the corpus split: `crumb search` must find it, and `crumb guard
"rewrite the auth middleware to cache parsed sessions" --files src/auth/middleware.ts`
must still answer `PROCEED` with **zero** matches. Scored in the lookup corpus the
same record clears the `READ_FIRST` band on file + tag + keyword, so the `PROCEED`
is the split doing the work rather than a weak fixture —
`tests/test_guard.py::SpeculativeIdeaTests` pins both halves.

All twelve run in CI on every push: `validate` over all twelve, `audit` over all
twelve (only Fixture 6 blocks), plus the guard / drift / instruction-like spot
checks.

> The fixture store is committed as canonical source. A `generated/resume-packet.md`
> produced by running `resume` against it is a rebuildable projection and is
> gitignored (CI regenerates it transiently) — **except** Fixtures 8, 9 and 11, which
> commit a packet on purpose (a stale one to exercise drift detection, an accurate one
> as the cloud-fallback artifact, and the one two machines must agree on).
