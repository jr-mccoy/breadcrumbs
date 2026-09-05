"""Tests for the shared `--json` envelope (C4).

`--json` grew one command at a time and every command named its result list
differently — `scan-secrets` returns `hits`, `validate` returns `findings`,
`search` returns `matches`. Every consumer needed a per-subcommand adapter, and
the failure mode is silent: a defensive `d.get("findings", [])` written against
`validate` and pointed at `scan-secrets` reports zero problems rather than
raising. The original keys are all still there; `items`, `ok` and `command` are
what a reader can rely on without knowing which command it is talking to.

Run with:  python -m unittest discover -s tests
       or:  python tests/test_json_envelope.py
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

FIXTURES = REPO_ROOT / "fixtures"


def run_json(argv: list[str]) -> tuple[int, dict]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv + ["--json"])
    return code, json.loads(buf.getvalue())


class EnvelopeTests(unittest.TestCase):
    STORE = str(FIXTURES / "fixture-01-fresh-resume")

    def _commands(self) -> list[list[str]]:
        return [
            ["validate", "--project", self.STORE],
            ["scan-secrets", "--project", self.STORE],
            ["audit", "--project", self.STORE],
            ["search", "auth", "--project", self.STORE],
            ["guard", "edit the auth middleware", "--project", self.STORE],
            ["doctor", "--project", self.STORE],
            ["resume", "--project", self.STORE],
        ]

    def test_every_command_carries_the_core_keys(self):
        for argv in self._commands():
            with self.subTest(argv=argv):
                _code, payload = run_json(argv)
                self.assertIn("ok", payload)
                self.assertIsInstance(payload["ok"], bool)
                self.assertTrue(payload["command"].startswith("crumb "))
                self.assertIsInstance(payload["items"], list)

    def test_items_aliases_each_commands_own_list(self):
        _c, validate = run_json(["validate", "--project", self.STORE])
        self.assertEqual(validate["items"], validate["findings"])
        _c, secrets = run_json(["scan-secrets", "--project", self.STORE])
        self.assertEqual(secrets["items"], secrets["hits"])
        _c, search = run_json(["search", "auth", "--project", self.STORE])
        self.assertEqual(search["items"], search["matches"])

    def test_the_old_keys_are_still_there(self):
        """The envelope is additive — nothing written against 0.1.12 breaks."""
        _c, validate = run_json(["validate", "--project", self.STORE])
        for key in ("passed", "failed", "findings"):
            self.assertIn(key, validate)
        _c, guard = run_json(["guard", "edit auth", "--project", self.STORE])
        for key in ("verdict", "action", "matches", "recommended_action"):
            self.assertIn(key, guard)

    def test_ok_tracks_the_exit_code(self):
        code, payload = run_json(
            ["validate", "--project", str(FIXTURES / "fixture-08-packet-stale")]
        )
        self.assertEqual(code, 1)
        self.assertIs(payload["ok"], False)
        code, payload = run_json(["validate", "--project", self.STORE])
        self.assertEqual(code, 0)
        self.assertIs(payload["ok"], True)

    def test_an_error_is_the_same_shape_as_a_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, payload = run_json(["validate", "--project", tmp])
            self.assertEqual(code, 2)
            self.assertIs(payload["ok"], False)
            self.assertEqual(payload["command"], "crumb validate")
            self.assertEqual(payload["items"], [])
            self.assertIn("error", payload)

    def test_one_reader_works_across_commands(self):
        """The point of the change: no per-subcommand adapter, no silent zero."""

        def problems(argv: list[str]) -> int:
            _code, payload = run_json(argv)
            return 0 if payload["ok"] else max(1, len(payload["items"]))

        stale = str(FIXTURES / "fixture-08-packet-stale")
        self.assertGreater(problems(["validate", "--project", stale]), 0)
        self.assertGreater(
            problems(["scan-secrets", "--project", str(FIXTURES / "fixture-06-secret-leak")]), 0
        )
        self.assertEqual(problems(["validate", "--project", self.STORE]), 0)


if __name__ == "__main__":
    unittest.main()
