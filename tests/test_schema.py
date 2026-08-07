"""Tests for `crumb schema` (schema discoverable without probing --help).

Run with:  python -m pytest tests/
       or:  python tests/test_schema.py
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
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


class SchemaTests(unittest.TestCase):
    def test_json_lists_all_record_types(self):
        code, out = run(["schema", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["schema_version"], crumb.SCHEMA_VERSION)
        self.assertEqual(
            set(payload["record_types"]),
            set(crumb.BODY_SECTIONS),
        )
        self.assertEqual(
            payload["record_types"]["attempt"]["body_sections"],
            crumb.BODY_SECTIONS["attempt"],
        )

    def test_no_memory_dir_required(self):
        # schema is a pure projection; works from any cwd with no store
        code, _ = run(["schema"])
        self.assertEqual(code, 0)

    def test_single_type_filter(self):
        code, out = run(["schema", "attempt", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(list(payload["record_types"]), ["attempt"])

    def test_unknown_type_errors(self):
        code, _ = run(["schema", "bogus", "--json"])
        self.assertEqual(code, 2)

    def test_template_emits_named_flags_for_attempt(self):
        code, out = run(["schema", "attempt", "--template"])
        self.assertEqual(code, 0)
        self.assertIn("crumb remember attempt", out)
        self.assertIn("--problem", out)
        self.assertIn("--do-not-retry", out)
        # Evidence is supplied via --evidence, not a body --set
        self.assertNotIn("--set 'Evidence'", out)

    def test_template_uses_set_for_decision(self):
        code, out = run(["schema", "decision", "--template"])
        self.assertEqual(code, 0)
        self.assertIn("--set 'Context'", out)

    def test_template_requires_type(self):
        code, _ = run(["schema", "--template"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
