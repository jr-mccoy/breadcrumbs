# Breadcrumbs: Technical Audit and Implementation Roadmap

**Prepared for:** Jeremy McCoy  
**Review date:** September 26, 2026  
**Repository:** `jr-mccoy/breadcrumbs`  
**Audited commit:** `30e41f6a36195faffdc197d0565abc7caf7c78da`  
**Package / record schema:** `crumb-kit 0.3.0` / schema `4`  
**Status:** Source-grounded audit and proposed implementation plan. No product changes have been applied.

> **For agentic workers:** Read Sections 1-6 before selecting a work package in Section 8. Execute one dependency-ready package at a time. Use test-driven development and verification before claiming completion; use the equivalent Superpowers execution workflow when it is available. This document is not permission to publish a release, change repository permissions, delete memory, or perform an unapproved schema migration.

**Goal:** Make Breadcrumbs a dependable, inspectable continuity system that preserves the meaning and scope of project knowledge, retrieves it when needed, and demonstrates its value with reproducible evidence.

**Architecture:** Keep human-readable, repository-local records authoritative. Improve the existing implementation through bounded repairs, a shared admission/validation path, coherent snapshots, indexed retrieval, and explicit adapter contracts. Do not replace the project with a mandatory database service, an opaque embedding store, or a large rewrite.

**Tech stack:** Existing Python package and standard-library baseline; optional MCP integration; Markdown plus the documented frontmatter subset; Git; disposable SQLite acceleration. Preserve the declared Python floor unless a separately approved compatibility decision changes it.

**Spec:** Sections 5-7 of this document are the proposed target design and acceptance requirements. Section 8 translates that design into work packages. The audit findings establish the evidence; proposed interfaces and targets are not claims about features already present.

---

## Contents

