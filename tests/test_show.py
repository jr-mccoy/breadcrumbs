"""Tests for `crumb show`, per-id MCP resources, and related records (WM-21, WM-25).

Packets and hook injections are one line per record by design. `show` is the
other half of that bargain: every id the tool prints — decision, attempt,
verification, idea, jot, trap or question — resolves to its full text through
one command and one URI scheme. `related.json` is the "see also" list printed
under it.

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
from breadcrumbs import mcp_core  # noqa: E402
from breadcrumbs import related as _related  # noqa: E402


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, buf.getvalue()


def init_store(tmp: str) -> Path:
    crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
    return Path(tmp) / crumb.MEMORY_DIRNAME


def remember(tmp: str, title: str, *, file: str, tags: str = "") -> str:
    argv = [
        "remember",
        "decision",
        "--project",
        tmp,
        "--title",
        title,
        "--set",
        "Decision",
        f"{title} — see `{file}`.",
        "--evidence",
        "file",
        file,
        "--json",
    ]
    if tags:
        argv += ["--tags", tags]
    code, out = run(argv)
    assert code == 0, out
    return json.loads(out)["id"]


class ShowTests(unittest.TestCase):
    def test_show_prints_a_decision_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            rid = remember(tmp, "keep the ledger in sqlite", file="src/ledger.py")
            code, out = run(["show", rid, "--project", tmp])
            self.assertEqual(code, 0)
            self.assertIn("keep the ledger in sqlite", out)
            self.assertIn("## Decision", out)

    def test_show_resolves_traps_and_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            trap = crumb.note(mem, Path(tmp), "trap", "the daemon holds a lock")["id"]
            question = crumb.note(mem, Path(tmp), "question", "Should we shard the ledger?")
            for rid, needle in ((trap, "the daemon holds a lock"), (question["id"], "shard")):
                with self.subTest(rid=rid):
                    code, out = run(["show", rid, "--project", tmp])
                    self.assertEqual(code, 0, out)
                    self.assertIn(needle, out)

    def test_a_legacy_colon_question_id_still_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            qid = crumb.note(mem, Path(tmp), "question", "Should we shard the ledger?")["id"]
            self.assertTrue(qid.startswith(crumb.QUESTION_ID_PREFIX))
            legacy = "q:" + qid[len(crumb.QUESTION_ID_PREFIX) :]
            item = crumb.find_item(mem, legacy)
            self.assertIsNotNone(item)
            self.assertEqual(item["id"], qid)

    def test_show_resolves_a_jot(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, out = run(
                ["jot", "the flaky test is timing-dependent", "--project", tmp, "--json"]
            )
            self.assertEqual(code, 0, out)
            jid = json.loads(out)["id"]
            code, out = run(["show", jid, "--project", tmp])
            self.assertEqual(code, 0, out)
            self.assertIn("timing-dependent", out)

    def test_an_unknown_id_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, _ = run(["show", "dec_20200101_nope", "--project", tmp])
            self.assertEqual(code, 1)

    def test_json_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            rid = remember(tmp, "keep the ledger in sqlite", file="src/ledger.py")
            code, out = run(["show", rid, "--project", tmp, "--json"])
            self.assertEqual(code, 0)
            doc = json.loads(out)
            self.assertEqual(doc["id"], rid)
            self.assertEqual(doc["kind"], "decision")
            self.assertEqual(doc["status"], "active")
            self.assertIn("keep the ledger", doc["text"])
            self.assertIsInstance(doc["related"], list)


class McpShowTests(unittest.TestCase):
    def test_the_record_resource_serves_any_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = remember(tmp, "keep the ledger in sqlite", file="src/ledger.py")
            trap = crumb.note(mem, Path(tmp), "trap", "the daemon holds a lock")["id"]
            self.assertIn("keep the ledger", mcp_core.resource_record(rid, root=tmp))
            self.assertIn("the daemon holds a lock", mcp_core.resource_record(trap, root=tmp))

    def test_typed_resources_refuse_the_wrong_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = remember(tmp, "keep the ledger in sqlite", file="src/ledger.py")
            trap = crumb.note(mem, Path(tmp), "trap", "the daemon holds a lock")["id"]
            self.assertIn("the daemon holds a lock", mcp_core.resource_trap(trap, root=tmp))
            with self.assertRaises(KeyError):
                mcp_core.resource_trap(rid, root=tmp)
            with self.assertRaises(KeyError):
                mcp_core.resource_question(trap, root=tmp)

    def test_the_resource_text_is_what_show_prints(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = remember(tmp, "keep the ledger in sqlite", file="src/ledger.py")
            trap = crumb.note(mem, Path(tmp), "trap", "the daemon holds a lock")["id"]
            for item_id in (rid, trap):
                with self.subTest(id=item_id):
                    _code, out = run(["show", item_id, "--project", tmp])
                    self.assertEqual(
                        mcp_core.resource_record(item_id, root=tmp).rstrip(), out.rstrip()
                    )

    def test_tool_show(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            rid = remember(tmp, "keep the ledger in sqlite", file="src/ledger.py")
            res = mcp_core.tool_show(rid, root=tmp)
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["kind"], "decision")
            self.assertFalse(mcp_core.tool_show("nope", root=tmp)["ok"])


class RelatedTests(unittest.TestCase):
    def _store(self, tmp: str) -> tuple[Path, dict[str, str]]:
        mem = init_store(tmp)
        ids = {
            "a": remember(tmp, "ledger rows are append only", file="src/ledger.py"),
            "b": remember(tmp, "ledger compaction runs nightly", file="src/ledger.py"),
            "c": remember(tmp, "logo lives in the design repo", file="assets/logo.svg"),
        }
        crumb.main(["reindex", "--project", tmp])
        return mem, ids

    def test_records_sharing_a_file_are_related(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, ids = self._store(tmp)
            related = crumb.load_related(mem)
            self.assertIn(ids["b"], related.get(ids["a"], []))
            self.assertIn(ids["a"], related.get(ids["b"], []))
            self.assertNotIn(ids["c"], related.get(ids["a"], []))

    def test_show_prints_see_also(self):
        with tempfile.TemporaryDirectory() as tmp:
            _mem, ids = self._store(tmp)
            code, out = run(["show", ids["a"], "--project", tmp])
            self.assertEqual(code, 0)
            self.assertIn("See also:", out)
            self.assertIn(ids["b"], out)

    def test_a_retired_record_relates_to_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, ids = self._store(tmp)
            code, out = run(["mark-status", ids["b"], "stale", "--project", tmp, "--reason", "x"])
            self.assertEqual(code, 0, out)
            crumb.main(["reindex", "--project", tmp])
            related = crumb.load_related(mem)
            self.assertNotIn(ids["b"], related.get(ids["a"], []))
            self.assertNotIn(ids["b"], related)

    def test_the_projection_is_machine_independent_and_stamped(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, _ids = self._store(tmp)
            doc = json.loads((mem / "generated" / _related.RELATED_FILENAME).read_text("utf-8"))
            self.assertEqual(doc["inputs_hash"], crumb._inputs_hash(mem, Path(tmp)))
            # Rendering twice gives byte-identical output: nothing time- or
            # machine-dependent goes into a committed file.
            self.assertEqual(
                _related.render_related(mem, Path(tmp)), _related.render_related(mem, Path(tmp))
            )

    def test_drift_detection_covers_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, _ids = self._store(tmp)
            self.assertEqual(crumb.detect_packet_drift(mem), [])
            remember(tmp, "a record written after the reindex", file="src/other.py")
            # `remember` refreshes projections itself; stamp an old hash by hand
            # to stand in for a checkout that pulled records but not the file.
            path = mem / "generated" / _related.RELATED_FILENAME
            doc = json.loads(path.read_text("utf-8"))
            doc["inputs_hash"] = "000000000000"
            path.write_text(json.dumps(doc), encoding="utf-8")
            drift = [d["path"] for d in crumb.detect_packet_drift(mem)]
            self.assertIn(f"generated/{_related.RELATED_FILENAME}", drift)

    def test_a_missing_or_corrupt_file_reads_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            self.assertEqual(crumb.load_related(mem), {})
            path = mem / "generated" / _related.RELATED_FILENAME
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(crumb.load_related(mem), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
