"""`crumb rename` and `crumb handoff trim` (DoWhat field report 2026-10-01,
issues 5 and 1), and the doctor checks that point at them.

Run with:  python -m unittest discover -s tests -p test_rename.py
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True, text=True)


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, buf.getvalue()


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@t")
        git(self.root, "config", "user.name", "t")
        run(["init", "--project", str(self.root), "--session-tracking", "full"])
        self.mem = self.root / crumb.MEMORY_DIRNAME

    def tearDown(self):
        self._tmp.cleanup()


class RenameTests(Case):
    def _long_record(self) -> tuple[str, Path]:
        stem = "2026-05-01-" + "-".join(["very-long-name"] * 13)
        path = self.mem / "decisions" / f"{stem}.md"
        rid = _cli.derive_identity(stem, "decision")[0]
        path.write_text(
            _cli.render_frontmatter(
                {
                    "id": rid,
                    "title": "Old long one",
                    "status": "active",
                    "created_at": "2026-05-01T00:00:00+00:00",
                    "updated_at": "2026-05-01T00:00:00+00:00",
                    "privacy": "repo-safe",
                    "confidence": "low",
                    "scope": "project",
                }
            )
            + "\n## Decision\nd\n"
        )
        return rid, path

    def test_rename_updates_references_and_the_old_id_still_resolves(self):
        old_id, old_path = self._long_record()
        run(
            [
                "remember",
                "decision",
                "--project",
                str(self.root),
                "--title",
                "Newer",
                "--set",
                "Decision",
                f"replaces {old_id}",
                "--confidence",
                "low",
            ]
        )
        code, out = run(
            ["rename", old_id, "--slug", "short-name", "--project", str(self.root), "--json"]
        )
        self.assertEqual(code, 0, out)
        doc = json.loads(out)
        self.assertEqual(doc["to"], "dec_20260501_short-name")
        self.assertFalse(old_path.exists())
        self.assertTrue((self.mem / "decisions" / "2026-05-01-short-name.md").exists())
        self.assertTrue(any("decisions/" in u for u in doc["updated"]))
        newer = [p for p in (self.mem / "decisions").glob("*newer*.md")][0].read_text(
            encoding="utf-8"
        )
        self.assertIn("dec_20260501_short-name", newer)
        self.assertNotIn(old_id, newer)
        self.assertEqual(crumb.find_record_by_id(self.mem, old_id).meta["id"], doc["to"])
        self.assertEqual([f for f in crumb.run_validate(self.mem) if f["status"] == "fail"], [])

    def test_doctor_names_an_over_long_path(self):
        self._long_record()
        code, out = run(["doctor", "--project", str(self.root), "--json"])
        doc = json.loads(out)
        checks = {c["check"]: c for c in doc.get("checks", [])}
        self.assertIn("path_length", checks, out)
        self.assertFalse(checks["path_length"]["ok"])
        self.assertIn("crumb rename", checks["path_length"]["detail"])


class TrimTests(Case):
    def test_trim_moves_old_entries_and_deletes_nothing(self):
        for i in range(5):
            run(["capture", "session", "--project", str(self.root), "--next", f"step {i}"])
        code, out = run(["handoff", "trim", "--keep", "2", "--project", str(self.root), "--json"])
        self.assertEqual(code, 0, out)
        doc = json.loads(out)
        self.assertEqual((doc["kept"], doc["moved"]), (2, 3))
        sec = crumb.split_md_sections((self.mem / "handoff.md").read_text(encoding="utf-8"))[
            "Next Action"
        ]
        self.assertEqual(crumb.split_next_entries(sec), ["step 4", "step 3"])
        hist = (self.mem / "handoff-history.md").read_text(encoding="utf-8")
        for i in range(3):
            self.assertIn(f"step {i}", hist)
        self.assertLess(hist.index("step 2"), hist.index("step 0"))
        run(["capture", "session", "--project", str(self.root), "--next", "step 5"])
        run(["handoff", "trim", "--keep", "2", "--project", str(self.root)])
        hist = (self.mem / "handoff-history.md").read_text(encoding="utf-8")
        self.assertLess(hist.index("step 3"), hist.index("step 2"))
        self.assertEqual(
            [
                f
                for f in crumb.run_validate(self.mem)
                if f["status"] == "fail" and f["check"] != "freshness"
            ],
            [],
        )


class HandKeptLogTests(Case):
    """DoWhat retest of 0.5.0, item 11: a hand-kept log of dated paragraphs under
    `### Earlier, as written` was one entry, so `trim --keep 10` could not
    move any of it and doctor reported "11309 characters (1 entries)"."""

    def _hand_kept_log(self, n: int = 12) -> str:
        paras = []
        for i in range(n):
            day = 30 - i
            paras.append(
                f"**2026-09-{day:02d} (Claude Code web session, branch `ccr-{i}`, NOT on `main`): "
                f"headline {i}**\n"
                + ("Details of what happened and what to do next. " * 30).strip()
                + f"\nMore on item {i}.\n"
            )
        return "\n".join(paras)

    def _write_handoff(self) -> tuple[str, str]:
        run(["capture", "session", "--project", str(self.root), "--next", "seed"])
        path = self.mem / "handoff.md"
        text = path.read_text(encoding="utf-8")
        sec = crumb.split_md_sections(text)["Next Action"]
        log = self._hand_kept_log()
        body = f"### 2026-10-01 · `abc1234`\nnewest crumb entry\n\n### Earlier, as written\n{log}"
        path.write_text(text.replace(sec, body + "\n"), encoding="utf-8")
        return path.read_text(encoding="utf-8"), body

    def test_doctor_counts_the_dated_paragraphs(self):
        self._write_handoff()
        code, out = run(["doctor", "--project", str(self.root)])
        self.assertIn("(13 entries)", out)

    def test_trim_moves_paragraphs_and_keeps_every_byte(self):
        before, body = self._write_handoff()
        code, out = run(["handoff", "trim", "--keep", "3", "--project", str(self.root), "--json"])
        self.assertEqual(code, 0, out)
        doc = json.loads(out)
        self.assertEqual((doc["kept"], doc["moved"]), (3, 10))
        sec = crumb.split_md_sections((self.mem / "handoff.md").read_text(encoding="utf-8"))[
            "Next Action"
        ]
        self.assertIn("headline 1**", sec)
        self.assertNotIn("headline 2**", sec)
        hist = (self.mem / "handoff-history.md").read_text(encoding="utf-8")
        moved = hist.split("<!-- entries below, newest first -->\n", 1)[1]
        kept = sec.strip("\n")
        # The kept text and the moved text together are the original, byte for
        # byte; only the blank line at the cut is not repeated.
        self.assertEqual(kept + "\n\n" + moved.rstrip("\n"), body.rstrip("\n"))

    def test_trim_before_a_date(self):
        self._write_handoff()
        code, out = run(
            ["handoff", "trim", "--before", "2026-09-25", "--project", str(self.root), "--json"]
        )
        self.assertEqual(code, 0, out)
        sec = crumb.split_md_sections((self.mem / "handoff.md").read_text(encoding="utf-8"))[
            "Next Action"
        ]
        self.assertIn("2026-09-25", sec)
        self.assertNotIn("2026-09-24", sec)
        self.assertIn("2026-09-24", (self.mem / "handoff-history.md").read_text(encoding="utf-8"))

    def test_split_on_another_lead_in(self):
        run(["capture", "session", "--project", str(self.root), "--next", "seed"])
        path = self.mem / "handoff.md"
        text = path.read_text(encoding="utf-8")
        sec = crumb.split_md_sections(text)["Next Action"]
        log = "\n".join(f"Day {i}: did thing {i}.\nmore {i}\n" for i in range(6))
        path.write_text(text.replace(sec, f"### Earlier, as written\n{log}"), encoding="utf-8")
        code, out = run(
            [
                "handoff",
                "trim",
                "--keep",
                "2",
                "--split-on",
                r"^Day \d+:",
                "--project",
                str(self.root),
                "--json",
            ]
        )
        self.assertEqual(json.loads(out)["moved"], 4)
