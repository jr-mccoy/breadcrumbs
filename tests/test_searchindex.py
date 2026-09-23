"""Tests for the disposable sqlite search index (WM-23).

The index is an accelerator, never a source of truth: every query answered
through it must return exactly what the full scan returns, and every way it can
be wrong (stale, absent, unreadable, too small to bother) must fall back to the
full scan rather than to a different answer.

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import io
import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import searchindex  # noqa: E402

VOCAB = (
    "ledger sqlite cache eviction billing invoice payment retry webhook queue "
    "worker migration schema index token packet resume guard hook release tag "
    "shard replica lock daemon gradle android flex window compose render"
).split()
FILES = [f"src/{name}.py" for name in ("ledger", "billing", "queue", "cache", "hooks", "release")]

QUERIES = [
    ("ledger shard", []),
    ("billing retry webhook", []),
    ("cache eviction", ["src/cache.py"]),
    ("release tag", []),
    ("", ["src/queue.py"]),
    ("sqlite migration schema", []),
    ("nonexistentword", []),
    ("daemon lock worker", ["src/hooks.py"]),
    ("flex window render compose", []),
    ("token packet resume guard", []),
]


def _write_record(mem: Path, rtype: str, index: int, rng: random.Random) -> None:
    words = rng.sample(VOCAB, 6)
    date = f"2026-0{1 + index % 9}-{10 + index % 18:02d}"
    stem = f"{date}-{'-'.join(words[:2])}-{index}"
    rid, slug = crumb.derive_identity(stem, rtype)
    meta = {
        "id": rid,
        "type": rtype,
        "slug": slug,
        "title": " ".join(words[:3]),
        "status": rng.choice(["active", "active", "active", "superseded", "stale"]),
        "created_at": f"{date}T10:00:00+00:00",
        "updated_at": f"{date}T10:00:00+00:00",
        "created_by": "tester",
        "agent": "human",
        "project": "demo",
        "scope": "project",
        "branch": "main",
        "commit": "abc1234",
        "dirty_files": [],
        "confidence": "low",
        "privacy": "repo-safe",
        "review_status": "unreviewed",
        "reviewed_by": None,
        "supersedes": [],
        "superseded_by": None,
        "expires_at": None,
        "tags": rng.sample(["memory", "billing", "infra", "release"], 1),
        "evidence": [],
    }
    body = (
        f"## Context\nTouches `{rng.choice(FILES)}` and {' '.join(words[3:])}.\n\n"
        f"## Decision\n{' '.join(rng.sample(VOCAB, 5))}.\n"
    )
    if rtype == "attempt":
        body = (
            f"## Goal\n{' '.join(words[3:])}.\n\n## What happened\nTouched `{rng.choice(FILES)}`.\n"
        )
    directory = mem / crumb.TYPE_DIR[rtype]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{stem}.md").write_text(
        crumb.render_frontmatter(meta) + "\n" + body, encoding="utf-8"
    )


def synthetic_store(tmp: str, n: int = 500) -> tuple[Path, Path]:
    root = Path(tmp)
    crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
    mem = root / crumb.MEMORY_DIRNAME
    rng = random.Random(1234)
    for i in range(n):
        _write_record(mem, rng.choice(["decision", "decision", "attempt", "idea"]), i, rng)
    crumb.note(mem, root, "trap", "ledger shard lock is held by the daemon")
    crumb.note(mem, root, "question", "Should the billing webhook retry forever?")
    return mem, root


def _summary(matches: list[dict]) -> list[tuple]:
    return [(m["id"], m["score"], m.get("status")) for m in matches]


@unittest.skipUnless(searchindex.available(), "sqlite3 is not available")
class SearchIndexEquivalenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        cls.mem, cls.root = synthetic_store(cls._tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _both(self, query: str, files: list[str], include_ideas: bool):
        with mock.patch.object(searchindex, "candidate_items", return_value=None):
            full, _ = crumb.search(
                self.mem, self.root, query, files=files, include_ideas=include_ideas
            )
        indexed, _ = crumb.search(
            self.mem, self.root, query, files=files, include_ideas=include_ideas
        )
        return full, indexed

    def test_the_index_is_built_for_a_large_store(self):
        res = searchindex.build_index(self.mem, self.root)
        self.assertTrue(res["built"], res)
        self.assertEqual(searchindex.index_status(self.mem, self.root)["state"], "fresh")

    def test_indexed_search_returns_exactly_the_full_scan(self):
        searchindex.build_index(self.mem, self.root)
        compared = 0
        for query, files in QUERIES:
            for include_ideas in (False, True):
                with self.subTest(query=query, files=files, ideas=include_ideas):
                    full, indexed = self._both(query, files, include_ideas)
                    self.assertEqual(_summary(indexed), _summary(full))
                    compared += len(full)
        # Equal-and-empty everywhere would prove nothing.
        self.assertGreater(compared, 100)

    def test_the_index_is_actually_used(self):
        searchindex.build_index(self.mem, self.root)
        got = searchindex.candidate_items(
            self.mem, self.root, set(crumb._specific("ledger shard")), set(), include_ideas=False
        )
        self.assertIsNotNone(got)
        items, _ubiquitous = got
        full = crumb._candidate_items(self.mem, include_ideas=False)
        self.assertLess(len(items), len(full), "the index must narrow the corpus")


@unittest.skipUnless(searchindex.available(), "sqlite3 is not available")
class SearchIndexFallbackTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.mem, self.root = synthetic_store(self._tmp, n=40)

    def test_a_small_store_builds_no_index(self):
        res = searchindex.build_index(self.mem, self.root)
        self.assertFalse(res["built"])
        self.assertEqual(res["reason"], "below threshold")
        self.assertFalse(searchindex.index_path(self.mem).exists())

    def test_a_stale_index_is_never_used(self):
        searchindex.build_index(self.mem, self.root, force=True)
        self.assertEqual(searchindex.index_status(self.mem, self.root)["state"], "fresh")
        rng = random.Random(99)
        _write_record(self.mem, "decision", 999, rng)
        self.assertEqual(searchindex.index_status(self.mem, self.root)["state"], "stale")
        self.assertIsNone(
            searchindex.candidate_items(
                self.mem, self.root, {crumb._stem("ledger")}, set(), include_ideas=False
            )
        )
        # …and search still answers, from the full scan, including the new record.
        matches, _ = crumb.search(self.mem, self.root, "ledger sqlite cache", include_ideas=True)
        self.assertIsInstance(matches, list)

    def test_a_corrupt_index_falls_back(self):
        path = searchindex.index_path(self.mem)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"this is not a sqlite database")
        self.assertEqual(searchindex.index_status(self.mem, self.root)["state"], "unreadable")
        self.assertIsNone(
            searchindex.candidate_items(
                self.mem, self.root, {crumb._stem("ledger")}, set(), include_ideas=False
            )
        )
        with mock.patch.object(searchindex, "candidate_items", return_value=None):
            full, _ = crumb.search(self.mem, self.root, "ledger shard", include_ideas=True)
        got, _ = crumb.search(self.mem, self.root, "ledger shard", include_ideas=True)
        self.assertEqual(_summary(got), _summary(full))

    def test_forced_small_index_still_matches_the_full_scan(self):
        searchindex.build_index(self.mem, self.root, force=True)
        for query, files in QUERIES:
            with self.subTest(query=query):
                with mock.patch.object(searchindex, "candidate_items", return_value=None):
                    full, _ = crumb.search(
                        self.mem, self.root, query, files=files, include_ideas=True
                    )
                got, _ = crumb.search(self.mem, self.root, query, files=files, include_ideas=True)
                self.assertEqual(_summary(got), _summary(full))

    def test_the_index_lives_under_the_ignored_index_dir(self):
        searchindex.build_index(self.mem, self.root, force=True)
        self.assertEqual(searchindex.index_path(self.mem).parent.name, "index")

    def test_doctor_reports_the_index(self):
        def doctor_row() -> str:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                crumb.main(["doctor", "--project", str(self.root)])
            return next((ln for ln in buf.getvalue().splitlines() if "search_index" in ln), "")

        self.assertIn("not built", doctor_row())
        searchindex.build_index(self.mem, self.root, force=True)
        self.assertIn("fresh", doctor_row())

    def test_reindex_search_index_flag_forces_a_build(self):
        code = crumb.main(["reindex", "--project", str(self.root), "--search-index"])
        self.assertEqual(code, 0)
        self.assertTrue(searchindex.index_path(self.mem).is_file())


class FixtureEquivalenceTests(unittest.TestCase):
    @unittest.skipUnless(searchindex.available(), "sqlite3 is not available")
    def test_fixture_10_answers_the_same_through_the_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fixture"
            shutil.copytree(REPO_ROOT / "fixtures" / "fixture-10-many-sessions", root)
            mem = root / crumb.MEMORY_DIRNAME
            self.assertTrue(searchindex.build_index(mem, root, force=True)["built"])
            for query in ("resume packet", "session capture", "handoff next step", "guard"):
                with self.subTest(query=query):
                    with mock.patch.object(searchindex, "candidate_items", return_value=None):
                        full, _ = crumb.search(mem, root, query, include_ideas=True)
                    got, _ = crumb.search(mem, root, query, include_ideas=True)
                    self.assertEqual(_summary(got), _summary(full))


if __name__ == "__main__":
    unittest.main(verbosity=2)
