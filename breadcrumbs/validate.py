"""breadcrumbs — `crumb validate`: every deterministic check on a store.

`run_validate` is the gate: core files, the manifest and schema version,
frontmatter, record identity, the record contract (`breadcrumbs.validation`,
which judges one record's fields), supersession, privacy placement, the
handoff, jots and projection freshness, each a pass/warn/fail finding. It
never scans content heuristically; that is `audit`'s job. Writers run it after
a write and refuse one that makes the store fail.

Moved out of `cli.py` (health review 2.1). `cli.cmd_validate` renders it.
"""

from __future__ import annotations

import re
from pathlib import Path

from breadcrumbs import cli
from breadcrumbs import path_policy
from breadcrumbs import validation as _validation


def _finding(
    check: str, status: str, path: str | None, message: str, code: str | None = None
) -> dict:
    """One validate result. `code` is the stable identifier (defaults to `check`)."""
    return {
        "check": check,
        "status": status,
        "path": path,
        "message": message,
        "code": code or check,
    }


# The validate `check` each record-contract code reports under.
_CONTRACT_CHECK = {
    _validation.CONFIDENCE_INVALID: "confidence",
    _validation.REVIEW_STATUS_INVALID: "review",
    _validation.SCOPE_UNSUPPORTED: "scope",
    _validation.EVIDENCE_MALFORMED: "evidence",
    _validation.TIMESTAMP_INVALID: "timestamp",
    _validation.SUPERSEDED_BY_MALFORMED: "superseded",
    _validation.SUPERSESSION_SELF: "superseded",
    _validation.SUPERSEDED_BY_MISSING: "superseded",
    _validation.SUPERSESSION_CYCLE: "superseded",
}


def _contract_finding(rel: str, issue: dict) -> dict:
    return _finding(
        _CONTRACT_CHECK.get(issue["code"], "contract"),
        "fail",
        rel,
        issue["message"],
        code=issue["code"],
    )


CONTRACT_WARNING_EXAMPLES = 3


def record_contract_warnings(memory_dir: Path) -> list[str]:
    """The packet's one-line notice that some records break the record contract.

    Readers tolerate a malformed record — it never takes a hook or the packet
    down — but tolerating it silently is how a `confidence: certainly` or an
    `expires_at` nothing can parse goes unnoticed for months. This says so where
    every session looks. Committed directories only: the packet is a committed
    projection, and a machine-local jot must not make it differ between checkouts.
    """
    memory_dir = Path(memory_dir)
    records = [
        rec
        for dirname, rtype in cli.DIR_TYPES.items()
        for rec in cli.records_in(memory_dir / dirname, rtype)
    ]
    entries = record_contract_entries(records, memory_dir)
    linked = _validation.store_issues(entries)
    problems: dict[str, list[str]] = {}
    hidden = 0
    for rec, (rel, rid, meta) in zip(records, entries):
        codes = ["frontmatter-malformed"] if rec.error else []
        codes += [i["code"] for i in _validation.record_issues(meta, rec.rtype, rid)]
        codes += [i["code"] for i in linked.get(rel, [])]
        codes += _reader_visible_problems(rec)
        if "status-invalid" in codes:
            hidden += 1
        if codes:
            problems[rid or rel] = codes
    if not problems:
        return []
    shown = [
        f"{rid} ({', '.join(dict.fromkeys(codes))})"
        for rid, codes in sorted(problems.items())[:CONTRACT_WARNING_EXAMPLES]
    ]
    more = len(problems) - len(shown)
    # Say what the readers actually do with them. "They are still read" was
    # untrue for an invalid status: such a decision is dropped from every
    # active list, and guard then PROCEEDs past it (field report 2026-10-01, N3).
    effect = (
        f" — {hidden} with an invalid status are left out of resume and guard; "
        if hidden
        else " — they are still read; "
    )
    return [
        f"⚠ {len(problems)} record(s) break the record contract: {'; '.join(shown)}"
        + (f"; +{more} more" if more > 0 else "")
        + effect
        + "run `crumb validate`."
    ]


