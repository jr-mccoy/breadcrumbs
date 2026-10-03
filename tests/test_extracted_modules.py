"""Modules extracted from `cli.py` (deferred health review 2.1).

`cli.py` held half the package. Seams move out one at a time into modules that
import `cli` for the helpers that stay there; `cli` imports them last. These
tests pin the contract every extraction keeps:

- the package names the module a function lives in, never `cli.NAME` for a
  moved name (the forward in `cli.__getattr__` is for code outside the
  package, such as the byte-identical audit probes in tools/audit);
- a name is moved, not copied: `cli` does not define it as well;
- the import cycle is harmless whichever side is imported first;
- `crumb.NAME`, the shim the suite uses, still reaches every moved name.

Run with:  python -m unittest discover -s tests -p test_extracted_modules.py
"""

from __future__ import annotations

import ast
import importlib
import subprocess
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402


def defined_names(path: Path) -> set[str]:
    """Top-level functions, classes and assigned names a module defines."""
    out: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                out.update(n.id for n in ast.walk(t) if isinstance(n, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
    return out


def moved_names() -> dict[str, str]:
    """{name: module} for every name an extracted module defines."""
    out = {}
    for module in _cli.EXTRACTED_MODULES:
        for name in defined_names(ROOT / "breadcrumbs" / f"{module}.py"):
            out[name] = module
    return out


class ExtractedModulesTests(unittest.TestCase):
    def test_the_package_names_the_module_not_cli(self):
        moved = moved_names()
        offenders = []
        for path in sorted((ROOT / "breadcrumbs").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in ("cli", "_cli")
                    and node.attr in moved
                ):
                    rel = path.relative_to(ROOT).as_posix()
                    offenders.append(f"{rel}:{node.lineno}: cli.{node.attr} -> {moved[node.attr]}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_a_moved_name_is_not_also_defined_in_cli(self):
        both = sorted(set(moved_names()) & defined_names(ROOT / "breadcrumbs" / "cli.py"))
        self.assertEqual(both, [])

    def test_every_moved_name_is_reachable_from_cli_and_the_shim(self):
        for name, module in sorted(moved_names().items()):
            with self.subTest(name=name):
                owner = importlib.import_module(f"breadcrumbs.{module}")
                self.assertIs(getattr(_cli, name), getattr(owner, name))
                self.assertIs(getattr(crumb, name), getattr(owner, name))

    def test_the_forward_does_not_hand_out_modules(self):
        # An extracted module's own imports (`_hooks_stop`, `_claude`, …) are not
        # names `cli` defines, and the forward must not make them look like it.
        for module in _cli.EXTRACTED_MODULES:
            owner = importlib.import_module(f"breadcrumbs.{module}")
            for name, value in vars(owner).items():
                if isinstance(value, types.ModuleType) and name not in vars(_cli):
                    with self.subTest(module=module, name=name):
                        with self.assertRaises(AttributeError):
                            getattr(_cli, name)

    def test_either_side_can_be_imported_first(self):
        for module in _cli.EXTRACTED_MODULES:
            with self.subTest(module=module):
                out = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        f"import breadcrumbs.{module} as m, breadcrumbs.cli as c; "
                        f"print(c.EXTRACTED_MODULES.count({module!r}))",
                    ],
                    capture_output=True,
                    text=True,
                    cwd=str(ROOT),
                )
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertEqual(out.stdout.strip(), "1")


if __name__ == "__main__":
    unittest.main()
