"""Multi-machine correctness — the projection/freshness cluster (MF-06 … MF-10).

Every defect these pin is invisible on one machine and wrong the moment a second
one exists: a freshness stamp no clone can reproduce, an absolute host path in a
committed artifact, a hash that cannot see a rename, a `resume` that half-writes
the projections, and a JSON projection that escapes the store's own commit policy.

Run with:  python -m unittest discover -s tests
       or:  python tests/test_multi_machine.py
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as bcli  # noqa: E402  (the module `crumb` re-exports)

FIXTURE = REPO_ROOT / "fixtures" / "fixture-11-multi-machine"


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = crumb.main(argv)
    return code, buf.getvalue()


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(root), check=True, capture_output=True, text=True
    )


def make_store(tmp: str | Path, tracking: str = "distillate", *, git_repo: bool = True) -> Path:
    """A store of the shape a team actually shares: git repo, chosen policy."""
    root = Path(tmp)
    root.mkdir(parents=True, exist_ok=True)
    if git_repo:
        git(root, "init", "-q")
        git(root, "config", "user.email", "t@t")
        git(root, "config", "user.name", "t")
    run(["init", "--project", str(root), "--session-tracking", tracking,
         "--no-adapter", "--no-mcp", "--no-hooks"])
    return root


def seed_record(root: Path, title: str = "Split the worker") -> None:
    run(["remember", "decision", "--title", title, "--confidence", "low",
         "--set", "Rationale", "it is cheaper", "--project", str(root)])


# --------------------------------------------------------------------------- #
# MF-06 — a local-only record directory is not a shared freshness input
# --------------------------------------------------------------------------- #
class InputsHashPolicyTests(unittest.TestCase):
    def test_MF06_distillate_hash_ignores_the_local_sessions_dir(self):
        """The stamp must survive the clone that has no `sessions/` at all."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp)
            mem = root / crumb.MEMORY_DIRNAME
            seed_record(root)
            run(["capture", "session", "--next", "keep going", "--project", str(root)])
            self.assertTrue(list((mem / "sessions").glob("*.md")), "need a session record")

            author = crumb._inputs_hash(mem)
            shutil.rmtree(mem / "sessions")  # what every clone of a distillate store sees
            self.assertEqual(crumb._inputs_hash(mem), author)

    def test_MF06_full_tracking_still_hashes_sessions(self):
        """The skip is the policy's, not a blanket exemption."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp, "full")
            mem = root / crumb.MEMORY_DIRNAME
            run(["capture", "session", "--next", "keep going", "--project", str(root)])
            before = crumb._inputs_hash(mem)
            shutil.rmtree(mem / "sessions")
            self.assertNotEqual(crumb._inputs_hash(mem), before)

    def test_MF06_clone_of_a_distillate_store_validates_clean(self):
        """End to end: author commits, teammate clones, validate agrees on both."""
        with tempfile.TemporaryDirectory() as tmp:
            author = make_store(Path(tmp) / "author", "distillate")
            seed_record(author)
            run(["capture", "session", "--next", "keep going", "--project", str(author)])
            run(["reindex", "--project", str(author)])
            git(author, "add", "-A")
            git(author, "commit", "-qm", "memory")

            clone = Path(tmp) / "teammate"
            subprocess.run(["git", "clone", "-q", str(author), str(clone)],
                           check=True, capture_output=True, text=True)
            self.assertFalse((clone / crumb.MEMORY_DIRNAME / "sessions").exists())

            for who in (author, clone):
                fails = [f for f in crumb.run_validate(who / crumb.MEMORY_DIRNAME)
                         if f["status"] == "fail"]
                self.assertEqual(fails, [], f"{who}: {fails}")

            # ...and the teammate's own reindex restamps with the SAME hash, so the
            # advice `validate` prints cannot ping-pong between the two machines.
            run(["reindex", "--project", str(clone)])
            stamp = crumb._stamped_inputs_hash
            self.assertEqual(
                stamp((clone / crumb.MEMORY_DIRNAME / "generated" / "resume-packet.md")
                      .read_text(encoding="utf-8")),
                stamp((author / crumb.MEMORY_DIRNAME / "generated" / "resume-packet.md")
                      .read_text(encoding="utf-8")),
            )

    def test_MF06_committed_gitignore_excludes_a_record_dir_from_the_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp, "full")
            mem = root / crumb.MEMORY_DIRNAME
            (mem / "ideas" / "2026-07-01-an-idea.md").write_text(
                "---\ntitle: An idea\nstatus: active\ncreated_at: 2026-07-01T09:00:00-05:00\n"
                "privacy: repo-safe\n---\n\n## Idea\nlocal only\n",
                encoding="utf-8",
            )
            before = crumb._inputs_hash(mem)
            with (root / ".gitignore").open("a", encoding="utf-8") as fh:
                fh.write(f"\n{crumb.MEMORY_DIRNAME}/ideas/\n")
            after = crumb._inputs_hash(mem)
            self.assertNotEqual(after, before, "excluding a dir must change what is hashed")
            # and the excluded directory's contents no longer move the hash at all
            (mem / "ideas" / "2026-07-02-another.md").write_text("x\n", encoding="utf-8")
            self.assertEqual(crumb._inputs_hash(mem), after)

    def test_MF06_machine_local_excludes_never_change_the_hash(self):
        """`.git/info/exclude` is per-machine; folding it in would recreate the bug."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp, "full")
            mem = root / crumb.MEMORY_DIRNAME
            before = crumb._inputs_hash(mem)
            with (root / ".git" / "info" / "exclude").open("a", encoding="utf-8") as fh:
                fh.write(f"\n{crumb.MEMORY_DIRNAME}/ideas/\n")
            self.assertIn("ideas", crumb._hashed_input_dirs(mem, root, {}))
            self.assertEqual(crumb._inputs_hash(mem), before)

    def test_MF06_flipping_the_policy_invalidates_the_stamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp, "full")
            mem = root / crumb.MEMORY_DIRNAME
            before = crumb._inputs_hash(mem)
            man = mem / "manifest.yml"
            man.write_text(
                man.read_text(encoding="utf-8").replace(
                    "session_tracking: full", "session_tracking: distillate"
                ),
                encoding="utf-8",
            )
            self.assertEqual(crumb.load_manifest(mem)["session_tracking"], "distillate")
            self.assertNotEqual(crumb._inputs_hash(mem), before)


