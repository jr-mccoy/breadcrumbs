# The continuity contract

What breadcrumbs promises a later session, what it does not, and where each
promise is tested. The promises are about *what is handed over*. What an agent
does with it is up to the agent.

## Promised

1. **Canonical, stable identity.**
   - Every durable record has one id, derived from its filename
     (`dec_YYYYMMDD_<slug>`, `att_…`, `ver_…`, `trap_<slug>`, `q_<slug>`).
   - Every surface uses the same id: the files, the CLI, MCP and the hooks.
   - An id never changes meaning. A replacement is a new record that names the
     old one (`supersedes`).
   - Tested by `tests/test_application_parity.py` (ids across transports) and
     by `test_cross_harness_resume_uses_same_records_and_rules`.
2. **Current means current.**
   - The resume packet, search, guard and the hooks present only live records:
     active and unexpired, and for questions, open.
   - A superseded, rejected, stale or quarantined record is history. It is
     never handed over as guidance.
   - Branch-scoped memory stays on its branch.
   - Tested by the critical eval cases (`evals/critical/`) and by the
     changed-decision and branch-switch replays
     (`docs/benchmarks/continuity-results.md`).
3. **Every surfaced record says why.**
   - A search result, prompt injection or guard warning carries its reasons:
     same file, same tag, shared keywords, named in the title, an explicit
     do-not-retry condition.
   - `crumb show <id>` prints the record, its evidence, and who wrote it,
     where and when.
4. **Bounded delivery.**
   - The packet stays within its declared budget (5,000 approx-tokens by
     default) and says what it left out.
   - The prompt injection is at most 5 records.
   - Tested by the delivery evals (`within_budget`).
5. **Correctable.** Anything wrong can be:
   - superseded (`remember … --supersedes`);
   - retired (`mark-status`);
   - quarantined;
   - demoted from a standing rule (`demote`).

   The record, and the reason it was retired, stay in history.
6. **Portable.**
   - The store is Markdown and YAML in the repository.
   - A reader without breadcrumbs can open it.
   - A second harness reading over MCP gets the same records, and the
     standing rules ride in its packet.
7. **Safe to share.**
   - Machine-local capture stays in `private/`.
   - `scan-secrets` reports secret-shaped strings in committed memory.
   - Record text is rendered as data, never as instructions to the reader
     (`security.md`).

## Not promised

- **Correctness of what was recorded.** Memory is what someone wrote, with
  the evidence they cited. A verification can be re-run (`crumb verify
  --recheck`) only when it carries an executable assertion.
- **That an agent reads or heeds it.**
  - Under Claude Code, the hooks deliver it.
  - Elsewhere, an agent must call the CLI or MCP.
  - A `PAUSE` asks the person; it does not block.
- **Authorization.** A guard verdict is advice. `PROCEED` means no relevant
  memory, not "safe".
- **Full facts in the packet.** The packet names a failed attempt and its
  do-not-retry condition. *Why* it failed is one `crumb show` away (a finding
  of the continuity replays).
- **Protection from an agent with a shell.** Review profiles bind MCP clients
  and hooks. An agent that can edit files can edit memory, and Git review is
  that boundary (`security.md` §4.2).
- **Hooks outside Claude Code** (`compatibility-matrix.md`).

## If a memory is wrong

1. `crumb show <id>`: read what it says, its evidence, and who wrote it.
2. Replace it: `crumb remember … --supersedes <id>`. Or retire it: `crumb
   mark-status <id> stale --reason "…"`. The reason is kept.
3. If it was promoted to a standing rule: `crumb demote <id>`. Retiring it
   demotes it too.
4. If it looks injected or hostile: `crumb mark-status <id> quarantined
   --reason "…"`. Like any retired record it is then not delivered, and a
   promoted rule from it is demoted. Under the `team` profile only a person
   can lift a quarantine; MCP cannot.
