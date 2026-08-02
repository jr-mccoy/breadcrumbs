# fixtures

Sample `.project-memory/` stores and expected outputs for the evaluation suite.

All eleven are built and run in CI on every push (see the bottom of this file):

| Fixture | Exercises | Phase |
|---|---|---|
| 1 — Fresh resume | `resume` answers project/active/decided/failed/next/do-not-retry | **4 (built)** |
| 2 — Guard true positive | `guard` returns `PAUSE`/`READ_FIRST` on a real match | **5 (built)** |
| 3 — Guard false-positive control | `guard` returns `PROCEED` on a generic-word-only overlap | **5 (built)** |
| 4 — Stale handoff | staleness warning on aged / wrong-branch handoff | **5 (built)** |
| 5 — Superseded decision | superseded decision not treated as active | **5 (built)** |
| 6 — Secret leak | `audit` / `scan-secrets` fails on token-like string | **6 (built)** |
| 7 — Poisoned memory text | `audit` flags instruction-like text; `guard` treats it as data | **6 (built)** |
| 8 — Generated packet stale | `audit` flags resume packet older than its source records | **6 (built)** |
| 9 — Cloud fallback | plain files + generated packet support manual resume, no CLI | **6 (built)** |
| 10 — Many sessions | resume packet stays bounded with 100 session records | **6 (built)** |
| 11 — Multi-machine | a `distillate` store with no `sessions/` stays clean from two checkout paths | **6 (built)** |

Phase 1 created this directory and tracker. Phase 4 committed **Fixture 1**
(`fixture-01-fresh-resume/`), a hand-authored sample `.project-memory/` store that
`validate` passes and `resume` reduces to a packet answering the six reorientation
questions. Phase 5 committed **Fixtures 2–5** (`fixture-02-guard-true-positive/`,
`fixture-03-guard-false-positive/`, `fixture-04-stale-handoff/`,
`fixture-05-superseded-decision/`), each of which `validate` passes and which pin one
`guard` behaviour (true positive → `PAUSE`/`READ_FIRST`; false-positive control →
`PROCEED`; stale handoff → staleness warning; superseded → history-only).

Phase 6 (MVP-trust) committed **Fixtures 6–10**. Every fixture `validate`s clean —
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

**11 — Multi-machine** (`fixture-11-multi-machine/`) was added with the Batch 3
fixes (MF-06 … MF-10). It is the store the suite had no example of: `session_tracking:
distillate`, so `sessions/` is gitignored and **absent**, with a committed
`generated/resume-packet.md` and `guard-prefilter.json`, an `AGENTS.md` signpost, and
records that only reference project-relative paths. It exists to be checked out at two
different paths at once: `tests/test_multi_machine.py` copies it to two temp paths and
requires `validate`, `audit` and `doctor` to come up clean at both, the committed
packet to be accepted unchanged at either path, and a reindex on either machine to
reproduce the same bytes. Before Batch 3 every one of those failed.

All eleven run in CI on every push: `validate` over all eleven, `audit` over all
eleven (only Fixture 6 blocks), plus the guard / drift / instruction-like spot
checks.

> The fixture store is committed as canonical source. A `generated/resume-packet.md`
> produced by running `resume` against it is a rebuildable projection and is
> gitignored (CI regenerates it transiently) — **except** Fixtures 8, 9 and 11, which
> commit a packet on purpose (a stale one to exercise drift detection, an accurate one
> as the cloud-fallback artifact, and the one two machines must agree on).
