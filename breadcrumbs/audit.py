"""breadcrumbs — `crumb audit`: the heuristic health view of a store.

`run_audit` collects advisory findings: a stale handoff, aged, expired or
low-confidence records, branch mismatch, instruction-like text, generated
packet drift, bloat, records never surfaced, and the validate failures again
for the health view. Only a secret leak is a FAIL.

Moved out of `cli.py` (health review 2.1). `cli.cmd_audit` renders it.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from breadcrumbs import cli
from breadcrumbs import git as _git
from breadcrumbs import packet as _packet
from breadcrumbs import path_policy
from breadcrumbs import scoring as _scoring
from breadcrumbs import secretscan as _secretscan
from breadcrumbs import textmatch as _textmatch
from breadcrumbs import validate as _validate
from breadcrumbs import validation as _validation


# --------------------------------------------------------------------------- #
# audit + scan-secrets — heuristic safety net
# --------------------------------------------------------------------------- #
#
# Design split: `validate` is deterministic and GATES; `audit`
# is heuristic and ADVISES. The one hard non-zero in audit is a secret leak — a
# token-like string in committed memory must block any "commit memory" workflow
# (§2.6, §15). Everything else — stale handoff, aged/expired/low-confidence
# records, branch mismatch, instruction-like text, generated-packet drift, bloat,
# and the validate-failing conditions re-surfaced for the health view — is a WARN
# (or INFO) and never flips the exit code on its own.
#
# Matched memory text is DATA, never instruction (§15, Fixture 7): the
# instruction-like heuristic only *flags* override phrasing for a human reviewer;
# audit never acts on it, exactly as `guard` ranks-but-never-executes record text.


# Severity ladder for audit findings.
AUDIT_FAIL = "fail"  # blocks (non-zero) — secrets only
AUDIT_WARN = "warn"  # flag for human review — never changes the exit code
AUDIT_INFO = "info"  # health/context note

# A record has to be old enough that never having been reached is a fact about
# the record rather than about the week. Bounded, because a neglected store
# would otherwise report every record it has.
AUDIT_NEVER_SURFACED_DAYS = 90
AUDIT_NEVER_SURFACED_MAX = 10
# WM-60: `crumb usage --decay`'s window, and how many candidates audit names.
DECAY_DAYS_DEFAULT = 180
AUDIT_DECAY_MAX = 10


# Bloat thresholds (heuristic).
ADAPTER_FILENAMES = (
    "AGENTS.md",
    "CLAUDE.md",
    ".cursorrules",
    ".clinerules",
    ".windsurfrules",
    ".github/copilot-instructions.md",
)
ADAPTER_BLOAT_CHARS = 4000  # signpost files should be small pointers, not copies
SESSIONS_GROWTH_NOTE = 50  # session count above which audit suggests promoting + pruning
# The always-on trap budget. Generous — a store of real traps is worth carrying —
# but bounded, because nothing else bounds it: the field store reached 167 KB and
# 77 active traps with no mechanism for anything to leave.
TRAPS_TOKEN_BUDGET = 8000


def _audit_bloat(memory_dir: Path, root: Path) -> list[dict]:
    """Bloat heuristics: over-budget packet, adapter duplication,
    runaway sessions/ growth."""
    memory_dir = Path(memory_dir)
    findings: list[dict] = []

    # Packet over budget.
    pkt = memory_dir / "generated" / "resume-packet.md"
    if pkt.is_file():
        # Lenient throughout: audit is the gate command, so an
        # undecodable file must cost it one heuristic, not every finding it had.
        toks = _packet.approx_tokens(cli.read_text_lenient(pkt)[0])
        if toks > _packet.TOKEN_BUDGET_MAX:
            findings.append(
                {
                    "kind": "packet-over-budget",
                    "path": "generated/resume-packet.md",
                    "message": f"resume packet ~{toks} tokens exceeds the {_packet.TOKEN_BUDGET_MAX}-token budget",
                }
            )

    # Adapter/signpost files duplicating canonical memory rather than pointing to it.
    canon: list[tuple[str, str]] = []
    for rec in cli.load_records(memory_dir):
        if not rec.error and rec.body.strip():
            canon.append((path_policy.posix_rel(rec.path, memory_dir), rec.body.strip()))
    for name in ADAPTER_FILENAMES:
        ap = Path(root) / name
        if not ap.is_file():
            continue
        text = cli.read_text_lenient(ap)[0]
        # The promoted-rules block (WM-40) mirrors records on purpose; only the
        # rest of the file is judged for copying memory into it.
        from breadcrumbs import promote as _promote

        unpromoted = _promote.strip_block(text)
        dup = next(
            (src for src, body in canon if len(body) >= 200 and body[:200] in unpromoted), None
        )
        if dup:
            findings.append(
                {
                    "kind": "adapter-duplication",
                    "path": name,
                    "message": (
                        f"adapter '{name}' copies memory record {dup} verbatim; "
                        "signpost files should point into memory, not duplicate it (§16.13)"
                    ),
                }
            )
            continue
        # Measure the managed block, not the host file. A repo's own
        # CLAUDE.md/AGENTS.md is legitimately large and is not ours to judge; what
        # §16.13 asks is that *our* signpost stay a small pointer. A file with no
        # managed block is not a signpost at all, so there is nothing to size —
        # `adapter-duplication` above still catches records copied into it.
        block = cli.managed_block_text(text)
        if block is not None and len(block) > ADAPTER_BLOAT_CHARS:
            findings.append(
                {
                    "kind": "adapter-bloat",
                    "path": name,
                    "message": (
                        f"the breadcrumbs managed block in '{name}' is {len(block)} chars; "
                        "the signpost should be a small pointer into memory, not a large "
                        "copy (§16.13)"
                    ),
                }
            )

    # known-traps.md growth. Unlike the packet, nothing bounds this file: traps
    # are appended and never age out, and every session loads all of them. The
    # check names the report that makes retirement possible — traps are
    # retired one by one, never rolled up.
    # From schema 3 the file is a one-line-per-trap index, so measure what the
    # packet and the hooks actually carry: the active traps' own text.
    from breadcrumbs import blockfiles as _blockfiles

    traps_path = memory_dir / "known-traps.md"
    if traps_path.is_file():
        traps = [t for t in cli.load_traps(memory_dir) if (t.get("status") or "active") == "active"]
        if _blockfiles.uses_files(memory_dir):
            toks = sum(_packet.approx_tokens(f"## {t['heading']}\n{t['body']}") for t in traps)
        else:
            toks = _packet.approx_tokens(cli.read_text_lenient(traps_path)[0])
        if toks > TRAPS_TOKEN_BUDGET:
            findings.append(
                {
                    "kind": "traps-growth",
                    "path": "known-traps.md",
                    "message": (
                        f"{len(traps)} active trap(s), ~{toks} tokens of always-on context "
                        f"(budget {TRAPS_TOKEN_BUDGET}) — `crumb traps --stale` lists the "
                        "ones nobody has confirmed lately; retire one with "
                        "`crumb mark-status <id> stale`"
                    ),
                }
            )

    # sessions/ growth note. The advice is what a human can do today: promote the
    # durable parts, then fold old machine snapshots into one record with
    # `crumb rollup sessions` (WM-35) or drop them with `crumb prune sessions`.
    sess = memory_dir / "sessions"
    n = len(list(sess.glob("*.md"))) if sess.is_dir() else 0
    if n > SESSIONS_GROWTH_NOTE:
        findings.append(
            {
                "kind": "sessions-growth",
                "path": "sessions/",
                "message": (
                    f"{n} session records — promote what still matters with `crumb "
                    "remember`, then `crumb rollup sessions --before YYYY-MM-DD` to fold "
                    "old machine snapshots into one record (or `crumb prune sessions` to "
                    "drop them) so the store stays navigable"
                ),
            }
        )
    return findings


# ---- audit core ------------------------------------------------------------ #

# validate-failing checks audit re-surfaces in its health view. These still gate
# `validate`; audit reports them so one pass shows the whole health picture (§19b.9).
_AUDIT_HEALTH_CHECKS = {"evidence", "status", "privacy", "superseded", "identity", "frontmatter"}


def _audit_finding(check: str, severity: str, path: str | None, message: str, **extra) -> dict:
    f = {"check": check, "severity": severity, "path": path, "message": message}
    f.update(extra)
    return f


# ---- decision staleness (health review 1.1) -------------------------------- #
#
# A decision staying unchanged for a month is the normal case, not a finding.
# "Active decision … is N days old with no update — is this still true?" was 17
# of this store's 21 audit warnings, and when most of the output is noise the
# one warning that matters is not read. Nor is "a cited file changed since":
# in a codebase under work, the files a decision cites usually do, and keyed on
# that alone 48 of this store's 56 active decisions warned. Staleness is keyed
# on how much the evidence moved:
#
# - `decision-evidence-rewritten` (WARN): since the decision was written, a
#   file it cites has been churned by at least AUDIT_EVIDENCE_REWRITE_SHARE of
#   its current size. Not counted: a hub file (one most commits touch, so a
#   change to it says nothing about this decision), and the decision's own
#   landing — the commit that created a cited file, or the first commit that
#   touched a file that was uncommitted when the decision was recorded.
# - `decision-evidence-changed` (INFO, one line): the decisions whose cited
#   files changed by less than that; `--json` lists them.
# - `possible-contradiction` and `evidence-missing-file` (WARN, lifecycle): a
#   newer record argues with it, or a file it cites is gone.
# - `decision-aged` (INFO): none of the above, and older than
#   AUDIT_DECISION_AGE_FACTOR times the age cutoff. Once per record, and only
#   here: the resume packet carries no age line for a decision.
#
# On this store at the start of this work (main at b8266a3) that is 6 warnings
# where the age rule gave 17. The history costs two git processes for the whole
# store, both bounded by `cli._REVLIST_INDEX_CAP`: HEAD's ancestry with parents,
# and the commits that touched any cited file, with line counts.

AUDIT_EVIDENCE_REWRITE_SHARE = 0.5
AUDIT_EVIDENCE_HUB_SHARE = 0.15
# Below this many commits of history nothing is a hub: in a young repository
# every file is touched by a large share of a handful of commits.
AUDIT_EVIDENCE_HUB_MIN_COMMITS = 40
AUDIT_DECISION_AGE_FACTOR = 8
AUDIT_EVIDENCE_FILES_SHOWN = 3
AUDIT_EVIDENCE_IDS_SHOWN = 5


class _Touch:
    __slots__ = ("sha", "time", "subject", "churn", "created")

    def __init__(self, sha: str, time: int, subject: str):
        self.sha, self.time, self.subject = sha, time, subject
        self.churn: dict[str, int] = {}  # path -> lines added + deleted
        self.created: set[str] = set()


class _EvidenceHistory:
    """HEAD's recent ancestry, and the commits that touched the cited files."""

    def __init__(self, root: Path, files: list[str]):
        self.root = root
        self.parents: dict[str, list[str]] = {}
        self.touching: list[_Touch] = []  # newest first
        self._ancestors: dict[str, set[str]] = {}
        cap = cli._REVLIST_INDEX_CAP
        graph = _git.run(
            root, "rev-list", "--topo-order", "--parents", f"--max-count={cap}", "HEAD"
        )
        for line in (graph or "").splitlines():
            shas = line.split()
            if shas:
                self.parents[shas[0]] = shas[1:]
        if not self.parents or not files:
            return
        # Paths relative to the project root on both sides (`--relative`),
        # unquoted, and no rename pairing: a renamed evidence file is gone,
        # which `evidence-missing-file` reports.
        log = _git.run(
            root,
            "-c",
            "core.quotepath=off",
            "log",
            f"--max-count={cap}",
            "--relative",
            "--no-renames",
            "--numstat",
            "--summary",
            "--format=%x00%H %ct %s",
            "HEAD",
            "--",
            *files,
        )
        for chunk in (log or "").split("\0")[1:]:
            head, _, rest = chunk.partition("\n")
            sha, _, tail = head.partition(" ")
            stamp, _, subject = tail.partition(" ")
            if not sha or not stamp.isdigit():
                continue
            touch = _Touch(sha, int(stamp), subject)
            for line in rest.splitlines():
                cols = line.split("\t")
                if len(cols) == 3:
                    added, deleted, path = cols
                    lines = (int(added) if added.isdigit() else 0) + (
                        int(deleted) if deleted.isdigit() else 0
                    )
                    touch.churn[_git.unquote_path(path.strip())] = lines
                elif line.startswith(" create mode "):
                    touch.created.add(_git.unquote_path(line.split(" ", 4)[-1].strip()))
            self.touching.append(touch)

    def hubs(self) -> set[str]:
        """Paths most commits touch: a change to one says nothing in particular."""
        if len(self.parents) < AUDIT_EVIDENCE_HUB_MIN_COMMITS:
            return set()
        counts: dict[str, int] = {}
        for t in self.touching:
            for path in t.churn:
                counts[path] = counts.get(path, 0) + 1
        bar = AUDIT_EVIDENCE_HUB_SHARE * len(self.parents)
        return {path for path, n in counts.items() if n > bar}

    def _resolve(self, commit: str) -> str | None:
        """The full sha in the window that `commit` (any abbreviation) names."""
        if not commit or commit == cli.NO_GIT_COMMIT:
            return None
        hits = [sha for sha in self.parents if _git.same_commit(commit, sha)]
        return hits[0] if len(hits) == 1 else None

    def _ancestors_of(self, sha: str) -> set[str]:
        if sha not in self._ancestors:
            seen, stack = set(), [sha]
            while stack:
                cur = stack.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                stack.extend(p for p in self.parents.get(cur, ()) if p in self.parents)
            self._ancestors[sha] = seen
        return self._ancestors[sha]

    def since(self, commit: str, written_at) -> list[_Touch]:
        """The touching commits made after the one a record was written at.

        By ancestry when the record's commit is in the window: a commit that
        is not its ancestor landed afterwards (a side branch merged later
        included). For an older commit git confirms it exists, and every
        commit in the window is then newer. A commit this clone does not have
        (a rebase, a record written elsewhere) falls back to commit time
        against the record's own timestamp.
        """
        base = self._resolve(commit)
        if base is not None:
            before = self._ancestors_of(base)
            return [t for t in self.touching if t.sha in self.parents and t.sha not in before]
        if commit and commit != cli.NO_GIT_COMMIT:
            known = _git.run(self.root, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}")
            if known:
                return [t for t in self.touching if t.sha in self.parents]
        when = _validation.parse_timestamp(written_at)
        if when is None:
            return []
        if when.tzinfo is None:
            when = when.astimezone()
        return [t for t in self.touching if t.time > when.timestamp()]