1. [Executive assessment and immediate priorities](#section-1)
2. [Review method, evidence, and limitations](#section-2)
3. [Corrections to the earlier chat review](#section-3)
4. [Detailed findings](#section-4)
5. [Target design and non-negotiable invariants](#section-5)
6. [Compatibility, migration, and failure recovery](#section-6)
7. [Evaluation and qualification program](#section-7)
8. [Dependency-ordered implementation work packages](#section-8)
9. [Release gates and a credible public launch](#section-9)
10. [Coding-agent execution protocol](#section-10)
11. [Evidence inventory and source references](#section-11)

---

<a id="section-1"></a>

## 1. Executive assessment

**The right next step is a reliability program, not a feature explosion.** Breadcrumbs already has the right central idea: project continuity belongs in inspectable records, with rebuildable retrieval and presentation layers above them. Decisions, failed attempts, verifications, traps, questions, and speculative notes should not all have the same evidentiary status. Preserve that differentiation.

The implementation is substantially more developed than a simple memory prototype. However, this review reproduced failures at the boundaries that determine whether memory deserves to be trusted: an unfinished test becoming a "passed" candidate; a promoted note losing its actual content; a branch-local finding becoming project-wide; a packet receiving a current hash for content it never read; and retrieval silently disappearing as the store grows.

These are fixable engineering problems. They also change the priority order from the earlier conversational review. A new approval workflow, semantic search, or architectural refactor should not displace repairs to **what gets remembered, whether it remains scoped correctly, and whether a consumer is told the truth about what it received**.

### 1.1 What to preserve

Keep the plain-file source of truth, explicit record taxonomy, negative knowledge, status/supersession history, local-only mined candidates, branch provenance, deterministic lexical baseline, optional integrations, and disposable indexes. Keep the existing tests and synthetic relevance suites. The package's zero-third-party-runtime-dependency baseline and its optional MCP layer are deliberate advantages, not deficiencies to remove merely to appear sophisticated.

The architecture and package metadata document these choices. The current CI also exercises multiple Python versions and both supported MCP SDK major ranges. See [architecture](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/docs/architecture.md), [package metadata](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/pyproject.toml), and [CI configuration](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/.github/workflows/ci.yml).

### 1.2 Immediate sequence

| Sequence | Outcome | Principal findings |
|---|---|---|
| First | Stop inventing success and losing meaning during capture/promotion/recheck | F01-F05 |
| Next | Make mutations and projections honest under failure and concurrency | F06-F08, F20 |
| Next | Restore reliable retrieval, guard coverage, portable packets, and bounded output | F09-F16 |
| Alongside these repairs | Contain paths, define real trust boundaries, and qualify supported adapters | F17-F19, F22, F25 |
| Before a broader reliability claim | Publish reproducible evaluations, platform results, and a small independently repeatable demo | F21, F23-F26 |

**Do not advertise "safe autonomous memory" on the strength of a green test badge alone.** A green baseline currently coexists with a known unsafe-command miss. Instead, describe exactly which guarantees are implemented and tested, on which platforms and harness versions.

### 1.3 Priority definitions

**P1** means fix before presenting the affected behavior as dependable for unattended or multi-agent use. It does not mean a remotely exploitable emergency has been demonstrated. **P2** means important hardening, usability, or maintainability work for the stabilization program. **P3** means a gated experiment or later extension, not an obligation to implement now.

No P0 incident is asserted. Security findings include their prerequisites and limits. "World-class" is a target to establish through evidence, not a rating awarded by this report.

<a id="section-2"></a>

## 2. Review method, evidence, and limitations

### 2.1 What was actually inspected and exercised

The review pinned `main` to the commit above, inspected the package's source, relevant tests, documentation, memory records, and workflow results, and retrieved the release workflow's `dist` artifact. The **21 Python package modules in the release source distribution matched the Git blob hashes returned for the pinned source tree**. The source manifest records each module's hash, byte count, and line count.

Local execution used **Python 3.13.5 on Linux**. Diagnostic stores were temporary and synthetic. No real credentials were used, no user repository was modified, and no product implementation was changed. The replay probe executed only a harmless Python no-op. The path-containment probe read only an intentionally created synthetic file outside its temporary project.

The source distribution is **not a complete Git checkout**. It omits some repository-only fixtures, helpers, workflows, and evaluation assets. An audit-only root `crumb.py` compatibility shim delegated to the unchanged package so selected existing tests could run. This limitation is recorded rather than hidden.

### 2.2 Results and what they mean

| Evidence | Observed result | Interpretation |
|---|---|---|
| Package source identity | 21/21 package module hashes match the pinned Git tree | Local probes exercised the reviewed implementation |
| Diagnostic probes | 19 probes completed; all 19 produced their specified defect signal; no probe setup errors in the final run | Reproductions of particular behaviors, not 19 independent security vulnerabilities |
| Selected upstream tests | 243 tests passed | A meaningful existing-test subset, not the entire upstream suite |
| Initial wider local attempt | 248 attempted: four missing-fixture errors and one interpreter-startup assumption failure | Recorded environmental/source-distribution limitations; not classified as five product regressions |
| Remote CI | GitHub reported success for run `36083137724`; all 19 returned jobs succeeded | Remote evidence at this exact commit, not a claim of local execution |
| Release workflow | GitHub reported success for run `36083177179`, attempt 2 | Confirms a successful reported release workflow, not blanket product qualification |
| Retrieval evaluations | 39 synthetic tasks; the successful eval job still reported `npm test` -> `PROCEED` | Regression baseline is not an absolute correctness gate |

The interpreter-startup test expected certain standard-library modules not to be loaded. They were already present **before importing Breadcrumbs** in this environment. That precondition failure is separately captured in `environment-startup.txt`; it is not attributed to the package.

Evidence is under [`2026-09-26-breadcrumbs-evidence/`](2026-09-26-breadcrumbs-evidence/). The original wider test log is retained alongside the successful selected run. The probe script is [`tools/audit/regression_probes.py`](../../tools/audit/regression_probes.py).

### 2.3 Evidence labels used below

**Reproduced** means the behavior occurred in a local synthetic case. **Controlled fault** means the review deliberately injected an interleaving, clock gap, or failure return to test the corresponding code path; it is not a claim that an OS-level stress test naturally produced that event. **Source-confirmed** means the relevant implementation path was inspected but the full operating scenario was not exercised. **CI-reported** identifies observations from GitHub's run or job output. **Proposal** identifies a design or product recommendation.

### 2.4 Explicit limits

This was not a comprehensive penetration test, a formal concurrency proof, a power-loss test, or a live multi-harness field study. The review did not independently rerun the complete fixture/evaluation/MCP matrix, test native Windows or macOS behavior, or establish production latency percentiles. Network filesystems, antivirus interference, real process suspension, real transcript rotation across host upgrades, and end-to-end model behavior still need qualification.

The report is complete as an **audit and executable roadmap for the reviewed scope**, not a guarantee that no other defect exists. Future agents must revalidate findings against the revision they actually modify.

<a id="section-3"></a>

## 3. Corrections to the earlier chat review

The earlier review was useful orientation, but several recommendations need refinement before becoming engineering instructions.

**Approval should not become a universal human bottleneck.** The user wants useful agentic memory. Routine capture can remain autonomous within a configured policy. Human review is most important for authority-changing and high-impact writes. Existing `review_status` and `reviewed_by` metadata should be evaluated before inventing another parallel lifecycle. A review label by itself is not proof that a human approved anything.

**CLI-only promotion is not a security boundary against an agent with shell access.** Removing an MCP endpoint reduces one interface, but an agent allowed to run `crumb promote` or edit `AGENTS.md` directly still has that capability. Strong enforcement requires a boundary outside the agent's own writable files and credentials.

**The 500-record cutoff counts retired candidates too.** The reproduction used only one active decision plus 500 stale decisions. The issue is worse than "more than 500 live memories" and should not be repaired by hiding history or deleting it to stay below a cap.

**Keep the existing guard exit-code contract by default.** Its integration cost is real, but changing it casually would break scripts and tests that already depend on it. Add a documented opt-in ergonomic mode only after contract tests and compatibility review; do not conflate this with fixing guard reasoning.

**Do not impose a blanket ban on LLM-assisted extraction or embeddings.** Keep deterministic parsing, provenance, admission, and the lexical baseline. An optional model may propose candidates or retrieval candidates when measured benefits justify it. It must not silently create authority, declare a test passed, or resolve factual contradictions.

**Current CI and release status were verified.** Both reported success at the audited revision. The concern is not an unverified assertion that the build is red; it is that existing passing tests do not cover the newly reproduced behaviors, and the evaluation baseline tolerates known misses.

**The prompt prefilter needs the right data, not merely a different empty-file test.** A guard-specific token index is not an adequate general "does this store have relevant memory?" summary. Do not fix `_store_has_content` by checking only whether trap tokens exist; that would suppress valid decision-only stores.

The source evidence for these corrections is given in F09-F12, F18-F19, and F24. Where this document differs from the prior chat review, use this document's qualified, evidence-grounded conclusion.

<a id="section-4"></a>

## 4. Detailed findings

The findings below distinguish actual broken behavior from architecture and product work. Each one identifies its repair intent and the test that must demonstrate completion. The proposed internal contracts are in Section 5; work-package dependencies and implementation steps follow in Section 8.

### Finding index

F01-F08 concern capture truth and storage consistency. F09-F16 concern what an agent actually receives. F17-F20 concern trust and failure boundaries. F21-F26 concern maintainability, integration, qualification, and adoption.

| Finding | Priority | Evidence category |
|---|---|---|
| [F01. Incomplete or misread tool results become successful verification candidates](#f01) | P1 | Reproduced |
| [F02. The transcript cursor can freeze on a sliding tail and lose cross-window state](#f02) | P1 | Reproduced and source-confirmed |
| [F03. Jot promotion can discard the actual note and silently broaden its meaning](#f03) | P1 | Reproduced |
| [F04. Verification replay confuses successful execution with proof and loses branch scope](#f04) | P1 | Reproduced |
| [F05. Validation admits malformed evidence and risky metadata defaults](#f05) | P1 | Reproduced |
| [F06. Full resume writes despite an existing writer lock](#f06) | P1 | Reproduced |
| [F07. A projection can be stamped with a current hash for records it did not include](#f07) | P1 | Controlled fault reproduced |
| [F08. Heartbeat age can classify a live lock holder as stale](#f08) | P1 | Controlled fault reproduced |
| [F09. Prompt retrieval stops above 500 candidates, even when nearly all are retired](#f09) | P1 | Reproduced |
| [F10. Short meaningful prompts and known hazardous commands can pass through the wrong gates](#f10) | P1 | Reproduced and CI-reported |
| [F11. An absent or unreadable guard prefilter is treated as no memory risk](#f11) | P2 | Source-confirmed |
| [F12. The metadata freshness shortcut can miss a valid same-size edit](#f12) | P2 | Reproduced |
| [F13. Promoted records disappear from a packet even when their rule is unavailable to its reader](#f13) | P1 | Reproduced |
| [F14. The advertised packet bound does not hold for large protected sections](#f14) | P1 | Reproduced |
| [F15. Compaction can retain an older matched task instead of the latest user task](#f15) | P2 | Reproduced |
| [F16. Usage counters can count content that was not delivered](#f16) | P2 | Reproduced and source-confirmed |
| [F17. A memory symlink can expose content outside the configured project](#f17) | P1 | Reproduced |
| [F18. Review metadata and interface separation do not establish an authority boundary](#f18) | P1 | Source-confirmed and proposed requirement |
| [F19. Evaluation gates do not measure the whole delivered experience or require critical correctness](#f19) | P1 | Source-confirmed and CI-reported |
| [F20. A failed retirement can leave two live decisions while the writer reports success](#f20) | P1 | Controlled fault reproduced |
| [F21. The CLI remains the domain kernel, making independent contracts difficult to maintain](#f21) | P2 | Source-confirmed |
| [F22. Platform and harness coverage is narrower than the portability ambition](#f22) | P1 | Reproduced, source-confirmed, and CI-reported |
| [F23. Full rebuilds and pairwise enrichment make capture cost grow unnecessarily](#f23) | P2 | Measured smoke behavior and source-confirmed |
| [F24. Documentation, compatibility rules, and the dogfood handoff need reconciliation](#f24) | P2 | Source-confirmed and CI-reported |
| [F25. Replay execution needs bounded output and process-tree cleanup, not just a timeout](#f25) | P2 | Source-confirmed |
| [F26. Public credibility needs demonstrated task outcomes, not more feature names](#f26) | P2 | Proposal grounded in the current evaluation scope |

## 4A. Capture, meaning, and storage correctness

<a id="f01"></a>

### F01. Incomplete or misread tool results become successful verification candidates

**Priority:** P1 | **Evidence:** Reproduced


**Observed.** A `Bash` tool call with no result produced `pytest passed`. A failure after 450 characters of output also produced a "passed" candidate. Conversely, `15 passed, 0 failed` was treated as a failure and produced no success candidate. When a failed result arrived in the next mining window, it did not repair the earlier false success.

**Cause.** Missing results initialize `is_error=False`; absence of a failure is then interpreted as success. Output is reduced to a 400-character snippet before textual failure detection. A broad failure-word regex cannot distinguish a failure count of zero from an actual failure. Pairing is local to the current mining slice.

**Required change.** Model `success`, `failure`, `unknown`, and `interrupted` separately, with an explicit `result_received` flag. Prefer structured completion/exit information from the adapter. Extract bounded display snippets only after outcome classification. An unrecognized result remains unknown. Use neutral wording such as "command observed" when success is not established; do not infer that an edit caused a later pass.

**Completion test.** Missing and interrupted results never generate "passed" or "fixed" language; failures beyond the display cutoff remain failures; zero-failure summaries are not false negatives; a delayed result joins its pending call exactly once. Private, low-confidence storage mitigates the current damage, but does not make an incorrect candidate acceptable.


**Evidence locations:** [breadcrumbs/transcript.py:150-201](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/transcript.py#L150-L201); [breadcrumbs/transcript.py:330-407](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/transcript.py#L330-L407). Local probe: `transcript_results, split_pair`.

<a id="f02"></a>

### F02. The transcript cursor can freeze on a sliding tail and lose cross-window state

**Priority:** P1 | **Evidence:** Reproduced and source-confirmed


**Observed.** A transcript larger than the 8 MB read window returned 15 complete tail entries. After a new correction was appended, the next tail also contained 15 entries. The stored cursor remained 15, so mining selected an empty slice even though the new correction was present. The second run reported no writes and no skipped work.

**Cause.** The cursor counts entries relative to a moving tail, then monotonically preserves that count as though it were an absolute append position. Calls and results spanning firings are not joined. Mining also advances past the whole read slice after bounded candidate selection, so cap/drop and write-failure semantics need an explicit accounting policy.

**Required change.** Use a cursor with file identity, absolute byte position, incomplete-line handling, and pending tool-call state. Distinguish bytes consumed from candidates durably acknowledged. Handle file replacement, truncation, host-session changes, partial trailing JSON, and exhausted mining budgets explicitly. Keep a bounded backlog or disclose a deliberate drop; never silently claim the unseen portion was processed.

**Completion test.** Append across the tail threshold repeatedly; each eligible new event is considered once. Split call/result pairs, partial writes, rotation, a crash between jot creation and cursor commit, and candidate caps must not create false success, permanent blindness, or unbounded duplicate capture.


**Evidence locations:** [breadcrumbs/transcript.py:58-87](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/transcript.py#L58-L87); [breadcrumbs/transcript.py:484-502](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/transcript.py#L484-L502); [breadcrumbs/transcript.py:595-632](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/transcript.py#L595-L632); [breadcrumbs/hooks_common.py:129-156](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/hooks_common.py#L129-L156). Local probe: `sliding_cursor, split_pair`.

<a id="f03"></a>

### F03. Jot promotion can discard the actual note and silently broaden its meaning

**Priority:** P1 | **Evidence:** Reproduced


**Observed.** A private, branch-scoped jot contained a concrete cache-invalidation instruction and a short title. Promoting it to a decision without explicit replacement sections succeeded, but the durable record contained only an empty Context stub. The substantive note was absent. Its scope became `project`, its confidence became `medium`, and the original jot was marked superseded.

**Impact.** The local source jot remains on disk, so this is not deletion of every copy. It is loss of content in the promoted/shared representation, precisely the record future sessions are expected to rely on. Scope and confidence changes compound the problem.

**Required change.** Promotion must be a meaning-preserving transformation unless the caller explicitly supplies a replacement. Carry the original text into an appropriate section or a provenance-preserving Notes section; inherit scope and confidence without elevation; retain the source jot ID and content digest. Require explicit authorization for widening scope or sharing private content. Route promotion through the same validation, deduplication, privacy, and transaction path as other durable writes.

**Completion test.** Promote each supported target with and without sections, from private and shared jots, with branch/project scope. Assert complete semantic text retention, source linkage, unchanged scope/confidence by default, duplicate-gate parity, and no retirement on a failed target write.


**Evidence locations:** [breadcrumbs/inbox.py:341-497](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/inbox.py#L341-L497). Local probe: `jot_promotion_loss`.

<a id="f04"></a>

### F04. Verification replay confuses successful execution with proof and loses branch scope

**Priority:** P1 | **Evidence:** Reproduced


**Observed.** Rechecking a branch-scoped open finding whose only command was a Python no-op created a project-scoped `fixed` verification. The command really exited zero; it did not test the alleged authentication defect.

**Cause.** Replay maps all-zero exit codes to `fixed` and any failure to `open`, while failing to pass the original scope to the new verification. A command/test evidence pointer is not necessarily an executable assertion about the subject. A test-file reference may not even be a runnable command.

**Required change.** Preserve scope, subject identity, provenance, and confidence. Separate execution status from finding status. Legacy diagnostic commands can produce an execution observation, but may not automatically settle a claim. A declared assertion must identify what it checks, its expected result, relevant platform/context, and the claim it can settle. Unavailable tools, timeouts, and malformed replay specs are inconclusive, not proof that the original bug is open or fixed.

**Completion test.** A successful no-op does not close the subject; a declared regression assertion can settle its bound claim; dependency failure stays inconclusive; branch scope survives every replay path. Preserve the existing consent/preview requirement and the absence of an unattended MCP replay endpoint.


**Evidence locations:** [breadcrumbs/lifecycle.py:348-420](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/lifecycle.py#L348-L420); [breadcrumbs/lifecycle_cmds.py](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/lifecycle_cmds.py). Local probe: `recheck_scope_and_claim`.

<a id="f05"></a>

### F05. Validation admits malformed evidence and risky metadata defaults

**Priority:** P1 | **Evidence:** Reproduced


**Observed.** Per-record validation accepted `confidence: certainly`, `scope: all-machines`, an evidence mapping with no meaningful `type` or `ref`, an invalid expiry value, and a superseded record pointing to a nonexistent ID. The packet builder returned rather than rejecting these records.

**Cause.** Important checks establish presence or truthiness, not a sufficiently strong validation contract. Free-text scope is explicitly documented as accepted and interpreted as project-wide; that is a risky compatibility policy, not an undocumented parser defect. In particular, any nonempty evidence container can satisfy the evidence-or-low-confidence rule. Requiring a nonempty `superseded_by` string does not establish referential integrity.

**Required change.** Introduce shared typed validation before admission and on reads: vocabularies; nonempty correctly shaped evidence; parseable timestamps; permitted scopes; field types; controlled size/depth limits; and reference validation. Reject self-supersession and cycles. Where an intentional external reference is supported, give it an explicit namespace rather than silently accepting a missing local ID. A valid evidence reference still does not prove the claim; record syntax validation must not be described as factual verification.

**Completion test.** The demonstrated invalid values yield stable finding codes. One malformed record cannot silently disable an entire hook. Legacy invalid stores get a diagnostic/migration report, not destructive auto-correction or automatic confidence upgrades.


**Evidence locations:** [breadcrumbs/cli.py:1497-1510](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L1497-L1510); [breadcrumbs/cli.py:1549-1855](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L1549-L1855); [docs/record-schema.md:210-307](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/docs/record-schema.md#L210-L307). Local probe: `schema_types`.

<a id="f06"></a>

### F06. Full resume writes despite an existing writer lock

**Priority:** P1 | **Evidence:** Reproduced


**Observed.** With a live foreign process represented as the current lock owner, `crumb resume --json` returned successfully and replaced the generated packet. The foreign lock remained in place.

**Cause.** `_needs_lock` exempts resume because its writes are described as atomic projections. Full resume nevertheless invokes reindexing, which publishes several files and may enter other maintenance paths. Per-file atomic replacement prevents a torn individual file; it does not serialize a multi-file generation or a read-modify-write operation. The SQLite builder also uses one fixed `.tmp` filename.

**Required change.** Separate building/printing a view from publishing projections. Every publication and canonical maintenance mutation must honor the writer coordination policy. Read paths should remain responsive by returning a coherent existing or freshly read snapshot with explicit freshness/consistency information, not by bypassing write coordination. Give each build a unique temporary path and keep index replacement inside the publication contract.

**Completion test.** A resume during another writer's transaction performs no uncoordinated shared writes, remains bounded in latency, and reports its view state accurately. Exercise two reindex processes, resume plus migration, and a concurrent index rebuild.


**Evidence locations:** [breadcrumbs/cli.py:3720-3790](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L3720-L3790); [breadcrumbs/cli.py:7095-7136](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L7095-L7136); [breadcrumbs/cli.py:13211-13245](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L13211-L13245); [breadcrumbs/searchindex.py:128-219](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/searchindex.py#L128-L219). Local probe: `resume_ignores_lock`.

<a id="f07"></a>

### F07. A projection can be stamped with a current hash for records it did not include

**Priority:** P1 | **Evidence:** Controlled fault reproduced


**Observed.** The probe inserted a valid decision after packet inputs had been read but immediately before the input hash was computed. The packet omitted the new decision while its `inputs_hash` matched the current store including that decision.

**Cause.** Content selection and provenance hashing read mutable state separately. An input hash computed later cannot certify the bytes used earlier. Validation that compares only that stamp can accept this inconsistent projection.

**Required change.** Build every projection from a single immutable input representation and hash exactly those bytes. Separate the canonical snapshot ID from view-specific context such as branch, HEAD, query, time, budget, and consumer capabilities. Publish a manifest with output digests only after all files for a generation are ready. A reader must detect a mixed generation, rather than treating each individually atomic file as a coherent set.

**Completion test.** Inject writes before, between, and after input reads and hash calculation. The result must either represent the old snapshot, represent the new snapshot, or disclose/retry the unstable read. It must never assert that an omitted input was incorporated.


**Evidence locations:** [breadcrumbs/cli.py:6415-6464](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L6415-L6464); [breadcrumbs/cli.py:6521-6750](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L6521-L6750); [breadcrumbs/cli.py:3720-3772](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L3720-L3772). Local probe: `snapshot_stamp_race`.

<a id="f08"></a>

### F08. Heartbeat age can classify a live lock holder as stale

**Priority:** P1 for the multi-writer guarantee | **Evidence:** Controlled fault reproduced


**Observed.** While the current process held the store lock, an injected 65-second wall-clock/heartbeat gap made `_is_stale` return true despite the owner still being alive. This tests the actual decision logic; it is not an OS suspension stress test.

**Cause.** Age is checked before live-owner evidence. A suspended process, a missed heartbeat, or a wall-clock jump can therefore permit lock stealing while the original writer may later resume. PID/host identity alone is also weaker than an ownership generation for release/fencing decisions.

**Required change.** Prefer OS-held local locks on supported local filesystems, retaining the in-process thread lock and re-entrancy. An OS lock can be released when the process exits without depending on a heartbeat lease. A lease-based fallback must use ownership tokens and prevent an old holder from publishing after losing ownership. Do not claim arbitrary shared-filesystem safety; qualify or explicitly exclude network/synchronization filesystems.

**Completion test.** Demonstrate mutual exclusion with real processes, process termination, delayed/suspended holders where supported, clock changes, stale-breaker contention, nested acquisition, and cleanup that never releases a newer owner's lock. Merely increasing the timeout is not a correctness repair.


**Evidence locations:** [breadcrumbs/lock.py:97-231](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/lock.py#L97-L231). Local probe: `live_lock_stale`.

## 4B. Retrieval, guard behavior, and delivered context

<a id="f09"></a>

### F09. Prompt retrieval stops above 500 candidates, even when nearly all are retired

**Priority:** P1 | **Evidence:** Reproduced


**Observed.** With one active relevant decision and 500 stale decisions, the SQLite index built normally and direct search found the relevant decision. `hooks_prompt.retrieve` returned nothing. A separate timing probe showed the same discontinuity between 500 and 501 records.

**Cause.** The hook loads the entire candidate set before enforcing `PROMPT_HOOK_MAX_CORPUS=500`. Historical entries count against the limit. This both pays much of the full-read cost and prevents the existing index from helping the hook at the very scale where it is useful.

**Required change.** Remove the all-or-nothing corpus-size gate. Use indexed candidate discovery and eligibility filters without first constructing the full corpus. Bound work or output by explicit budgets and disclose a partial/degraded result. Keep exact full-search equivalence separate from any intentionally bounded hook view. Do not delete old records to stay below a limit.

**Completion test.** Stores at 199/200/201 and 499/500/501 records, 1,000 records, and a larger stress tier must preserve relevant eligible hits. Repeat with mostly retired/expired/other-branch records, missing/corrupt indexes, filter-only queries, and aliases.


**Evidence locations:** [breadcrumbs/hooks_prompt.py:38-105](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/hooks_prompt.py#L38-L105); [breadcrumbs/cli.py:8067-8106](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L8067-L8106); [breadcrumbs/searchindex.py](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/searchindex.py). Local probe: `prompt_cliff`.

<a id="f10"></a>

### F10. Short meaningful prompts and known hazardous commands can pass through the wrong gates

**Priority:** P1 | **Evidence:** Reproduced and CI-reported


**Observed.** Direct retrieval found a decision for the short prompt `quasar`, but the actual prompt hook returned nothing because the prompt was shorter than 12 characters. A trap explicitly describing destructive `npm test` behavior was retrieved by direct guard, yet the verdict remained `PROCEED`; the tool hook also stayed silent. The successful upstream eval job independently reported its `npm test` case as `PROCEED`.

**Cause.** Character length is used as a proxy for an acknowledgment. Separately, short-query/title relevance, verdict specificity, and the prefilter's two-specific-token rule are not the same contract. Fixing retrieval alone does not fix the delivered warning or verdict.

**Required change.** Recognize a small, tested acknowledgment vocabulary rather than suppressing all short prompts. Give an exact known command hazard a narrowly defined surfacing rule; preserve stance and permission-mode boundaries so an ordinary matching topic does not become a blanket block. Make the prefilter a conservative candidate selector: it must not exclude a command the full policy would warn about. `PROCEED` must be explained as "no applicable memory warning found," never authorization or a general safety certificate.

**Completion test.** Exercise `npm test`, `pytest`, short package names, abbreviations, safe diagnostic controls, a hazard's documented remedy, and the complete hook path. Assert useful warning delivery for the known hazard without restoring the previous flood of unrelated warnings.


**Evidence locations:** [breadcrumbs/hooks_prompt.py:31-36](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/hooks_prompt.py#L31-L36); [breadcrumbs/hooks_prompt.py:185-231](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/hooks_prompt.py#L185-L231); [breadcrumbs/cli.py:8150-8315](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L8150-L8315); [breadcrumbs/cli.py:8503-8569](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L8503-L8569); [breadcrumbs/cli.py:11319-11345](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L11319-L11345). Local probe: `guard_prefilter, short_prompt_and_stale_task`.

<a id="f11"></a>

### F11. An absent or unreadable guard prefilter is treated as no memory risk

**Priority:** P2, elevated for affected guarded workflows | **Evidence:** Source-confirmed


The prefilter returns false when its file is missing, malformed, or unreadable. It does not establish a source-generation match before relying on the token/path set. For a routine-shaped command that depends on a recorded trap to trigger a full check, this can turn an unavailable acceleration artifact into silence.

A disposable index should change cost, not covertly remove the underlying capability. Use a verified generation, a conservative fallback, or an explicit degraded-state advisory. A cache miss is not evidence that the canonical store has no hazard. Do not solve this by demanding a human prompt on every cache failure; keep the ordinary host permission flow and distinguish a memory-system fault from an action verdict.

**Completion test.** Corrupt, remove, stale, and replace the prefilter between publication and a tool call. A relevant canonical hazard is still considered, or the consumer is told that the guard did not complete. An unrelated action remains quiet when a valid check actually finds no warning.


**Evidence locations:** [breadcrumbs/cli.py:3688-3717](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L3688-L3717); [breadcrumbs/cli.py:11319-11345](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L11319-L11345); [breadcrumbs/cli.py:11594-11628](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L11594-L11628).

<a id="f12"></a>

### F12. The metadata freshness shortcut can miss a valid same-size edit

**Priority:** P2 | **Evidence:** Reproduced


**Observed.** After building an index over 201 valid records, the probe changed one word in a valid record body to another same-length word and restored its mtime. The index reported `fresh`. Indexed search missed the new word; the full scan found it. The record's filename and ID remained valid.

**Cause.** Equal path/size/mtime metadata immediately returns fresh without checking content. This is a useful optimization under limited assumptions, but it is not the advertised unconditional indexed/full-scan equivalence guarantee.

**Required change.** Initially prefer the existing content-hash check over the unsafe shortcut, then measure the actual cost. Future fast paths must have an explicit consistency model tied to cooperating writers or verified content generations; adding ctime/inode is an improvement, not a cryptographic proof. Version index formats when tokenization, aliases, eligibility, or freshness semantics change. A digest establishes content identity, not authorship or trust.

**Completion test.** Same-size/restored-mtime edits, atomic replacements, changed aliases, checkouts, malformed metadata, and old index versions must not produce different full-search results under the promised strict mode. Any weaker fast mode must identify its weaker guarantee rather than quietly claiming exact equivalence.


**Evidence locations:** [breadcrumbs/searchindex.py:83-125](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/searchindex.py#L83-L125); [breadcrumbs/searchindex.py:232-347](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/searchindex.py#L232-L347). Local probe: `index_metadata_collision`.

<a id="f13"></a>

### F13. Promoted records disappear from a packet even when their rule is unavailable to its reader

**Priority:** P1 for portable continuity | **Evidence:** Reproduced


**Observed.** A decision was promoted into an existing `CLAUDE.md`; the adapter file was then removed. The active decision still disappeared from `active_decisions` in the generated packet, which merely reported a promoted count. The same assumption is problematic for a consumer that reads the packet but never loads that particular agent instruction file.

**Cause.** Packet elision follows `promoted_to` metadata, not evidence that this consumer received the corresponding current rule. An audit warning about adapter drift does not restore omitted content to that consumer.

**Required change.** Portable packets must include the effective rule or an explicit, useful rule reference by default. Only a harness-specific view may elide redundant content, and only when it has a verified loaded-rule capability/digest for that session. Preserve the full record and source reference; promotion is an additional delivery channel, not a reason to make memory disappear elsewhere.

**Completion test.** Missing/stale adapter, CLAUDE-only promotion consumed by another harness, demotion, a read-only clone, and explicit loaded-rule acknowledgment all produce the intended coverage without uncontrolled duplicate context.


**Evidence locations:** [breadcrumbs/cli.py:6570-6635](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L6570-L6635); [breadcrumbs/promote.py:276-348](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/promote.py#L276-L348); [breadcrumbs/promote.py:399-404](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/promote.py#L399-L404). Local probe: `promoted_adapter_missing`.

<a id="f14"></a>

### F14. The advertised packet bound does not hold for large protected sections

**Priority:** P1 for the bounded-context contract | **Evidence:** Reproduced


**Observed.** A large Current Focus produced a packet of 7,333 approximate tokens despite a configured maximum of 5,000. No actual model tokenizer was involved; the implementation exceeded its own estimate.

**Cause.** Trimming targets list sections and eventually stops, while core singleton content can remain arbitrarily large. In addition, `len(text)/4` is a heuristic, not a universal token count, and different output surfaces have different framing overhead.

**Required change.** Bound the final serialized view, including headings, warnings, protected sections, and adapter wrappers. Preserve canonical text intact; use explicitly marked excerpts and source pointers when a view must be shorter. Name the estimator and budget unit. Offer optional exact tokenizer accounting for a declared consumer, but do not advertise an all-model token guarantee from a character heuristic. Apply a separate explicit contract to fast and JSON views.

**Completion test.** Long focus/next-action fields, huge titles, warning-heavy stores, Unicode/code-heavy text, promoted rules, and tiny budgets terminate predictably and stay within the declared view budget. The result discloses omissions instead of silently corrupting or deleting canonical information.


**Evidence locations:** [breadcrumbs/cli.py:5510-5512](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L5510-L5512); [breadcrumbs/cli.py:6877-6913](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L6877-L6913); [breadcrumbs/cli.py:6934-7092](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L6934-L7092). Local probe: `packet_bound`.

<a id="f15"></a>

### F15. Compaction can retain an older matched task instead of the latest user task

**Priority:** P2 | **Evidence:** Reproduced


**Observed.** The prompt hook saved an amber-quasar task that matched memory. A later, unrelated calendar-design task matched nothing. Session state still reported the quasar task as `last_prompt`.

**Cause.** Updating the latest task is conditional on retrieval success. The state used for continuity is therefore the last successful retrieval query, not necessarily the latest user intent.

**Required change.** Separate latest-task state from latest-retrieval state. Update the former for substantive prompts before retrieval/no-match exits, while preserving explicit handling for acknowledgments, slash-command expansion, and session forks. Record provenance and timestamp without turning raw user prose into a durable instruction. Privacy policy should control local retention of this text.

**Completion test.** Matched task A followed by no-match task B, a short meaningful task, an acknowledgment, and compaction restores B or a clearly defined substantive-task state, not A merely because A had a retrieval hit.


**Evidence locations:** [breadcrumbs/hooks_prompt.py:185-231](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/hooks_prompt.py#L185-L231); [breadcrumbs/hooks_common.py:165-190](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/hooks_common.py#L165-L190); [breadcrumbs/cli.py:11505-11591](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L11505-L11591). Local probe: `short_prompt_and_stale_task`.

<a id="f16"></a>

### F16. Usage counters can count content that was not delivered

**Priority:** P2 | **Evidence:** Reproduced and source-confirmed


**Observed.** Two identical advisory guard calls in one session produced context on the first call and `{}` on the second. The usage counter still increased to two surfacings.

**Cause.** The guard records usage before its deduplication exit. Prompt rendering also trims content after selecting IDs, so accounting must follow the final rendered IDs rather than the pre-render candidate set. Related local state files use best-effort read-modify-write operations and need explicit concurrency semantics.

**Required change.** Distinguish retrieved, selected, rendered, emitted, and outcome-confirmed events. Count surfacing only for IDs actually emitted. Do not treat surfacing counts as proof that a memory helped or that an agent read it. Keep telemetry content-minimal and local by default; make dropped or approximate counts visible. Prefer a short append-only local event path or similarly contention-safe accounting over repeated whole-file rewrites.

**Completion test.** Deduped, over-budget, failed, and empty emissions contribute no surfacing count. Parallel emissions do not silently lose increments within the promised accounting model. Promotion/decay heuristics must not make authority or deletion decisions solely from these counters.


**Evidence locations:** [breadcrumbs/cli.py:11630-11679](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L11630-L11679); [breadcrumbs/hooks_prompt.py:205-231](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/hooks_prompt.py#L205-L231); [breadcrumbs/usage.py](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/usage.py); [breadcrumbs/hooks_common.py:93-122](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/hooks_common.py#L93-L122). Local probe: `guard_usage_dedupe`.

## 4C. Trust, containment, and failure boundaries

<a id="f17"></a>

### F17. A memory symlink can expose content outside the configured project

**Priority:** P1 for the MCP/root-containment boundary | **Evidence:** Reproduced


**Observed.** Replacing `current.md` with a symlink to a synthetic sibling file outside the project caused `memory://current` to return the external file's contents.

**Threat model.** This requires control of a memory filesystem entry and an MCP/CLI process with permission to read the target. It is not a demonstrated remote exploit against an internet-facing server. It matters when a project-local memory reader is expected to stay within an allowed root, including when repository content is less trusted than the process's filesystem access.

**Required change.** Define and enforce a symlink/containment policy across singleton reads, record enumeration, hashes, projections, exports, promotion targets, and writes through symlinked parent directories. The simplest supportable default is to reject symlinks inside the memory tree. Resolve and authorize the project root separately; do not turn every caller-supplied path into a trusted boundary. Guard against check/use races to the extent required by the supported threat model, and fail closed with a sanitized diagnostic.

**Completion test.** Internal and external symlinks, symlinked directories, broken links, traversal, platform junction/reparse equivalents, and paths with Unicode/spaces never leak external bytes or write outside authorized locations. Use only synthetic fixtures.


**Evidence locations:** [breadcrumbs/mcp_core.py:90-128](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/mcp_core.py#L90-L128); [breadcrumbs/cli.py:1211-1285](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L1211-L1285); [breadcrumbs/cli.py:308-324](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L308-L324). Local probe: `symlink_read`.

<a id="f18"></a>

### F18. Review metadata and interface separation do not establish an authority boundary

**Priority:** P1 design decision; implementation should remain proportional | **Evidence:** Source-confirmed and proposed requirement


The package already records `review_status: unreviewed` and `reviewed_by`, but record admission, retrieval, and guard behavior do not constitute an independently enforced human-approval system. MCP writers can create active durable records, and an actor with general shell/file access can use CLI promotion or directly edit instruction files. `agent: human` is a claim unless the caller identity is established outside the payload.

**Required change.** Adopt an explicit threat and authority model. Keep a low-friction solo profile, while offering a reviewed/team profile for sensitive shared memory. Separate claim lifecycle, evidence confidence, review state, and authenticated/observed writer identity. High-impact changes should enter review rather than self-authorize. Use trusted operator configuration and, where stronger enforcement is needed, OS/service or Git-review permissions outside the agent's writable policy files.

Do not market `reviewed_by`, CLI-only commands, a "data not instructions" banner, secret scanning, or a hash as a complete prompt-injection defense. They are useful controls with different limits. Do not make all mundane capture wait for a human. A recalled historical approval must not silently become present authorization for a new high-impact action.

**Completion test.** Forged actor/review fields and an untrusted imported record cannot obtain capabilities prohibited by the selected deployment boundary. A user-delegated routine capture still works unattended. Document precisely what a full-shell agent can bypass.


**Evidence locations:** [breadcrumbs/cli.py:1497-1510](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L1497-L1510); [breadcrumbs/mcp_core.py:419-530](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/mcp_core.py#L419-L530); [breadcrumbs/promote.py:276-348](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/promote.py#L276-L348); [docs/security.md](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/docs/security.md).

<a id="f19"></a>

### F19. Evaluation gates do not measure the whole delivered experience or require critical correctness

**Priority:** P1 | **Evidence:** Source-confirmed and CI-reported


The baseline reports prompt precision 0.6606 and recall 0.8687, packet precision 0.5854 and recall 0.9747, one prompt rejected-record hit, two packet rejected-record hits, and guard accuracy 0.875. Guard's denominator is eight verdict-scored tasks; the webapp's 0.5 is one miss among two. These are useful diagnostics, not broad estimates of autonomous safety.

The precision metric divides by the number actually returned up to five, not always by five. That can be a reasonable metric, but must be named/defined accurately. Packet evaluation filters out zero-relevance entries and reranks the retained records; it therefore does not measure the actual recency-first reading order or all noise in the delivered packet. Prompt evaluation calls retrieval directly rather than the full length-gating/deduplication/rendering hook.

**Required change.** Preserve these diagnostics, add actual serialized-delivery evaluation, and introduce hard critical invariants plus independently reviewed baseline changes. Grade assertion correctness, lifecycle/scope exclusion, relevant-rule coverage, false-safe command cases, actual token cost, and silence on controls. Separate development cases from held-out scenarios.

**Completion test.** A known hazardous command returning `PROCEED`, a forbidden record surfacing, or a malformed/oversized delivery must fail its critical suite even when aggregate metrics equal the old baseline. A baseline rewrite requires explained task-level deltas, not a reflexive route back to green.


**Evidence locations:** [evals/run.py](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/evals/run.py); [evals/baseline.json](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/evals/baseline.json); [evals/README.md](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/evals/README.md); [.github/workflows/ci.yml](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/.github/workflows/ci.yml).

<a id="f20"></a>

### F20. A failed retirement can leave two live decisions while the writer reports success

**Priority:** P1 | **Evidence:** Controlled fault reproduced


**Observed.** The probe injected a failed return from the real retirement interface during `remember --supersedes`. The command exited zero, the replacement was written, and both the old and new decisions remained active.

**Cause.** The caller extracts demotion information from `mark_superseded` results without requiring the retirements to succeed. Several writers also treat a failed projection rebuild as incidental rather than exposing a durable pending/degraded state. Atomic single-file writes are not a transaction for replacement, source retirement, rule demotion, and projection invalidation.

**Required change.** Give multi-record mutations an explicit prepare/commit/recovery contract. Validate all participants first, detect stale expected revisions, record sufficient recovery information, and return a truthful result when any step fails. Do not imply rollback when it has not happened. Projection rebuild may be recoverable/deferred, but its pending state must be visible and must invalidate acceleration artifacts until safely rebuilt.

**Completion test.** Inject failure after each write, before old-record retirement, during automatic demotion, and before projection publication. Recovery is idempotent, preserves the original evidence, and yields one intended live successor or a clearly reported unresolved transaction, never a false success.


**Evidence locations:** [breadcrumbs/cli.py:3380-3437](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L3380-L3437); [breadcrumbs/lifecycle.py:582-629](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/lifecycle.py#L582-L629); [breadcrumbs/cli.py:2705-2837](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L2705-L2837); [breadcrumbs/cli.py:3720-3790](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L3720-L3790). Local probe: `partial_supersession`.

## 4D. Architecture, compatibility, and public readiness

<a id="f21"></a>

### F21. The CLI remains the domain kernel, making independent contracts difficult to maintain

**Priority:** P2 | **Evidence:** Source-confirmed


`cli.py` contains 13,272 lines and 365 function definitions when nested/class definitions are included. More important than those counts, storage, parsing, validation, ranking, policy, projection construction, integrations, and transport behavior remain intertwined, and specialized modules call back into CLI internals.

**Required change.** Extract seams when repairing them: validation/admission, immutable reads, projection publication, retrieval, and adapter normalization. Keep existing CLI names as compatibility facades until callers migrate. Introduce a small explicit context containing root, clock, policy, and consumer capabilities rather than adding more store-global state. A public Python application layer should not import the CLI.

Do not schedule a giant rewrite or set a line-count target as a substitute for architecture. Preserve tested scoring and on-disk behavior while moving ownership. Use structural import checks and behavioral parity tests to show the direction of dependency has improved.

**Completion test.** New domain/service modules can be imported and tested without argument-parser construction or CLI output. CLI, MCP, and hooks exercise the same admission and retrieval functions, with documented differences confined to adapters.


**Evidence locations:** [breadcrumbs/cli.py](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py); [breadcrumbs/mcp_core.py](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/mcp_core.py); [breadcrumbs/searchindex.py](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/searchindex.py); [docs/architecture.md](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/docs/architecture.md).

<a id="f22"></a>

### F22. Platform and harness coverage is narrower than the portability ambition

**Priority:** P1 for unsupported advertised behavior; P2 expansion | **Evidence:** Reproduced, source-confirmed, and CI-reported


The core is portable in intent, but all current CI jobs run on Ubuntu. The reviewed hook matcher names Bash, Edit, Write, MultiEdit, Task, and Agent. A `PowerShell` tool input translated to an empty action; NotebookEdit is recognized by transcript mining but is not included in that guard matcher. Current Claude Code documentation explicitly describes a PowerShell tool and corresponding hook matching.

**Required change.** Publish a capability matrix separating plain-file reading, CLI, MCP, automatic capture, prompt retrieval, and pre-tool advisories. Normalize documented host payloads in adapters, and qualify exact host/version/platform combinations. Add native Windows and macOS smoke/contract tests, including path quoting, encodings, atomic replacement, locks, and installed-package behavior. Do not imply that a Claude-specific hook automatically works in every other agent.

**Completion test.** Every supported tool/event is either normalized and tested or explicitly reported as unsupported. Unsupported events must not be advertised as covered. Demonstrate at least one cross-harness continuation using the same canonical records; no new daemon is required.


**Evidence locations:** [breadcrumbs/cli.py:10500-10555](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L10500-L10555); [breadcrumbs/cli.py:11364-11402](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L11364-L11402); [breadcrumbs/transcript.py:49-52](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/transcript.py#L49-L52); [.github/workflows/ci.yml](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/.github/workflows/ci.yml). Local probe: `powershell_translation`.

<a id="f23"></a>

### F23. Full rebuilds and pairwise enrichment make capture cost grow unnecessarily

**Priority:** P2 | **Evidence:** Measured smoke behavior and source-confirmed


In the synthetic, no-git smoke benchmark, indexed search at 1,000 records had a five-sample median of 9.71 ms, while a single complete reindex took 2,770.83 ms. Prompt retrieval spent a median 104.34 ms before returning zero hits because of its cutoff. These are local measurements with a simple store, not production percentiles or Windows results.

Related-record generation performs pairwise work and stops above 2,000 items. Rebuilding full enrichment on routine mutations can compete with short hook lock budgets, and a size cutoff can remove a feature rather than degrade it transparently.

**Required change.** Profile parsing, hashing, related/conflict generation, Git calls, and serialization separately. Reuse one parsed snapshot per operation. Generate candidate relationships from postings and update only affected relationships when correctness permits. Local candidate capture should not pay for every shared enrichment pass. Use explicit dirty/pending generations and coalesced rebuilds without pretending old projections are current.

**Completion test.** Quality stays stable across thresholds, indexed search preserves its contract, and capture remains within a declared budget on the qualified workload. Measure the cost of safety checks; never improve a latency number by silently skipping the useful work.


**Evidence locations:** [breadcrumbs/related.py:38-97](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/related.py#L38-L97); [breadcrumbs/lifecycle.py:915-987](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/lifecycle.py#L915-L987); [breadcrumbs/cli.py:3720-3772](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/cli.py#L3720-L3772).

<a id="f24"></a>

### F24. Documentation, compatibility rules, and the dogfood handoff need reconciliation

**Priority:** P2 | **Evidence:** Source-confirmed and CI-reported


The repository's default handoff says Phase 2 is next in Current Focus while its Next Action refers to Phase 4 having shipped and Phase 5 being a possible next step. The package and changelog now describe the combined phases 0-6 release. This is a concrete reminder that a recent timestamp does not make narrative state correct.

The README is roughly 63 KB and mixes onboarding with an extensive command reference. Schema/package version language also needs a consistent pre-1.0 policy: prose about a package major bump accompanying schema changes does not describe the actual 0.3.0 schema 1-to-4 release. Existing guard exit codes, JSON keys, IDs, and adapter managed blocks are compatibility surfaces, not casual cleanup targets.

**Required change.** Separate a small golden-path quickstart from reference documentation without deleting useful detail. Reconcile the default and branch handoffs after a merge/release through an explicit workflow. Publish a compatibility/version matrix and migration policy. Derive command/schema reference sections where practical. Keep verdict exit codes stable by default and add opt-in alternatives only with tests.

**Completion test.** A clean checkout can follow the quickstart successfully; `resume` on the default branch does not direct the reader to redo completed phases; version/migration documentation matches tested upgrade behavior and release tooling.


**Evidence locations:** [.project-memory/handoff.md](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/.project-memory/handoff.md); [README.md](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/README.md); [CHANGELOG.md](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/CHANGELOG.md); [pyproject.toml](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/pyproject.toml); [docs/record-schema.md](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/docs/record-schema.md).

<a id="f25"></a>

### F25. Replay execution needs bounded output and process-tree cleanup, not just a timeout

**Priority:** P2; combine with the P1 replay correctness repair | **Evidence:** Source-confirmed


Replay currently uses a shell command with captured output. A timeout on the immediate subprocess and trimming output after completion do not, by themselves, establish bounded memory use or termination of all spawned descendants. Consent to replay is already present; preserve it. The concern is containment and accurate reporting, not a claim that every use of `shell=True` is an exploitable vulnerability.

**Required change.** Distinguish executable assertion specifications from documentation/test-file references. Record the command's working directory, platform, permitted environment inputs, and bounded timeout/output limits. Prefer an explicit argument vector where that preserves the intended command; require an explicit shell form where shell behavior is actually needed. Apply platform-appropriate process-tree cleanup. Preserve only a bounded, scrubbed output artifact with clear truncation and exit/signal/timeout fields.

**Completion test.** High-volume output, a spawned child that outlives its parent, a missing executable, cancellation, a timeout, and a command containing a secret-shaped output value produce bounded, truthful execution observations. No replay takes place solely because a memory record includes a command string.


**Evidence locations:** [breadcrumbs/lifecycle.py:348-420](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/lifecycle.py#L348-L420); [breadcrumbs/lifecycle_cmds.py](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/breadcrumbs/lifecycle_cmds.py).

<a id="f26"></a>

### F26. Public credibility needs demonstrated task outcomes, not more feature names

**Priority:** P2 product/qualification work; optional extensions P3 | **Evidence:** Proposal grounded in the current evaluation scope


The synthetic evaluations are a valuable foundation, but they do not establish that real agents repeat fewer mistakes, resume more accurately, or spend fewer total tokens after capture and maintenance costs are included. No claim of community recognition or superior real-world performance is justified by this audit alone.

**Required change.** Make the public differentiator auditable continuity: explain why a record surfaced, show its evidence and current scope, expose uncertainty, and demonstrate that a later agent avoids a specific repeated failure. Publish versioned replay datasets, negative controls, benchmark scripts, and limitations. Compare against no memory and a small manually maintained Markdown handoff, not only against the project's earlier version.

Ship a repeatable two-agent/two-session demo, an operator guide, a contribution path for regression fixtures, and a release report that distinguishes known limitations from supported guarantees. Be transparent about AI-assisted implementation while making tests, review, and design ownership visible. Recognition may follow useful work; it cannot be engineered as a guaranteed outcome.

**Completion test.** Someone outside the project can install it, reproduce the demo and reported results, understand what it does not protect against, and contribute a meaningful failing scenario without reading the entire implementation.


**Evidence locations:** [evals/README.md](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/evals/README.md); [docs/field-test.md](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/docs/field-test.md); [README.md](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/README.md).


<a id="section-5"></a>

## 5. Target design and non-negotiable invariants

### 5.1 The recommended scope

Build a **project continuity engine**, not a general personal-memory platform. Its job is to help a human or agent recover the relevant state of a particular project: decisions, failed approaches, findings, hazards, open questions, and a trustworthy next action. It should do that without vendor lock-in, hidden authority changes, or a requirement to run a permanent service.

The recommended architecture retains today's storage and interfaces while changing dependency direction:

```text
CLI / MCP / harness adapters
              |
              v
Shared application operations
  - capture observation / propose record
  - validate / admit / promote / supersede
  - read snapshot / retrieve / build bounded view
  - evaluate guard advisory / execute approved assertion
              |
              v
Record contract + policy + storage transaction + snapshot
              |
              v
Canonical Markdown records / explicit configuration
              |
              v
Disposable indexes and generated views
```

An optional semantic retriever or model-assisted extractor is a candidate producer. It does not own truth, scope, authority, or execution permissions. The deterministic baseline remains available for comparison and fallback.

### 5.2 Invariants that tests must enforce

| Invariant | Required behavior |
|---|---|
| Observation is not proof | No completed result means no claim of success; a passing command is not automatically a fixed subject |
| Transformation preserves meaning | Promotion/supersession retains content and source linkage, or explicitly records an authorized replacement |
| Scope does not widen accidentally | Branch/private/local information cannot silently become project/shared/standing guidance |
| Admission is shared | CLI, MCP, hooks, and promotion use the same validation and policy path |
| Mutation results are truthful | Failed retirement or partial publication cannot be reported as an unqualified successful replacement |
| Provenance describes actual input | A projection hash represents the exact snapshot used to build it, not a later filesystem read |
| Acceleration does not erase capability | Missing/stale indexes change cost or produce an explicit degraded result, not covertly different semantics |
| Eligibility precedes context selection | Lifecycle, scope, privacy, and applicable review policy are checked before budget trimming |
| A view has a real budget | Final serialized output respects its declared unit and discloses omissions |
| Authorized paths stay bounded | No implicit following of memory links outside the authorized root |
| Memory never grants execution authority | Retrieval and guard results are advisory; recalled historical instructions do not override current authorization |
| Failure is visible without hijacking the host | Hooks do not erase user prompts or auto-approve actions; faults have bounded, content-minimal diagnostics |
| Telemetry names what it counts | Retrieval, emission, reading, usefulness, and task success are not interchangeable |
| Reproducibility has explicit inputs | Results are deterministic for a fixed snapshot, query, policy, branch context, clock, and algorithm version |

### 5.3 Small internal contracts, not a new framework

The following are recommended internal contracts. Preserve existing public CLI/MCP responses through adapters while migrating ownership. Exact class names may change by a recorded design decision; the semantics may not disappear.

**ValidationIssue** carries a stable code, source path, field, severity, and message. Validation checks shape and integrity, not whether a natural-language claim is true. A store-level pass adds reference/cycle checks that a single record cannot perform alone.

**MutationRequest / MutationResult** carry the actor context, expected source revisions, requested changes, operation ID, committed state, changed record IDs, projection state, and issues. `ok`, `committed`, and `projection_state` must distinguish a rejected write, a committed write with pending projections, and an unresolved partial operation. Do not invent success when rollback fails.

**StoreSnapshot** contains the exact input bytes or immutable parsed representations used by an operation, their relative paths, schema/config/alias inputs, a canonical snapshot digest, and a consistency assessment. A separate **ViewContext** supplies branch/HEAD, evaluation time, task, policy, budget, and verified consumer capabilities. This prevents machine-specific context from masquerading as a universally reproducible shared artifact.

**RetrievalRequest / RetrievalResult** identify the purpose (`lookup`, `prompt`, `guard`, or `portable_resume`), query/files/filters, context, matched records, explanations, excluded counts/reasons, index state, truncation, and degradation. Keep permissive historical lookup different from live advice. Exact matching and ranking changes require versioned evaluation evidence.

**ToolObservation / CheckResult** distinguish a seen tool call, a received result, execution outcome, bounded output evidence, and a claim-level assessment. Replay specifications must distinguish a diagnostic from an assertion and bind the latter to a subject. Do not attempt to infer a trustworthy exit code from arbitrary prose when the adapter cannot establish one.

**EmissionReport** identifies IDs actually rendered/emitted and their budget cost. Usage instrumentation consumes this report after deduplication and truncation, not an earlier retrieval candidate list.

Keep these contracts small and testable. Do not create a service locator, plugin architecture, distributed event bus, or elaborate graph database merely to implement them.

### 5.4 Admission and review without destroying autonomy

Reuse the existing review vocabulary: `unreviewed`, `reviewed`, and `needs-review`. Keep it separate from record lifecycle and verification outcome. A reviewed but superseded record is still historical; a high-confidence claim can still be unreviewed; a reviewed record can still be wrong.

Start with two documented deployment profiles rather than many interacting toggles:

**Solo/delegated profile.** Routine, user-delegated capture remains automatic. Records retain their provenance and uncertainty. Explicitly approved promotion operations can share a jot without a redundant ceremony, but the sharing/scope effect must be apparent and policy-controlled. No capture can self-authorize a new executable action or silently become a standing instruction.

**Reviewed/team profile.** High-impact shared changes and standing-rule promotion enter `needs-review`; only a trusted review event establishes reviewed authority. Configure that policy outside the untrusted caller's payload. If the agent can edit the policy, forge review metadata, or bypass Git protections with its own credentials, document that limitation rather than implying enforcement exists.

High-impact changes include authority/permission boundaries, reduced testing, security/privacy posture, major dependency strategy, broad supersession, and quarantine changes. Avoid pretending a lexical classifier can perfectly recognize all of them. Combine explicit operation categories, operator policy, and reviewable evidence.

MCP deployments should be able to expose read-only, proposal/capture, and approved mutation capabilities deliberately. Tool annotations and human-readable banners help clients reason about tools; they are not authorization mechanisms. Raw instruction-like memory remains untrusted content even when enclosed in a data block.

### 5.5 Coherent reads, writes, and generations

Use OS-held local locking on qualified filesystems, plus the existing in-process thread discipline. Keep lock ownership stable through force-init and migration. Do not unlink a live lock inode as routine cleanup. A fallback lease must be fenced so an old owner cannot publish after ownership changes.

For a multi-record operation, validate and prepare the complete change set before committing. Persist recovery information sufficient to determine what completed. Check expected revisions to avoid overwriting a newer edit. On recovery, finish or revert deterministically and report any operation that cannot be resolved automatically without choosing between conflicting authored facts.

Build projections from one snapshot. Use unique temporary files. Publish a generation manifest last, containing the snapshot ID, view context, format/algorithm versions, output digests, and build status. Consumers reject mixed/unverified generations. Preserve the existing portable packet path as a compatibility export; a read-only consumer of one packet still gets an atomically replaced, self-identifying artifact.

Do not promise an instantaneous global filesystem snapshot in the presence of arbitrary non-cooperating writers. Use bounded optimistic validation/retry or a verified prior snapshot, and label an unstable read. Never compute a fresh hash after reading older content and pass it off as the content's provenance.

Local candidate ingestion may use uniquely named, atomic pending entries so a brief global-lock conflict does not lose an acknowledged correction. Cursor advancement follows durable acceptance or an explicitly counted policy rejection. Bounded backlog, expiry, and dropped-work metrics must be honest; no daemon is required for opportunistic draining.

### 5.6 Retrieval and context delivery

The main optimization is **avoid parsing everything**, not "return nothing when the store is large." Candidate lookup uses the existing lexical index or a correct fallback. Cache freshness is checked against content/generation semantics. Apply purpose-specific eligibility before ranking and context budgets.

Keep explanations inspectable: source ID and revision, matched file/tag/phrase, score components, age/scope effects, why a record was excluded, and whether an accelerator or degraded fallback was used. Avoid returning a giant explanation on every ordinary call; expose structured details through an explicit explain mode.

A portable packet includes its effective promoted rules unless the particular consumer has verified that it already loaded them. A harness-local packet may suppress duplicates using that capability. Latest user task and latest successful retrieval query are different state fields.

Treat a known dangerous command signature as narrow project knowledge, not a general shell security policy. Include command context where needed: tool, working directory, relevant script/config revision, and explicit hazard conditions. Do not normalize away the directory or arguments that distinguish safe and dangerous executions.

<a id="section-6"></a>

## 6. Compatibility, migration, and recovery

### 6.1 Preserve established surfaces

Preserve record IDs, existing filename rules, supported schema readers, CLI names, current verdict exit codes, documented JSON keys, and managed adapter blocks unless a versioned change explicitly says otherwise. Keep the package schema version, projection/index format versions, and wire-contract version distinct. A generated-index change does not automatically require rewriting canonical records.

The current schema deliberately treats unknown scope text as project-wide. Tightening that policy must be announced and tested. New writers should accept only supported scopes; legacy records with other text must be diagnosed and require an explicit interpretation, not silently converted to a different meaning. Similarly, stricter confidence/date/evidence validation must not rewrite historical content into whatever value makes validation pass.

Missing `superseded_by` targets, self-links, and cycles need integrity checks. Historical `supersedes` links to intentionally rolled-up or archived records require a documented tombstone/archive representation or an explicit legacy exception. Do not break intentional session rollups by treating every historical missing source as the same error as a nonexistent live replacement target.

### 6.2 Migration procedure

1. Preview the exact affected files, unsupported values, semantic changes, and minimum reader version. Obtain the required operator approval.
2. Create and verify a backup manifest with content hashes. Do not assume that a copy operation proves a restorable backup.
3. Acquire the appropriate coordination boundary and record a resumable migration operation.
4. Transform records without changing their IDs or dropping unknown fields, source text, privacy, scope, or provenance. Ambiguous facts remain unresolved for review.
5. Validate records and links; publish the new schema/version state only after the corresponding changes are complete.
6. Rebuild projections and indexes from the migrated snapshot. Run positive/negative retrieval parity tests and explicitly approved semantic-difference tests.
7. Test restart, interrupted migration, idempotent rerun, and restoration. Downgrading the binary alone is not a valid rollback if the old binary cannot read the new store.

Use this same approach for a reviewed-mode feature that older tools would misinterpret. Do not add a security-critical field that an old reader silently ignores and then claim all readers enforce the new rule.

### 6.3 Failure and recovery result contract

A committed canonical write with a failed enrichment rebuild can be recoverable. It must return something equivalent to `committed=true, projection_state=pending` and invalidate affected accelerators. A failed replacement that leaves both records active is not an unqualified success. The operator must have a clear `doctor`/recovery action for pending operations.

Power-loss durability requires an explicit support statement and appropriate flushing/replace behavior; atomic rename alone is not the whole guarantee. Test what is claimed. Network-mounted or sync-managed stores should be explicitly unsupported for strong local-writer guarantees until separately qualified; Git-based sharing across independent checkouts remains a different, supported design goal.

<a id="section-7"></a>

## 7. Evaluation and qualification program

### 7.1 Four layers, four different questions

| Layer | Question | Required evidence |
|---|---|---|
| Contract/unit/property | Is each operation structurally and semantically correct? | Deterministic fixtures, invalid-input cases, metamorphic/property tests, field-preservation assertions |
| Fault/concurrency | Does it remain honest under interruption and competing writers? | Process tests, injected failures at each transaction boundary, recovery/identity checks |
| Delivered retrieval/guard | Did the consumer actually receive the right bounded context? | Full hook/MCP/CLI invocation, serialized output and emitted-ID inspection, critical negative controls |
| Real agent tasks | Does it improve project work after costs are counted? | Replayed tasks with independent correctness oracles and no-memory/minimal-handoff baselines |

A passed unit test is not a task-success benchmark. A retrieval hit is not proof that the agent used the record. A successful shell process is not proof that the memory system's claim is true.

### 7.2 Hard acceptance gates

Critical suites require **zero observed violations** of: fabricated execution success; accidental scope/privacy widening; lost promoted text; false-fresh projection stamps; unreported partial supersession; external-root reads/writes; forbidden lifecycle/scope records in live advice; and known-command false-safe cases. Every critical scenario must assert its required result directly. Passing all finite tests is evidence for those scenarios, not a universal proof.

Preserve and extend negative controls: unrelated tasks, ordinary read-only commands, speculative ideas, expired findings, answered questions, a documented safe remedy, and branches on which a record does not apply. The solution to one missed hazard must not restore an unusable flood of prompts.

Existing baseline comparison remains useful, but a baseline file is a measurement artifact, not an approval to tolerate any measured behavior. Require task-level diffs, a named rationale, and review for updates. Keep critical thresholds separate from tunable aggregate metrics. A known failing critical case remains a release blocker or a clearly scoped unsupported capability, not a silently accepted average.

### 7.3 Delivered-context metrics

Record both candidate-ranking quality and actual delivered-context quality. For the latter, evaluate the serialized packet in its real order, including the recency floor, unrelated retained records, warnings, duplicated promoted rules, and wrapper overhead. Test the complete prompt hook rather than only `retrieve()`.

Report denominators and definitions explicitly. Useful metrics include returned-set precision, must-have-record recall, first relevant item position, forbidden-record count, no-match correctness, truncation disclosure, context bytes/estimated tokens/exact declared-tokenizer tokens, and emitted records per turn. Measure record revisions as well as IDs so an obsolete version is not counted as a successful retrieval of the current claim.

Proposed initial engineering targets for a reviewed holdout set are returned-set precision of at least 0.80 and must-have recall of at least 0.95, with every critical case passing. These are **targets, not current achievements or universal thresholds**. Approve them before evaluating the candidate release; revise them only through documented task-cost reasoning, not to fit the latest scores.

### 7.4 Scale and latency qualification

The included smoke timings demonstrate a design issue but are too small for percentile claims. Use a documented reference machine and at least 200 warm samples for each chosen workload before setting a p95 gate. Record hardware, OS, Python/SQLite/host versions, filesystem, git-history shape, record sizes, active/history mix, index state, and whether startup is included.

An initial target at 1,000 representative records is p95 <=250 ms for a warm retrieval operation and <=500 ms for a complete ordinary prompt hook, including its process overhead. Target a durable ordinary capture acknowledgment within one second when heavy enrichment is separated safely. These targets must be validated on native Windows as well as the reference Linux environment; do not insert wall-clock assertions into otherwise deterministic unit tests.

Test at 100, 200, 500, 501, 1,000, and 10,000 records. Include both sparse and highly overlapping evidence, long records, mostly retired history, cold/missing/corrupt indexes, large Git histories, and several concurrent sessions. The higher tier may have different latency targets; it must not simply return an unexplained empty result. Track CPU, peak memory, bytes read, parse counts, subprocess counts, and write amplification, not only elapsed time.

### 7.5 Adversarial and lifecycle scenarios

Use a security/robustness corpus with synthetic secrets, injected role-like text, fabricated review fields, invalid paths/symlinks, oversized metadata, stale and conflicting decisions, same-size/restored-mtime edits, branch switches, detached HEAD, partial JSONL records, >8 MB transcript rollover, tool results arriving after a hook, and intentional replay failures. Explicitly test an old reader/new store and an old index/new tokenizer.

Command replay cases must include a harmless successful diagnostic that does not prove the subject, a genuine assertion, missing tooling, nonzero exits, timeout, output flooding, and child-process cleanup. Test known-safe recovery workflows as carefully as rejection cases.

### 7.6 Real-task experiment

Compare the same task families under three baselines: no persistent memory, a compact manually maintained Markdown handoff, and Breadcrumbs. Include the memory-maintenance work in cost. Use task-specific tests or externally defined acceptance criteria, not the acting agent's own claim that it succeeded.

Start with at least three real repositories, including one not designed specifically to flatter the benchmark. Separate development scenarios from held-out scenarios and hold out projects where possible. Repeated runs should vary session history, branch context, and the participating model/harness while controlling other factors.

Measure task success, repeated-known-failure rate, time to first correct action, total tokens including capture/retrieval/retries, human interruptions, and memory errors. Report sample counts, uncertainty, and failures; account for repeated tasks from the same repository rather than treating every turn as independent. Do not publish a savings percentage until a reproducible experiment supports it.

Optional semantic retrieval is eligible for a trial only after lexical failures are classified. Optional model-assisted extraction is eligible only after the observation/admission boundary is reliable. Compare both against the deterministic baseline and include their latency, cost, privacy, and new false-positive risks.

<a id="section-8"></a>

## 8. Dependency-ordered implementation work packages

Each package is a reviewable outcome, not permission for an agent to implement the whole roadmap. `S`, `M`, and `L` describe relative complexity, not elapsed-time estimates. Split a large package into small pull requests without weakening its acceptance gate.

**Every package follows the same sequence:** inspect the current revision; run its baseline; add a failing regression that isolates the observed cause; implement the smallest complete fix; run targeted and full applicable checks; inspect serialized outputs and negative controls; update documentation and compatibility notes; record the evidence and remaining limitations. Refactoring-only changes require before/after parity.

The companion `2026-09-26-breadcrumbs-work-packages.json` is a machine-readable tracker. All packages begin `not_started`. The narrative in this document is the plan of record; an agent updates status only after attaching real verification evidence.

<a id="wp00"></a>

### WP00. Establish the baseline and preserve reproducible evidence

**Priority / complexity:** P1 / S | **Dependencies:** none | **Findings:** F19, F26

**Modify:** none.

**Create, if needed:** `docs/reviews/2026-09-26-breadcrumbs-audit-and-roadmap.md`; `tests/test_audit_regressions.py`.

**Implementation sequence**

1. Compare HEAD with the audited commit; classify findings as still present, already fixed, or changed. Do not treat changed line numbers as a disproved finding.
2. Run the complete repository test/eval commands on a real checkout, then the supplied diagnostic probes. Record environment, commit, command, exit code, and output. Preserve the audit evidence separately.
3. Convert confirmed cases into focused upstream regressions as their repair packages proceed. Do not make a diagnostic script reporting defects look like a green product test.

**Named acceptance tests / checks**

- Baseline: `python -m unittest discover -s tests -p "test_*.py"` and `python evals/run.py --verbose`.
- Audit probe output is machine-readable; errors and observed defects are distinguished.

**Done when:** The current baseline and all deviations from this report are recorded; no production behavior has been changed merely to obtain a baseline.

<a id="wp01"></a>

### WP01. Centralize and strengthen record validation

**Priority / complexity:** P1 / M | **Dependencies:** WP00 | **Findings:** F05

**Modify:** `breadcrumbs/cli.py`; `breadcrumbs/mcp_core.py`; `breadcrumbs/inbox.py`; `docs/record-schema.md`.

**Create, if needed:** `breadcrumbs/validation.py`; `tests/test_validation_contract.py`.

**Implementation sequence**

1. Extract pure field/shape checks and store-level reference checks without changing record IDs or source text. Preserve unknown fields during round trips.
2. Validate confidence/review vocabularies, evidence item shape, timestamps, supported new-write scopes, and replacement links. Treat legacy free-text scope and archived rollup references explicitly rather than silently normalizing them.
3. Call the same validator from every writer and from store validation. Return stable codes and useful locations; isolate malformed records on reads with an explicit degraded result.

**Named acceptance tests / checks**

- `test_invalid_confidence_evidence_and_dates_are_reported`
- `test_new_write_rejects_unknown_scope_without_widening_legacy_scope`
- `test_missing_replacement_self_link_and_cycle_are_reported`
- `test_unknown_metadata_round_trips_without_loss`

**Done when:** The schema probes have intentional, documented outcomes and no adapter bypasses the shared contract; existing valid stores retain their identities and meaning.

<a id="wp02"></a>

### WP02. Make transcript outcome detection truthful

**Priority / complexity:** P1 / M | **Dependencies:** WP00 | **Findings:** F01

**Modify:** `breadcrumbs/transcript.py`; `tests/test_transcript.py`.

**Create, if needed:** `tests/test_transcript_outcomes.py`.

**Implementation sequence**

1. Add explicit result-received and outcome state to normalized calls. Missing, interrupted, and unrecognized results are unknown, never implicitly successful.
2. Classify from structured adapter result data where available; analyze any necessary textual fallback before producing bounded excerpts. Remove naive zero-failure false positives.
3. Reword candidate creation to distinguish observed execution from causal claims. Keep private, low-confidence candidate admission and current secret-dropping safeguards.

**Named acceptance tests / checks**

- `test_missing_result_never_produces_passed_candidate`
- `test_failure_after_excerpt_limit_is_failure`
- `test_zero_failed_summary_is_not_failure`
- `test_edit_then_success_does_not_assert_unproven_causality`

**Done when:** The F01 cases pass as ordinary regressions and uncertain events remain accurately labeled. Cross-firing joins complete in WP09.

<a id="wp03"></a>

### WP03. Make jot promotion lossless and scope-preserving

**Priority / complexity:** P1 / M | **Dependencies:** WP01 | **Findings:** F03

**Modify:** `breadcrumbs/inbox.py`; `breadcrumbs/mcp_core.py`; `tests/test_inbox.py`.

**Create, if needed:** `tests/test_promotion_contract.py`.

**Implementation sequence**

1. Preserve the entire jot body by default, not just its title. Record source ID/revision in the target.
2. Inherit scope, confidence, and provenance. Make private-to-shared and branch-to-project effects explicit and policy-authorized; explicit replacement sections must not silently erase the source trail.
3. Route all promotion targets through shared validation and duplicate checks. Retire the source only after a successful durable target transition; integrate WP06 transaction semantics when available.

**Named acceptance tests / checks**

- `test_promote_without_sections_preserves_note_text`
- `test_private_branch_promotion_does_not_default_to_project_medium`
- `test_promotion_obeys_duplicate_gate`
- `test_failed_target_leaves_source_live`

**Done when:** A reader of the new durable record can recover the original substantive information, its uncertainty, and its scope without access to an omitted private body.

<a id="wp04"></a>

### WP04. Separate assertion replay from claim verification

**Priority / complexity:** P1 / L | **Dependencies:** WP01 | **Findings:** F04, F25

**Modify:** `breadcrumbs/lifecycle.py`; `breadcrumbs/lifecycle_cmds.py`; `tests/test_lifecycle.py`; `docs/cli-spec.md`.

**Create, if needed:** `breadcrumbs/checks.py`; `tests/test_replay_contract.py`.

**Implementation sequence**

1. Preserve original scope, subject, confidence, and provenance when recording replay results. Add an internal CheckResult separate from a verification outcome.
2. Define a minimally sufficient, versioned assertion/replay specification. Legacy command/test references remain evidence pointers or diagnostics unless explicitly bound to an assertion; do not assume a test-file path is executable.
3. Keep preview/consent, bound output while it is collected, and implement platform-aware cancellation/process-tree cleanup. Preserve exact command semantics rather than applying POSIX parsing to Windows strings.
4. Only a successfully evaluated assertion may settle its bound subject. Missing tools, timeout, unavailable evidence, and interrupted execution remain inconclusive.

**Named acceptance tests / checks**

- `test_noop_diagnostic_does_not_fix_claim`
- `test_recheck_preserves_branch_scope_across_checkout`
- `test_assertion_failure_differs_from_runner_unavailability`
- `test_output_and_descendant_processes_are_bounded`

**Done when:** Replay is accurate, consented, bounded, and auditable; it cannot elevate a successful process into an unrelated factual conclusion.

<a id="wp05"></a>

### WP05. Repair writer coordination and lock ownership

**Priority / complexity:** P1 / L | **Dependencies:** WP00 | **Findings:** F06, F08

**Modify:** `breadcrumbs/lock.py`; `breadcrumbs/cli.py`; `breadcrumbs/mcp_core.py`; `tests/test_lock.py`.

**Create, if needed:** `tests/test_lock_processes.py`.

**Implementation sequence**

1. Adopt OS-held local locking on qualified POSIX/Windows paths, keeping thread re-entrancy and bounded caller waits. Define the filesystem support boundary.
2. Ensure every writing invocation, including projection publication and maintenance hidden behind resume, participates. A read-only response must not bypass the lock by publishing.
3. Keep ownership stable through init/migrate/cleanup. If any lease fallback remains, add ownership generations/fencing and prove an old holder cannot publish or release a newer lock.

**Named acceptance tests / checks**

- `test_resume_does_not_publish_under_foreign_writer`
- `test_process_death_releases_os_lock`
- `test_live_owner_is_not_stolen_after_clock_gap`
- `test_force_init_preserves_coordination`

**Done when:** Real-process exclusion and bounded contention behavior pass on qualified platforms; stale-clock logic no longer permits concurrent live owners.

<a id="wp06"></a>

### WP06. Make replacement and lifecycle mutations recoverable

**Priority / complexity:** P1 / L | **Dependencies:** WP01, WP05 | **Findings:** F20

**Modify:** `breadcrumbs/cli.py`; `breadcrumbs/lifecycle.py`; `breadcrumbs/inbox.py`; `breadcrumbs/promote.py`.

**Create, if needed:** `breadcrumbs/mutations.py`; `tests/test_mutation_recovery.py`.

**Implementation sequence**

1. Introduce one application mutation path with expected revisions, an operation ID, a prepared change set, and truthful result states.
2. Check every retirement/demotion result. Implement rollback or resumable recovery without erasing authored history; track projection invalidation separately from canonical commit.
3. Persist sufficient journal/recovery metadata for failures between participants. Make retries idempotent and expose unresolved operations through doctor/recovery commands.

**Named acceptance tests / checks**

- `test_failed_retirement_is_not_success_with_two_live_decisions`
- `test_failure_after_each_participant_is_recoverable`
- `test_expected_revision_prevents_lost_update`
- `test_retry_does_not_duplicate_or_orphan_records`

**Done when:** Replacement, consolidation, promotion, and automatic demotion cannot acknowledge an unresolved partial operation as a fully successful transition.

<a id="wp07"></a>

### WP07. Build and publish coherent snapshots and projections

**Priority / complexity:** P1 / L | **Dependencies:** WP05, WP06 | **Findings:** F06, F07, F11, F12

**Modify:** `breadcrumbs/cli.py`; `breadcrumbs/searchindex.py`; `breadcrumbs/related.py`; `breadcrumbs/lifecycle.py`.

**Create, if needed:** `breadcrumbs/snapshots.py`; `breadcrumbs/projections.py`; `tests/test_snapshot_consistency.py`.

**Implementation sequence**

1. Capture one immutable input representation per operation and derive its digest from those exact inputs. Keep branch/time/query/consumer context in a separate view identity.
2. Build packet, prefilter, related/conflict maps, and index from the snapshot. Use unique temporary files and publish a manifest with output digests last.
3. Separate resume read/print from publication. Handle contention with a verified prior view, bounded retry, or explicit degraded output; never a false-current stamp.
4. Remove the same-size/mtime shortcut from the strict freshness path and benchmark the correct path before introducing replacement optimizations.

**Named acceptance tests / checks**

- `test_mutation_between_read_and_hash_cannot_false_certify`
- `test_mixed_generation_is_not_consumed`
- `test_two_index_builders_do_not_share_temp_file`
- `test_same_size_restored_mtime_edit_invalidates_strict_index`

**Done when:** Every emitted source stamp describes the actual input snapshot, and disposable artifacts cannot be trusted across an unverified generation boundary.

<a id="wp08"></a>

### WP08. Make packets genuinely bounded and portable

**Priority / complexity:** P1 / M | **Dependencies:** WP07 | **Findings:** F13, F14

**Modify:** `breadcrumbs/cli.py`; `breadcrumbs/promote.py`; `breadcrumbs/mcp_core.py`; `tests/test_resume.py`.

**Create, if needed:** `tests/test_packet_delivery.py`.

**Implementation sequence**

1. Enforce budget on the final serialized view, including focus/next-action fields, warnings, rules, and framing. Define units for Markdown, JSON, and fast views.
2. Include effective promoted rules in portable packets. Permit elision only for a verified consumer-loaded rule revision.
3. Use explicit excerpts/source pointers and omission counts without altering canonical content. Add estimator metadata; exact tokenizer support is optional and consumer-specific.

**Named acceptance tests / checks**

- `test_long_focus_cannot_exceed_declared_view_budget`
- `test_missing_adapter_does_not_hide_promoted_decision`
- `test_cross_harness_packet_includes_effective_rules`
- `test_unicode_and_tiny_budgets_terminate_and_disclose_omissions`

**Done when:** Read-only and cross-harness readers receive the necessary rules and an accurately bounded, self-identifying packet.

<a id="wp09"></a>

### WP09. Replace the relative transcript cursor with durable incremental ingestion

**Priority / complexity:** P1 / L | **Dependencies:** WP02, WP03, WP05, WP06 | **Findings:** F02

**Modify:** `breadcrumbs/transcript.py`; `breadcrumbs/hooks_common.py`; `breadcrumbs/hooks_compact.py`; `tests/test_hooks_phase1.py`.

**Create, if needed:** `tests/test_transcript_recovery.py`.

**Implementation sequence**

1. Use file identity plus absolute byte progress and an incomplete-line buffer. Persist bounded pending call/result state across firings.
2. Advance acknowledgments only after durable acceptance or an explicitly counted policy rejection. Add idempotent pending capture entries where necessary to survive lock contention.
3. Handle >8 MB windows, rotation/truncation, restart, session fork, candidate caps, and write failure. Report backlog/skips without retaining unnecessary full transcripts or secret content.

**Named acceptance tests / checks**

- `test_sliding_tail_does_not_freeze_cursor`
- `test_call_and_late_result_join_across_firings`
- `test_partial_line_rotation_and_restart_preserve_progress`
- `test_crash_between_jot_and_cursor_is_idempotent`

**Done when:** Long sessions remain mineable and no acknowledged event is silently lost, replayed into duplicate authority, or reclassified as success without a result.

<a id="wp10"></a>

### WP10. Unify indexed retrieval eligibility and short-prompt handling

**Priority / complexity:** P1 / L | **Dependencies:** WP01, WP07 | **Findings:** F09, F10, F11, F12

**Modify:** `breadcrumbs/hooks_prompt.py`; `breadcrumbs/searchindex.py`; `breadcrumbs/cli.py`.

**Create, if needed:** `breadcrumbs/retrieval.py`; `tests/test_retrieval_boundaries.py`.

**Implementation sequence**

1. Remove the full-corpus pre-count and the >500 return-empty gate. Query indexed candidates directly and apply purpose-specific eligibility before output budgets.
2. Replace raw character-length suppression with tested acknowledgment handling. Keep historical lookup distinct from current advice.
3. Unify alias, tokenizer, index-version, scope, and lifecycle semantics. Distinguish exact full search from intentionally bounded hook retrieval, with explicit truncation/degradation metadata.
4. Add a cheap valid corpus/generation summary instead of treating guard-prefilter existence as general retrieval content.

**Named acceptance tests / checks**

- `test_one_active_plus_500_stale_records_still_retrieves`
- `test_199_200_201_and_499_500_501_preserve_results`
- `test_short_meaningful_prompt_is_not_acknowledgment`
- `test_index_missing_stale_or_corrupt_has_honest_fallback`

**Done when:** Memory does not disappear at a size boundary and the consumer can tell whether a lookup completed normally or used a limited fallback.

<a id="wp11"></a>

### WP11. Close the known-command guard miss without restoring warning spam

**Priority / complexity:** P1 / M | **Dependencies:** WP10, WP18 | **Findings:** F10, F11

**Modify:** `breadcrumbs/cli.py`; `tests/test_guard.py`; `tests/test_guard_precision.py`; `tests/test_hooks.py`.

**Create, if needed:** `tests/test_guard_delivery.py`.

**Implementation sequence**

1. Make exact project-known command hazards eligible for an appropriately bounded advisory even when generic-token filtering removes a word such as test.
2. Ensure prefilter candidate selection cannot reject a case that full guard would surface. Preserve record stance, safe-remedy behavior, read-only ceilings, and host permission-mode rules.
3. Document PROCEED as no applicable memory warning, not action authorization. Preserve the existing verdict exit-code mapping; add transport convenience only separately and opt-in.

**Named acceptance tests / checks**

- `test_known_destructive_npm_test_never_proceeds_silently`
- `test_full_guard_and_hook_agree_on_required_warning`
- `test_safe_remedy_and_unrelated_controls_remain_nonblocking`
- `test_permission_mode_never_gains_auto_allow`

**Done when:** The critical npm case passes through the actual hook, while established false-positive controls and permission boundaries remain intact.

<a id="wp12"></a>

### WP12. Separate latest intent from retrieval state and correct telemetry

**Priority / complexity:** P2 / M | **Dependencies:** WP07, WP09, WP10 | **Findings:** F15, F16

**Modify:** `breadcrumbs/hooks_prompt.py`; `breadcrumbs/hooks_common.py`; `breadcrumbs/usage.py`; `breadcrumbs/cli.py`; `breadcrumbs/hooklog.py`.

**Create, if needed:** `tests/test_emission_accounting.py`.

**Implementation sequence**

1. Update substantive latest-task state independently of whether retrieval found anything; retain distinct retrieval-query and matched-ID state.
2. Introduce final emission accounting after deduplication and budget trimming. Distinguish retrieved, selected, emitted, and externally confirmed usefulness.
3. Make local state updates concurrency-safe or explicitly approximate, report drops, and keep telemetry content-minimal. Do not turn frequency into automatic factual approval.

**Named acceptance tests / checks**

- `test_unmatched_new_task_replaces_old_matched_task`
- `test_deduped_guard_does_not_increment_surfaced`
- `test_trimmed_ids_are_not_counted_as_emitted`
- `test_parallel_telemetry_does_not_silently_lose_acknowledged_events`

**Done when:** Compaction follows current intent and usage reports measure actual emissions under their stated accounting model.

<a id="wp13"></a>

### WP13. Enforce filesystem containment and safe rendering boundaries

**Priority / complexity:** P1 / M | **Dependencies:** WP00 | **Findings:** F17

**Modify:** `breadcrumbs/mcp_core.py`; `breadcrumbs/cli.py`; `breadcrumbs/promote.py`; `breadcrumbs/migrate.py`.

**Create, if needed:** `breadcrumbs/path_policy.py`; `tests/test_path_containment.py`.

**Implementation sequence**

1. Define an authorized-root and symlink policy shared by read, enumerate, hash, write, export, migration, and adapter-target operations.
2. Reject or safely constrain symlinked leaves and parent directories; handle Windows junction/reparse cases during platform qualification. Sanitize diagnostics rather than returning external contents or sensitive host paths.
3. Apply bounded, data-oriented rendering to record text. Preserve original source text but prevent malformed framing/control characters from impersonating a tool response envelope.

**Named acceptance tests / checks**

- `test_mcp_singleton_symlink_cannot_read_external_file`
- `test_symlinked_parent_cannot_redirect_write`
- `test_traversal_broken_link_and_unicode_paths_are_safe`
- `test_record_text_cannot_break_serialized_response_envelope`

**Done when:** All supported filesystem surfaces remain within authorized boundaries for the documented threat model; no production secret is needed to verify this.

<a id="wp14"></a>

### WP14. Implement proportional review and capability policies

**Priority / complexity:** P1 design / P2 rollout / L | **Dependencies:** WP01, WP06, WP13, WP21 | **Findings:** F18

**Modify:** `breadcrumbs/mcp_core.py`; `breadcrumbs/mcp_server.py`; `breadcrumbs/promote.py`; `docs/security.md`; `docs/mcp-spec.md`.

**Create, if needed:** `breadcrumbs/admission.py`; `tests/test_admission_policy.py`.

**Implementation sequence**

1. Implement the approved solo/delegated and reviewed/team profiles using existing review states. Keep claim lifecycle and execution outcome independent.
2. Bind writer capabilities to trusted runtime/operator context rather than payload actor strings. Gate high-impact sharing/promotion and expose read-only/proposal modes where configured.
3. Preserve low-friction ordinary capture, disclose private-to-shared transitions, and prevent historical approval text from becoming new authorization.
4. Document the full-shell-agent limit and test the real deployment boundary. Do not call CLI-only exposure, annotations, or unsigned review fields enforcement.

**Named acceptance tests / checks**

- `test_payload_cannot_forge_trusted_review_identity`
- `test_delegated_routine_capture_stays_unattended`
- `test_high_impact_promotion_requires_profile_authority`
- `test_legacy_reader_policy_mismatch_is_detected_or_excluded`

**Done when:** The supported authority model is implemented, tested, and described without claiming stronger protection than the deployment actually provides.

<a id="wp15"></a>

### WP15. Reduce rebuild cost without weakening correctness

**Priority / complexity:** P2 / L | **Dependencies:** WP07, WP10, WP11, WP12 | **Findings:** F23

**Modify:** `breadcrumbs/related.py`; `breadcrumbs/lifecycle.py`; `breadcrumbs/searchindex.py`; `breadcrumbs/inbox.py`.

**Create, if needed:** `tests/test_incremental_equivalence.py`; `benchmarks/continuity_scale.py`.

**Implementation sequence**

1. Profile the correct snapshot/retrieval path before optimizing it. Reuse parsed records and avoid repeated whole-store hashing/reading within one operation.
2. Generate related/conflict candidate pairs from postings; maintain full-oracle equivalence for incremental updates and removals.
3. Decouple local candidate acknowledgment from expensive shared enrichment using explicit invalidation/pending generations. Coalesce rebuilds opportunistically without a mandatory daemon.
4. Replace hard feature cutoffs with measured, visible behavior at larger scales; publish workload-specific timing and quality results.

**Named acceptance tests / checks**

- `test_incremental_related_and_conflict_results_match_full_oracle`
- `test_local_capture_does_not_rebuild_unaffected_shared_views`
- `test_1000_and_10000_record_quality_does_not_collapse`
- Performance evidence includes latency, parse count, memory, and write amplification.

**Done when:** The system meets its qualified capture/retrieval budgets without silently omitting work or weakening strict cache correctness.

<a id="wp16"></a>

### WP16. Finish extracting the application layer from the CLI

**Priority / complexity:** P2 / L | **Dependencies:** WP06, WP07, WP10, WP14 | **Findings:** F21

**Modify:** `breadcrumbs/cli.py`; `breadcrumbs/mcp_core.py`; `breadcrumbs/hooks_prompt.py`; `breadcrumbs/hooks_compact.py`.

**Create, if needed:** `breadcrumbs/service.py`; `tests/test_application_parity.py`.

**Implementation sequence**

1. Move ownership of repaired domain operations out of cli.py while retaining compatible forwarding names where needed.
2. Introduce an explicit per-operation context for root, clock, policy, and consumer; remove reliance on shared mutable store-specific globals from the new path.
3. Route CLI, MCP, and hooks through the same application methods. Keep transport output, argument parsing, and host payload mapping at the edges.
4. Use import-direction tests and before/after serialized-output parity rather than a cosmetic file-size target.

**Named acceptance tests / checks**

- `test_service_import_does_not_import_cli_parser`
- `test_cli_mcp_and_hook_admission_parity`
- `test_two_store_contexts_do_not_share_alias_or_policy_state`
- `test_refactor_preserves_ids_scores_and_wire_contracts`

**Done when:** The CLI is an adapter for the repaired operations rather than the dependency every internal module must import.

<a id="wp17"></a>

### WP17. Qualify adapters, MCP contracts, and native platforms

**Priority / complexity:** P1 coverage / P2 expansion / L | **Dependencies:** WP04, WP05, WP08, WP09, WP11, WP13 | **Findings:** F22, F25

**Modify:** `breadcrumbs/mcp_server.py`; `breadcrumbs/cli.py`; `.github/workflows/ci.yml`; `docs/mcp-spec.md`.

**Create, if needed:** `breadcrumbs/adapters/claude.py`; `tests/test_adapter_contracts.py`; `docs/compatibility-matrix.md`.

**Implementation sequence**

1. Create normalized host payload fixtures and versioned capability declarations. Add supported PowerShell/NotebookEdit handling rather than relying on accidental regex matching.
2. Test native Windows and macOS package install, quoting, Unicode output, path replacement, locks, and replay cleanup; retain the Linux/Python/MCP matrix.
3. Verify actual MCP tools/resources/errors across the supported SDK versions and add appropriate advisory annotations without treating them as access control.
4. Publish which harnesses support files, CLI, MCP, capture hooks, prompt retrieval, and guard hooks. Use documented mechanisms for each host; do not invent unsupported hook parity.

**Named acceptance tests / checks**

- `test_supported_tool_names_normalize_expected_actions`
- `test_mcp_errors_and_resources_match_versioned_contract`
- Native platform smoke jobs include installed-wheel execution.
- A cross-harness resume uses the same canonical record IDs and effective rules.

**Done when:** Advertised capabilities correspond to tested host/platform/version combinations, and unsupported surfaces are clearly identified.

<a id="wp18"></a>

### WP18. Add delivered-context evaluation and non-negotiable critical gates

**Priority / complexity:** P1 / M | **Dependencies:** WP00 | **Findings:** F19

**Modify:** `evals/run.py`; `evals/README.md`; `evals/baseline.json`; `tests/test_evals.py`; `.github/workflows/ci.yml`.

**Create, if needed:** `evals/critical/`; `evals/delivery/`.

**Implementation sequence**

1. Preserve old ranking diagnostics and their definitions; add separate actual-delivery evaluation instead of silently changing metric meanings.
2. Invoke complete hooks and serialize packets in real order. Score emitted revisions, exclusions, budget cost, and negative controls.
3. Create critical assertions independent of aggregate baselines. Keep unresolved critical failures visible during the repair program; require all supported critical cases to pass at release.
4. Require reviewed task-level deltas for baseline updates, with fixed holdout scenarios and explicit waivers for unsupported capabilities rather than laundering a known bug into the baseline.

**Named acceptance tests / checks**

- `test_baseline_cannot_approve_critical_false_safe`
- `test_delivery_metric_includes_recency_noise_and_wrappers`
- `test_hook_length_dedupe_and_render_paths_are_evaluated`
- `test_metric_definitions_and_denominators_are_serialized`

**Done when:** A green release gate means the stated critical scenarios pass, not only that averages did not fall below previously accepted failures.

<a id="wp19"></a>

### WP19. Demonstrate real continuity value with controlled task replays

**Priority / complexity:** P2 / L | **Dependencies:** WP15, WP17, WP18 | **Findings:** F26

**Modify:** none.

**Create, if needed:** `evals/task_replays/`; `docs/benchmarks/continuity-results.md`; `docs/demos/two-session-handoff.md`.

**Implementation sequence**

1. Build the three-baseline experiment described in Section 7 with independent task oracles and at least three real repositories.
2. Include repeated-failure, changed-decision, compaction, branch-switch, and cross-harness scenarios; count capture/maintenance overhead.
3. Publish scripts, sanitized inputs, versions, denominators, uncertainty, failure examples, and limitations. Avoid unverifiable adoption or savings claims.
4. Produce a small repeatable demo showing one specific mistake avoided by a later session, with the memory/evidence trail visible.

**Named acceptance tests / checks**

- An independent rerun can reproduce the task oracle and inspect the surfaced record revision.
- No-memory and minimal-Markdown baselines use comparable task/harness conditions.
- All reported cost includes maintenance and retries.

**Done when:** The project has defensible task-level evidence and an understandable demonstration, not only a large feature list.

<a id="wp20"></a>

### WP20. Make onboarding and ongoing operation understandable

**Priority / complexity:** P2 / M | **Dependencies:** WP08, WP14, WP17, WP21 | **Findings:** F24, F26

**Modify:** `README.md`; `docs/cli-spec.md`; `docs/security.md`; `CONTRIBUTING.md`; `.project-memory/handoff.md`.

**Create, if needed:** `docs/quickstart.md`; `docs/operator-guide.md`; `docs/continuity-contract.md`.

**Implementation sequence**

1. Create a short golden path: install, init, record one decision, resume, inspect evidence, and recover from a deliberate stale/invalid state. Move detailed reference material without deleting it.
2. Explain capture versus durable memory versus standing rules; clarify supported profiles, privacy, budgets, unsupported platforms, and what guard does not authorize.
3. Improve doctor/recovery guidance for degraded indexes, pending operations, unsupported hooks, and invalid legacy records. Reconcile the default handoff after merged/released work.
4. Document a contributor path for one failing scenario, one regression, and one evidence-backed fix.

**Named acceptance tests / checks**

- Clean-checkout quickstart works with the installed package.
- A reader can identify why a memory surfaced and how to retire or correct it.
- Default-branch handoff does not direct the next agent to redo completed phases.

**Done when:** New users can get value and understand limitations without reading a 13,000-line implementation or an entire command catalog.

<a id="wp21"></a>

### WP21. Approve and test the compatibility and migration policy

**Priority / complexity:** P1 prerequisite for semantic changes / M | **Dependencies:** WP01, WP06 | **Findings:** F05, F18, F24

**Modify:** `breadcrumbs/migrate.py`; `docs/record-schema.md`; `RELEASING.md`; `tests/test_migrate.py`.

**Create, if needed:** `docs/compatibility.md`; `tests/test_store_upgrade_contract.py`.

**Implementation sequence**

1. Reconcile package, canonical schema, projection, index, and wire versions. Decide the pre-1.0 breaking-change policy before shipping stricter semantics.
2. Classify legacy free scopes, invalid metadata, reviewed-state enforcement, archived links, and unknown fields. Determine which changes need migration versus a rebuild.
3. Implement only the approved migrations with preview, verified backup, interruption recovery, stable IDs, and explicit reader requirements.
4. Test upgrade/downgrade boundaries and preserve the existing release workflow rather than inventing a second tagging/publishing process.

**Named acceptance tests / checks**

- `test_upgrade_preserves_content_ids_scope_and_unknown_fields`
- `test_interrupted_migration_is_resumable_and_backup_restores`
- `test_old_reader_cannot_silently_misinterpret_new_authority_semantics`
- Documentation/version policy matches actual emitted manifests and package behavior.

**Done when:** An operator can predict what an upgrade changes, recover safely, and distinguish compatible metadata additions from changes that old readers must not ignore.

<a id="wp22"></a>

### WP22. Apply release gates and publish an evidence-backed release

**Priority / complexity:** P2 / M | **Dependencies:** WP14, WP16, WP17, WP19, WP20, WP21 | **Findings:** F26

**Modify:** `RELEASING.md`; `.github/workflows/ci.yml`.

**Create, if needed:** `docs/releases/reliability-release-checklist.md`.

**Implementation sequence**

1. Run the complete acceptance matrix and collect the exact build/source hashes, supported platforms/harnesses, migrations, and known limitations.
2. Require critical correctness/security gates to pass. Review baseline changes, dependency changes, sensitive memory changes, and publication artifacts separately.
3. Publish the bounded demo, reproducible benchmark report, contribution instructions, and a plain statement of what remains experimental.
4. Use the existing reviewed release process. Public communication should report demonstrated outcomes and AI-assisted development honestly, without invented novelty, adoption, or reliability claims.

**Named acceptance tests / checks**

- Release artifact installs and passes the supported-platform smoke tests.
- Every supported critical scenario is green and every unresolved exclusion is explicit.
- Published results identify source revision, methodology, and reproducible artifacts.

**Done when:** The public release is supported by verifiable behavior, a clear operating contract, and evidence that another developer can inspect and reproduce.

### 8.1 Practical execution order

After WP00, the first independent starting points are WP01, WP02, WP05, WP13, and WP18. Do not let optional product work delay these. An individual coding agent should choose one package, not run every ready package in the same branch.

A reasonable single-agent sequence is:

```text
WP00 -> WP01 -> WP02 -> WP03 -> WP04 -> WP05 -> WP06
     -> WP07 -> WP08 -> WP09 -> WP18 -> WP10 -> WP11
     -> WP12 -> WP13 -> WP21 -> WP14 -> WP15 -> WP16
     -> WP17 -> WP19 -> WP20 -> WP22
```

Dependencies, not numeric order, are authoritative. Path containment and measurement work can be pulled earlier by separate workers with non-overlapping ownership. Do not dispatch parallel writers into the same checkout to work on the lock/reindex core before that concurrency model is qualified.

### 8.2 Deliberate non-goals for the stabilization program

Do not add a mandatory vector database, hosted service, full transcript archive, automatic contradiction resolver, automatic deletion based on usage, universal human approval for ordinary notes, or an entirely new application framework. Do not change guard exit codes by default or rename existing IDs for cosmetic reasons.

A semantic candidate retriever, optional LLM extraction assistant, a read-only inspector UI, richer task/session handoffs, and language-specific tokenizers can be proposed later. Each needs a concrete unmet use case, an isolated integration contract, privacy/cost boundaries, and measured value against the repaired baseline. Feature count is not a release criterion.

<a id="section-9"></a>

## 9. Release gates and a credible public launch

### 9.1 Three milestones, not invented release dates

**Reliability repair milestone.** Close the reproduced capture, promotion, replay, validation, locking, snapshot, retrieval, guard, containment, and packet-contract failures relevant to the supported configuration. Keep changes narrow and ship compatible fixes as they become verified. Do not wait for an optional semantic feature to repair a false verification claim.

**Qualified continuity milestone.** Complete the shared application path, review/capability contract, native-platform qualification, migration tests, delivered-context evaluations, and realistic scale measurements. Publish a support matrix that distinguishes stable core behavior from adapter-specific or experimental functionality.

**Evidence-backed public milestone.** Release the repeatable multi-session/cross-harness demonstration and real-task results with their controls and limitations. Another developer should be able to reproduce the claimed benefit without trusting a promotional paragraph or the agent that wrote the code.

### 9.2 What deserves to be prominent in the project story

The strongest positioning is not "another AI memory database." It is **portable project continuity with inspectable evidence, explicit uncertainty, and honest recovery when something goes wrong**. Demonstrate three things visibly: the record that explained an old decision, the known failure that a later session avoided, and the supersession/recheck that stopped old information from masquerading as current.

AI-assisted implementation can be part of the story. Pair it with a public audit trail: a failing reproduction, a focused fix, a regression test, and a measurable result. Do not describe review labels as proof, repeat a benchmark percentage without its denominator, or claim a first/best status without comparative evidence.

The likely foundation of community interest is usefulness and reproducibility. Attention and reputation are outcomes to earn; this roadmap cannot guarantee them.

### 9.3 Operator and repository safeguards

Protect sensitive code/configuration, baseline changes, and high-impact memory changes with a review process suited to the deployment. GitHub's branch response at the reviewed moment reported the branch-protection flag disabled; that observation alone is not a complete audit of organization/repository rulesets. Inspect the actual rules and bypass permissions before changing anything.

Use required checks and least-privilege credentials where they provide a genuine independent boundary. A coding agent holding the owner's unrestricted administrative credentials can often bypass controls the owner meant it to obey. Repository settings changes and release publication require explicit operator authorization; this report does not perform or authorize them.

<a id="section-10"></a>

## 10. Coding-agent execution protocol

Use the following as the operational handoff when this report is uploaded:

> Read `docs/reviews/2026-09-26-breadcrumbs-audit-and-roadmap.md` and the work-package tracker. Inspect the current repository revision and do not assume the audit line numbers still match. Start with WP00 unless the user names a different dependency-ready package. Reproduce the selected finding, add a failing regression, implement only that package, and verify the positive, negative, compatibility, and failure cases. Do not reset evaluation baselines to hide a regression. Do not silently widen scope, raise confidence, remove historical evidence, change default exit codes, or make schema/authority changes outside the approved package. Record commands, exit codes, source revision, and limitations. Stop after the selected package and present the result for review.

For each package, record: starting/ending commit, changed paths, reproduced cause, tests added, commands/results, migration/compatibility impact, remaining limitations, and a link to its review. The tracker status sequence should be `not_started -> in_progress -> review_required -> completed`; use `blocked` with a concrete dependency or evidence gap. A completed status requires evidence, not the author's assertion that the work is done.

When a finding is no longer reproducible, record the actual revised behavior and source change. Do not delete the original audit evidence or rename the case to make it pass. If the proposed repair proves more complicated than necessary, present a smaller equivalent design that preserves the stated invariants and tests.

**Definition of done for the overall program:** trustworthy capture semantics, preserved meaning/scope, recoverable mutations, coherent provenance, no silent retrieval cliffs, explicit safety/authority boundaries, tested portability, and reproducible task-level benefit within a documented support envelope. That is a stronger foundation for pride in the project than simply adding more commands.

<a id="section-11"></a>

## 11. Evidence inventory and source references

### 11.1 Included files

| File | Purpose |
|---|---|
| `2026-09-26-breadcrumbs-work-packages.json` | Machine-readable dependency/status tracker; all work starts unimplemented |
| `2026-09-26-breadcrumbs-evidence/source-manifest.json` | Pinned source identity and hashes for 21 package modules |
| `2026-09-26-breadcrumbs-evidence/probe-results.json` | Final 19 diagnostic results, with controlled-fault labels |
| `2026-09-26-breadcrumbs-evidence/probe-results.log` | Readable final diagnostic output |
| `2026-09-26-breadcrumbs-evidence/selected-tests.json` and `.log` | 243-test local subset, explicit exclusions, and results |
| `2026-09-26-breadcrumbs-evidence/original-tests.log` | Initial 248-test attempt, retained for transparency |
| `2026-09-26-breadcrumbs-evidence/environment-startup.txt` | Why the pristine-interpreter assertion was not applicable locally |
| `2026-09-26-breadcrumbs-evidence/benchmark-smoke.json` and `.log` | Small in-process synthetic timings; not production SLO results |
| `2026-09-26-breadcrumbs-evidence/ci-observation.json` | Observed remote CI/release results and eval misses |
| `tools/audit/regression_probes.py` | Safe temporary-store reproductions; `--fail-on-observed` gives a nonzero result for observed defects |
| `tools/audit/run_selected_tests.py` | Repeats the explicitly selected upstream-test subset; not a substitute for full CI |
| `tools/audit/benchmark_smoke.py` | Repeats the limited scale/timing experiment |

The scripts are audit tools for the pinned implementation. Convert their cases into ordinary focused regression tests before using them as a long-term release gate. A script setup error is not a fixed bug. Run them only against code you trust; importing any repository's Python code executes that code.

### 11.2 Pinned repository evidence

Source references beside each finding point to the exact audited commit, not moving `main`. Broad design context is in [architecture.md](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/docs/architecture.md), [record-schema.md](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/docs/record-schema.md), [security.md](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/docs/security.md), [MCP specification](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/docs/mcp-spec.md), and [field-test.md](https://github.com/jr-mccoy/breadcrumbs/blob/30e41f6a36195faffdc197d0565abc7caf7c78da/docs/field-test.md).

Remote results: [CI run 36083137724](https://github.com/jr-mccoy/breadcrumbs/actions/runs/36083137724), [evaluation job 107909193816](https://github.com/jr-mccoy/breadcrumbs/actions/runs/36083137724/job/107909193816), and [release run 36083177179](https://github.com/jr-mccoy/breadcrumbs/actions/runs/36083177179). These are remote observations, distinct from the local probe and selected-test evidence.

### 11.3 External primary documentation checked September 26, 2026

[Claude Code hooks reference](https://code.claude.com/docs/en/hooks) documents the PowerShell tool/matcher and current event/payload contracts. It supports the adapter-coverage finding; this review did not run a live Claude Code session to qualify every documented event.

[MCP tool specification, version 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) is the referenced protocol contract for tool results, errors, and client-facing safety semantics. Version-specific SDK behavior still requires runtime tests; annotations do not substitute for operator authorization.

[Python `os` documentation](https://docs.python.org/3/library/os.html) and [Python `fcntl` documentation](https://docs.python.org/3/library/fcntl.html) describe the low-level filesystem/locking primitives relevant to atomic replacement, flushing, and POSIX locking. They are not evidence that this project has already implemented crash durability or Windows locking correctly.

---

**End of report.** All proposed product work remains unimplemented until a work package is executed and verified. The attached evidence characterizes the audited release; it is not a certification of all possible uses of agentic memory.

