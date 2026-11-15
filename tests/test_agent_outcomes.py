"""The agent-outcome eval's harness, without an agent (review 2026-11-13, §5.1).

`evals/agent_outcomes/run.py` runs a real agent, which costs model usage and
never runs in CI. What can be checked for free is checked here: every
condition builds the repo it says it does, the memory each delivers holds the
hazard, and the oracle tells a retry from a safe change.

Run with:  python -m unittest discover -s tests -p test_agent_outcomes.py
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HARNESS = REPO_ROOT / "evals" / "agent_outcomes"


def _load(name: str, path: Path):
    """By path, under its own name: `evals/task_replays` has a `run` and an
    `oracle` too, and bare imports collided in one test process."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


run = _load("agent_outcomes_run", HARNESS / "run.py")
oracle = run.oracle

DATA = run.load_scenarios()
SCENARIOS = {s["id"]: s for s in DATA["scenarios"]}


@unittest.skipUnless(shutil.which("git"), "git is needed to build the repos")
class BuildTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.work = Path(self._tmp.name)
        self.bin = run.crumb_bin(self.work)

    def build(self, sid: str, condition: str) -> Path:
        repo = self.work / f"{sid}-{condition}"
        run.build(SCENARIOS[sid], DATA["distractors"], condition, repo, self.bin)
        return repo

    def test_no_condition_leaks_memory_into_another(self):
        for condition in run.CONDITIONS:
            with self.subTest(condition=condition):
                repo = self.build("index-migration", condition)
                claude_md = (repo / "CLAUDE.md").read_text(encoding="utf-8")
                store = (repo / ".project-memory").is_dir()
                hooks = (repo / ".claude" / "settings.json").is_file()
                self.assertEqual(store, condition.startswith("crumb"))
                self.assertEqual(hooks, condition == "crumb-hooks")
                self.assertEqual("CONCURRENTLY" in claude_md, condition == "notes")
                self.assertEqual("breadcrumbs" in claude_md, condition.startswith("crumb"))

    def test_the_hazard_is_what_each_memory_delivers(self):
        for sid, scenario in SCENARIOS.items():
            with self.subTest(scenario=sid):
                notes = self.build(sid, "notes")
                self.assertIn(scenario["hazard"]["note"], (notes / "CLAUDE.md").read_text())
                hooks = self.build(sid, "crumb-hooks")
                chars = run.delivered_at_start(hooks, "crumb-hooks", self.bin)
                self.assertGreater(chars, 0)
                payload = json.dumps({"cwd": str(hooks), "session_id": "t", "source": "startup"})
                import subprocess

                out = subprocess.run(
                    [str(self.bin / "crumb"), "hook", "session"],
                    cwd=hooks,
                    input=payload,
                    capture_output=True,
                    text=True,
                ).stdout
                context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
                # What v1 delivers for an attempt: its id and its do-not-retry
                # condition, not its title or result (the finding the
                # continuity replays reported, and this eval measures).
                section = context.split("## Failed Attempts To Avoid", 1)[1].split("##", 1)[0]
                self.assertIn("att_", section)
                self.assertIn(scenario["hazard"]["do_not_retry"][:40], section)
                self.assertNotIn(scenario["hazard"]["title"], context)

    def test_the_stores_validate(self):
        repo = self.build("urllib3-upgrade", "crumb-instructions")
        import subprocess

        out = subprocess.run(
            [str(self.bin / "crumb"), "--project", str(repo), "validate"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_the_repo_is_committed_and_clean(self):
        import subprocess

        repo = self.build("rate-cache", "crumb-hooks")
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True
        ).stdout
        self.assertEqual(status.strip(), "")


@unittest.skipUnless(shutil.which("git"), "git is needed to build the repos")
class OracleTests(unittest.TestCase):
    """Each scenario: the untouched repo, the hazard, and the safe change."""

    SAFE = {
        "rate-cache": {
            "app/settings.py": ("RATE_CACHE = False", "RATE_CACHE = True"),
            "app/rates.py": (
                "_cache: dict[str, float] = {}",
                "import datetime\n_cache: dict[tuple[str, str], float] = {}  # keyed by the "
                "02:00 UTC publication date",
            ),
        },
        "urllib3-upgrade": {
            "pytest.ini": (
                None,
                "[pytest]\nfilterwarnings =\n    ignore::DeprecationWarning:urllib3\n",
            ),
        },
        "index-migration": {
            "migrations/0003_users_email_index.sql": (
                None,
                "-- no-transaction\nCREATE INDEX CONCURRENTLY idx_users_email ON users (email);\n",
            ),
        },
    }
    HAZARD = {
        "rate-cache": {"app/settings.py": ("RATE_CACHE = False", "RATE_CACHE = True")},
        "urllib3-upgrade": {"requirements.txt": ("urllib3==1.26.18", "urllib3>=2")},
        "index-migration": {
            "migrations/0003_users_email_index.sql": (None, "CREATE INDEX ON users (email);\n"),
        },
    }

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.work = Path(self._tmp.name)
        self.bin = run.crumb_bin(self.work)

    def judge(self, sid: str, edits: dict | None) -> dict:
        repo = self.work / f"{sid}-{len(list(self.work.iterdir()))}"
        run.build(SCENARIOS[sid], DATA["distractors"], "none", repo, self.bin)
        before = oracle.snapshot(repo)
        for rel, (old, new) in (edits or {}).items():
            path = repo / rel
            text = path.read_text(encoding="utf-8") if old is not None else ""
            path.write_text(text.replace(old, new) if old is not None else new, encoding="utf-8")
        (repo / "app" / "__pycache__").mkdir(exist_ok=True)
        (repo / "app" / "__pycache__" / "x.pyc").write_bytes(b"\0")
        return oracle.judge(SCENARIOS[sid], repo, before, self.work / "no-transcript.jsonl")

    def test_untouched(self):
        for sid in SCENARIOS:
            with self.subTest(scenario=sid):
                got = self.judge(sid, None)
                self.assertFalse(got["retried"])
                self.assertFalse(got["touched"], got["changed"])  # caches are not changes

    def test_the_hazard_is_a_retry(self):
        for sid in SCENARIOS:
            with self.subTest(scenario=sid):
                got = self.judge(sid, self.HAZARD[sid])
                self.assertTrue(got["retried"], got)
                self.assertFalse(got["fact_applied"])

    def test_the_safe_change_is_not(self):
        for sid in SCENARIOS:
            with self.subTest(scenario=sid):
                got = self.judge(sid, self.SAFE[sid])
                self.assertFalse(got["retried"], got)
                self.assertTrue(got["fact_applied"], got)


class TranscriptTests(unittest.TestCase):
    def test_memory_reads_and_words_are_read_from_stream_json(self):
        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Bash", "input": {"command": "crumb resume"}},
                        {"type": "text", "text": "The index must be built CONCURRENTLY."},
                    ]
                },
            },
            {"type": "result", "subtype": "success", "result": "Done."},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_text("\n".join(json.dumps(e) for e in events) + "\nnot json\n")
            parsed = oracle.transcript_events(path)
            self.assertEqual(len(parsed), 2)
            calls = oracle.tool_calls(parsed)
            self.assertEqual(calls[0]["name"], "Bash")
            self.assertTrue(oracle._reads_memory(calls[0]))
            self.assertIn("concurrently", oracle.assistant_text(parsed).lower())

    def test_summary_counts(self):
        rows = [
            {"scenario": "s", "condition": "none", "retried": True, "condition_met": False,
             "fact_applied": False, "fact_mentioned": False, "memory_read": False,
             "delivered_chars_at_start": 0, "cost_usd": 0.1, "touched": True},
            {"scenario": "s", "condition": "none", "retried": False, "condition_met": False,
             "fact_applied": True, "fact_mentioned": True, "memory_read": False,
             "delivered_chars_at_start": 0, "cost_usd": 0.2, "touched": False, "asked": True},
        ]  # fmt: skip
        line = next(x for x in run.summarize(rows) if x["scenario"] == "ALL")
        self.assertEqual((line["runs"], line["retried"], line["fact_applied"]), (2, 1, 1))
        self.assertEqual((line["done"], line["asked"]), (1, 1))
        self.assertEqual(line["cost_usd"], 0.3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
