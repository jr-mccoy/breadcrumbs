"""Tests for the inbox: `crumb jot`, `crumb inbox`, promotion and retention (WM-03).

The short-term tier. What it must do: accept a one-liner with no evidence,
expire it, keep machine-written notes out of the committed store, stay out of
every guard verdict, and turn into a real record on demand through the *same*
writer a hand-written record uses.

Run with:  python -m pytest tests/
       or:  python tests/test_inbox.py
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402  (patch target for cli helpers)
from breadcrumbs import inbox as ibx  # noqa: E402
from breadcrumbs import mcp_core  # noqa: E402


def init_store(tmp: str) -> Path:
    root = Path(tmp)
    with contextlib.redirect_stdout(io.StringIO()):
        crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
    return root / crumb.MEMORY_DIRNAME


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = crumb.main(argv)
    return code, buf.getvalue()


def jot(tmp: str, text: str, *extra: str) -> str:
    code, out = run(["jot", text, "--project", tmp, "--json", *extra])
    assert code == 0, out
    return json.loads(out)["id"]


def age_record(path: Path, days: int) -> None:
    """Backdate a record's created_at/expires_at by `days`."""
    text = path.read_text(encoding="utf-8")
    then = (datetime.now().astimezone() - timedelta(days=days)).replace(microsecond=0)
    out = []
    for line in text.splitlines():
        if line.startswith("created_at:") or line.startswith("updated_at:"):
            out.append(f"{line.split(':', 1)[0]}: {then.isoformat()}")
        elif line.startswith("expires_at:") and "null" not in line:
            out.append(f"expires_at: {(then + timedelta(days=ibx.JOT_TTL_DAYS)).isoformat()}")
        else:
            out.append(line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


class WriteTests(unittest.TestCase):
    def test_a_jot_is_valid_without_evidence(self):
        """The whole point: no evidence, no --confidence low, still a valid record."""
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = jot(tmp, "the flaky screenshot test only fails under pytest -n auto")
            self.assertTrue(rid.startswith("jot_"))
            fails = [f for f in crumb.run_validate(mem) if f["status"] == "fail"]
            self.assertEqual(fails, [], fails)

    def test_it_carries_a_ttl_and_a_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            jot(tmp, "a short-lived observation")
            rec = ibx.load_jots(mem)[0]
            self.assertEqual(rec.meta["source"], "agent")
            self.assertTrue(rec.meta["expires_at"])
            due = _cli._parse_iso(rec.meta["expires_at"])
            made = _cli._parse_iso(rec.meta["created_at"])
            self.assertEqual((due - made).days, ibx.JOT_TTL_DAYS)

    def test_files_become_file_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            jot(tmp, "this module is fragile", "--file", "src/auth/session.py")
            rec = ibx.load_jots(mem)[0]
            self.assertEqual(rec.meta["evidence"], [{"type": "file", "ref": "src/auth/session.py"}])
            # ...which is what makes `search --file` reach it.
            matches, _ = crumb.search(
                mem, Path(tmp), "", filters={"file": "src/auth/session.py"}, include_ideas=True
            )
            self.assertIn(rec.meta["id"], [m["id"] for m in matches])

    def test_two_jots_with_one_text_get_distinct_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            a = jot(tmp, "same text entirely")
            b = jot(tmp, "same text entirely")
            self.assertNotEqual(a, b)
            self.assertEqual(len(ibx.load_jots(mem)), 2)

    def test_long_text_is_truncated_not_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            code, out = run(["jot", "x" * 2000, "--project", tmp, "--json"])
            self.assertEqual(code, 0)
            self.assertIn("hint", json.loads(out))
            self.assertLessEqual(len(ibx.jot_rows(mem)[0]["text"]), ibx.JOT_MAX_CHARS)

    def test_empty_text_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, _ = run(["jot", "   ", "--project", tmp])
            self.assertEqual(code, 1)

    def test_whitespace_is_flattened(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            jot(tmp, "line one\n\n  line two\ttabbed")
            self.assertEqual(ibx.jot_rows(mem)[0]["text"], "line one line two tabbed")


class PrivacyTests(unittest.TestCase):
    def test_local_jots_land_under_private_and_are_gitignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=tmp, check=True)
            mem = init_store(tmp)
            jot(tmp, "the user said do not touch the migration", "--local")
            rec = ibx.load_jots(mem)[0]
            self.assertTrue(ibx.is_private(mem, rec))
            self.assertEqual(rec.meta["privacy"], "local-private")
            ignored = subprocess.run(
                ["git", "check-ignore", str(rec.path.relative_to(root))],
                cwd=tmp,
                capture_output=True,
                text=True,
            )
            self.assertEqual(ignored.returncode, 0, "a --local jot must be gitignored")

    def test_a_local_private_jot_validates_where_a_committed_one_would_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            jot(tmp, "machine-local note", "--local")
            fails = [f for f in crumb.run_validate(mem) if f["status"] == "fail"]
            self.assertEqual(fails, [], fails)

    def test_a_repo_safe_record_under_private_is_a_finding(self):
        """The inverse rule: `private/` is where nothing is committed."""
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            jot(tmp, "machine-local note", "--local")
            rec = ibx.load_jots(mem)[0]
            text = rec.path.read_text(encoding="utf-8").replace(
                "privacy: local-private", "privacy: repo-safe"
            )
            rec.path.write_text(text, encoding="utf-8")
            fails = [f for f in crumb.run_validate(mem) if f["status"] == "fail"]
            self.assertTrue(any(f["check"] == "privacy" for f in fails), fails)

    def test_the_committed_packet_never_lists_a_private_jot(self):
        """Otherwise the packet differs between checkouts while its hash agrees."""
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            public = jot(tmp, "a committed observation about the parser")
            private = jot(tmp, "something the user said in passing", "--local")
            packet = crumb.build_resume_packet(mem, Path(tmp))
            ids = [j["id"] for j in packet["inbox"]]
            self.assertIn(public, ids)
            self.assertNotIn(private, ids)
            # And the hash is unaffected by writing one.
            before = crumb._inputs_hash(mem, Path(tmp))
            jot(tmp, "another private one", "--local")
            self.assertEqual(crumb._inputs_hash(mem, Path(tmp)), before)


class ExpiryTests(unittest.TestCase):
    def test_an_expired_jot_drops_out_of_the_live_views(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = jot(tmp, "this will age out")
            age_record(ibx.find_jot(mem, rid).path, ibx.JOT_TTL_DAYS + 3)
            self.assertEqual(ibx.load_jots(mem), [])
            self.assertEqual(crumb.build_resume_packet(mem, Path(tmp))["inbox"], [])
            # ...but is still there when asked for.
            self.assertEqual([r["id"] for r in ibx.jot_rows(mem, include_expired=True)], [rid])

    def test_the_ttl_is_configurable_per_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            text = (mem / "manifest.yml").read_text(encoding="utf-8")
            (mem / "manifest.yml").write_text(
                text.replace(f"jot_ttl_days: {ibx.JOT_TTL_DAYS}", "jot_ttl_days: 3"),
                encoding="utf-8",
            )
            self.assertEqual(ibx.jot_ttl_days(mem), 3)
            jot(tmp, "short-lived")
            rec = ibx.load_jots(mem)[0]
            due = _cli._parse_iso(rec.meta["expires_at"])
            made = _cli._parse_iso(rec.meta["created_at"])
            self.assertEqual((due - made).days, 3)

    def test_an_unparseable_ttl_falls_back_to_the_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            text = (mem / "manifest.yml").read_text(encoding="utf-8")
            (mem / "manifest.yml").write_text(
                text.replace(f"jot_ttl_days: {ibx.JOT_TTL_DAYS}", "jot_ttl_days: soon"),
                encoding="utf-8",
            )
            self.assertEqual(ibx.jot_ttl_days(mem), ibx.JOT_TTL_DAYS)


class RetrievalTests(unittest.TestCase):
    def test_search_finds_a_jot(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = jot(tmp, "the screenshot comparison is sensitive to display scaling")
            matches, _ = crumb.search(mem, Path(tmp), "screenshot scaling", include_ideas=True)
            self.assertIn(rid, [m["id"] for m in matches])

    def test_guard_never_rests_on_a_jot(self):
        """A jot naming the file being edited must not raise a verdict."""
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            jot(tmp, "the auth session module is fragile", "--file", "src/auth/session.py")
            result = crumb.guard(
                mem, Path(tmp), "rewrite the auth session module", files=["src/auth/session.py"]
            )
            self.assertEqual(result["verdict"], "PROCEED")
            self.assertEqual(result["matches"], [])

    def test_the_packet_section_appears_only_when_there_is_something_in_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            md = crumb.render_packet_markdown(crumb.build_resume_packet(mem, Path(tmp)))
            self.assertNotIn("## Inbox", md)
            jot(tmp, "something worth a line")
            md = crumb.render_packet_markdown(crumb.build_resume_packet(mem, Path(tmp)))
            self.assertIn("## Inbox (unsorted, expires)", md)

    def test_the_section_is_capped(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            for i in range(crumb.SECTION_CAPS["inbox"] + 5):
                jot(tmp, f"observation number {i} about the parser")
            packet = crumb.build_resume_packet(mem, Path(tmp))
            self.assertEqual(len(packet["inbox"]), crumb.SECTION_CAPS["inbox"])
            self.assertEqual(packet["omitted"]["inbox"], 5)

    def test_it_is_trimmed_before_the_durable_sections(self):
        """At no budget is a decision dropped while a jot is still in the packet."""
        self.assertLess(crumb.TRIM_ORDER.index("inbox"), crumb.TRIM_ORDER.index("active_decisions"))
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            for i in range(5):
                jot(tmp, f"a jot that should give way to a decision, number {i}")
            run(
                [
                    "remember",
                    "decision",
                    "--project",
                    tmp,
                    "--title",
                    "A decision that must survive the trim",
                    "--set",
                    "Decision",
                    "keep this",
                    "--confidence",
                    "low",
                ]
            )
            full = crumb.build_resume_packet(mem, Path(tmp))
            budget = crumb.approx_tokens(crumb.render_packet_markdown(full))
            saw_trim = False
            for cut in range(budget, 50, -25):
                with mock.patch.object(_cli, "TOKEN_BUDGET_MAX", cut):
                    packet = crumb.build_resume_packet(mem, Path(tmp))
                if packet["omitted"].get("inbox"):
                    saw_trim = True
                if packet["omitted"].get("active_decisions"):
                    self.assertEqual(
                        packet["inbox"],
                        [],
                        f"a decision was trimmed at budget {cut} while jots remained",
                    )
            self.assertTrue(saw_trim, "the sweep never forced an inbox trim")

    def test_fast_drops_the_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            jot(tmp, "not in the fast view")
            packet = crumb.build_resume_packet(mem, Path(tmp), fast=True)
            self.assertEqual(packet["inbox"], [])


class PromoteTests(unittest.TestCase):
    def test_promote_to_a_decision_carries_evidence_and_supersedes_the_jot(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = jot(tmp, "we should store records as markdown", "--file", "docs/schema.md")
            code, out = run(
                [
                    "inbox",
                    "promote",
                    rid,
                    "decision",
                    "--project",
                    tmp,
                    "--set",
                    "Decision",
                    "markdown plus yaml frontmatter",
                    "--json",
                ]
            )
            self.assertEqual(code, 0, out)
            new_id = json.loads(out)["promoted_to"]
            self.assertTrue(new_id.startswith("dec_"))
            rec = crumb.find_record_by_id(mem, new_id)
            self.assertEqual(rec.meta["title"], "we should store records as markdown")
            # The jot's file evidence came with it, so the new record is at
            # least as reachable as the note it replaced.
            self.assertIn({"type": "file", "ref": "docs/schema.md"}, rec.meta["evidence"])
            jot_rec = ibx.find_jot(mem, rid)
            self.assertEqual(jot_rec.meta["status"], "superseded")
            self.assertEqual(jot_rec.meta["superseded_by"], new_id)
            self.assertEqual([f for f in crumb.run_validate(mem) if f["status"] == "fail"], [])

    def test_promotion_obeys_the_evidence_rule(self):
        """A jot is a shortcut into memory, not around its contract."""
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = jot(tmp, "a claim with nothing behind it")
            code, _ = run(["inbox", "promote", rid, "decision", "--project", tmp])
            self.assertEqual(code, 1)
            # Nothing was left behind, and the jot is still promotable.
            self.assertEqual(crumb.load_records(mem, types=("decision",)), [])
            self.assertEqual(ibx.find_jot(mem, rid).meta["status"], "active")

    def test_promote_to_a_trap(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = jot(tmp, "gradlew --stop corrupts the R.jar lock")
            code, out = run(
                [
                    "inbox",
                    "promote",
                    rid,
                    "trap",
                    "--project",
                    tmp,
                    "--area",
                    "build.gradle",
                    "--why",
                    "the daemon holds the lock",
                    "--safe",
                    "kill by pid",
                    "--json",
                ]
            )
            self.assertEqual(code, 0, out)
            self.assertTrue(
                any("gradlew" in t["heading"] for t in crumb.load_traps(mem)),
                "the trap should be in known-traps.md",
            )
            self.assertEqual(ibx.find_jot(mem, rid).meta["status"], "superseded")

    def test_promote_to_a_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = jot(tmp, "the export path no longer double-encodes", "--file", "src/export.py")
            code, out = run(
                [
                    "inbox",
                    "promote",
                    rid,
                    "verification",
                    "--project",
                    tmp,
                    "--status",
                    "fixed",
                    "--method",
                    "test",
                    "--json",
                ]
            )
            self.assertEqual(code, 0, out)
            new_id = json.loads(out)["promoted_to"]
            rec = crumb.find_record_by_id(mem, new_id)
            self.assertEqual(rec.meta["outcome"], "fixed")

    def test_a_promoted_jot_cannot_be_promoted_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            rid = jot(tmp, "an idea worth keeping")
            self.assertEqual(run(["inbox", "promote", rid, "idea", "--project", tmp])[0], 0)
            self.assertEqual(run(["inbox", "promote", rid, "idea", "--project", tmp])[0], 1)

    def test_promoting_a_private_jot_publishes_the_content_not_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = jot(tmp, "the retry loop should back off exponentially", "--local")
            code, out = run(["inbox", "promote", rid, "idea", "--project", tmp, "--json"])
            self.assertEqual(code, 0, out)
            new_id = json.loads(out)["promoted_to"]
            # The idea is in the committed tree...
            self.assertEqual(
                crumb.find_record_by_id(mem, new_id).path.relative_to(mem).parts[0], "ideas"
            )
            # ...and the jot itself stayed private.
            self.assertTrue(ibx.is_private(mem, ibx.find_jot(mem, rid)))

    def test_an_unknown_target_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = jot(tmp, "x marks the spot")
            res = ibx.promote_jot(mem, Path(tmp), rid, "session")
            self.assertFalse(res["ok"])
            self.assertIn("unknown promote target", res["error"])

    def test_an_unknown_jot_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, _ = run(["inbox", "promote", "jot_nope", "idea", "--project", tmp])
            self.assertEqual(code, 1)


class DropAndPruneTests(unittest.TestCase):
    def test_drop_retires_without_deleting(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = jot(tmp, "noise, not signal")
            code, _ = run(["inbox", "drop", rid, "--project", tmp, "--reason", "not useful"])
            self.assertEqual(code, 0)
            self.assertEqual(ibx.find_jot(mem, rid).meta["status"], "rejected")
            self.assertEqual(ibx.load_jots(mem), [])

    def test_prune_deletes_only_old_retired_or_expired_jots(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            fresh = jot(tmp, "recent and live")
            old_live = jot(tmp, "old but nobody has triaged it")
            expired = jot(tmp, "old and past its ttl")
            dropped = jot(tmp, "old and dropped")
            run(["inbox", "drop", dropped, "--project", tmp])
            for rid in (old_live, expired, dropped):
                age_record(ibx.find_jot(mem, rid).path, 60)
            # `old_live` is aged but its TTL was moved with it, so it is still live.
            text = ibx.find_jot(mem, old_live).path.read_text(encoding="utf-8")
            future = (datetime.now().astimezone() + timedelta(days=5)).replace(microsecond=0)
            ibx.find_jot(mem, old_live).path.write_text(
                "\n".join(
                    f"expires_at: {future.isoformat()}" if ln.startswith("expires_at:") else ln
                    for ln in text.splitlines()
                )
                + "\n",
                encoding="utf-8",
            )

            res = ibx.prune_jots(mem, Path(tmp), dry_run=True)
            self.assertEqual(sorted(res["deleted"]), sorted([expired, dropped]))
            self.assertTrue(ibx.find_jot(mem, expired))  # dry run deleted nothing

            res = ibx.prune_jots(mem, Path(tmp))
            self.assertEqual(sorted(res["deleted"]), sorted([expired, dropped]))
            self.assertIsNone(ibx.find_jot(mem, expired))
            self.assertIsNotNone(ibx.find_jot(mem, fresh))
            self.assertIsNotNone(ibx.find_jot(mem, old_live))

    def test_prune_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, out = run(["prune", "jots", "--project", tmp, "--dry-run"])
            self.assertEqual(code, 0)
            self.assertIn("prune jots", out)


class ListCommandTests(unittest.TestCase):
    def test_empty_inbox_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, out = run(["inbox", "--project", tmp])
            self.assertEqual(code, 0)
            self.assertIn("empty", out)

    def test_listing_shows_text_source_and_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            jot(tmp, "a committed note")
            jot(tmp, "a machine-local note", "--local")
            code, out = run(["inbox", "--project", tmp])
            self.assertEqual(code, 0)
            self.assertIn("a committed note", out)
            self.assertIn("[local]", out)

    def test_the_audit_trail_comment_never_leaks_into_the_text(self):
        """`set_record_status` appends an HTML comment; a jot's body is printed raw."""
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = jot(tmp, "clean text only")
            run(["inbox", "drop", rid, "--project", tmp, "--reason", "noise"])
            row = ibx.jot_rows(mem, include_retired=True)[0]
            self.assertEqual(row["text"], "clean text only")
            self.assertNotIn("<!--", row["text"])

    def test_json_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            rid = jot(tmp, "structured output please")
            code, out = run(["inbox", "--project", tmp, "--json"])
            self.assertEqual(code, 0)
            doc = json.loads(out)
            self.assertTrue(doc["ok"])
            self.assertEqual([i["id"] for i in doc["items"]], [rid])

    def test_needs_a_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run(["inbox", "--project", tmp])[0], 2)
            self.assertEqual(run(["jot", "x", "--project", tmp])[0], 2)


class McpTests(unittest.TestCase):
    def test_tool_jot_and_promote_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            res = mcp_core.tool_jot("an mcp-written observation", files=["src/x.py"], root=tmp)
            self.assertTrue(res["ok"], res)
            # Store-relative path, never the absolute host path (issue #7).
            self.assertFalse(Path(res["path"]).is_absolute())
            promoted = mcp_core.tool_inbox_promote(
                res["id"], "idea", sections={"Idea": "worth trying"}, root=tmp
            )
            self.assertTrue(promoted["ok"], promoted)
            self.assertEqual(ibx.find_jot(mem, res["id"]).meta["status"], "superseded")

    def test_resource_lists_both_inboxes(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            jot(tmp, "committed one")
            jot(tmp, "private one", "--local")
            text = mcp_core.resource_inbox(tmp)
            self.assertIn("committed one", text)
            self.assertIn("private one", text)

    def test_resource_on_an_empty_inbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            self.assertIn("empty", mcp_core.resource_inbox(tmp))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