# --------------------------------------------------------------------------- #
# MF-07 — the committed packet carries no host path
# --------------------------------------------------------------------------- #
class PacketPathTests(unittest.TestCase):
    def test_MF07_packet_path_is_project_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp, "full", git_repo=False)
            packet = crumb.build_resume_packet(root / crumb.MEMORY_DIRNAME, root)
            self.assertEqual(packet["project"]["path"], ".")
            md = crumb.render_packet_markdown(packet)
            self.assertNotIn(str(root), md)
            self.assertNotIn(str(root), json.dumps(packet))

    def test_MF07_byte_identical_store_at_another_path_is_not_stale(self):
        """The clone-at-a-different-path case `doctor` used to call stale."""
        with tempfile.TemporaryDirectory() as tmp:
            here = make_store(Path(tmp) / "here", "full", git_repo=False)
            seed_record(here)
            run(["resume", "--project", str(here)])
            there = Path(tmp) / "somewhere-else-entirely"
            shutil.copytree(here, there)

            self.assertEqual(
                (here / crumb.MEMORY_DIRNAME / "generated" / "resume-packet.md").read_bytes(),
                (there / crumb.MEMORY_DIRNAME / "generated" / "resume-packet.md").read_bytes(),
            )
            for root in (here, there):
                self.assertFalse(
                    crumb._packet_is_stale(root / crumb.MEMORY_DIRNAME, root), str(root)
                )
                checks = {c["check"]: c for c in crumb.doctor_report(root)["checks"]}
                self.assertTrue(checks["resume_packet"]["ok"], checks["resume_packet"])

    def test_MF07_legacy_absolute_path_line_is_not_read_as_staleness(self):
        """Belt-and-braces for packets written by an older version."""
        md = (
            "<!-- source_commit: abc | inputs_hash: deadbeef | generated_at: X -->\n"
            "# Resume Packet\n\n## Project\n"
            "**svc** — `/Users/someone/code/svc`  \nbranch `main`\n"
        )
        other = md.replace("/Users/someone/code/svc", "/home/other/svc")
        self.assertEqual(
            crumb._strip_packet_volatile(md), crumb._strip_packet_volatile(other)
        )


