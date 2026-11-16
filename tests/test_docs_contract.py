"""Docs that state facts the code can check (review 2026-11-13, §3.5).

Run with:  python -m unittest discover -s tests -p test_docs_contract.py
"""

from __future__ import annotations

import argparse
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from breadcrumbs import cli_parser  # noqa: E402


def _commands() -> list[str]:
    """Every command and sub-command the parser accepts, as typed."""
    parser = cli_parser.build_parser()
    top = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    out = []
    for name, sub in top.choices.items():
        nested = [a for a in sub._actions if isinstance(a, argparse._SubParsersAction)]
        out.extend([f"{name} {n}" for n in nested[0].choices] if nested else [name])
    return out


def _table_heads() -> list[list[str]]:
    """The command table's first cells, each as `[command, alternatives…]`.

    `hook session\\|guard` reads as `["hook", "session", "guard"]`.
    """
    spec = (REPO_ROOT / "docs" / "cli-spec.md").read_text(encoding="utf-8")
    table = spec.split("## Command table", 1)[1].split("\n## ", 1)[0]
    heads = []
    for line in table.splitlines():
        m = re.match(r"\| `([^`]*)`", line)
        if m:
            words = m.group(1).split()
            alts = words[1].split("\\|") if len(words) > 1 else []
            heads.append([words[0], *alts])
    return heads


class CliSpecTests(unittest.TestCase):
    def test_every_command_has_a_row(self):
        """`docs/quickstart.md` says cli-spec documents every command; `repair`,
        `rename`, `retitle`, `traps`, `handoff trim` and `inbox import` had none."""
        heads = _table_heads()
        missing = []
        for command in _commands():
            name, _, sub = command.partition(" ")
            if not any(h[0] == name and (not sub or sub in h[1:]) for h in heads):
                missing.append(command)
        self.assertEqual(missing, [], "add a row to docs/cli-spec.md's command table")


class VersioningProseTests(unittest.TestCase):
    FILES = ("README.md", "RELEASING.md", "pyproject.toml")

    def test_no_doc_ties_a_schema_change_to_a_major_release(self):
        """A schema_version change is a minor release (docs/compatibility.md §1)."""
        for name in self.FILES:
            text = " ".join((REPO_ROOT / name).read_text(encoding="utf-8").split())
            with self.subTest(file=name):
                self.assertNotRegex(text, r"(?i)MAJOR (bump accompanies|version moves with)")
                self.assertNotRegex(text, r"(?i)package MAJOR only alongside")
                self.assertNotIn("schema_version: 1`", text)

    def test_get_version_has_no_fallback_to_describe(self):
        """It returns `__version__` unconditionally."""
        for name in ("RELEASING.md", "CONTRIBUTING.md", ".github/workflows/release.yml"):
            with self.subTest(file=name):
                text = (REPO_ROOT / name).read_text(encoding="utf-8")
                self.assertNotIn("source-checkout fallback", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
