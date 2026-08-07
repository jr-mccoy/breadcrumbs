"""Tests for `crumb doctor` — integration health.

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


class AdapterBloatTests(unittest.TestCase):
    """The bloat check must size our managed block, not the host file.

    CLAUDE.md/AGENTS.md are the project's own agent-instruction files; a mature
    repo's is tens of KB. Measuring the file meant the adapter row went ✗
    "bloated" the moment the signpost was installed correctly, and stayed there.
    """

    def _install(self, tmp: str, host: str) -> dict:
        root = Path(tmp)
        (root / "CLAUDE.md").write_text(host, encoding="utf-8")
        run(
            [
                "init",
                "--project",
                tmp,
                "--session-tracking",
                "full",
                "--with-adapter=CLAUDE.md",
            ]
        )
        code, out = run(["doctor", "--project", tmp, "--json"])
        return {"code": code, **checks_by_name(json.loads(out))["adapter"]}

    def test_large_host_file_with_small_block_passes(self):
        host = "# FamilyHub\n\n" + ("guidance line for the agent\n" * 4000)
        self.assertGreater(len(host), 10 * crumb.ADAPTER_BLOAT_CHARS)
        with tempfile.TemporaryDirectory() as tmp:
            adapter = self._install(tmp, host)
            self.assertTrue(adapter["ok"], adapter["detail"])
            self.assertNotIn("BLOATED", adapter["detail"])
            # The host content survived; we measured the block, not the file.
            self.assertIn(
                "guidance line for the agent",
                (Path(tmp) / "CLAUDE.md").read_text(encoding="utf-8"),
            )

    def test_a_bloated_managed_block_is_still_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._install(tmp, "# small\n")
            path = Path(tmp) / "CLAUDE.md"
            padded = path.read_text(encoding="utf-8").replace(
                crumb.ADAPTER_END,
                ("x" * (crumb.ADAPTER_BLOAT_CHARS + 1)) + "\n" + crumb.ADAPTER_END,
            )
            path.write_text(padded, encoding="utf-8")
            _, out = run(["doctor", "--project", tmp, "--json"])
            adapter = checks_by_name(json.loads(out))["adapter"]
            self.assertFalse(adapter["ok"])
            self.assertIn("BLOATED", adapter["detail"])

    def test_managed_block_text_extracts_only_the_block(self):
        text = "before\n" + crumb.adapter_block() + "\nafter\n"
        block = crumb.managed_block_text(text)
        self.assertIsNotNone(block)
        self.assertNotIn("before", block)
        self.assertNotIn("after", block)
        self.assertTrue(block.startswith(crumb.ADAPTER_BEGIN))
        self.assertTrue(block.endswith(crumb.ADAPTER_END))
        self.assertIsNone(crumb.managed_block_text("no block here\n"))


if __name__ == "__main__":
    unittest.main()
