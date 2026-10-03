"""Projections describe the snapshot they were built from (audit F07, F11, F12; WP07).

- A projection's `inputs_hash` used to be computed *after* its records were
  read, so a record written in between was stamped as included while missing
  from the content.
- The guard hook treated a missing, corrupt or out-of-date pre-filter as "no
  risk".
- The search index called itself fresh on a path/size/mtime match, so a
  same-size edit with a restored mtime made indexed search disagree with the
  full scan.

These pin the replacement:

- stamps come from a snapshot verified unchanged across the build (or say
  `unstable`);
- a generation manifest is written last;
- the hook trusts only a verified pre-filter;
- index freshness is the content hash.

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli, hooklog, projections, searchindex, snapshots  # noqa: E402
from breadcrumbs import packet as _packet  # noqa: E402


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True)


def run_hook(event: str, payload: dict) -> dict:
    out = io.StringIO()
    saved = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload))
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = crumb.main(["hook", event])
    finally:
        sys.stdin = saved
    assert code == 0, code
    text = out.getvalue().strip()
    return json.loads(text) if text else {}


class SnapshotCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@t")
        git(self.root, "config", "user.name", "t")
        with contextlib.redirect_stdout(io.StringIO()):
            crumb.main(["init", "--project", str(self.root), "--session-tracking", "full"])
        self.mem = self.root / crumb.MEMORY_DIRNAME

    def decision(self, title: str, **kwargs) -> str:
        _path, meta = crumb.write_record(
            self.mem,
            self.root,
            "decision",
            title,
            {"Decision": f"{title}."},
            evidence=[{"type": "file", "ref": "src/app.py"}],
            **kwargs,
        )
        return meta["id"]

    def inject_during_build(self, *, every_time: bool):
        """Write a new decision after the packet has read its decisions."""
        real = _packet.compute_staleness
        written: list[str] = []

        def compute_staleness(*args, **kwargs):
            if every_time or not written:
                written.append(self.decision(f"Injected cerulean policy number {len(written)}"))
            return real(*args, **kwargs)

        return mock.patch.object(
            _packet, "compute_staleness", side_effect=compute_staleness
        ), written


class StampTests(SnapshotCase):
    def test_mutation_between_read_and_hash_cannot_false_certify(self):
        self.decision("Existing amber policy")
        patch, written = self.inject_during_build(every_time=False)
        with patch:
            packet = _packet.build_resume_packet(self.mem, self.root)
        current = cli._inputs_hash(self.mem, self.root)
        ids = [d["id"] for d in packet["active_decisions"]]
        # Either the stamp is current and the record is in, or the stamp is not current.
        if packet["source"]["inputs_hash"] == current:
            self.assertIn(written[0], ids, "a current stamp certified an omitted record")
        # Here the retry makes it the former.
        self.assertEqual(packet["source"]["inputs_hash"], current)
        self.assertIn(written[0], ids)

    def test_a_store_that_keeps_changing_is_stamped_unstable(self):
        patch, _written = self.inject_during_build(every_time=True)
        with patch:
            packet = _packet.build_resume_packet(self.mem, self.root)
        self.assertEqual(packet["source"]["inputs_hash"], snapshots.UNSTABLE)
        self.assertIn(snapshots.UNSTABLE_WARNING, packet["warnings"])

    def test_an_unstable_publication_is_never_certified(self):
        patch, _written = self.inject_during_build(every_time=True)
        with patch:
            ok, reason = cli.try_reindex_projections(self.mem, self.root)
        self.assertFalse(ok)
        self.assertIn("kept changing", reason)
        stamps = {d["path"] for d in cli.detect_packet_drift(self.mem)}
        self.assertIn("generated/resume-packet.md", stamps)
        manifest = projections.load_manifest(self.mem)
        self.assertFalse(manifest["stable"])
        fails = [f["check"] for f in crumb.run_validate(self.mem) if f["status"] == "fail"]
        self.assertIn("freshness", fails)
        # The next quiet publication certifies again.
        self.assertTrue(cli.try_reindex_projections(self.mem, self.root)[0])
        self.assertEqual(cli.detect_packet_drift(self.mem), [])

    def test_every_output_of_a_generation_carries_one_stamp(self):
        self.decision("Existing amber policy")
        self.assertTrue(cli.try_reindex_projections(self.mem, self.root)[0])
        digest = cli._inputs_hash(self.mem, self.root)
        gen = self.mem / "generated"
        self.assertIn(f"inputs_hash: {digest}", (gen / "resume-packet.md").read_text())
        for name in (cli.GUARD_PREFILTER_FILENAME, "related.json", "conflicts.json"):
            path = cli.projection_path(self.mem, name)
            self.assertEqual(json.loads(path.read_text())["inputs_hash"], digest, name)
        manifest = projections.load_manifest(self.mem)
        self.assertEqual((manifest["inputs_hash"], manifest["stable"]), (digest, True))
        self.assertEqual(
            sorted(manifest["files"]),
            sorted(
                ["resume-packet.md", cli.GUARD_PREFILTER_FILENAME, "related.json", "conflicts.json"]
            ),
        )


class GenerationTests(SnapshotCase):
    def _attempt(self, path: str, title: str) -> None:
        crumb.write_record(
            self.mem,
            self.root,
            "attempt",
            title,
            {"Tried": "batched writes", "Do Not Retry Unless": "an idempotency key exists"},
            evidence=[{"type": "file", "ref": path}],
        )

    def _edit_warns(self, path: str) -> bool:
        out = run_hook(
            "guard",
            {"cwd": str(self.root), "tool_name": "Edit", "tool_input": {"file_path": path}},
        )
        hso = out.get("hookSpecificOutput") or {}
        return bool(hso.get("permissionDecisionReason") or hso.get("additionalContext"))

    def test_mixed_generation_is_not_consumed(self):
        self._attempt("src/billing.py", "Batched the billing reconciler writes")
        cli.try_reindex_projections(self.mem, self.root)
        prefilter = cli.guard_prefilter_path(self.mem)
        self.assertTrue(self._edit_warns("src/billing.py"))
        # A verified generation keeps an unrelated action quiet, cheaply.
        self.assertFalse(self._edit_warns("docs/unrelated.md"))
        self.assertEqual(hooklog.read_log(self.mem)[-1].get("skipped"), "prefilter")

        good = prefilter.read_bytes()
        for label, damage in (
            ("replaced by another generation's file", b'{"paths": [], "tokens": []}\n'),
            ("corrupt", b"{not json"),
            ("removed", None),
        ):
            with self.subTest(prefilter=label):
                if damage is None:
                    prefilter.unlink()
                else:
                    prefilter.write_bytes(damage)
                self.assertTrue(self._edit_warns("src/billing.py"), "a real hazard went silent")
                self.assertEqual(hooklog.read_log(self.mem)[-1].get("prefilter"), "unverified")
                prefilter.write_bytes(good)

    def test_records_changed_since_publication_are_not_hidden(self):
        self._attempt("src/billing.py", "Batched the billing reconciler writes")
        cli.try_reindex_projections(self.mem, self.root)
        # A hazard written straight to disk, with no reindex: the published
        # pre-filter cannot know it, and must not vouch for the store any more.
        path = self.mem / "attempts" / "2026-09-01-sharded-the-ledger-writes.md"
        src = next((self.mem / "attempts").glob("*.md")).read_text()
        path.write_text(src.replace("src/billing.py", "src/ledger.py").replace("billing", "ledger"))
        self.assertTrue(self._edit_warns("src/ledger.py"))

    def test_an_unstable_generation_is_not_trusted(self):
        cli.try_reindex_projections(self.mem, self.root)
        manifest = projections.manifest_path(self.mem)
        doc = json.loads(manifest.read_text())
        doc["stable"] = False
        manifest.write_text(json.dumps(doc))
        self.assertIsNone(projections.verified(self.mem, self.root, cli.GUARD_PREFILTER_FILENAME))


class IndexTests(SnapshotCase):
    def _big_store(self) -> Path:
        target = None
        for i in range(searchindex.INDEX_MIN_CORPUS + 1):
            _path, meta = crumb.write_record(
                self.mem,
                self.root,
                "decision",
                f"Ordinary record number {i:04d}",
                {"Decision": "Route amber quasar traffic." if i == 7 else "Unrelated text."},
                evidence=[{"type": "file", "ref": f"src/m{i}.py"}],
            )
            if i == 7:
                target = _path
        return target

    def test_same_size_restored_mtime_edit_invalidates_strict_index(self):
        path = self._big_store()
        self.assertTrue(searchindex.build_index(self.mem, self.root)["built"])
        self.assertEqual(searchindex.index_status(self.mem, self.root)["state"], "fresh")
        st = path.stat()
        path.write_text(path.read_text().replace("amber quasar", "amber nebula"))
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
        self.assertEqual(path.stat().st_size, st.st_size)
        self.assertEqual(searchindex.index_status(self.mem, self.root)["state"], "stale")
        indexed, _ = cli.search(self.mem, self.root, "nebula", include_ideas=False)
        with mock.patch.object(searchindex, "candidate_items", return_value=None):
            full, _ = cli.search(self.mem, self.root, "nebula", include_ideas=False)
        self.assertEqual([m["id"] for m in indexed], [m["id"] for m in full])
        self.assertTrue(full)

    def test_two_index_builders_do_not_share_temp_file(self):
        self._big_store()
        digest = cli._inputs_hash(self.mem, self.root)
        real_connect = searchindex.sqlite3.connect
        paths: list[str] = []
        both_open = threading.Barrier(2, timeout=10)

        def connect(target, *args, **kwargs):
            if str(target).endswith(".tmp"):
                paths.append(str(target))
                both_open.wait()  # the two builds really overlap
            return real_connect(target, *args, **kwargs)

        results: list[dict] = []
        with mock.patch.object(searchindex.sqlite3, "connect", side_effect=connect):
            threads = [
                threading.Thread(
                    target=lambda: results.append(
                        searchindex.build_index(
                            self.mem, self.root, inputs_hash=digest, publish=False
                        )
                    )
                )
                for _ in range(2)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(len(set(paths)), 2, paths)
        self.assertTrue(all(r["built"] for r in results), results)
        for r in results:
            searchindex.discard_index(r["staged"])
        self.assertEqual(list((self.mem / "index").glob("*.tmp")), [])

    def test_a_failed_publication_leaves_no_staged_index_and_no_manifest(self):
        self._big_store()
        self.assertTrue(cli.try_reindex_projections(self.mem, self.root)[0])
        self.decision("One more amber policy")
        real = cli.write_text_atomic

        def failing(path, text, *args, **kwargs):
            if Path(path).name == "related.json":
                raise OSError("disk full")
            return real(path, text, *args, **kwargs)

        with mock.patch.object(cli, "write_text_atomic", side_effect=failing):
            ok, reason = cli.try_reindex_projections(self.mem, self.root)
        self.assertFalse(ok)
        self.assertIn("disk full", reason)
        self.assertEqual(list((self.mem / "index").glob("*.tmp")), [])
        # The half-replaced set is vouched for by no manifest, old or new.
        self.assertIsNone(projections.load_manifest(self.mem))
        self.assertIsNone(projections.verified(self.mem, self.root, cli.GUARD_PREFILTER_FILENAME))
        self.assertTrue(cli.try_reindex_projections(self.mem, self.root)[0])
        self.assertTrue(projections.load_manifest(self.mem)["stable"])

    def test_a_self_verifying_build_refuses_a_changing_store(self):
        self._big_store()
        real = cli._inputs_hash
        calls = [0]

        def changing(*args, **kwargs):
            calls[0] += 1
            return real(*args, **kwargs) + str(calls[0])

        with mock.patch.object(cli, "_inputs_hash", side_effect=changing):
            res = searchindex.build_index(self.mem, self.root)
        self.assertFalse(res["built"])
        self.assertIn("changed during the build", res["reason"])


if __name__ == "__main__":
    unittest.main()
