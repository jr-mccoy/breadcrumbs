"""Retrieval does not vanish at a size boundary or a short prompt (audit F09-F12; WP10).

- F09: the prompt hook loaded and counted every candidate, and returned nothing
  above 500, retired records included.
- F10: a prompt under 12 characters was never looked up, and `npm test` got
  PROCEED from a trap naming exactly that command; the pre-filter let the hook
  skip it.
- F11: the pre-filter file's existence stood in for "the store has records".
- F12: whether a lookup used the index or fell back was never reported.

These pin the replacement: indexed lookup with no pre-count, eligibility
before the cap, an acknowledgement vocabulary, a narrow exact-command rule, and
lookups that report how they ran.

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli, hooklog, hooks_prompt, retrieval, searchindex  # noqa: E402


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True)


def hook(event: str, payload: dict) -> dict:
    out = io.StringIO()
    saved = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload))
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            crumb.main(["hook", event])
    finally:
        sys.stdin = saved
    text = out.getvalue().strip()
    return json.loads(text) if text else {}


def context(doc: dict) -> str:
    return str((doc.get("hookSpecificOutput") or {}).get("additionalContext") or "")


class StoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        git(self.root, "init", "-q")
        with contextlib.redirect_stdout(io.StringIO()):
            crumb.main(["init", "--project", str(self.root), "--session-tracking", "full"])
        self.mem = self.root / crumb.MEMORY_DIRNAME
        _path, self.meta = crumb.write_record(
            self.mem,
            self.root,
            "decision",
            "Amber quasar routing policy",
            {"Decision": "Route quasar traffic through the amber queue."},
            evidence=[{"type": "file", "ref": "src/quasar.py"}],
        )
        self.rid = self.meta["id"]

    def fill(self, n: int, *, status: str = "stale") -> None:
        """`n` other decisions, written straight to disk (fast), then reindexed."""
        for i in range(n):
            dest = self.mem / "decisions" / f"2026-01-01-other-entry-{i:04d}.md"
            meta = dict(self.meta)
            meta["id"], meta["slug"] = cli.derive_identity(dest.stem, "decision")
            meta["title"] = f"Unrelated record {i:04d} about subsystem {i % 37}"
            meta["status"] = status if i % 2 == 0 else "active"
            dest.write_text(
                cli.render_frontmatter(meta) + "\n\n## Decision\nOrdinary history.\n",
                encoding="utf-8",
            )
        cli.reindex_projections(self.mem, self.root)

    def prompt(self, text: str, session: str = "s1") -> dict:
        return hook("prompt", {"cwd": str(self.root), "session_id": session, "prompt": text})


class SizeBoundaryTests(StoreCase):
    def test_one_active_plus_500_stale_records_still_retrieves(self):
        self.fill(500, status="stale")
        self.assertGreater(retrieval.count_records(self.mem), hooks_prompt.PROMPT_HOOK_MAX_CORPUS)
        lookup = retrieval.prompt_lookup(self.mem, self.root, "amber quasar routing")
        self.assertEqual([m["id"] for m in lookup.matches], [self.rid])
        self.assertEqual((lookup.mode, lookup.complete), ("indexed", True))
        # Through the real hook, as the harness calls it.
        self.assertIn(f"`{self.rid}`", context(self.prompt("amber quasar routing")))
        self.assertEqual(hooklog.read_log(self.mem)[-1].get("retrieval"), "indexed")

    def test_199_200_201_and_499_500_501_preserve_results(self):
        # Sizes are total prompt-corpus records: the relevant one plus fillers.
        filled = 0
        for size in (199, 200, 201, 499, 500, 501):
            with self.subTest(records=size):
                for i in range(filled, size - 1):
                    dest = self.mem / "decisions" / f"2026-01-01-other-entry-{i:04d}.md"
                    meta = dict(self.meta)
                    meta["id"], meta["slug"] = cli.derive_identity(dest.stem, "decision")
                    meta["title"] = f"Unrelated record {i:04d} about subsystem {i % 37}"
                    meta["status"] = "stale" if i % 2 == 0 else "active"
                    dest.write_text(
                        cli.render_frontmatter(meta) + "\n\n## Decision\nOrdinary history.\n",
                        encoding="utf-8",
                    )
                filled = size - 1
                cli.reindex_projections(self.mem, self.root)
                self.assertEqual(retrieval.count_records(self.mem), size)
                delivered = context(self.prompt("amber quasar routing", f"s{size}"))
                self.assertIn(f"`{self.rid}`", delivered)
                # Indexed or not, search returns what the full scan returns.
                indexed, _ = cli.search(self.mem, self.root, "amber quasar routing subsystem")
                with mock.patch.object(searchindex, "candidate_items", return_value=None):
                    full, _ = cli.search(self.mem, self.root, "amber quasar routing subsystem")
                self.assertEqual(
                    [(m["id"], m["score"]) for m in indexed], [(m["id"], m["score"]) for m in full]
                )

    def test_history_never_takes_a_prompt_slot(self):
        # Six superseded records that match better than the live one: the live
        # one is still delivered, because eligibility comes before the cap.
        for i in range(6):
            crumb.write_record(
                self.mem,
                self.root,
                "decision",
                f"Amber quasar routing rule {i}",
                {"Decision": f"Old amber quasar routing rule {i}."},
                evidence=[{"type": "file", "ref": "src/quasar.py"}],
                status="superseded",
            )
        cli.reindex_projections(self.mem, self.root)
        ids = [
            m["id"]
            for m in retrieval.prompt_lookup(self.mem, self.root, "amber quasar routing").matches
        ]
        self.assertEqual(ids, [self.rid])


class ShortPromptTests(StoreCase):
    def test_short_meaningful_prompt_is_not_acknowledgment(self):
        crumb.note(
            self.mem,
            self.root,
            "trap",
            "npm test truncates the local database",
            fields={"safe": "Use `npm run test:unit` against a disposable database."},
        )
        cli.reindex_projections(self.mem, self.root)
        self.assertIn(f"`{self.rid}`", context(self.prompt("quasar", "a")))
        self.assertIn(
            "trap_npm-test-truncates-the-local-database", context(self.prompt("npm test", "b"))
        )
        for ack in ("ok", "Yes please", "go on", "thanks!", "👍", "LGTM", "ok, continue", "..."):
            with self.subTest(prompt=ack):
                self.assertTrue(retrieval.is_acknowledgment(ack))
                with mock.patch.object(cli, "search", side_effect=AssertionError("searched")):
                    self.assertEqual(self.prompt(ack, f"ack-{ack}"), {})
                self.assertEqual(hooklog.read_log(self.mem)[-1].get("retrieval"), "acknowledgment")
        for meaningful in ("quasar", "npm test", "ruff", "no, use the amber queue", "ok quasar"):
            with self.subTest(prompt=meaningful):
                self.assertFalse(retrieval.is_acknowledgment(meaningful))


class IndexFallbackTests(StoreCase):
    def lookup(self):
        return retrieval.prompt_lookup(self.mem, self.root, "amber quasar routing")

    def test_index_missing_stale_or_corrupt_has_honest_fallback(self):
        self.fill(210)
        index = searchindex.index_path(self.mem)
        self.assertTrue(index.is_file())
        cases = []
        found = self.lookup()
        cases.append(("fresh", found.mode, found.reason))
        self.assertEqual(found.mode, "indexed")

        index.unlink()
        found = self.lookup()
        self.assertEqual((found.mode, found.reason), ("full_scan", "no search index"))
        self.assertEqual([m["id"] for m in found.matches], [self.rid])

        cli.reindex_projections(self.mem, self.root)
        path = next(p for p in (self.mem / "decisions").glob("*amber*"))
        path.write_text(path.read_text() + "\nAlso: amber quasar nebula.\n", encoding="utf-8")
        found = self.lookup()
        self.assertEqual((found.mode, found.reason), ("full_scan", "the search index is stale"))
        self.assertEqual([m["id"] for m in found.matches], [self.rid])

        index.write_bytes(b"this is not a sqlite database")
        found = self.lookup()
        self.assertEqual(found.mode, "full_scan")
        self.assertIn("unreadable", found.reason)
        self.assertEqual([m["id"] for m in found.matches], [self.rid])

        # Too big to scan within the hook's budget without an index: the hook
        # says so, once per session, instead of passing it off as "nothing".
        with mock.patch.object(retrieval, "PROMPT_FULL_SCAN_MAX", 100):
            found = self.lookup()
            self.assertEqual((found.mode, found.complete), ("skipped", False))
            first = context(self.prompt("amber quasar routing", "big"))
            second = self.prompt("amber quasar routing", "big")
        self.assertIn("memory was not searched for this prompt", first)
        self.assertIn("crumb reindex", first)
        self.assertEqual(second, {})
        self.assertEqual(hooklog.read_log(self.mem)[-1].get("retrieval"), "skipped")

        # `crumb search` is exact whatever the index, and says how it ran.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            crumb.main(["search", "amber quasar", "--json", "--project", str(self.root)])
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["lookup"]["mode"], "full_scan")
        self.assertIn(self.rid, [m["id"] for m in doc["matches"]])

    def test_store_content_comes_from_the_corpus_not_the_prefilter(self):
        (self.mem / "generated" / cli.GUARD_PREFILTER_FILENAME).unlink(missing_ok=True)
        self.assertTrue(hooks_prompt._store_has_content(self.mem))
        cli.reindex_projections(self.mem, self.root)
        summary = retrieval.corpus_summary(self.mem, self.root)
        self.assertEqual(summary, {"records": 1, "source": "manifest"})


class CommandHazardTests(StoreCase):
    def setUp(self):
        super().setUp()
        crumb.note(
            self.mem,
            self.root,
            "trap",
            "npm test truncates the local database",
            fields={"safe": "Use `npm run test:unit` against a disposable database."},
        )
        crumb.note(
            self.mem,
            self.root,
            "trap",
            "Workers leak connections",
            fields={"symptom": "`pytest -n auto` exhausts the database connection pool."},
        )
        cli.reindex_projections(self.mem, self.root)

    def bash(self, command: str, session: str) -> dict:
        return hook(
            "guard",
            {
                "cwd": str(self.root),
                "session_id": session,
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
        )

    def test_a_named_command_warns_and_nothing_else_does(self):
        warns = ("npm test", "npm test --watch", "pytest -n auto", "cd web && npm test 2>&1")
        quiet = (
            "npm run test:unit",
            "npm install",
            "git status",
            "pytest -q",
            "make",
            "npm testing",
        )
        for i, command in enumerate(warns):
            with self.subTest(command=command):
                self.assertEqual(cli.guard(self.mem, self.root, command)["verdict"], "READ_FIRST")
                self.assertTrue(cli._prefilter_trap_hit(self.mem, command, None))
                out = self.bash(command, f"w{i}")
                self.assertIn("READ_FIRST", context(out))
                # Advisory: the reader is told; the permission flow is untouched.
                self.assertNotIn("permissionDecision", out.get("hookSpecificOutput") or {})
        for i, command in enumerate(quiet):
            with self.subTest(command=command):
                self.assertEqual(cli.guard(self.mem, self.root, command)["verdict"], "PROCEED")
                self.assertEqual(self.bash(command, f"q{i}"), {})

    def test_proceed_is_explained_as_no_warning_not_permission(self):
        advice = cli.guard(self.mem, self.root, "rename a local variable")["recommended_action"]
        self.assertIn("No applicable memory warning found", advice)
        self.assertIn("not an authorization or a safety check", advice)

    def test_an_old_format_prefilter_is_not_trusted(self):
        path = self.mem / "generated" / cli.GUARD_PREFILTER_FILENAME
        doc = json.loads(path.read_text("utf-8"))
        del doc["format"]
        path.write_text(json.dumps(doc), encoding="utf-8")
        self.assertTrue(cli._prefilter_trap_hit(self.mem, "echo hello", None))


if __name__ == "__main__":
    unittest.main()