def _reader_visible_problems(rec: "cli.Record") -> list[str]:
    """Contract breaks that change what readers show, which `record_issues` does
    not cover: a status outside the vocabulary (readers drop the record), no
    frontmatter at all (hand-written), a verification with no subject or no
    valid outcome (shown as outcome `unknown`)."""
    if rec.error:
        return []
    if not rec.meta:
        codes = ["no-frontmatter"]
        return codes + (["outcome-missing"] if rec.rtype == "verification" else [])
    codes: list[str] = []
    status = rec.meta.get("status")
    vocab = cli.VALID_QUESTION_STATUS if rec.rtype == "question" else cli.VALID_STATUS
    if status is not None and str(status) not in vocab and rec.rtype != "jot":
        codes.append("status-invalid")
    if rec.rtype == "verification":
        if rec.meta.get("outcome") not in cli.VALID_VERIFICATION_OUTCOME:
            codes.append("outcome-missing")
        if rec.meta.get("subject") in (None, ""):
            codes.append("subject-missing")
    return codes


def record_contract_entries(records: list["cli.Record"], memory_dir: Path) -> list[tuple]:
    """`(relative path, derived id, meta)` per record, for `validation.store_issues`.

    A record whose frontmatter did not parse is still a link target: its id comes
    from its filename, so a replacement pointing at it is not reported missing.
    """
    out = []
    for rec in records:
        ident = cli.derive_identity(rec.stem, rec.rtype)
        out.append(
            (path_policy.posix_rel(rec.path, memory_dir), ident[0] if ident else None, rec.meta)
        )
    return out


