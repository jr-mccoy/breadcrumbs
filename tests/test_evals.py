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
from unittest import mock

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
        self.assertEqual(
            set(summary),
            {"prompt", "packet", "prompt_delivered", "packet_delivered", "guard", "tasks"},
        )
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
            code, _o, _e = quiet(run.main, [*args, "--write-baseline", "--reason", "first"])
            self.assertEqual(code, 0)
            data = json.loads(baseline.read_text("utf-8"))
            data["scopes"]["tiny"]["prompt"]["precision_at_5"] = 1.5  # unreachable
            baseline.write_text(json.dumps(data), encoding="utf-8")
            code, _o, err = quiet(run.main, args)
            self.assertEqual(code, 1)
            self.assertIn("REGRESSION", err)


CRITICAL_FALSE_SAFE = """\
cases:
  - id: npm-test-is-not-proceed
    suite: tiny
    check: guard_not
    task: "npm test"
    verdict_not: [PROCEED]
"""

HAZARD_STORE = (
    TINY_STORE
    + """\
@2026-05-03 note trap "npm test also truncates the local database" --slug npm-test-db
  --safe "run the unit tests only"
"""
)

HAZARD_TASKS = """\
as_of: 2026-06-01
tasks:
  - task: "npm test"
    expect: [trap_npm-test-db]
    verdict: [PROCEED, READ_FIRST, PAUSE, ASK_HUMAN]
    note: "a task that tolerates PROCEED, so the aggregate cannot see a false safe"
"""


def critical_file(tmp: str, text: str, name: str = "cases.yml") -> Path:
    path = Path(tmp) / name
    path.write_text(text, encoding="utf-8")
    return path


class CriticalTests(unittest.TestCase):
    """Audit WP18: critical cases are independent of every aggregate baseline."""

    def hazard_suite(self, tmp: str) -> Path:
        suite = tiny_suite(tmp, HAZARD_TASKS)
        (suite / "store.crumb").write_text(HAZARD_STORE, encoding="utf-8")
        return suite

    def args(self, tmp: str, suite: Path, cases: str) -> list[str]:
        return [
            "--suites",
            str(suite.parent),
            "--baseline",
            str(Path(tmp) / "baseline.json"),
            "--critical",
            str(critical_file(tmp, cases)),
        ]

    def test_baseline_cannot_approve_critical_false_safe(self):
        # A guard that says PROCEED to a recorded hazard, whatever guard does
        # today: the gate must not depend on the verdict F10 happens to give.
        real_guard = run.cli.guard

        def false_safe(*a, **k):
            return {**real_guard(*a, **k), "verdict": "PROCEED"}

        with tempfile.TemporaryDirectory() as tmp:
            suite = self.hazard_suite(tmp)
            args = self.args(tmp, suite, CRITICAL_FALSE_SAFE)
            baseline = Path(tmp) / "baseline.json"
            with mock.patch.object(run.cli, "guard", side_effect=false_safe):
                # 1. The baseline cannot be written over the failure.
                code, _o, err = quiet(run.main, [*args, "--write-baseline", "--reason", "x"])
                self.assertEqual(code, 1)
                self.assertIn("refusing to write the baseline: critical cases fail", err)
                self.assertFalse(baseline.exists())
                # 2. A baseline that already records the false safe (every
                #    aggregate equal to it) does not make the run pass.
                code, _o, _e = quiet(
                    run.main,
                    [
                        *args[:4],
                        "--critical",
                        str(critical_file(tmp, "cases:\n", "none.yml")),
                        "--write-baseline",
                        "--reason",
                        "x",
                    ],
                )
                self.assertEqual(code, 0)
                code, out, err = quiet(run.main, args)
                self.assertEqual(code, 1)
                self.assertNotIn("REGRESSION", err)
                self.assertIn("CRITICAL: cases fail regardless of the baseline", err)
                self.assertIn("npm-test-is-not-proceed — guard said PROCEED", err)
                # 3. Marked as a known failure it is visible on every run, and
                #    blocks a release.
                known = CRITICAL_FALSE_SAFE + "    known: F10\n"
                args = self.args(tmp, suite, known)
                code, out, err = quiet(run.main, args)
                self.assertEqual(code, 0)
                self.assertIn("KNOWN FAILURE [F10]: npm-test-is-not-proceed", out)
                code, _o, err = quiet(run.main, [*args, "--release"])
                self.assertEqual(code, 1)
                self.assertIn("block the release", err)
            # 4. Once it passes, the stale marker fails the run.
            with mock.patch.object(
                run.cli,
                "guard",
                side_effect=lambda *a, **k: {**real_guard(*a, **k), "verdict": "PAUSE"},
            ):
                code, out, _e = quiet(run.main, args)
            self.assertEqual(code, 1)
            self.assertIn("STALE MARKER", out)

    def test_a_waiver_is_reported_never_gated(self):
        with tempfile.TemporaryDirectory() as tmp:
            suite = self.hazard_suite(tmp)
            waived = CRITICAL_FALSE_SAFE + '    waiver: "not a claimed capability"\n'
            with mock.patch.object(
                run.cli, "guard", side_effect=lambda *a, **k: {"verdict": "PROCEED"}
            ):
                code, out, _e = quiet(run.main, [*self.args(tmp, suite, waived), "--release"])
        self.assertEqual(code, 0)
        self.assertIn("waived: npm-test-is-not-proceed", out)

    def test_malformed_critical_cases_are_errors(self):
        for text in (
            "cases:\n  - id: a\n    suite: s\n    check: nope\n    task: t\n",
            "cases:\n  - id: a\n    suite: s\n    check: quiet\n",  # no task
            "cases:\n  - id: a\n    suite: s\n    check: quiet\n    task: t\n"
            "    known: F1\n    waiver: w\n",
            "cases:\n  - id: a\n    suite: s\n    check: quiet\n    task: t\n    via: [mail]\n",
        ):
            with self.subTest(text=text), self.assertRaises(run.SuiteError):
                run.parse_critical(text)