# --------------------------------------------------------------------------- #
# MF-08 — the hash sees renames, not just contents
# --------------------------------------------------------------------------- #
class InputsHashIdentityTests(unittest.TestCase):
    def _store_with_two_records(self, tmp: str) -> tuple[Path, Path]:
        root = make_store(tmp, "full", git_repo=False)
        mem = root / crumb.MEMORY_DIRNAME
        for stem, title in (("2026-01-01-foo", "Foo"), ("2026-01-03-baz", "Baz")):
            (mem / "decisions" / f"{stem}.md").write_text(
                f"---\ntitle: {title}\nstatus: active\n"
                f"created_at: 2026-01-01T09:00:00-05:00\nprivacy: repo-safe\n---\n\n"
                f"## Decision\n{title} body\n",
                encoding="utf-8",
            )
        return root, mem

    def test_MF08_renaming_a_record_invalidates_the_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._store_with_two_records(tmp)
            before = crumb._inputs_hash(mem)
            (mem / "decisions" / "2026-01-01-foo.md").rename(
                mem / "decisions" / "2026-02-02-bar.md"
            )
            self.assertNotEqual(
                crumb._inputs_hash(mem), before,
                "a rename changes every derived record id — the stamp must not survive it",
            )

    def test_MF08_rename_is_caught_by_the_freshness_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._store_with_two_records(tmp)
            run(["reindex", "--project", str(root)])
            self.assertEqual(crumb.detect_packet_drift(mem), [])
            (mem / "decisions" / "2026-01-01-foo.md").rename(
                mem / "decisions" / "2026-02-02-bar.md"
            )
            self.assertTrue(
                any(d["path"].endswith("resume-packet.md")
                    for d in crumb.detect_packet_drift(mem)),
                "validate/audit must see the projection built from ids that no longer exist",
            )
            fails = [f for f in crumb.run_validate(mem) if f["status"] == "fail"]
            self.assertTrue(any(f["check"] == "freshness" for f in fails), fails)

    def test_MF08_moving_text_between_records_invalidates_the_hash(self):
        """Undelimited concatenation could not see content move across files."""
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._store_with_two_records(tmp)
            before = crumb._inputs_hash(mem)
            foo = mem / "decisions" / "2026-01-01-foo.md"
            baz = mem / "decisions" / "2026-01-03-baz.md"
            foo_text, baz_text = foo.read_text(encoding="utf-8"), baz.read_text(encoding="utf-8")
            foo.write_text(foo_text[:-1], encoding="utf-8")
            baz.write_text("\n" + baz_text, encoding="utf-8")
            self.assertNotEqual(crumb._inputs_hash(mem), before)


# --------------------------------------------------------------------------- #
# MF-09 — `resume` refreshes every projection, atomically
# --------------------------------------------------------------------------- #
class ResumeReindexTests(unittest.TestCase):
    TRAP = (
        "\n## trap_xdist-deadlock: never run `pytest -n auto` here\n"
        "- Area / files: `tests/conftest.py`\n"
        "- Symptom: it deadlocks on the xdist worker pool\n"
    )

    def test_MF09_resume_rebuilds_the_guard_prefilter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp, "full", git_repo=False)
            mem = root / crumb.MEMORY_DIRNAME
            prefilter = mem / "generated" / crumb.GUARD_PREFILTER_FILENAME
            with (mem / "known-traps.md").open("a", encoding="utf-8") as fh:
                fh.write(self.TRAP)
            prefilter.unlink(missing_ok=True)

            code, _ = run(["resume", "--project", str(root)])
            self.assertEqual(code, 0)
            self.assertTrue(prefilter.is_file(), "resume must rebuild the hook's index")
            self.assertIn("xdist", json.loads(prefilter.read_text(encoding="utf-8"))["tokens"])
            # the index guard actually consults now sees the newly recorded trap
            self.assertTrue(crumb._prefilter_trap_hit(mem, "pytest -n auto", None))

    def test_MF09_resume_writes_the_packet_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp, "full", git_repo=False)
            mem = root / crumb.MEMORY_DIRNAME
            with mock.patch.object(
                bcli, "write_text_atomic", wraps=bcli.write_text_atomic
            ) as spy:
                run(["resume", "--project", str(root)])
            written = {Path(c.args[0]).name for c in spy.call_args_list}
            self.assertIn("resume-packet.md", written)
            self.assertIn(crumb.GUARD_PREFILTER_FILENAME, written)
            self.assertFalse(list((mem / "generated").glob("*.tmp")))

    def test_MF09_fast_and_task_views_stay_print_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp, "full", git_repo=False)
            mem = root / crumb.MEMORY_DIRNAME
            run(["resume", "--project", str(root)])
            before = (mem / "generated" / "resume-packet.md").read_bytes()
            run(["resume", "--fast", "--project", str(root)])
            run(["resume", "--task", "something else", "--project", str(root)])
            self.assertEqual((mem / "generated" / "resume-packet.md").read_bytes(), before)


