# shared-service — agent guidance

House rules for anyone (human or agent) working in this repo.

<!-- >>> breadcrumbs managed block (managed by `crumb init`) — edit above/below, not inside >>> -->
## Project memory (breadcrumbs)

This repo has a durable memory store under `.project-memory/`. Use it:

- **Starting work / new session:** read the resume packet first —
  `crumb resume` (or MCP resource `memory://resume-packet`).
- **Before any risky or irreversible action** (deletes, force-push, schema
  or build-system changes, rewrites): `crumb guard "<action>"` and honor a
  `PAUSE` / `ASK_HUMAN` verdict.
- **After a durable decision or a failed approach:**
  `crumb remember decision|attempt …`.
- **After checking whether something is still true / fixed:**
  `crumb verify "<subject>" --status fixed|open|regressed|… --evidence …`.
- **Leaving a note for the next agent:** `crumb note question|trap|idea …`.
- **Session end:** `crumb capture session`.

Memory must never contain secrets; `crumb scan-secrets` gates commits.
<!-- <<< breadcrumbs managed block <<< -->
