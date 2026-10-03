"""Packets are bounded on the view a reader receives, and portable (audit F13, F14; WP08).

- F14: the 5,000-token bound applied to the list sections only. A large Current
  Focus, Next Action, title or warning set could carry the packet far past it,
  and `len/4` was presented as if it were a token count.
- F13: a promoted record was dropped from every packet because its rule was
  "in the instruction file", even when that file was gone, or the reader never
  loads it.

These pin the replacement:

- every view (Markdown, JSON, fast, MCP, hook) is measured on its final text,
  within a declared budget in a named unit;
- oversize fields become marked excerpts with pointers, and nothing canonical
  changes;
- a promoted record stays in a portable packet with its rule, and is left out
  only for a consumer that has loaded that rule.

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli, mcp_core, promote  # noqa: E402
from breadcrumbs import hooks_session  # noqa: E402
from breadcrumbs import packet as _packet  # noqa: E402


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True)


def run(argv: list[str], stdin: str | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    saved = sys.stdin
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = crumb.main(argv)
    finally:
        sys.stdin = saved
    return code, out.getvalue(), err.getvalue()


class PacketCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@t")
        git(self.root, "config", "user.name", "t")
        run(["init", "--project", str(self.root), "--session-tracking", "full"])
        self.mem = self.root / crumb.MEMORY_DIRNAME
        self.p = str(self.root)

    def decision(self, title: str, rationale: str = "the audit trail needs it") -> str:
        _path, meta = crumb.write_record(
            self.mem,
            self.root,
            "decision",
            title,
            {"Decision": f"{title}.", "Rationale": rationale},
            evidence=[{"type": "file", "ref": "src/ledger.py"}],
        )
        return meta["id"]

    def set_focus(self, text: str) -> None:
        (self.mem / "current.md").write_text(
            f"# Current State\n\n## Current Focus\n{text}\n", encoding="utf-8"
        )

    def views(self, **kwargs) -> dict[str, tuple[str, dict]]:
        """Every packet view a reader can receive: `{name: (text, budget)}`."""
        out = {}
        for name, argv in (
            ("markdown", ["resume"]),
            ("markdown-fast", ["resume", "--fast"]),
            ("json", ["resume", "--json"]),
            ("json-fast", ["resume", "--fast", "--json"]),
        ):
            extra = [f"--budget={kwargs['budget']}"] if kwargs.get("budget") else []
            code, text, err = run([*argv, "--project", self.p, *extra])
            self.assertEqual(code, 0, err)
            budget = json.loads(text)["budget"] if "--json" in argv else self._md_budget(text)
            out[name] = (text, budget)
        doc = mcp_core.tool_build_resume_packet(root=self.p)
        out["mcp"] = (json.dumps(doc, indent=2), doc["budget"])
        code, text, _err = run(["hook", "session"], stdin=json.dumps({"cwd": self.p}))
        context = json.loads(text)["hookSpecificOutput"]["additionalContext"]
        out["hook"] = (context, self._md_budget(context))
        return out

    @staticmethod
    def _md_budget(text: str) -> dict:
        line = next(line for line in text.splitlines() if line.startswith("<!-- view:"))
        used, limit = line.split("budget: ", 1)[1].split(" ", 1)[0].split("/")
        return {"used": int(used), "limit": int(limit), "line": line}

    def assert_within(self, views: dict) -> None:
        for name, (text, budget) in views.items():
            with self.subTest(view=name):
                self.assertLessEqual(_packet.approx_tokens(text.rstrip("\n")), budget["limit"])
                self.assertLessEqual(_packet.approx_tokens(text.rstrip("\n")), budget["used"] + 1)


class BoundTests(PacketCase):
    def test_long_focus_cannot_exceed_declared_view_budget(self):
        focus = "Reconcile every ledger shard before the cutover. " * 900  # ~45k chars
        self.set_focus(focus)
        code, _o, err = run(
            ["capture", "session", "--project", self.p, "--next", "Ship it. " * 4000]
        )
        self.assertEqual(code, 0, err)
        before = (self.mem / "current.md").read_bytes()
        views = self.views()
        self.assert_within(views)
        packet = json.loads(views["json"][0])
        self.assertEqual(packet["budget"]["unit"], "approx_tokens")
        self.assertEqual(packet["budget"]["estimator"], _packet.TOKEN_ESTIMATOR)
        self.assertTrue(packet["budget"]["within"])
        excerpt = packet["excerpted"]["current_focus"]
        self.assertEqual(excerpt["total_chars"], len(focus.strip()))
        self.assertEqual(excerpt["source"], "current.md → Current Focus")
        self.assertIn("[excerpt: ", packet["current_focus"])
        self.assertIn("full text: current.md → Current Focus]", views["markdown"][0])
        self.assertIn("full text: handoff.md → Next Action]", views["markdown"][0])
        # The canonical text is never shortened.
        self.assertEqual((self.mem / "current.md").read_bytes(), before)
        # The committed packet obeys the same bound.
        md = (self.mem / "generated" / "resume-packet.md").read_text(encoding="utf-8")
        self.assertLessEqual(_packet.approx_tokens(md), _packet.TOKEN_BUDGET_MAX)

    def test_huge_titles_and_warnings_are_excerpted_with_pointers(self):
        rid = self.decision("Ledger " * 400, rationale="because " * 600)
        warnings = [f"warning {i}: " + "stale " * 200 for i in range(60)]
        with mock.patch.object(_packet, "compute_staleness", return_value=warnings):
            packet = _packet.build_resume_packet(self.mem, self.root, view="json")
            text = _packet.packet_json_text(packet)
        self.assertLessEqual(_packet.approx_tokens(text), packet["budget"]["limit"])
        entry = next(d for d in packet["active_decisions"] if d["id"] == rid)
        for field in ("title", "rationale"):
            shown, mark = entry[field].split("… [excerpt: ", 1)
            self.assertLessEqual(len(shown), _packet.ITEM_EXCERPT_CHARS)
            self.assertTrue(mark.endswith(f"; full text: crumb show {rid}]"), mark)
        self.assertGreater(packet["excerpted"]["active_decisions"], 0)
        self.assertTrue(all(len(w) <= _packet.ITEM_EXCERPT_CHARS + 60 for w in packet["warnings"]))
        self.assertGreater(packet["omitted"]["warnings"], 0)

    def test_unicode_and_tiny_budgets_terminate_and_disclose_omissions(self):
        # Two tokens' worth of estimate per character would have been 0.5 under
        # chars/4; the named estimator counts each non-ASCII char as one.
        self.assertEqual(_packet.approx_tokens("日本語のテキスト"), 8)
        self.assertEqual(_packet.approx_tokens("abcd" * 10), 10)
        self.set_focus("台帳の照合を完了する 🚀 " * 900)
        for i in range(30):
            self.decision(f"決定 {i} " + "記録 " * 60, rationale="理由 " * 200)
        for kind in ("trap", "question"):
            for i in range(15):
                crumb.note(self.mem, self.root, kind, f"{kind} {i} ⚠ " + "注意 " * 150)
        for view in ("markdown", "json"):
            for fast in (False, True):
                name = f"{view}-fast" if fast else view
                floor = _packet.PACKET_MIN_BUDGET[name]
                for budget in (1, floor, floor + 1, floor * 2, 2500, _packet.TOKEN_BUDGET_MAX):
                    with self.subTest(view=name, budget=budget):
                        started = time.monotonic()
                        packet = _packet.build_resume_packet(
                            self.mem, self.root, view=view, fast=fast, budget=budget
                        )
                        self.assertLess(time.monotonic() - started, 30)
                        render = (
                            _packet.render_packet_markdown
                            if view == "markdown"
                            else _packet.packet_json_text
                        )
                        size = _packet.approx_tokens(render(packet))
                        limit = packet["budget"]["limit"]
                        self.assertEqual(limit, max(budget, floor))
                        self.assertLessEqual(size, limit)
                        self.assertTrue(packet["budget"]["within"])
                        if budget < floor:
                            self.assertEqual(packet["budget"]["requested"], budget)
                        # Whatever did not fit is disclosed, never silently gone.
                        self.assertIn("current_focus", packet["excerpted"])
                        if not fast:
                            self.assertTrue(packet["omitted"] or packet["excerpted"])
                            shown = len(packet["active_decisions"]) + packet["omitted"].get(
                                "active_decisions", 0
                            )
                            self.assertEqual(shown, 30)
        # The CLI refuses a budget below what a view can honour.
        code, _o, err = run(["resume", "--project", self.p, "--budget", "10"])
        self.assertEqual(code, 2)
        self.assertIn("below the smallest", err)

    def test_the_hook_adds_only_its_declared_preamble(self):
        self.set_focus("Reconcile every ledger shard. " * 2000)
        packet_budget = _packet.TOKEN_BUDGET_MAX
        with mock.patch.object(
            hooks_session, "_compaction_preamble", return_value="x" * 3000 + "\n\n"
        ):
            code, text, _err = run(
                ["hook", "session"], stdin=json.dumps({"cwd": self.p, "source": "compact"})
            )
        context = json.loads(text)["hookSpecificOutput"]["additionalContext"]
        self.assertLessEqual(
            _packet.approx_tokens(context), packet_budget + hooks_session._COMPACT_PREAMBLE_TOKENS
        )


class PortabilityTests(PacketCase):
    def promote(self, rid: str, *extra: str) -> None:
        code, _o, err = run(["promote", rid, "--project", self.p, *extra])
        self.assertEqual(code, 0, err)

    def test_missing_adapter_does_not_hide_promoted_decision(self):
        (self.root / "CLAUDE.md").write_text("# Guide\n", encoding="utf-8")
        rid = self.decision("Ledger rows are append-only")
        self.promote(rid)
        (self.root / "CLAUDE.md").unlink()
        for label, packet in (
            ("portable", _packet.build_resume_packet(self.mem, self.root)),
            (
                "claude hook",
                _packet.build_resume_packet(
                    self.mem,
                    self.root,
                    loaded_rules=promote.loaded_rules(self.root, ("CLAUDE.md",)),
                    loaded_rules_from=("CLAUDE.md",),
                ),
            ),
        ):
            with self.subTest(packet=label):
                entry = next(d for d in packet["active_decisions"] if d["id"] == rid)
                self.assertFalse(entry["rule_in_file"])
                self.assertIn("Ledger rows are append-only", entry["rule"])
                self.assertEqual(packet["promoted"], {})
                md = _packet.render_packet_markdown(packet)
                self.assertIn(
                    f"`{rid}` — standing rule (promoted to CLAUDE.md, not found there):", md
                )
        # The committed packet, which any reader of the repository sees, too.
        cli.try_reindex_projections(self.mem, self.root)
        committed = (self.mem / "generated" / "resume-packet.md").read_text(encoding="utf-8")
        self.assertIn(rid, committed)

    def test_cross_harness_packet_includes_effective_rules(self):
        (self.root / "CLAUDE.md").write_text("# Guide\n", encoding="utf-8")
        (self.root / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
        claude_rid = self.decision("Ledger rows are append-only")
        agents_rid = self.decision("Invoices are immutable once sent")
        self.promote(claude_rid, "--rule", "Never UPDATE the ledger table")
        self.promote(agents_rid, "--to", "AGENTS.md")
        # A hand edit in the file is the rule that file's readers have.
        claude_md = self.root / "CLAUDE.md"
        claude_md.write_text(
            claude_md.read_text("utf-8").replace("Never UPDATE", "Never UPDATE or DELETE"),
            encoding="utf-8",
        )

        portable = [
            _packet.build_resume_packet(self.mem, self.root),
            mcp_core.tool_build_resume_packet(root=self.p),
            json.loads(run(["resume", "--json", "--project", self.p])[1]),
        ]
        for packet in portable:
            with self.subTest(consumer="portable"):
                rules = {d["id"]: d for d in packet["active_decisions"] if d.get("rule")}
                self.assertIn("Never UPDATE or DELETE the ledger table", rules[claude_rid]["rule"])
                self.assertEqual(rules[agents_rid]["promoted_to"], "AGENTS.md")
                self.assertIn("Invoices are immutable once sent", rules[agents_rid]["rule"])
                self.assertEqual(packet["rules"], {"mode": "portable"})

        # Claude Code loads CLAUDE.md but not AGENTS.md: only the first is left out.
        code, text, _err = run(["hook", "session"], stdin=json.dumps({"cwd": self.p}))
        context = json.loads(text)["hookSpecificOutput"]["additionalContext"]
        # (a warning may still name it; its list line is what is left out)
        self.assertNotIn(f"`{claude_rid}` —", context)
        self.assertIn(f"`{agents_rid}` — standing rule in AGENTS.md:", context)
        self.assertIn("1 standing rule(s) left out — already loaded from CLAUDE.md", context)
        self.assertIn("rules: elided when loaded from CLAUDE.md", context)

        # Demoted, it is an ordinary decision again, everywhere.
        self.assertEqual(run(["demote", claude_rid, "--project", self.p])[0], 0)
        code, text, _err = run(["hook", "session"], stdin=json.dumps({"cwd": self.p}))
        context = json.loads(text)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(f"`{claude_rid}` — the audit trail needs it", context)
        entry = next(
            d
            for d in _packet.build_resume_packet(self.mem, self.root)["active_decisions"]
            if d["id"] == claude_rid
        )
        self.assertNotIn("rule", entry)

    def test_a_read_only_clone_gets_the_rules_from_the_committed_packet(self):
        (self.root / "CLAUDE.md").write_text("# Guide\n", encoding="utf-8")
        rid = self.decision("Ledger rows are append-only")
        self.promote(rid)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "store")
        with tempfile.TemporaryDirectory() as other:
            clone = Path(other) / "clone"
            git(Path(other), "clone", "-q", str(self.root), str(clone))
            (clone / "CLAUDE.md").unlink()  # a harness that never reads it
            packet = (clone / crumb.MEMORY_DIRNAME / "generated" / "resume-packet.md").read_text(
                encoding="utf-8"
            )
        self.assertIn(f"`{rid}` — standing rule in CLAUDE.md: Ledger rows are append-only", packet)


if __name__ == "__main__":
    unittest.main()
