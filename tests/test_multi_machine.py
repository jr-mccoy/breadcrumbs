"""Multi-machine correctness — the projection/freshness cluster.

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
from breadcrumbs import projections as bprojections  # noqa: E402
from breadcrumbs import snapshots as bsnapshots  # noqa: E402
from breadcrumbs import cli as bcli  # noqa: E402  (the module `crumb` re-exports)
from breadcrumbs import packet as _packet  # noqa: E402

FIXTURE = REPO_ROOT / "fixtures" / "fixture-11-multi-machine"


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = crumb.main(argv)
    return code, buf.getvalue()


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True, text=True)


def make_store(tmp: str | Path, tracking: str = "distillate", *, git_repo: bool = True) -> Path:
    """A store of the shape a team actually shares: git repo, chosen policy."""
    root = Path(tmp)
    root.mkdir(parents=True, exist_ok=True)
    if git_repo:
        git(root, "init", "-q")
        git(root, "config", "user.email", "t@t")
        git(root, "config", "user.name", "t")
    run(
        [
            "init",
            "--project",
            str(root),
            "--session-tracking",
            tracking,
            "--no-adapter",
            "--no-mcp",
            "--no-hooks",
        ]
    )
    return root


def seed_record(root: Path, title: str = "Split the worker") -> None:
    run(
        [
            "remember",
            "decision",
            "--title",
            title,
            "--confidence",
            "low",
            "--set",
            "Rationale",
            "it is cheaper",
            "--project",
            str(root),
        ]
    )


# --------------------------------------------------------------------------- #
# A local-only record directory is not a shared freshness input
# --------------------------------------------------------------------------- #
class InputsHashPolicyTests(unittest.TestCase):
    def test_distillate_hash_ignores_the_local_sessions_dir(self):
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

    def test_full_tracking_still_hashes_sessions(self):
        """The skip is the policy's, not a blanket exemption."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp, "full")
            mem = root / crumb.MEMORY_DIRNAME
            run(["capture", "session", "--next", "keep going", "--project", str(root)])
            before = crumb._inputs_hash(mem)
            shutil.rmtree(mem / "sessions")
            self.assertNotEqual(crumb._inputs_hash(mem), before)

    def test_clone_of_a_distillate_store_validates_clean(self):
        """End to end: author commits, teammate clones, validate agrees on both."""
        with tempfile.TemporaryDirectory() as tmp:
            author = make_store(Path(tmp) / "author", "distillate")
            seed_record(author)
            run(["capture", "session", "--next", "keep going", "--project", str(author)])
            run(["reindex", "--project", str(author)])
            git(author, "add", "-A")
            git(author, "commit", "-qm", "memory")

            clone = Path(tmp) / "teammate"
            subprocess.run(
                ["git", "clone", "-q", str(author), str(clone)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertFalse((clone / crumb.MEMORY_DIRNAME / "sessions").exists())

            for who in (author, clone):
                fails = [
                    f
                    for f in crumb.run_validate(who / crumb.MEMORY_DIRNAME)
                    if f["status"] == "fail"
                ]
                self.assertEqual(fails, [], f"{who}: {fails}")

            # ...and the teammate's own reindex restamps with the SAME hash, so the
            # advice `validate` prints cannot ping-pong between the two machines.
            run(["reindex", "--project", str(clone)])
            stamp = crumb._stamped_inputs_hash
            self.assertEqual(
                stamp(
                    (clone / crumb.MEMORY_DIRNAME / "generated" / "resume-packet.md").read_text(
                        encoding="utf-8"
                    )
                ),
                stamp(
                    (author / crumb.MEMORY_DIRNAME / "generated" / "resume-packet.md").read_text(
                        encoding="utf-8"
                    )
                ),
            )

    def test_committed_gitignore_excludes_a_record_dir_from_the_hash(self):
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

    def test_machine_local_excludes_never_change_the_hash(self):
        """`.git/info/exclude` is per-machine; folding it in would recreate the bug."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp, "full")
            mem = root / crumb.MEMORY_DIRNAME
            before = crumb._inputs_hash(mem)
            with (root / ".git" / "info" / "exclude").open("a", encoding="utf-8") as fh:
                fh.write(f"\n{crumb.MEMORY_DIRNAME}/ideas/\n")
            self.assertIn("ideas", crumb._hashed_input_dirs(mem, root, {}))
            self.assertEqual(crumb._inputs_hash(mem), before)

    def test_flipping_the_policy_invalidates_the_stamp(self):
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
# The committed packet carries no host path
# --------------------------------------------------------------------------- #
class PacketPathTests(unittest.TestCase):
    def test_packet_path_is_project_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp, "full", git_repo=False)
            packet = crumb.build_resume_packet(root / crumb.MEMORY_DIRNAME, root)
            self.assertEqual(packet["project"]["path"], ".")
            md = crumb.render_packet_markdown(packet)
            self.assertNotIn(str(root), md)
            self.assertNotIn(str(root), json.dumps(packet))

    def test_byte_identical_store_at_another_path_is_not_stale(self):
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

    def test_legacy_absolute_path_line_is_not_read_as_staleness(self):
        """Belt-and-braces for packets written by an older version."""
        md = (
            "<!-- source_commit: abc | inputs_hash: deadbeef | generated_at: X -->\n"
            "# Resume Packet\n\n## Project\n"
            "**svc** — `/Users/someone/code/svc`  \nbranch `main`\n"
        )
        other = md.replace("/Users/someone/code/svc", "/home/other/svc")
        self.assertEqual(crumb._strip_packet_volatile(md), crumb._strip_packet_volatile(other))


# --------------------------------------------------------------------------- #
# The hash sees renames, not just contents
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

    def test_renaming_a_record_invalidates_the_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._store_with_two_records(tmp)
            before = crumb._inputs_hash(mem)
            (mem / "decisions" / "2026-01-01-foo.md").rename(
                mem / "decisions" / "2026-02-02-bar.md"
            )
            self.assertNotEqual(
                crumb._inputs_hash(mem),
                before,
                "a rename changes every derived record id — the stamp must not survive it",
            )

    def test_rename_is_caught_by_the_freshness_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._store_with_two_records(tmp)
            run(["reindex", "--project", str(root)])
            self.assertEqual(crumb.detect_packet_drift(mem), [])
            (mem / "decisions" / "2026-01-01-foo.md").rename(
                mem / "decisions" / "2026-02-02-bar.md"
            )
            self.assertTrue(
                any(d["path"].endswith("resume-packet.md") for d in crumb.detect_packet_drift(mem)),
                "validate/audit must see the projection built from ids that no longer exist",
            )
            fails = [f for f in crumb.run_validate(mem) if f["status"] == "fail"]
            self.assertTrue(any(f["check"] == "freshness" for f in fails), fails)

    def test_moving_text_between_records_invalidates_the_hash(self):
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
# `resume` refreshes every projection, atomically
# --------------------------------------------------------------------------- #
class ResumeReindexTests(unittest.TestCase):
    TRAP = (
        "\n## trap_xdist-deadlock: never run `pytest -n auto` here\n"
        "- Area / files: `tests/conftest.py`\n"
        "- Symptom: it deadlocks on the xdist worker pool\n"
    )

    def test_resume_rebuilds_the_guard_prefilter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp, "full", git_repo=False)
            mem = root / crumb.MEMORY_DIRNAME
            prefilter = crumb.guard_prefilter_path(mem)
            with (mem / "known-traps.md").open("a", encoding="utf-8") as fh:
                fh.write(self.TRAP)
            prefilter.unlink(missing_ok=True)

            code, _ = run(["resume", "--project", str(root)])
            self.assertEqual(code, 0)
            self.assertTrue(prefilter.is_file(), "resume must rebuild the hook's index")
            self.assertIn("xdist", json.loads(prefilter.read_text(encoding="utf-8"))["tokens"])
            # the index guard actually consults now sees the newly recorded trap
            self.assertTrue(crumb._prefilter_trap_hit(mem, "pytest -n auto", None))

    def test_resume_writes_the_packet_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp, "full", git_repo=False)
            mem = root / crumb.MEMORY_DIRNAME
            # An input changed, so the committed packet is due for a rewrite
            # (a fresh one is kept as it is: `ResumeLeavesAFreshPacketTests`).
            with (mem / "known-traps.md").open("a", encoding="utf-8") as fh:
                fh.write(self.TRAP)
            with mock.patch.object(bcli, "write_text_atomic", wraps=bcli.write_text_atomic) as spy:
                run(["resume", "--project", str(root)])
            written = {Path(c.args[0]).name for c in spy.call_args_list}
            self.assertIn("resume-packet.md", written)
            self.assertIn(crumb.GUARD_PREFILTER_FILENAME, written)
            self.assertFalse(list((mem / "generated").glob("*.tmp")))

    def test_fast_and_task_views_stay_print_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_store(tmp, "full", git_repo=False)
            mem = root / crumb.MEMORY_DIRNAME
            run(["resume", "--project", str(root)])
            before = (mem / "generated" / "resume-packet.md").read_bytes()
            run(["resume", "--fast", "--project", str(root)])
            run(["resume", "--task", "something else", "--project", str(root)])
            self.assertEqual((mem / "generated" / "resume-packet.md").read_bytes(), before)


# --------------------------------------------------------------------------- #
# A fresh committed packet is left alone: the tree settles (0.6.0)
# --------------------------------------------------------------------------- #
class ResumeLeavesAFreshPacketTests(unittest.TestCase):
    """Reading memory must not dirty the tree.

    The packet embeds HEAD, the clock and the dirty count. `resume` and the
    SessionStart republish rewrote it on every run, so every session started
    with a modified packet, and committing it moved HEAD, so the next read
    rewrote it again.
    """

    def _committed_store(self, tmp: str) -> tuple[Path, Path]:
        root = make_store(tmp, "full")
        (root / "app.py").write_text("x = 1\n", encoding="utf-8")
        seed_record(root)
        git(root, "add", "-A")
        git(root, "commit", "-qm", "store")
        return root, root / crumb.MEMORY_DIRNAME

    @staticmethod
    def _dirty(root: Path) -> list[str]:
        return [ln for ln in git(root, "status", "--porcelain").stdout.splitlines() if ln]

    def _session_start(self, root: Path) -> None:
        saved = sys.stdin
        sys.stdin = io.StringIO(
            json.dumps({"cwd": str(root), "session_id": "s", "hook_event_name": "SessionStart"})
        )
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(crumb.main(["hook", "session"]), 0)
        finally:
            sys.stdin = saved

    def test_resume_on_a_clean_tree_leaves_it_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._committed_store(tmp)
            self.assertEqual(run(["resume", "--project", str(root)])[0], 0)
            self.assertEqual(self._dirty(root), [])
            # HEAD moves by real work: still nothing for a read to rewrite.
            (root / "app.py").write_text("x = 2\n", encoding="utf-8")
            git(root, "commit", "-qam", "work")
            self.assertEqual(run(["resume", "--project", str(root)])[0], 0)
            self.assertEqual(self._dirty(root), [])
            self.assertFalse(crumb.detect_packet_drift(mem), "the kept packet is fresh")
            self.assertFalse(crumb._packet_is_stale(mem, root), "doctor must not chase HEAD")

    def test_session_start_on_a_fresh_clone_leaves_it_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._committed_store(tmp)
            # A fresh clone has no machine-local index/: the pre-filter is
            # unverified, so SessionStart republishes.
            for f in (mem / "index").iterdir():
                if f.name != "README.md":  # committed; the rest is machine-local
                    shutil.rmtree(f) if f.is_dir() else f.unlink()
            self._session_start(root)
            self.assertEqual(self._dirty(root), [])
            self.assertTrue(crumb.guard_prefilter_path(mem).is_file(), "pre-filter rebuilt")
            self.assertIsNotNone(
                bprojections.verified(mem, root, crumb.GUARD_PREFILTER_FILENAME),
                "the generation that kept the packet is still vouched for",
            )
            self.assertIsNotNone(bprojections.verified(mem, root, "resume-packet.md"))

    def test_a_changed_input_still_rewrites_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._committed_store(tmp)
            packet = mem / "generated" / "resume-packet.md"
            before = crumb._stamped_inputs_hash(packet.read_text(encoding="utf-8"))
            (mem / "current.md").write_text(
                (mem / "current.md").read_text(encoding="utf-8") + "\nhand edit\n",
                encoding="utf-8",
            )
            run(["resume", "--project", str(root)])
            after = crumb._stamped_inputs_hash(packet.read_text(encoding="utf-8"))
            self.assertNotEqual(before, after)
            self.assertEqual(after, crumb._inputs_hash(mem, root))

    def test_reindex_forces_the_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._committed_store(tmp)
            packet = mem / "generated" / "resume-packet.md"
            real = _packet.render_packet_markdown
            with mock.patch.object(
                _packet, "render_packet_markdown", lambda p: real(p) + "<!-- newer renderer -->\n"
            ):
                run(["resume", "--project", str(root)])
                self.assertNotIn("newer renderer", packet.read_text(encoding="utf-8"))
                self.assertEqual(run(["reindex", "--project", str(root)])[0], 0)
            self.assertIn("newer renderer", packet.read_text(encoding="utf-8"))

    def test_doctor_still_sees_a_warning_about_the_store(self):
        """Only clock- and HEAD-derived warnings are ignored: a packet published
        while the store kept changing must still read as stale to doctor."""
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._committed_store(tmp)
            packet = mem / "generated" / "resume-packet.md"
            text = packet.read_text(encoding="utf-8")
            unstable = text.replace(
                "## Stale / Risk Warnings\n",
                "## Stale / Risk Warnings\n- " + bsnapshots.UNSTABLE_WARNING + "\n",
            )
            self.assertNotEqual(text, unstable)
            packet.write_text(unstable, encoding="utf-8")
            self.assertTrue(crumb._packet_is_stale(mem, root))

    def test_an_unresolved_merge_is_never_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._committed_store(tmp)
            packet = mem / "generated" / "resume-packet.md"
            text = packet.read_text(encoding="utf-8")
            packet.write_text(
                text + "<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> feat\n", encoding="utf-8"
            )
            run(["resume", "--project", str(root)])
            self.assertNotIn("<<<<<<<", packet.read_text(encoding="utf-8"))

    def test_landed_since_ignores_memory_only_commits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._committed_store(tmp)
            run(["capture", "session", "--project", str(root), "--next", "ship app.py"])
            git(root, "add", "-A")
            git(root, "commit", "-qm", "memory: capture")
            (root / "app.py").write_text("x = 3\n", encoding="utf-8")
            git(root, "commit", "-qam", "real work")
            run(
                [
                    "remember",
                    "decision",
                    "--project",
                    str(root),
                    "--title",
                    "Keep x small",
                    "--set",
                    "Decision",
                    "x stays under ten.",
                    "--evidence",
                    "file",
                    "app.py",
                ]
            )
            git(root, "add", "-A")
            git(root, "commit", "-qm", "memory: decision")
            landed = crumb.build_resume_packet(mem, root)["commits_since_handoff"]
            self.assertEqual([c.split(" ", 1)[1] for c in landed], ["real work"])


# --------------------------------------------------------------------------- #
# The JSON projection obeys the store's commit policy
# --------------------------------------------------------------------------- #
class GeneratedJsonPolicyTests(unittest.TestCase):
    def test_local_only_projections_cover_the_json_index(self):
        block = crumb.gitignore_block("full", False)
        self.assertIn(f"{crumb.MEMORY_DIRNAME}/generated/*.json", block)
        self.assertNotIn(
            f"{crumb.MEMORY_DIRNAME}/generated/*.json", crumb.gitignore_block("full", True)
        )

    def test_prefilter_is_git_ignored_under_either_policy(self):
        # Machine-local since the DoWhat retest of 0.5.0 (item 8, decision D8):
        # it lives in index/, whatever the store's commit policy.
        for policy in ("--no-commit-generated", None):
            with self.subTest(policy), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                git(root, "init", "-q")
                run(
                    [
                        "init",
                        "--project",
                        str(root),
                        "--session-tracking",
                        "full",
                        *([policy] if policy else []),
                        "--no-adapter",
                        "--no-mcp",
                        "--no-hooks",
                    ]
                )
                run(["reindex", "--project", str(root)])
                rel = f"{crumb.MEMORY_DIRNAME}/index/{crumb.GUARD_PREFILTER_FILENAME}"
                self.assertTrue((root / rel).is_file())
                gen = root / crumb.MEMORY_DIRNAME / "generated" / crumb.GUARD_PREFILTER_FILENAME
                self.assertFalse(gen.exists())
                r = subprocess.run(
                    ["git", "check-ignore", rel], cwd=str(root), capture_output=True, text=True
                )
                self.assertEqual(r.returncode, 0, f"{rel} is not machine-local")

    def test_template_readmes_say_where_the_prefilter_is(self):
        tpl = Path(bcli.__file__).parent / "templates" / "project-memory"
        self.assertIn(crumb.GUARD_PREFILTER_FILENAME, (tpl / "index" / "README.md").read_text())


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

    def test_fixture_packet_carries_no_host_path_and_a_live_stamp(self):
        mem = FIXTURE / ".project-memory"
        text = (mem / "generated" / "resume-packet.md").read_text(encoding="utf-8")
        self.assertIn("**shared-service** — `.`", text)
        self.assertNotIn(str(REPO_ROOT), text)
        self.assertEqual(crumb._stamped_inputs_hash(text), crumb._inputs_hash(mem))
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
                self.assertTrue(
                    checks["resume_packet"]["ok"], f"{root.name}: {checks['resume_packet']}"
                )

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
                    (root / ".project-memory" / "generated" / "resume-packet.md").read_text(
                        encoding="utf-8"
                    )
                )
                for root in (a, b)
            ]
            self.assertEqual(packets[0], packets[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