def _covers(cited: str, path: str) -> bool:
    return path == cited or path.startswith(cited + "/")


def _cited_files(root: Path, rec) -> list[str]:
    """The files a record cites as evidence that exist here, store files aside."""
    out = []
    for ref in cli._evidence_refs(rec, ("file",)):
        p = path_policy.to_posix(ref).strip()
        while p.startswith("./"):
            p = p[2:]
        p = p.rstrip("/")
        parts = PurePosixPath(p).parts
        if not p or PurePosixPath(p).is_absolute() or ".." in parts:
            continue
        if parts[0] == cli.MEMORY_DIRNAME:
            continue
        if (Path(root) / p).exists():  # a gone file is `evidence-missing-file`'s
            out.append(p)
    return sorted(set(out))


def _line_count(path: Path) -> int | None:
    """Lines in a text file; None for a directory or a binary file."""
    try:
        data = path.read_bytes() if path.is_file() else None
    except OSError:
        return None
    if data is None or b"\0" in data[:8192]:
        return None
    return max(1, data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1))


def evidence_churn(rec, files: list[str], history: _EvidenceHistory) -> dict[str, list[int]]:
    """`{file: [lines churned, commits]}` since `rec` was written, its landing excluded."""
    dirty = [
        path_policy.to_posix(d).rstrip("/")
        for d in rec.meta.get("dirty_files") or []
        if isinstance(d, str)
    ]
    was_dirty = lambda f: any(_covers(d, f) or _covers(f, d) for d in dirty)  # noqa: E731
    written = rec.meta.get("updated_at") or rec.meta.get("created_at")
    landed: set[str] = set()
    out: dict[str, list[int]] = {}
    for t in reversed(history.since(str(rec.meta.get("commit") or ""), written)):  # oldest first
        hit = {f for f in files if any(_covers(f, path) for path in t.churn)}
        made = {f for f in hit if any(_covers(f, path) for path in t.created)}
        land = {f for f in hit - made if was_dirty(f) and f not in landed}
        landed |= made | land
        for f in hit - made - land:
            row = out.setdefault(f, [0, 0])
            row[0] += sum(n for path, n in t.churn.items() if _covers(f, path))
            row[1] += 1
    return out


