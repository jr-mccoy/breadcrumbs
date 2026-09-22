# Open Questions

_Unresolved ambiguities and blockers. Remove or resolve each as it is answered._
_Aged-unresolved questions are surfaced by `resume`/`audit` as "is this still open?"_

<!-- Format suggestion (one block per question):

## Q: <the question in one line>
- Opened: <YYYY-MM-DD>
- Why it matters: <impact / what is blocked>
- Needs: <human input | investigation | a decision>
- Status: open
-->

## Q: Should the extraction turn also fire on PreCompact (memory extraction at the moment context is about to be destroyed)? Needs a field test of prompt fatigue first.
- Opened: 2026-08-15
- Status: open

## Q: Migrate this repo's own .project-memory store to schema 3?
- Opened: 2026-09-22
- Why it matters: crumb guard returned ASK_HUMAN for the migration during the Phase 2 session, so the store was left at schema 2; doctor reports schema-version until it runs
- Needs: human input
- Status: open