class DeliveryTests(unittest.TestCase):
    """Audit WP18: what the hooks and `resume` actually print is scored."""

    def test_delivery_metric_includes_recency_noise_and_wrappers(self):
        topics = [
            ("Invoices round half-even", "src/billing/round.ts"),
            ("Emails are sent from the worker queue", "src/mail/queue.ts"),
            ("Feature flags are read once at boot", "src/flags.ts"),
            ("Dates are stored in UTC", "src/db/dates.ts"),
        ]
        store = TINY_STORE + "".join(
            f'@2026-05-{10 + i:02d} remember decision --title "{title}"\n'
            f'  --set Decision "{title}." --evidence file {path}\n'
            for i, (title, path) in enumerate(topics)
        )
        tasks = (
            'as_of: 2026-06-01\ntasks:\n  - task: "cache the orders API responses"\n'
            "    expect: [dec_20260501_cache-the-orders-api-in-redis]\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            suite = tiny_suite(tmp, tasks)
            (suite / "store.crumb").write_text(store, encoding="utf-8")
            res = run.run_suite(suite)
        row = res["tasks"][0]
        # The re-ranked diagnostic drops zero-score entries: the relevant
        # decision is all it sees.
        self.assertEqual(row["packet"]["precision_at_5"], 1.0)
        # As printed, the newest entries come first (the recency floor), and
        # they are noise for this task.
        delivered = row["packet_delivered"]
        self.assertLess(delivered["precision_at_5"], 0.5)
        newest = ("invoices-round", "emails-are-sent", "feature-flags", "dates-are-stored")
        self.assertTrue(any(n in r for r in delivered["top"][:3] for n in newest), delivered)
        self.assertEqual(delivered["recall_in_view"], 1.0)
        # The cost is the whole printed packet: headers, notes, warnings.
        self.assertGreater(delivered["tokens"], 300)
        self.assertTrue(delivered["within_budget"])

    def test_hook_length_dedupe_and_render_paths_are_evaluated(self):
        with tempfile.TemporaryDirectory() as tmp:
            suite = tiny_suite(tmp, HAZARD_TASKS)
            (suite / "store.crumb").write_text(HAZARD_STORE, encoding="utf-8")
            res = run.run_suite(suite)
            row = res["tasks"][0]
            # An 8-character prompt is answered by the real hook (audit WP10
            # removed the length gate)...
            self.assertIn("trap_npm-test-db", row["prompt"]["top"])
            self.assertTrue(row["prompt_delivered"]["spoke"])
            self.assertEqual(row["prompt_delivered"]["recall_at_5"], 1.0)
            # ...and the gate is what the delivered view measures: if the hook
            # took it for an acknowledgement, retrieval would still find the
            # trap while nothing reached the reader.
            from breadcrumbs import retrieval

            with mock.patch.object(retrieval, "is_acknowledgment", return_value=True):
                row = run.run_suite(suite)["tasks"][0]
            self.assertIn("trap_npm-test-db", row["prompt"]["top"])
            self.assertFalse(row["prompt_delivered"]["spoke"])
            self.assertEqual(row["prompt_delivered"]["recall_at_5"], 0.0)

            suite2 = tiny_suite(str(Path(tmp) / "b"))
            res = run.run_suite(suite2)
            spoke = res["tasks"][0]["prompt_delivered"]
            # The render path: the injected text, header and footer included.
            self.assertTrue(spoke["spoke"])
            self.assertGreater(spoke["tokens"], 20)
            self.assertTrue(spoke["deduped"])
            self.assertEqual(res["summary"]["prompt_delivered"]["dedupe"], 1.0)
            # And the dedupe is really measured: a hook that never remembers
            # speaks twice.
            with mock.patch.object(
                run.hooks_prompt.hooks_common, "advisory_seen", return_value=False
            ):
                res = run.run_suite(suite2)
            self.assertEqual(res["summary"]["prompt_delivered"]["dedupe"], 0.0)

    def test_metric_definitions_and_denominators_are_serialized(self):
        with tempfile.TemporaryDirectory() as tmp:
            suite = tiny_suite(tmp)
            args = [
                "--suites",
                str(suite.parent),
                "--baseline",
                str(Path(tmp) / "baseline.json"),
                "--critical",
                str(critical_file(tmp, "cases:\n")),
            ]
            code, out, _e = quiet(run.main, [*args, "--json"])
            doc = json.loads(out)
            quiet(run.main, [*args, "--write-baseline", "--reason", "first"])
            written = json.loads((Path(tmp) / "baseline.json").read_text("utf-8"))
        defs = doc["definitions"]
        for system, metrics in doc["scopes"]["tiny"].items():
            if not isinstance(metrics, dict):
                continue
            for metric, value in metrics.items():
                if metric == "n":
                    continue
                with self.subTest(system=system, metric=metric):
                    self.assertIn(metric, defs[system])
                    self.assertTrue(defs[system][metric]["definition"])
                    self.assertTrue(defs[system][metric]["denominator"])
                    self.assertIn(metric, metrics["n"])
        summary = doc["scopes"]["tiny"]
        self.assertEqual(summary["guard"]["n"]["guard_accuracy"], 1)  # one verdict task
        self.assertEqual(summary["prompt"]["n"]["quiet"], 1)  # one control task
        self.assertEqual(summary["prompt"]["n"]["precision_at_5"], 1)
        # "not divided by 5" is part of the stated definition.
        self.assertIn("not divided by 5", defs["prompt"]["precision_at_5"]["definition"])
        self.assertEqual(written["definitions"], defs)
        self.assertEqual(written["changes"][-1]["reason"], "first")
        self.assertIn("tiny::cache the orders API responses", written["tasks"])


class BaselineReviewTests(unittest.TestCase):
    def test_a_task_level_regression_needs_explicit_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            suite = tiny_suite(tmp)
            baseline = Path(tmp) / "baseline.json"
            args = [
                "--suites",
                str(suite.parent),
                "--baseline",
                str(baseline),
                "--critical",
                str(critical_file(tmp, "cases:\n")),
            ]
            quiet(run.main, [*args, "--write-baseline", "--reason", "first"])
            # The expected decision stops surfacing (a regression at task level).
            with mock.patch.object(run.hooks_prompt, "retrieve", return_value=[]):
                code, _o, err = quiet(run.main, [*args, "--write-baseline", "--reason", "x"])
                self.assertEqual(code, 1)
                self.assertIn("prompt now misses dec_20260501_cache-the-orders-api-in-redis", err)
                self.assertIn("--accept-regressions", err)
                code, _o, _e = quiet(
                    run.main,
                    [*args, "--write-baseline", "--reason", "accepted", "--accept-regressions"],
                )
            self.assertEqual(code, 0)
            change = json.loads(baseline.read_text("utf-8"))["changes"][-1]
            self.assertEqual(change["reason"], "accepted")
            self.assertTrue(change["regressions"])

    def test_a_holdout_suite_is_reported_apart_from_overall(self):
        with tempfile.TemporaryDirectory() as tmp:
            tiny_suite(tmp)
            held = Path(tmp) / "suites" / "held"
            held.mkdir()
            (held / "store.crumb").write_text(TINY_STORE, encoding="utf-8")
            (held / "tasks.yml").write_text(
                TINY_TASKS.replace("as_of: 2026-06-01\n", "as_of: 2026-06-01\nsplit: holdout\n"),
                encoding="utf-8",
            )
            code, out, _e = quiet(
                run.main,
                [
                    "--suites",
                    str(held.parent),
                    "--baseline",
                    str(Path(tmp) / "b.json"),
                    "--critical",
                    str(critical_file(tmp, "cases:\n")),
                    "--json",
                ],
            )
        scopes = json.loads(out)["scopes"]
        self.assertEqual(scopes["overall"]["tasks"], 2)  # tiny only
        self.assertEqual(scopes["holdout"]["tasks"], 2)


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

    def test_the_session_just_written_survives_a_timestamp_tie(self):
        # Audit WP18: the delivered-prompt dedupe metric read below 1.0. The
        # hook state keeps the 8 most recently updated sessions, `updated_at`
        # has one-second resolution, and on a tie the newest session was the
        # one dropped, so its dedupe record vanished as it was written.
        from breadcrumbs import cli as _cli
        from breadcrumbs import hooks_common

        with tempfile.TemporaryDirectory() as tmp:
            mem = self.store(tmp)
            with mock.patch.object(_cli, "now_iso", return_value="2026-09-27T00:00:00+00:00"):
                for i in range(hooks_common.MAX_SESSIONS + 3):
                    self.assertFalse(hooks_common.advisory_seen(mem, f"s{i}", "k"))
                    self.assertTrue(hooks_common.advisory_seen(mem, f"s{i}", "k"), i)

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
