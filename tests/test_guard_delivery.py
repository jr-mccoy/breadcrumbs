"""The guard hook delivers what full guard would, and never more authority (audit F10, F11; WP11).

- F10: `npm test` against a trap about `npm test` got PROCEED, and the hook
  stayed silent.
- F11: the hook runs full guard only when a cheap pre-filter says it might
  match. That pre-filter covered traps and do-not-retry attempts only, so an
  edit to a file a *decision* declares could draw READ_FIRST from
  `crumb guard` and silence from the hook.

These pin the replacement:

- a named command is never PROCEED;
- the pre-filter is a strict superset of what full guard surfaces, checked on
  every eval suite;
- remedies, controls, stance, read-only ceilings and permission modes behave
  as before;
- the exit-code mapping stands, with an opt-in `--exit-zero`.

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli  # noqa: E402
from breadcrumbs import hooks_guard  # noqa: E402
from breadcrumbs import scoring as _scoring  # noqa: E402

RUN_PY = REPO_ROOT / "evals" / "run.py"
MODES = (None, "default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "unknownMode")
PROMPTING = (None, "default", "acceptEdits", "plan", "unknownMode")


def load_evals():
    spec = importlib.util.spec_from_file_location("crumb_evals_run_wp11", RUN_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hook_guard(root: Path, tool: str, tool_input: dict, session: str, mode=None) -> dict:
    payload = {"cwd": str(root), "session_id": session, "tool_name": tool, "tool_input": tool_input}
    if mode is not None:
        payload["permission_mode"] = mode
    out = io.StringIO()
    saved = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload))
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = crumb.main(["hook", "guard"])
    finally:
        sys.stdin = saved
    assert code == 0
    text = out.getvalue().strip()
    return json.loads(text) if text else {}


def spoke(doc: dict) -> bool:
    hso = doc.get("hookSpecificOutput") or {}
    return bool(hso.get("additionalContext") or hso.get("permissionDecisionReason"))


class StoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        with contextlib.redirect_stdout(io.StringIO()):
            crumb.main(["init", "--project", str(self.root), "--session-tracking", "full"])
        self.mem = self.root / crumb.MEMORY_DIRNAME
        crumb.note(
            self.mem,
            self.root,
            "trap",
            "npm test also runs the integration suite, which truncates the local database",
            fields={"safe": "Run `npm run test:unit` for the unit tests only."},
        )
        crumb.note(
            self.mem,
            self.root,
            "trap",
            "git log --all is slow on the monorepo",
            fields={"safe": "Scope it with a path."},
        )
        crumb.write_record(
            self.mem,
            self.root,
            "attempt",
            "Rewrote the billing reconciler in one pass",
            {"Tried": "a full rewrite", "Do Not Retry Unless": "the ledger tests are green first"},
            evidence=[{"type": "file", "ref": "src/billing.py"}],
        )
        crumb.write_record(
            self.mem,
            self.root,
            "decision",
            "Orders are cached in Redis for 60 seconds",
            {"Decision": "GET /orders is cached."},
            evidence=[{"type": "file", "ref": "src/cache.ts"}],
            tags=["orders"],
        )
        cli.reindex_projections(self.mem, self.root)

    def bash(self, command: str, session: str, mode=None) -> dict:
        return hook_guard(self.root, "Bash", {"command": command}, session, mode)


class KnownCommandTests(StoreCase):
    def test_known_destructive_npm_test_never_proceeds_silently(self):
        variants = ("npm test", "npm test --watch", "cd web && npm test", "npm test 2>&1 | tail -5")
        for command in variants:
            with self.subTest(command=command):
                self.assertNotEqual(
                    _scoring.guard(self.mem, self.root, command)["verdict"], "PROCEED"
                )
        for i, mode in enumerate(MODES):
            for j, command in enumerate(variants):
                with self.subTest(mode=mode, command=command):
                    out = self.bash(command, f"m{i}-{j}", mode)
                    self.assertTrue(spoke(out), out)
                    self.assertIn("trap_npm-test", json.dumps(out))
        # With the pre-filter unverified (a stale publication), the full guard
        # runs anyway and still warns.
        (self.mem / "index" / "generation.json").unlink()
        self.assertTrue(spoke(self.bash("npm test", "unverified")))


class AgreementTests(unittest.TestCase):
    """Across every eval suite: whatever full guard would surface, the hook does."""

    @classmethod
    def setUpClass(cls):
        if not RUN_PY.is_file():  # pragma: no cover - an sdist ships without evals/
            raise unittest.SkipTest("evals/ is not in this tree")
        cls.evals = load_evals()

    def actions(self, mem: Path, root: Path, tasks: list[dict]) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        for task in tasks:
            out.append(("Bash", {"command": task["task"]}))
            for f in task["files"]:
                out.append(("Edit", {"file_path": f, "new_string": task["task"]}))
        for item in _scoring._candidate_items(mem, include_ideas=False):
            if not cli._may_drive_verdict(item):
                continue
            title = str(item.get("title") or "").split(":", 1)[-1].strip()
            words = title.split()
            out.append(("Bash", {"command": title}))
            if len(words) >= 2:
                out.append(("Bash", {"command": " ".join(words[:2])}))
            for f in sorted(item.get("files") or ()) + sorted(item.get("mentioned_files") or ()):
                if "/" in f:
                    out.append(("Edit", {"file_path": f, "new_string": "x = 1"}))
            for head in item.get("command_heads") or ():
                out.append(("Bash", {"command": " ".join(head[1:4])}))
        return out

    def test_full_guard_and_hook_agree_on_required_warning(self):
        checked = surfaced = 0
        for suite in self.evals.discover():
            spec = self.evals.parse_tasks((suite / "tasks.yml").read_text("utf-8"))
            with tempfile.TemporaryDirectory() as tmp:
                project = Path(tmp) / suite.name
                mem = self.evals.build_store(suite, project)
                with mock.patch.object(cli, "_now", return_value=self.evals._clock(spec["as_of"])):
                    cli.reindex_projections(mem, project)
                    for i, (tool, tool_input) in enumerate(
                        self.actions(mem, project, spec["tasks"])
                    ):
                        action, files = hooks_guard._hook_action_from_tool(tool, tool_input)
                        if not action:
                            continue
                        checked += 1
                        verdict = _scoring.guard(mem, project, action, files=files)["verdict"]
                        if verdict == "PROCEED":
                            continue
                        surfaced += 1
                        with self.subTest(suite=suite.name, action=action[:80], verdict=verdict):
                            # The pre-filter admits it (or the action is risky
                            # enough to bypass it), and the real hook speaks.
                            _p, classes = _scoring.classify_action(action)
                            self.assertTrue(
                                hooks_guard._prefilter_trap_hit(mem, action, files)
                                or classes != ["routine_edit"]
                                or bool(_scoring._HOOK_RISK_RE.search(action))
                            )
                            out = hook_guard(project, tool, tool_input, f"agree-{i}")
                            self.assertTrue(spoke(out), (verdict, out))
        self.assertGreater(checked, 200)
        self.assertGreater(surfaced, 20)

    def test_the_old_prefilter_missed_a_decision_file(self):
        # The shape F11 names: an edit to a file only a decision declares.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            with contextlib.redirect_stdout(io.StringIO()):
                crumb.main(["init", "--project", str(root)])
            mem = root / crumb.MEMORY_DIRNAME
            crumb.write_record(
                mem,
                root,
                "decision",
                "Session tokens are parsed only in the session parser",
                {"Decision": "Nothing else parses tokens."},
                evidence=[{"type": "file", "ref": "src/auth/session_parser.py"}],
            )
            cli.reindex_projections(mem, root)
            edit = {"file_path": "src/auth/session_parser.py", "new_string": "x = 1"}
            action, files = hooks_guard._hook_action_from_tool("Edit", edit)
            self.assertEqual(
                _scoring.guard(mem, root, action, files=files)["verdict"], "READ_FIRST"
            )
            self.assertTrue(hooks_guard._prefilter_trap_hit(mem, action, files))
            self.assertTrue(spoke(hook_guard(root, "Edit", edit, "s")))


class BoundaryTests(StoreCase):
    def test_safe_remedy_and_unrelated_controls_remain_nonblocking(self):
        for i, command in enumerate(
            ("npm run test:unit", "npm install", "git status", "ls -la", "make", "pytest -q")
        ):
            with self.subTest(command=command):
                self.assertEqual(_scoring.guard(self.mem, self.root, command)["verdict"], "PROCEED")
                self.assertEqual(self.bash(command, f"c{i}"), {})
        # A read-only command a trap names is told, never blocked: READ_FIRST
        # is its ceiling, and READ_FIRST never takes a permission decision.
        result = _scoring.guard(self.mem, self.root, "git log --all")
        self.assertEqual(result["verdict"], "READ_FIRST")
        out = self.bash("git log --all", "ro")
        self.assertTrue(spoke(out))
        self.assertNotIn("permissionDecision", out["hookSpecificOutput"])
        # A blocking attempt keeps its stance: an edit of its file still PAUSEs.
        edit = {"file_path": "src/billing.py", "new_string": "rewrite everything"}
        action, files = hooks_guard._hook_action_from_tool("Edit", edit)
        self.assertEqual(
            _scoring.guard(self.mem, self.root, action, files=files)["verdict"], "PAUSE"
        )

    def test_permission_mode_never_gains_auto_allow(self):
        cases = {
            "PROCEED": ("Bash", {"command": "ls -la"}),
            "READ_FIRST": ("Bash", {"command": "npm test"}),
            "PAUSE": ("Edit", {"file_path": "src/billing.py", "new_string": "rewrite"}),
            "ASK_HUMAN": ("Bash", {"command": "rm -rf src/billing.py"}),
        }
        for verdict, (tool, tool_input) in cases.items():
            action, files = hooks_guard._hook_action_from_tool(tool, tool_input)
            self.assertEqual(
                _scoring.guard(self.mem, self.root, action, files=files)["verdict"], verdict
            )
            for i, mode in enumerate(MODES):
                for advisory in ("", "1"):
                    with self.subTest(verdict=verdict, mode=mode, advisory=advisory):
                        env = {"CRUMB_GUARD_ADVISORY": advisory} if advisory else {}
                        with mock.patch.dict(os.environ, env):
                            out = hook_guard(
                                self.root, tool, tool_input, f"{verdict}-{i}-{advisory}", mode
                            )
                        decision = (out.get("hookSpecificOutput") or {}).get("permissionDecision")
                        self.assertNotIn(decision, ("allow", "deny"))
                        asks = verdict in ("PAUSE", "ASK_HUMAN") and mode in PROMPTING
                        self.assertEqual(decision == "ask", asks and not advisory)
                        self.assertEqual(spoke(out), verdict != "PROCEED")

    def test_exit_codes_keep_their_mapping_and_exit_zero_is_opt_in(self):
        def guard(*extra: str) -> int:
            with contextlib.redirect_stdout(io.StringIO()):
                return crumb.main(["guard", *extra, "--project", str(self.root)])

        self.assertEqual(guard("ls -la"), 0)
        self.assertEqual(guard("npm test"), 10)
        self.assertEqual(guard("rewrite the billing reconciler", "--files", "src/billing.py"), 15)
        self.assertEqual(guard("rm -rf src/billing.py"), 20)
        for action in ("npm test", "rm -rf src/billing.py"):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = crumb.main(
                    ["guard", action, "--exit-zero", "--json", "--project", str(self.root)]
                )
            self.assertEqual(code, 0)
            self.assertIn(json.loads(out.getvalue())["verdict"], ("READ_FIRST", "ASK_HUMAN"))


if __name__ == "__main__":
    unittest.main()
