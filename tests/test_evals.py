"""Tests for the relevance eval harness (WM-61).

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


RUN_PY = REPO_ROOT / "evals" / "run.py"


def _load_run():
    spec = importlib.util.spec_from_file_location("crumb_evals_run", RUN_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# setuptools puts tests/test_*.py in the sdist but not evals/, which is repo-only.
if not RUN_PY.is_file():  # pragma: no cover - only in an unpacked sdist
    raise unittest.SkipTest("evals/ is not in this tree (an sdist ships without it)")
run = _load_run()

TINY_STORE = """\
# two records, one about each topic
@2026-05-01 remember decision --title "Cache the orders API in Redis"
  --set Decision "GET /api/orders is cached in Redis for 60 seconds."
  --evidence file src/cache.ts --tags orders,cache
@2026-05-02 note trap "Screenshot tests flake when fonts load late" --slug fonts
  --area "tests/visual/"
  --safe "await document.fonts.ready before the screenshot"
"""

TINY_TASKS = """\
as_of: 2026-06-01
tasks:
  - task: "cache the orders API responses"
    expect: [dec_20260501_cache-the-orders-api-in-redis]
    reject: [trap_fonts]
  - task: "rename a variable"   # a control
    expect: []
    verdict: [PROCEED]
"""


def tiny_suite(tmp: str, tasks: str = TINY_TASKS) -> Path:
    suite = Path(tmp) / "suites" / "tiny"
    suite.mkdir(parents=True)
    (suite / "store.crumb").write_text(TINY_STORE, encoding="utf-8")
    (suite / "tasks.yml").write_text(tasks, encoding="utf-8")
    return suite


def quiet(fn, *args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = fn(*args)
    return code, out.getvalue(), err.getvalue()


class ParseTests(unittest.TestCase):
    def test_tasks_parse_with_lists_quotes_and_comments(self):
        doc = run.parse_tasks(
            'as_of: 2026-01-01\ntasks:\n  - task: "a # not a comment"  # a comment\n'
            "    expect: [x, 'y z']\n  - task: b\n"
        )
        self.assertEqual(doc["as_of"], "2026-01-01")
        self.assertEqual(doc["tasks"][0]["task"], "a # not a comment")
        self.assertEqual(doc["tasks"][0]["expect"], ["x", "y z"])
        self.assertEqual(doc["tasks"][1]["reject"], [])

    def test_a_malformed_task_is_an_error_not_a_guess(self):
        for text in (
            "tasks:\n  - task: a\n    expcet: [x]\n",  # typo'd key
            "tasks:\n  - task: a\n    verdict: [MAYBE]\n",  # unknown verdict
            "tasks:\n  - task: a\n    expect: x\n",  # not a list
            "tasks:\n  - expect: [x]\n",  # no task text
        ):
            with self.subTest(text=text), self.assertRaises(run.SuiteError):
                run.parse_tasks(text)

    def test_store_commands_join_continuation_lines(self):
        cmds = run.parse_store('@2026-01-02 note trap "x y"\n  --slug z\n# c\n@2026-01-03 jot hi\n')
        self.assertEqual(
            cmds,
            [("2026-01-02", ["note", "trap", "x y", "--slug", "z"]), ("2026-01-03", ["jot", "hi"])],
        )
        with self.assertRaises(run.SuiteError):
            run.parse_store("note trap x\n")


class RunTests(unittest.TestCase):
    def test_a_suite_reports_every_metric(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = run.run_suite(tiny_suite(tmp))
        self.assertEqual(res["suite"], "tiny")
        self.assertEqual(len(res["tasks"]), 2)
        summary = res["summary"]
        self.assertEqual(set(summary), {"prompt", "packet", "guard", "tasks"})
        for system in run.SYSTEMS:
            for metric in ("precision_at_5", "recall_at_5"):
                self.assertTrue(0.0 <= summary[system][metric] <= 1.0, (system, metric))
            self.assertIsInstance(summary[system]["reject_hits"], int)
        self.assertEqual(summary["prompt"]["recall_at_5"], 1.0)
        self.assertEqual(summary["prompt"]["reject_hits"], 0)
        self.assertEqual(summary["prompt"]["quiet"], 1.0)
        self.assertEqual(summary["guard"]["guard_accuracy"], 1.0)

    def test_an_id_missing_from_the_store_fails_the_suite(self):
        with tempfile.TemporaryDirectory() as tmp:
            suite = tiny_suite(
                tmp, "as_of: 2026-06-01\ntasks:\n  - task: x\n    expect: [dec_nope]\n"
            )
            with self.assertRaises(run.SuiteError) as ctx:
                run.run_suite(suite)
        self.assertIn("dec_nope", str(ctx.exception))

    def test_a_failing_store_command_names_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            suite = tiny_suite(tmp)
            (suite / "store.crumb").write_text("@2026-01-01 remember decision --title x\n")
            with self.assertRaises(run.SuiteError) as ctx:
                run.run_suite(suite)
        self.assertIn("remember decision", str(ctx.exception))

    def test_the_committed_suites_match_the_committed_baseline(self):
        # The same check the `evals` CI job runs: a retrieval change that moves
        # a metric past the tolerance must come with a new baseline.json.
        code, out, err = quiet(run.main, [])
        self.assertEqual(code, 0, out + err)


class CompareTests(unittest.TestCase):
    BASE = {
        "s": {
            "prompt": {"precision_at_5": 0.8, "recall_at_5": 0.9, "reject_hits": 1, "quiet": 1.0},
            "guard": {"guard_accuracy": 1.0},
            "tasks": 3,
        }
    }

    def cur(self, **prompt) -> dict:
        cur = json.loads(json.dumps(self.BASE))
        cur["s"]["prompt"].update(prompt)
        return cur

    def test_within_tolerance_is_not_a_regression(self):
        self.assertEqual(run.compare(self.cur(precision_at_5=0.76), self.BASE), [])

    def test_a_drop_past_tolerance_is(self):
        problems = run.compare(self.cur(recall_at_5=0.84), self.BASE)
        self.assertEqual(len(problems), 1)
        self.assertIn("recall_at_5", problems[0])

    def test_any_new_reject_hit_is(self):
        self.assertEqual(len(run.compare(self.cur(reject_hits=2), self.BASE)), 1)
        self.assertEqual(run.compare(self.cur(reject_hits=0), self.BASE), [])

    def test_a_missing_scope_is_and_a_new_metric_is_not(self):
        self.assertEqual(len(run.compare({}, self.BASE)), 1)
        self.assertEqual(run.compare(self.cur(new_metric=0.1), self.BASE), [])

    def test_main_exits_1_on_a_regression_and_0_after_rewriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            suite = tiny_suite(tmp)
            baseline = Path(tmp) / "baseline.json"
            args = ["--suites", str(suite.parent), "--baseline", str(baseline)]
            code, _o, _e = quiet(run.main, [*args, "--write-baseline"])
            self.assertEqual(code, 0)
            data = json.loads(baseline.read_text("utf-8"))
            data["scopes"]["tiny"]["prompt"]["precision_at_5"] = 1.5  # unreachable
            baseline.write_text(json.dumps(data), encoding="utf-8")
            code, _o, err = quiet(run.main, args)
            self.assertEqual(code, 1)
            self.assertIn("REGRESSION", err)


class FoundByTheEvalsTests(unittest.TestCase):
    """Two retrieval bugs the first eval run found, pinned directly."""

    def store(self, tmp: str) -> Path:
        import crumb

        crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
        return Path(tmp) / crumb.MEMORY_DIRNAME

    def test_the_prompt_hook_leaves_out_a_superseded_decision(self):
        import crumb
        from breadcrumbs import hooks_prompt

        with tempfile.TemporaryDirectory() as tmp:
            mem = self.store(tmp)
            common = [
                "--evidence",
                "file",
                "src/auth.ts",
                "--tags",
                "auth,session",
                "--project",
                tmp,
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                crumb.main(
                    ["remember", "decision", "--title", "Keep the login session in localStorage"]
                    + common
                )
                old = crumb.active_records(mem, "decision")[0].meta["id"]
                crumb.main(
                    ["remember", "decision", "--title", "Keep the login session in a cookie"]
                    + common
                    + ["--supersedes", old]
                )
            ids = [
                m["id"] for m in hooks_prompt.retrieve(mem, Path(tmp), "store the login session")
            ]
            self.assertNotIn(old, ids)
            self.assertEqual(len(ids), 1)

    def test_a_short_action_matches_a_record_titled_with_it(self):
        import crumb

        with tempfile.TemporaryDirectory() as tmp:
            mem = self.store(tmp)
            with contextlib.redirect_stdout(io.StringIO()):
                crumb.main(
                    ["note", "trap", "npm test also truncates the local database", "--project", tmp]
                )
                crumb.main(["note", "trap", "npm install rewrites the lockfile", "--project", tmp])
            kw = crumb.GUARD_MIN_KEYWORD_OVERLAP
            hits, _ = crumb.search(mem, Path(tmp), "npm test", min_keyword=kw)
            self.assertEqual(
                [m["id"] for m in hits], ["trap_npm-test-also-truncates-the-local-database"]
            )
            # A longer query still needs the full keyword floor: sharing one word
            # of three with a title is not enough.
            hits, _ = crumb.search(mem, Path(tmp), "npm audit fix", min_keyword=kw)
            self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
