"""Tests for `crumb doctor` — integration health (review §A.7).

Run with:  python -m pytest tests/
       or:  python tests/test_doctor.py
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = crumb.main(argv)
    return code, buf.getvalue()


def checks_by_name(report: dict) -> dict:
    return {c["check"]: c for c in report["checks"]}


class DoctorTests(unittest.TestCase):
    def test_unintegrated_store_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            run(["init", "--project", tmp, "--session-tracking", "full"])
            code, out = run(["doctor", "--project", tmp, "--json"])
            self.assertEqual(code, 1)  # store exists but nothing wired up (the §5 finding)
            report = json.loads(out)
            self.assertFalse(report["integrated"])

    def test_integrated_store_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CLAUDE.md").write_text("# x\n", encoding="utf-8")
            run(
                [
                    "init",
                    "--project",
                    tmp,
                    "--session-tracking",
                    "full",
                    "--with-adapter",
                    "--with-mcp",
                ]
            )
            code, out = run(["doctor", "--project", tmp, "--json"])
            self.assertEqual(code, 0)
            report = json.loads(out)
            self.assertTrue(report["integrated"])
            checks = checks_by_name(report)
            self.assertTrue(checks["adapter"]["ok"])
            self.assertTrue(checks["mcp"]["ok"])

    def test_no_store_is_not_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(["doctor", "--project", tmp, "--json"])
            self.assertEqual(code, 0)  # no store at all is not "broken integration"
            self.assertFalse(checks_by_name(json.loads(out))["store"]["ok"])

    def test_detects_installed_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            run(
                [
                    "init",
                    "--project",
                    tmp,
                    "--session-tracking",
                    "full",
                    "--with-hooks",
                ]
            )
            _, out = run(["doctor", "--project", tmp, "--json"])
            self.assertTrue(checks_by_name(json.loads(out))["hooks"]["ok"])


if __name__ == "__main__":
    unittest.main()