def _questioned_ids(findings) -> set[str]:
    ids: set[str] = set()
    for f in findings:
        if f.get("severity") in (AUDIT_WARN, AUDIT_FAIL):
            if f.get("id"):
                ids.add(str(f["id"]))
            ids.update(str(i) for i in f.get("ids") or ())
    return ids


def decision_staleness_findings(
    memory_dir: Path, root: Path, decisions: list, stale_days: int, prior=()
) -> list[dict]:
    """`decision-evidence-rewritten`, `decision-evidence-changed` and `decision-aged`."""
    findings: list[dict] = []
    cited = {id(rec): _cited_files(root, rec) for rec in decisions}
    every = sorted({f for files in cited.values() for f in files})
    history = _EvidenceHistory(root, every) if every and _git.is_repo(root) else None
    hubs = history.hubs() if history is not None else set()
    sizes = {f: _line_count(Path(root) / f) for f in every}
    rewritten_ids: set[str] = set()
    changed: list[dict] = []
    for rec in decisions:
        rid = rec.meta.get("id", rec.stem)
        files = [f for f in cited[id(rec)] if f not in hubs]
        if not files or history is None:
            continue
        churn = evidence_churn(rec, files, history)
        if not churn:
            continue
        rewritten = sorted(
            f
            for f, (lines, _n) in churn.items()
            if sizes.get(f) and lines >= AUDIT_EVIDENCE_REWRITE_SHARE * sizes[f]
        )
        if not rewritten:
            changed.append({"id": rid, "files": sorted(churn)})
            continue
        shown = ", ".join(
            f"{f} ({churn[f][0] / sizes[f]:.0%} in {churn[f][1]} commit(s))"
            for f in rewritten[:AUDIT_EVIDENCE_FILES_SHOWN]
        )
        more = len(rewritten) - AUDIT_EVIDENCE_FILES_SHOWN
        findings.append(
            _audit_finding(
                "decision-evidence-rewritten",
                AUDIT_WARN,
                path_policy.posix_rel(rec.path, memory_dir),
                f"{rid}: its evidence was rewritten since it was written — {shown}"
                + (f" (+{more} more)" if more > 0 else "")
                + " — is it still true?",
                id=rid,
                files=rewritten,
                churn={f: churn[f][0] for f in rewritten},
            )
        )
        rewritten_ids.add(rid)
    if changed:
        ids = [c["id"] for c in changed]
        more = len(ids) - AUDIT_EVIDENCE_IDS_SHOWN
        findings.append(
            _audit_finding(
                "decision-evidence-changed",
                AUDIT_INFO,
                None,
                f"{len(ids)} active decision(s) cite files changed since they were written, "
                f"none rewritten: {', '.join(ids[:AUDIT_EVIDENCE_IDS_SHOWN])}"
                + (f" (+{more} more; `crumb audit --json` lists them)" if more > 0 else ""),
                ids=ids,
                decisions=changed,
            )
        )
    questioned = rewritten_ids | {c["id"] for c in changed} | _questioned_ids(prior)
    limit = stale_days * AUDIT_DECISION_AGE_FACTOR
    for rec in decisions:
        rid = rec.meta.get("id", rec.stem)
        if rid in questioned:
            continue
        age = cli._age_days(rec.meta.get("updated_at") or rec.meta.get("created_at"))
        if age is not None and age > limit:
            findings.append(
                _audit_finding(
                    "decision-aged",
                    AUDIT_INFO,
                    path_policy.posix_rel(rec.path, memory_dir),
                    f"{rid} is {age} days old and nothing has questioned or updated it — "
                    "confirm it still holds, or retire it.",
                    id=rid,
                    age_days=age,
                )
            )
    return findings