def run_validate(memory_dir: Path) -> list[dict]:
    """Run the deterministic validation checks; return a list of findings.

    Every finding is {check, status: pass|fail, path, message}. Heuristic content
    scanning (secrets, instruction-like text) is intentionally absent — that lives
    in `audit`.
    """
    memory_dir = Path(memory_dir)
    findings: list[dict] = []

    # Containment (audit F17): nothing in the store may be a link. Every reader
    # already refuses one; this says where they are.
    for rel in path_policy.find_links(memory_dir):
        findings.append(
            _finding(
                "containment",
                "fail",
                rel,
                "is a symbolic link or junction; memory files and directories must be the "
                "real thing inside the store (readers refuse it; replace it with the file "
                "or directory itself)",
                code="path-link",
            )
        )

    # 16.1 — manifest exists + supported schema_version.
    manifest = cli.load_manifest(memory_dir)
    if manifest is None:
        findings.append(_finding("manifest", "fail", "manifest.yml", "manifest.yml is missing"))
    else:
        # A version mismatch has two opposite causes and two opposite remedies,
        # and one message for both sent everyone to the wrong one. An *older*
        # store needs migrating; a *newer* store means this build is behind and
        # must not touch it, because writing schema-N records into a schema-N+1
        # store is how a store gets corrupted by a well-meaning downgrade.
        sv = manifest.get("schema_version")
        try:
            sv_int = int(str(sv).strip())
        except (TypeError, ValueError):
            sv_int = None
        if sv_int is None:
            findings.append(
                _finding(
                    "schema-version",
                    "fail",
                    "manifest.yml",
                    f"unreadable schema_version {sv!r} (this build supports {cli.SCHEMA_VERSION})",
                )
            )
        elif sv_int < cli.SCHEMA_VERSION:
            findings.append(
                _finding(
                    "schema-version",
                    "fail",
                    "manifest.yml",
                    f"store is schema_version {sv_int}, this crumb understands "
                    f"{cli.SCHEMA_VERSION} — run `crumb migrate`",
                )
            )
        elif sv_int > cli.SCHEMA_VERSION:
            findings.append(
                _finding(
                    "schema-version",
                    "fail",
                    "manifest.yml",
                    f"store is schema_version {sv_int}, this crumb understands "
                    f"{cli.SCHEMA_VERSION} — upgrade crumb-kit",
                )
            )
        else:
            findings.append(
                _finding("schema-version", "pass", "manifest.yml", f"schema_version {sv_int}")
            )
        findings.append(_finding("manifest", "pass", "manifest.yml", "manifest.yml present"))

    # 16.2 — required core files exist, and are readable. An undecodable core
    # file used to pass silently here while aborting `audit` and `resume`
    # elsewhere — validate is the trust primitive, so it says so.
    for name in cli.CORE_FILES:
        if not (memory_dir / name).is_file():
            findings.append(_finding("core-files", "fail", name, "required core file missing"))
            continue
        problem = cli.read_text_lenient(memory_dir / name)[1]
        if problem:
            findings.append(_finding("core-files", "fail", name, problem))
        else:
            findings.append(_finding("core-files", "pass", name, "present"))

    # Load durable records once for the record-level checks (16.3–10).
    records = cli.load_records(memory_dir)
    seen_ids: dict[str, str] = {}

    for rec in records:
        rel = path_policy.posix_rel(rec.path, memory_dir)

        # 16.3 — valid frontmatter (parses + required keys present).
        if rec.error:
            findings.append(
                _finding("frontmatter", "fail", rel, f"malformed frontmatter: {rec.error}")
            )
            continue
        missing = [k for k in cli.REQUIRED_RECORD_KEYS if rec.meta.get(k) in (None, "")]
        if missing:
            findings.append(
                _finding("frontmatter", "fail", rel, f"missing required keys: {', '.join(missing)}")
            )
        else:
            findings.append(_finding("frontmatter", "pass", rel, "frontmatter valid"))

        # 16.4 — identity: filename canonical; id uniqueness + id/slug agreement.
        ident = cli.derive_identity(rec.stem, rec.rtype)
        if ident is None:
            findings.append(
                _finding(
                    "identity",
                    "fail",
                    rel,
                    "filename does not match <YYYY-MM-DD>-<slug>.md with a real calendar "
                    "date and a lowercase [a-z0-9-] slug; id/slug underivable",
                )
            )
        else:
            rid, slug = ident
            is_duplicate = rid in seen_ids
            if is_duplicate:
                findings.append(
                    _finding(
                        "identity", "fail", rel, f"duplicate id {rid!r} (also {seen_ids[rid]})"
                    )
                )
            else:
                seen_ids[rid] = rel
            stored_id = rec.meta.get("id")
            stored_slug = rec.meta.get("slug")
            disagree = []
            if stored_id is not None and stored_id != rid:
                disagree.append(f"id frontmatter {stored_id!r} != derived {rid!r}")
            if stored_slug is not None and stored_slug != slug:
                disagree.append(f"slug frontmatter {stored_slug!r} != derived {slug!r}")
            stored_type = rec.meta.get("type")
            if stored_type is not None and stored_type != rec.rtype:
                disagree.append(f"type frontmatter {stored_type!r} != directory {rec.rtype!r}")
            if disagree:
                findings.append(_finding("identity", "fail", rel, "; ".join(disagree)))
            elif not is_duplicate:
                # A duplicate already produced a fail; don't also emit a redundant
                # identity pass that would inflate the passed count.
                findings.append(_finding("identity", "pass", rel, f"id {rid}"))

        # 16.5 — status in vocabulary. A question has its own (open / answered /
        # closed); everything else, traps included, uses the record lifecycle.
        status = rec.meta.get("status")
        vocab = cli.VALID_QUESTION_STATUS if rec.rtype == "question" else cli.VALID_STATUS
        if status is not None and status not in vocab:
            findings.append(
                _finding(
                    "status",
                    "fail",
                    rel,
                    f"invalid status {status!r} (allowed: {', '.join(vocab)})",
                )
            )

        # 16.6 — superseded requires superseded_by.
        if status == "superseded" and rec.meta.get("superseded_by") in (None, "", []):
            findings.append(
                _finding("superseded", "fail", rel, "status superseded but superseded_by is empty")
            )

        # 16.7 / 16.8 — privacy placement and prohibition.
        privacy = rec.meta.get("privacy")
        if privacy is not None and privacy not in cli.VALID_PRIVACY:
            # A typo'd value (e.g. "secret-prohibitted") must not silently slip
            # past the exact-match leak gate below — flag the out-of-vocab value.
            findings.append(
                _finding(
                    "privacy",
                    "fail",
                    rel,
                    f"invalid privacy {privacy!r} (allowed: {', '.join(cli.VALID_PRIVACY)})",
                )
            )
        if privacy == "secret-prohibited":
            findings.append(
                _finding(
                    "privacy",
                    "fail",
                    rel,
                    "privacy: secret-prohibited must not be stored in memory",
                )
            )
        elif privacy == "local-private" and not rel.startswith("private/"):
            # A local-private record has to live where git cannot see it. Most
            # record directories are committed, so this used to be unconditional
            # — `private/inbox/` is the first record directory that is not, and
            # an unconditional fail would reject every machine-local jot.
            findings.append(
                _finding(
                    "privacy",
                    "fail",
                    rel,
                    "privacy: local-private record is under a committed path (must live under private/)",
                )
            )
        elif rel.startswith("private/") and privacy == "repo-safe":
            findings.append(
                _finding(
                    "privacy",
                    "fail",
                    rel,
                    "privacy: repo-safe record is under private/, where nothing is "
                    "committed — mark it local-private or move it into the store proper",
                )
            )

        # 16.8b — the record contract: vocabularies, evidence shape, timestamps,
        # scope and self-links (breadcrumbs/validation.py; audit F05).
        for issue in _validation.record_issues(rec.meta, rec.rtype, ident[0] if ident else None):
            findings.append(_contract_finding(rel, issue))

        # 16.9 — decisions/attempts/verifications need evidence OR confidence: low.
        # Only a well-formed pointer counts: any non-empty `evidence` used to
        # satisfy this, so `[{nonsense: x}]` let a claim stand at medium.
        if rec.rtype in ("decision", "attempt", "verification"):
            has_evidence = bool(_validation.well_formed_evidence(rec.meta.get("evidence")))
            if not has_evidence and rec.meta.get("confidence") != "low":
                findings.append(
                    _finding(
                        "evidence",
                        "fail",
                        rel,
                        f"{rec.rtype} has no evidence and confidence is not 'low'",
                    )
                )

        # 16.9c — a jot names where it came from. A hook-written candidate and a
        # note somebody typed are read very differently by whoever triages the
        # inbox, and without this the two are indistinguishable on disk.
        if rec.rtype == "jot":
            src = rec.meta.get("source")
            if not (isinstance(src, str) and src.strip()):
                findings.append(
                    _finding("jot", "fail", rel, "jot has no source (who or what wrote it)")
                )
            else:
                findings.append(_finding("jot", "pass", rel, f"source {src}"))

        # 16.9b — verifications carry a subject and a valid outcome.
        if rec.rtype == "verification":
            subj = rec.meta.get("subject")
            # A non-string subject (e.g. a hand-edited YAML list) is a finding,
            # not a crash.
            if not (isinstance(subj, str) and subj.strip()):
                findings.append(
                    _finding(
                        "verification",
                        "fail",
                        rel,
                        "verification has no subject"
                        if subj in (None, "")
                        else f"verification subject must be a string, got {type(subj).__name__}",
                    )
                )
            outcome = rec.meta.get("outcome")
            if outcome not in cli.VALID_VERIFICATION_OUTCOME:
                findings.append(
                    _finding(
                        "verification",
                        "fail",
                        rel,
                        f"invalid outcome {outcome!r} (allowed: {', '.join(cli.VALID_VERIFICATION_OUTCOME)})",
                    )
                )
            method = rec.meta.get("method")
            if method not in (None, "") and method not in cli.VALID_VERIFICATION_METHOD:
                findings.append(
                    _finding(
                        "verification",
                        "fail",
                        rel,
                        f"invalid method {method!r} (allowed: {', '.join(cli.VALID_VERIFICATION_METHOD)})",
                    )
                )

        # 16.10 — session records need a Next Action (or convergence/done marker).
        if rec.rtype == "session":
            has_next = any(re.search(r"next action", h, re.I) for h in rec.sections)
            body_l = rec.body.lower()
            # Word-boundary match: a raw substring test let
            # "done" match "abandoned", false-passing the convergence check.
            has_done = any(
                re.search(rf"\b{re.escape(mark)}\b", body_l) for mark in cli.SESSION_DONE_MARKERS
            )
            if not (has_next or has_done):
                findings.append(
                    _finding(
                        "session",
                        "fail",
                        rel,
                        "session record lacks a '## Next Action' or convergence/done marker",
                    )
                )

    # 16.10b — links between records: a `superseded_by` must name a record in
    # this store, and a replacement chain must not loop back on itself.
    for rel, issues in _validation.store_issues(
        record_contract_entries(records, memory_dir)
    ).items():
        findings.extend(_contract_finding(rel, issue) for issue in issues)

    # 16.11 — handoff has branch, commit, next action, stale conditions.
    handoff = memory_dir / "handoff.md"
    if handoff.is_file():
        try:
            htext = path_policy.read_text(handoff)
        except (OSError, UnicodeDecodeError) as exc:
            # A finding, not a crash.
            findings.append(_finding("handoff", "fail", "handoff.md", f"unreadable file: {exc}"))
            htext = None
    else:
        htext = None
    if htext is not None:
        required = {
            "branch": re.search(r"branch\s*:", htext, re.I),
            "commit": re.search(r"commit\s*:", htext, re.I),
            "next action": re.search(r"##\s+next action", htext, re.I),
            "stale conditions": re.search(r"##\s+stale", htext, re.I),
        }
        missing_h = [name for name, hit in required.items() if not hit]
        if missing_h:
            findings.append(
                _finding("handoff", "fail", "handoff.md", f"missing: {', '.join(missing_h)}")
            )
        else:
            findings.append(
                _finding("handoff", "pass", "handoff.md", "branch/commit/next action/stale present")
            )

    # 16.12 — generated files are not treated as canonical (carry the projection marker).
    gen_dir = memory_dir / "generated"
    if gen_dir.is_dir():
        for p in sorted(gen_dir.glob("*.md")):
            if p.name == "README.md":
                continue
            rel = path_policy.posix_rel(p, memory_dir)
            try:
                head = "\n".join(path_policy.read_text(p).splitlines()[:5])
            except (OSError, UnicodeDecodeError) as exc:
                # A finding, not a crash.
                findings.append(_finding("generated", "fail", rel, f"unreadable file: {exc}"))
                continue
            if cli.GENERATED_MARKER in head:
                findings.append(
                    _finding("generated", "pass", rel, "carries generated-projection marker")
                )
            else:
                findings.append(
                    _finding(
                        "generated",
                        "fail",
                        rel,
                        f"generated file lacks the '{cli.GENERATED_MARKER}' marker",
                    )
                )

    # 16.12b — projection freshness: a generated projection stamped
    # with an inputs_hash that no longer matches the live canonical records is
    # stale. `validate` is the trust primitive, so it must not stay green while a
    # projection silently desyncs — that would *certify* drift. Unstamped/older
    # projections carry no hash and are skipped (handled by detect_packet_drift).
    for d in cli.detect_packet_drift(memory_dir):
        findings.append(
            _finding(
                "freshness",
                "fail",
                d["path"],
                f"stale projection (built from inputs_hash {d['stamped']}; "
                f"live is {d['current']}). Run `crumb reindex`.",
            )
        )

    # 16.13 — adapter files are not loaded as canonical records. By construction the
    # loader walks only decisions/attempts/sessions/ideas, so project-root adapter
    # files (AGENTS.md/CLAUDE.md/etc.) are never treated as records. Recorded as pass.
    findings.append(
        _finding(
            "adapters", "pass", None, "adapter/signpost files are not loaded as canonical records"
        )
    )

    return findings
