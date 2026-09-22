"""Tests for per-store search aliases (WM-24, `.project-memory/aliases.txt`).

The built-in stemmer folds morphology (`migrations` → `migrat`), never meaning:
`billing` and `payments` are different stems, so a trap filed under one was
invisible to a guard phrased with the other. A store's own vocabulary is the one
thing the package can never ship, so the store says it, one group per line.

Run with:  python -m unittest discover -s tests
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
from breadcrumbs import cli as _cli  # noqa: E402


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, buf.getvalue()


def store_with_trap(tmp: str) -> Path:
    crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
    mem = Path(tmp) / crumb.MEMORY_DIRNAME
    res = crumb.note(
        mem,
        Path(tmp),
        "trap",
        "billing webhook retries double-charge",
        fields={
            "area": "src/billing/webhook.py",
            "symptom": "a customer is charged twice",
            "why": "the billing provider retries on timeout",
            "safe": "make the handler idempotent",
            "verify": "python -m unittest",
        },
    )
    assert res["ok"], res
    return mem


class ParseAliasesTests(unittest.TestCase):
    def test_first_word_is_canonical(self):
        mapping, problems = _cli.parse_store_aliases("billing payments invoicing\n")
        self.assertEqual(problems, [])
        canonical = _cli._base_stem("billing")
        self.assertEqual(mapping[_cli._base_stem("payments")], canonical)
        self.assertEqual(mapping[_cli._base_stem("invoicing")], canonical)
        self.assertNotIn(canonical, mapping, "the canonical stem maps to itself implicitly")

    def test_comments_and_blank_lines_are_ignored(self):
        mapping, problems = _cli.parse_store_aliases("# vocabulary\n\nauth login  # same thing\n")
        self.assertEqual(problems, [])
        self.assertEqual(mapping, {_cli._base_stem("login"): _cli._base_stem("auth")})

    def test_a_one_word_line_is_a_problem_not_a_crash(self):
        mapping, problems = _cli.parse_store_aliases("lonely\nauth login\n")
        self.assertEqual([p["line"] for p in problems], [1])
        self.assertIn(_cli._base_stem("login"), mapping)

    def test_an_earlier_group_keeps_a_word(self):
        mapping, problems = _cli.parse_store_aliases("auth login\nsession login\n")
        self.assertEqual(mapping[_cli._base_stem("login")], _cli._base_stem("auth"))
        self.assertEqual([p["line"] for p in problems], [2])

    def test_chains_resolve_so_stemming_stays_idempotent(self):
        # `login` -> `auth`, and a later group makes `auth`'s canonical form a
        # member of nothing new; every value must itself be a fixpoint.
        mapping, _ = _cli.parse_store_aliases("signin login\nauth signin\n")
        for value in mapping.values():
            self.assertNotIn(value, mapping)


class AliasSearchTests(unittest.TestCase):
    def tearDown(self):
        # Aliases are process-global while active; never leak into other tests.
        _cli._STORE_ALIASES = {}
        _cli._STORE_ALIASES_KEY = None

    def test_an_alias_makes_the_synonym_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = store_with_trap(tmp)
            trap = "trap_billing-webhook-retries-double-charge"
            before, _ = crumb.search(mem, Path(tmp), "payments")
            self.assertNotIn(trap, [m["id"] for m in before])
            (mem / "aliases.txt").write_text("billing payments\n", encoding="utf-8")
            after, _ = crumb.search(mem, Path(tmp), "payments")
            self.assertIn(trap, [m["id"] for m in after])

    def test_removing_the_file_turns_aliases_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = store_with_trap(tmp)
            (mem / "aliases.txt").write_text("billing payments\n", encoding="utf-8")
            crumb.search(mem, Path(tmp), "payments")
            self.assertTrue(_cli._STORE_ALIASES)
            (mem / "aliases.txt").unlink()
            crumb.search(mem, Path(tmp), "payments")
            self.assertEqual(_cli._STORE_ALIASES, {})

    def test_editing_aliases_makes_projections_stale(self):
        # The guard prefilter stores stems; a new alias changes what they are,
        # so the aliases file is one of the inputs the freshness hash covers.
        with tempfile.TemporaryDirectory() as tmp:
            mem = store_with_trap(tmp)
            before = _cli._inputs_hash(mem, Path(tmp))
            (mem / "aliases.txt").write_text("billing payments\n", encoding="utf-8")
            self.assertNotEqual(_cli._inputs_hash(mem, Path(tmp)), before)

    def test_guard_sees_the_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = store_with_trap(tmp)
            (mem / "aliases.txt").write_text("billing payments\n", encoding="utf-8")
            crumb.main(["reindex", "--project", tmp])
            res = crumb.guard(mem, Path(tmp), "edit the payments webhook retry handler")
            self.assertIn(
                "trap_billing-webhook-retries-double-charge",
                [m["id"] for m in res["matches"]],
            )

    def test_explain_shows_the_query_stems(self):
        with tempfile.TemporaryDirectory() as tmp:
            store_with_trap(tmp)
            code, out = run(["search", "payments webhooks", "--project", tmp, "--explain"])
            self.assertEqual(code, 0)
            self.assertIn("query stems:", out)
            self.assertIn(_cli._base_stem("webhooks"), out)
            code, out = run(
                ["search", "payments webhooks", "--project", tmp, "--explain", "--json"]
            )
            self.assertEqual(code, 0)
            self.assertIn("query_stems", json.loads(out))

    def test_a_malformed_line_is_an_audit_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = store_with_trap(tmp)
            (mem / "aliases.txt").write_text("billing payments\nlonely\n", encoding="utf-8")
            findings = [f for f in crumb.run_audit(mem, Path(tmp)) if f["check"] == "aliases"]
            self.assertEqual(len(findings), 1, findings)
            self.assertEqual(findings[0]["line"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
