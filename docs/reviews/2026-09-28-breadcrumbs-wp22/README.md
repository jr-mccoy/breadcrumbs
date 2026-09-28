# WP22: release gates and an evidence-backed release, prepared (2026-09-28)

This implements work package WP22 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), finding F26,
**up to the point where the operator decides**. The starting commit is
`529356e`. The operator authorized the remaining work on 2026-09-27, and
asked on 2026-09-28 to limit how often the native full suite runs.

Nothing was released. At the operator's request the branch carries the bump
to `0.4.0` (version, CHANGELOG section, compatibility row), so they can run
`release.yml` after merging. No tag, GitHub Release, merge to `main` or upload
was made.

## Change

- **[`docs/releases/reliability-release-checklist.md`](../../releases/reliability-release-checklist.md)**
  (new), covering:
  - the source revision and the commits since `v0.3.1`;
  - why the next version is 0.4.0 and not a patch;
  - reference build hashes;
  - the acceptance matrix, with the CI run behind each gate;
  - the reviews a green suite does not do: evaluation baselines,
    dependencies, this repository's memory, publication artifacts and audit
    evidence;
  - what is explicitly not claimed;
  - the published material;
  - draft release notes, honest that an AI coding agent did the work and
    that seven packages await a person's review;
  - the operator's steps, in order.
- **`RELEASING.md`** points to the checklist.
- **`.github/workflows/ci.yml`** (`a8c3960`, at the operator's request). The
  native full suite moves to a `native-full` job that runs on `main`, weekly
  and on demand. Every push still gates on the installed-wheel smoke test and
  the contract tests on Windows and macOS. `native-full` stays reported, not
  gating: its failure turns the job red, but not the run.

## Decisions left to the operator

- **Whether the native full suite should gate.** It was green on all four
  combinations in run 248. Gating it would make every push to `main` wait up
  to 25 minutes on Windows, and would put a runner-image flake between a
  merge and a release. The checklist instead asks the operator to read the
  `native-full` jobs on the merge commit before publishing.
- **The release itself**: the review of the `review_required` packages, the
  merge, the version bump, and `release.yml` dry-run then publish.

## Evidence

| Check | Result |
|---|---|
| CI run 249 (`529356e`) | 23 jobs green; `native-full` skipped on the branch push, as designed |
| CI run 248 (`9b55822`), native full suite | 1,365 run, 0 failures on Windows and macOS, Python 3.9 and 3.13 |
| Local build of `529356e` | wheel and sdist built; hashes in the checklist |
| Audit evidence (`docs/reviews/2026-09-26-breadcrumbs-evidence/`, `tools/audit/`, the roadmap) | unchanged since `31e56da`, the commit that added them |
| Critical eval gate (`evals/run.py --release`) | 20 of 20 pass (local, on `529356e`) |

**The roadmap's acceptance checks:**
- *Release artifact installs and passes the supported-platform smoke tests.*
  Yes, on every push: `native` installs the built wheel on Windows and macOS,
  and `package` does so on Linux. `release.yml` repeats the Linux check on the
  artifact it publishes.
- *Every supported critical scenario is green and every unresolved exclusion
  is explicit.* 20 of 20 critical cases pass. The exclusions are in checklist
  section 4.
- *Published results identify source revision, methodology, and reproducible
  artifacts.* The checklist names the revision and runs. The benchmark report
  names its scripts, inputs and results file, and a test reruns them.

## Limits

- **Not done until the operator releases.** The WP's "done when" is a public
  release, which is the operator's decision.
- **The build hashes are for reference.** They are for the 0.4.0 artifacts
  of `8242861`, and a build is not byte-reproducible. The artifacts that
  matter are the ones `release.yml` builds on the merge commit it tags.
- **The native full suite does not gate.** The reason is above.
