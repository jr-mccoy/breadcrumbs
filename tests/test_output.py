"""Tests for the output layer: encoding safety (W1) and error visibility (C2).

W1: a Windows console is cp1252, which cannot encode the ✓/✗ markers. `print`
raised UnicodeEncodeError mid-line, so `validate` and `scan-secrets` kept their
(correct) exit code and lost every per-item detail — you were told twelve
secrets and never which. C2: an argparse rejection led with a usage block and
ended with the caller's own prose, so a piped, truncated run read like success.

Run with:  python -m unittest discover -s tests
       or:  python tests/test_output.py
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402

FIXTURES = REPO_ROOT / "fixtures"


def run_on_console(argv: list[str], encoding: str) -> tuple[int, str]:
    """Run `argv` with stdout as a real encoding-enforcing stream, like a console."""
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding=encoding, newline="")
    saved_out, saved_marks = sys.stdout, (_cli.MARK_PASS, _cli.MARK_FAIL)
    sys.stdout = stream
    try:
        code = crumb.main(argv)
        stream.flush()
        data = raw.getvalue()
    finally:
        sys.stdout = saved_out
        _cli.MARK_PASS, _cli.MARK_FAIL = saved_marks
        stream.detach()  # leave the BytesIO open for the caller
    return code, data.decode(encoding, errors="replace")


# --------------------------------------------------------------------------- #
# W1 — the diagnostic payload survives a non-UTF-8 console
# --------------------------------------------------------------------------- #
class LegacyConsoleTests(unittest.TestCase):
    def test_validate_keeps_its_findings_on_cp1252(self):
        code, out = run_on_console(
            ["validate", "--project", str(FIXTURES / "fixture-08-packet-stale")], "cp1252"
        )
        self.assertEqual(code, 1, out)
        # The summary always survived; the per-item lines are what was lost.
        self.assertIn("problem(s) found", out)
        self.assertIn("[x]", out)
        self.assertNotIn("✗", out)

    def test_scan_secrets_keeps_its_hits_on_cp1252(self):
        code, out = run_on_console(
            ["scan-secrets", "--project", str(FIXTURES / "fixture-06-secret-leak")], "cp1252"
        )
        self.assertEqual(code, 1, out)
        self.assertIn("possible secret", out)
        self.assertIn("[x]", out)

    def test_utf8_console_keeps_the_unicode_markers(self):
        code, out = run_on_console(
            ["validate", "--project", str(FIXTURES / "fixture-08-packet-stale")], "utf-8"
        )
        self.assertEqual(code, 1, out)
        self.assertIn("✗", out)
        self.assertNotIn("[x]", out)

    def test_configure_output_never_raises_on_odd_streams(self):
        for stream in (io.StringIO(), None):
            _cli.configure_output(stream)
        self.assertIn(_cli.MARK_FAIL, ("✗", "[x]"))

    def test_non_marker_unicode_degrades_instead_of_crashing(self):
        """An em dash in any line must not take the line down on cp1252."""
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252", newline="")
        saved_out, saved_marks = sys.stdout, (_cli.MARK_PASS, _cli.MARK_FAIL)
        sys.stdout = stream
        try:
            _cli.configure_output()
            print("kept \u2014 dash")
            stream.flush()
            data = raw.getvalue()
        finally:
            sys.stdout = saved_out
            _cli.MARK_PASS, _cli.MARK_FAIL = saved_marks
            stream.detach()
        self.assertIn("kept", data.decode("cp1252", errors="replace"))


# --------------------------------------------------------------------------- #
# C2 — an error says so on its first line, and names the subcommand
# --------------------------------------------------------------------------- #
class ErrorVisibilityTests(unittest.TestCase):
    def _argparse_error(self, argv: list[str]) -> str:
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                crumb.main(argv)
        self.assertEqual(ctx.exception.code, 2)
        return err.getvalue()

    def test_unknown_flag_leads_with_the_marker(self):
        text = self._argparse_error(["note", "trap", "x", "--body", "some long text"])
        self.assertTrue(text.startswith(_cli.ERROR_PREFIX), text)

    def test_unknown_flag_names_the_subcommand_that_rejected_it(self):
        text = self._argparse_error(["note", "trap", "x", "--body", "some long text"])
        self.assertIn("crumb note trap:", text)
        self.assertIn("crumb note trap --help", text)

    def test_bad_flag_value_leads_with_the_marker(self):
        text = self._argparse_error(["mark-status", "dec_x", "not-a-status"])
        self.assertTrue(text.startswith(_cli.ERROR_PREFIX), text)

    def test_handled_errors_lead_with_the_marker_and_the_subcommand(self):
        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = crumb.main(["capture", "session", "--project", tmp, "--fast"])
        self.assertEqual(code, 2)
        self.assertTrue(err.getvalue().startswith(f"{_cli.ERROR_PREFIX} crumb capture session:"))

    def test_json_errors_carry_ok_false(self):
        import json

        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = crumb.main(["capture", "session", "--project", tmp, "--json", "--fast"])
        self.assertEqual(code, 2)
        payload = json.loads(buf.getvalue())
        self.assertIs(payload["ok"], False)
        self.assertIn("error", payload)

    def test_success_names_the_written_file_before_any_trailing_note(self):
        """`head -2` on a success must already hold the path that was written."""
        with tempfile.TemporaryDirectory() as tmp:
            crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = crumb.main(
                    ["verify", "subject-under-test", "--status", "fixed", "--project", tmp]
                )
        self.assertEqual(code, 0, buf.getvalue())
        lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
        self.assertIn("file:", lines[1])


if __name__ == "__main__":
    unittest.main()