def run_audit(memory_dir: Path, root: Path, *, stale_days: int = cli.STALE_AGE_DAYS) -> list[dict]:
    """Heuristic health + safety audit.

    Returns findings tagged with a severity. Only `secret` is fail-severity (blocks);
    everything else advises. Policy-aware: reads tracking policy via the manifest /
    loaders rather than guessing (§7).
    """
    memory_dir = Path(memory_dir)
    findings: list[dict] = []

    # B. Secret scan — the only blocking check (§15, §17.6, Fixture 6).
    for s in _secretscan.scan_secrets(memory_dir):
        if s["pattern"] == "unscannable-file":
            # Blocking, like a secret: the scan could not certify this file, and
            # "we didn't look" must never read as "nothing there".
            findings.append(
                _audit_finding(
                    "secret",
                    AUDIT_FAIL,
                    s["path"],
                    f"{s.get('detail') or 'could not be read'} — the secret scan cannot "
                    "certify this file; fix it before committing memory",
                    pattern=s["pattern"],
                )
            )
            continue
        severity = s.get("severity", AUDIT_FAIL)
        remedy = (
            "must not be committed to memory; remove before any commit"
            if severity == AUDIT_FAIL
            else f"heuristic, not a structured credential shape — confirm, then add a "
            f"pattern to {cli.MEMORY_DIRNAME}/{_secretscan.CRUMBIGNORE_FILENAME} if it is not a secret here"
        )
        findings.append(
            _audit_finding(
                "secret",
                severity,
                s["path"],
                f"possible secret ({s['pattern']}) at line {s['line']} — {remedy}",
                line=s["line"],
                pattern=s["pattern"],
            )
        )

    # A. Staleness / health (reuse compute_staleness): handoff age +
    # commit-distance, branch mismatch (incl. detached HEAD), aged-unresolved
    # questions/decisions, expired + low-confidence records.
    # Lenient read: audit is the gate command, so an undecodable
    # handoff must not abort it. scan_secrets above already emits the blocking
    # `unscannable-file` finding that names the file, so this read stays quiet.
    from breadcrumbs import handoffs as _handoffs

    handoff_text, _problem, handoff_path = _handoffs.read_text(memory_dir, root)
    for w in _packet.compute_staleness(
        root,
        cli.parse_handoff_meta(handoff_text),
        cli.active_decisions(memory_dir),
        cli.active_attempts(memory_dir),
        cli.load_open_questions(memory_dir),
        stale_days,
        memory_dir=memory_dir,
        handoff_path=handoff_path,
    ):
        # The handoff age/distance line is emitted unconditionally; it is only a
        # *warning* when compute_staleness marked it cold (⚠). "handoff is 0
        # day(s) old, written 0 commit(s) behind" on a seconds-old store is
        # health context, not a problem.
        sev = AUDIT_INFO if (w.startswith("handoff is") and not w.startswith("⚠")) else AUDIT_WARN
        findings.append(
            _audit_finding("staleness", sev, path_policy.posix_rel(handoff_path, memory_dir), w)
        )

    # WM-31 / WM-32 / WM-34: evidence that points at a vanished file, live
    # records that say the same thing, and records that may argue with each
    # other. All advisory — each is a question for the author, never a fix.
    from breadcrumbs import lifecycle as _lifecycle

    findings.extend(_lifecycle.audit_findings(memory_dir, root))
    # WM-40/42/43: the promoted-rules block — its size, rules whose record is
    # gone or retired, rules that drifted from their record, and records that
    # have earned a place there.
    from breadcrumbs import promote as _promote

    findings.extend(_promote.audit_findings(memory_dir, root))

    # Decision staleness keyed on evidence, not elapsed time (health review 1.1).
    # After the lifecycle findings, so a decision they already question is not
    # questioned again for its age.
    findings.extend(
        decision_staleness_findings(
            memory_dir, root, cli.active_decisions(memory_dir), stale_days, findings
        )
    )

    # A (cont). Re-surface the validate-failing health conditions for the health view
    # (missing evidence, invalid status, private-path violation, id/frontmatter
    # disagreement). These still FAIL `validate`; audit only reports them (§19b.9).
    for vf in _validate.run_validate(memory_dir):
        if vf["status"] == "fail" and vf["check"] in _AUDIT_HEALTH_CHECKS:
            findings.append(_audit_finding(vf["check"], AUDIT_WARN, vf["path"], vf["message"]))

    # B (cont). A hand-written trap/question block that reindex could not adopt
    # (WM-22): its id belongs to an existing file with different content. The
    # file drives every reader; the block is someone's edit waiting to be merged.
    from breadcrumbs import blockfiles as _blockfiles

    for rid in _blockfiles.unadopted_blocks(memory_dir):
        findings.append(
            _audit_finding(
                "unadopted-block",
                AUDIT_WARN,
                "known-traps.md" if rid.startswith("trap") else "open-questions.md",
                f"{rid} is a hand-written block whose id already has a file with different "
                "content — merge the block into that file by hand, then delete the block",
            )
        )

    # B (cont). A malformed alias line. Audit, not validate: an unusable line is
    # simply skipped by the parser, so the store still works — but the author
    # meant something by it, and silently doing nothing is how a synonym
    # "doesn't work" for a month before anybody reads `_stem`.
    alias_path = memory_dir / _textmatch.ALIASES_FILENAME
    if alias_path.is_file():
        for problem in _textmatch.parse_store_aliases(cli.read_text_lenient(alias_path)[0])[1]:
            findings.append(
                _audit_finding(
                    "aliases",
                    AUDIT_WARN,
                    _textmatch.ALIASES_FILENAME,
                    f"line {problem['line']}: {problem['problem']} — the line is ignored",
                    line=problem["line"],
                )
            )

    # B (cont). Records nothing has ever reached. `audit`'s [unreachable] check
    # asks whether a record *could* be found; this asks whether it ever *was* —
    # the one question only observation can answer. Gated on there being any
    # history at all, because on a fresh clone the answer is "all of them" and
    # that is a fact about the clone, not about the records.
    from breadcrumbs import usage as _usage

    if _usage.has_usage_data(memory_dir):
        # WM-60: old records nothing has surfaced for the whole decay window.
        # Only once this machine has counted that long (`decay_candidates`
        # returns none before). The finding carries the command; nothing runs.
        decaying = _usage.decay_candidates(memory_dir)["candidates"]
        for row in decaying[:AUDIT_DECAY_MAX]:
            findings.append(
                _audit_finding(
                    "decay-candidate",
                    AUDIT_INFO,
                    None,
                    f"{row['id']} is {row['age_days']} days old and nothing has surfaced it "
                    f"in {DECAY_DAYS_DEFAULT} days — if it no longer applies: "
                    f"`{row['command']}`",
                    id=row["id"],
                )
            )
        decaying_ids = {row["id"] for row in decaying}
        never = [r for r in _usage.never_surfaced(memory_dir) if r["id"] not in decaying_ids]
        for row in never[:AUDIT_NEVER_SURFACED_MAX]:
            if (row["age_days"] or 0) < AUDIT_NEVER_SURFACED_DAYS:
                continue
            findings.append(
                _audit_finding(
                    "never-surfaced",
                    AUDIT_INFO,
                    None,
                    f"{row['id']} is {row['age_days']} days old and has never been "
                    "surfaced by a packet or a guard verdict — consider retiring it "
                    "(`crumb mark-status`) or making it reachable (--tags / --evidence file)",
                )
            )

    # C. Instruction-like text (flag only; never a gate — §16 note, Fixture 7).
    for il in _secretscan.scan_instruction_like(memory_dir):
        findings.append(
            _audit_finding(
                "instruction-like",
                AUDIT_WARN,
                il["path"],
                f'override-style phrasing "{il["phrase"]}" at line {il["line"]} — '
                "review (treated as data, never executed)",
                line=il["line"],
                phrase=il["phrase"],
            )
        )

    # D. Generated-packet drift (§15, §17.8, Fixture 8).
    for d in cli.detect_packet_drift(memory_dir):
        findings.append(
            _audit_finding(
                "packet-drift",
                AUDIT_WARN,
                d["path"],
                f"generated projection is stale (stamped inputs_hash {d['stamped']} != "
                f"current {d['current']}) — regenerate with `crumb resume`",
                stamped=d["stamped"],
                current=d["current"],
            )
        )

    # E. Bloat (§16.13, §12).
    for b in _audit_bloat(memory_dir, root):
        sev = AUDIT_INFO if b["kind"] == "sessions-growth" else AUDIT_WARN
        findings.append(_audit_finding("bloat", sev, b["path"], b["message"], kind=b["kind"]))

    # F. Guard reachability (field test 2026-08-04). Guard's strong signals
    # are file and tag overlap; a record carrying neither can only surface through
    # generic keyword overlap, which the stale/branch factors readily push under
    # the noise floor. That is an authoring rule nothing stated: a prose-only
    # record is quietly on its way to unreachable, so say so while the author is
    # still around to add tags or file evidence.
    for rec in cli.load_records(memory_dir, types=_scoring.JUDGING_ITEM_TYPES):
        if rec.error or str(rec.meta.get("status") or "active") != "active":
            continue  # unparseable is its own finding; non-active never drives verdicts
        item = _scoring._item_from_record(rec)
        if item["tags"] or item["files"] or item["mentioned_files"]:
            continue
        findings.append(
            _audit_finding(
                "unreachable",
                AUDIT_WARN,
                path_policy.posix_rel(rec.path, memory_dir),
                "no tags and no file references — guard can reach this record "
                "only through generic keyword overlap; add tags or file/path "
                "evidence so it can drive a verdict",
            )
        )

    return findings