# --------------------------------------------------------------------------- #
# MF-10 — the JSON projection obeys the store's commit policy
# --------------------------------------------------------------------------- #
class GeneratedJsonPolicyTests(unittest.TestCase):
    def test_MF10_local_only_projections_cover_the_json_index(self):
        block = crumb.gitignore_block("full", False)
        self.assertIn(f"{crumb.MEMORY_DIRNAME}/generated/*.json", block)
        self.assertNotIn(
            f"{crumb.MEMORY_DIRNAME}/generated/*.json", crumb.gitignore_block("full", True)
        )

    def test_MF10_prefilter_is_git_ignored_under_no_commit_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init", "-q")
            run(["init", "--project", str(root), "--session-tracking", "full",
                 "--no-commit-generated", "--no-adapter", "--no-mcp", "--no-hooks"])
            run(["reindex", "--project", str(root)])
            rel = f"{crumb.MEMORY_DIRNAME}/generated/{crumb.GUARD_PREFILTER_FILENAME}"
            self.assertTrue((root / rel).is_file())
            r = subprocess.run(["git", "check-ignore", rel], cwd=str(root),
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f"{rel} escaped the local-only policy")

    def test_MF10_template_readme_documents_the_prefilter(self):
        readme = (Path(bcli.__file__).parent / "templates" / "project-memory"
                  / "generated" / "README.md").read_text(encoding="utf-8")
        self.assertIn(crumb.GUARD_PREFILTER_FILENAME, readme)


# --------------------------------------------------------------------------- #
# Fixture 11 — the multi-developer store, exercised from two paths
# --------------------------------------------------------------------------- #
class MultiMachineFixtureTests(unittest.TestCase):
    """The fixture the suite lacked: distillate, no `sessions/`, two checkouts."""

    def test_fixture_shape_is_the_multi_developer_one(self):
        mem = FIXTURE / ".project-memory"
        manifest = crumb.load_manifest(mem)
        self.assertEqual(manifest["session_tracking"], "distillate")
        self.assertEqual(manifest["commit_generated_projections"], "true")
        self.assertFalse((mem / "sessions").exists(), "a distillate clone has no sessions/")
        self.assertTrue((mem / "generated" / "resume-packet.md").is_file())
        self.assertTrue((mem / "generated" / crumb.GUARD_PREFILTER_FILENAME).is_file())

    def test_fixture_packet_carries_no_host_path_and_a_live_stamp(self):
        mem = FIXTURE / ".project-memory"
        text = (mem / "generated" / "resume-packet.md").read_text(encoding="utf-8")
        self.assertIn("**shared-service** — `.`", text)
        self.assertNotIn(str(REPO_ROOT), text)
        self.assertEqual(
            crumb._stamped_inputs_hash(text), crumb._inputs_hash(mem)
        )
        self.assertEqual(crumb.detect_packet_drift(mem), [])

    def _checkout(self, parent: Path, name: str) -> Path:
        """Copy the fixture to a NON-git path, as a second machine would have it."""
        dest = parent / name
        shutil.copytree(FIXTURE, dest)
        return dest

    def test_fixture_is_clean_at_two_different_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = self._checkout(Path(tmp), "alex-laptop")
            b = self._checkout(Path(tmp), "sam-workstation-with-a-longer-path")

            # One developer regenerates; the file that lands in git is the artifact
            # the other developer must be able to accept unchanged.
            run(["reindex", "--project", str(a)])
            shutil.copyfile(
                a / ".project-memory" / "generated" / "resume-packet.md",
                b / ".project-memory" / "generated" / "resume-packet.md",
            )

            for root in (a, b):
                mem = root / ".project-memory"
                fails = [f for f in crumb.run_validate(mem) if f["status"] == "fail"]
                self.assertEqual(fails, [], f"{root.name}: {fails}")
                self.assertEqual(run(["audit", "--project", str(root)])[0], 0, root.name)
                report = crumb.doctor_report(root)
                checks = {c["check"]: c for c in report["checks"]}
                self.assertTrue(report["integrated"], checks)
                self.assertTrue(checks["adapter"]["ok"], checks["adapter"])
                self.assertTrue(checks["resume_packet"]["ok"],
                                f"{root.name}: {checks['resume_packet']}")

            self.assertEqual(
                crumb._inputs_hash(a / ".project-memory"),
                crumb._inputs_hash(b / ".project-memory"),
            )

    def test_fixture_regenerates_byte_identically_at_two_paths(self):
        """No path churn: two machines reindexing produce the same bytes."""
        with tempfile.TemporaryDirectory() as tmp:
            a = self._checkout(Path(tmp), "one")
            b = self._checkout(Path(tmp), "two-somewhere-much-deeper/nested")
            for root in (a, b):
                run(["reindex", "--project", str(root)])
            packets = [
                crumb._strip_packet_volatile(
                    (root / ".project-memory" / "generated" / "resume-packet.md")
                    .read_text(encoding="utf-8")
                )
                for root in (a, b)
            ]
            self.assertEqual(packets[0], packets[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
