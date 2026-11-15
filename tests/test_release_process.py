"""Release-process regression tests.

The release workflow had no tests at all, which is how it shipped a pre-flight
that made a partial publish unrecoverable and a publish path that never
ran the suite. The decision logic now lives in
`.github/scripts/release_preflight.py` — a plain stdlib module — so the rules can
be exercised here instead of during a release. The rest of this file pins the
workflow-level guarantees by reading the YAML as text (the suite is stdlib-only;
there is no YAML parser to lean on, and these are presence/ordering claims).

Run with:  python -m unittest discover -s tests
       or:  python tests/test_release_process.py
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

RELEASE_YML = REPO_ROOT / ".github" / "workflows" / "release.yml"
PREFLIGHT_PY = REPO_ROOT / ".github" / "scripts" / "release_preflight.py"
CI_GATE_PY = REPO_ROOT / ".github" / "scripts" / "ci_gate.py"


def _load_script(name: str, path: Path):
    """Import a script by path — `.github/scripts` is not an importable package."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_preflight():
    return _load_script("release_preflight", PREFLIGHT_PY)


preflight = _load_preflight()
ci_gate = _load_script("ci_gate", CI_GATE_PY)


def decide(**kw):
    base = dict(
        version="0.1.8",
        on_pypi=preflight.ON_PYPI_NO,
        latest_on_pypi="0.1.7",
        tag_exists=False,
        mode="publish",
    )
    base.update(kw)
    return preflight.decide(**base)


# --------------------------------------------------------------------------- #
# A partial publish must be recoverable by re-run
# --------------------------------------------------------------------------- #
class PreflightRecoveryTests(unittest.TestCase):
    def test_published_but_untagged_continues(self):
        """The whole point: PyPI accepted the upload, the tag step did not run."""
        d = decide(on_pypi=preflight.ON_PYPI_YES, latest_on_pypi="0.1.8", tag_exists=False)
        self.assertTrue(d.ok, d.reason())
        self.assertIn("recovering an untagged publish", d.reason())

    def test_recovery_warns_that_the_tag_follows_this_run(self):
        d = decide(on_pypi=preflight.ON_PYPI_YES, latest_on_pypi="0.1.8", tag_exists=False)
        self.assertTrue(
            any("main has not advanced" in text for _, text in d.messages),
            d.messages,
        )

    def test_recovery_also_allowed_in_dry_run(self):
        d = decide(
            on_pypi=preflight.ON_PYPI_YES,
            latest_on_pypi="0.1.8",
            tag_exists=False,
            mode="dry-run",
        )
        self.assertTrue(d.ok, d.reason())
        self.assertTrue(
            any("dry-run publishes nothing" in text for _, text in d.messages), d.messages
        )

    def test_published_and_tagged_still_stops(self):
        """A forgotten version bump must still fail fast, before anything is built."""
        d = decide(on_pypi=preflight.ON_PYPI_YES, latest_on_pypi="0.1.8", tag_exists=True)
        self.assertFalse(d.ok)
        self.assertIn("already released", d.reason())

    def test_recovery_is_not_a_way_to_retag_an_old_version(self):
        """0.1.2 is on PyPI and untagged forever; re-running it must not tag today."""
        d = decide(version="0.1.2", on_pypi=preflight.ON_PYPI_YES, latest_on_pypi="0.1.7")
        self.assertFalse(d.ok)
        self.assertIn("version regression", d.reason())

    def test_unknown_latest_blocks_the_recovery_path(self):
        d = decide(on_pypi=preflight.ON_PYPI_YES, latest_on_pypi=None, tag_exists=False)
        self.assertFalse(d.ok)
        self.assertIn("could not be determined", d.reason())

    def test_dead_tag_without_a_publish_stops(self):
        """v0.1.5 / v0.1.6: tagged, never published. Re-using a tag is never right."""
        d = decide(on_pypi=preflight.ON_PYPI_NO, tag_exists=True)
        self.assertFalse(d.ok)
        self.assertIn("dead tag", d.reason())

    def test_a_tag_with_pypi_unreachable_is_not_called_dead(self):
        """It may be a full release; "delete the dead tag" would be wrong (review C2)."""
        d = decide(on_pypi=preflight.ON_PYPI_UNKNOWN, tag_exists=True)
        self.assertFalse(d.ok)
        self.assertNotIn("dead tag", d.reason())
        self.assertIn("could not be reached", d.reason())

    def test_a_fresh_version_below_the_newest_release_stops(self):
        """Not on PyPI, tag free, but lower than what is published (review C2)."""
        d = decide(version="0.6.1", on_pypi=preflight.ON_PYPI_NO, latest_on_pypi="0.6.2")
        self.assertFalse(d.ok)
        self.assertIn("version regression", d.reason())
        for newer in ("0.7.0", "0.6.10", "1.0"):
            with self.subTest(version=newer):
                d = decide(version=newer, on_pypi=preflight.ON_PYPI_NO, latest_on_pypi="0.6.2")
                self.assertTrue(d.ok, d.reason())
        d = decide(version="0.7.0rc1", on_pypi=preflight.ON_PYPI_NO, latest_on_pypi="0.6.2")
        self.assertTrue(d.ok, d.reason())  # not a plain release: not compared

    def test_clean_version_proceeds(self):
        d = decide()
        self.assertTrue(d.ok, d.reason())
        self.assertIn("good to publish", d.reason())

    def test_unreachable_pypi_warns_but_proceeds(self):
        d = decide(on_pypi=preflight.ON_PYPI_UNKNOWN)
        self.assertTrue(d.ok, d.reason())
        self.assertTrue(any(level == preflight.WARNING for level, _ in d.messages), d.messages)

    def _run_cli(self, *, tag_exists: str) -> tuple[int, str]:
        """Run the pre-flight CLI, capturing what it prints.

        The capture is not incidental. `main()` prints GitHub Actions
        annotations — `::error::…` — and this suite runs *inside* the release
        workflow's build job, where the runner reads stdout for exactly those
        commands. Left uncaptured, this test stamped a red
        "crumb-kit 0.1.8 is already released" annotation onto every release run,
        including the one where the pre-flight had in fact passed. That is a
        false failure report on the one job whose annotations an operator reads
        first when a release breaks.
        """
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = preflight.main(
                [
                    "--version",
                    "0.1.8",
                    "--on-pypi",
                    "yes",
                    "--latest-on-pypi",
                    "0.1.8",
                    "--tag-exists",
                    tag_exists,
                    "--mode",
                    "publish",
                ]
            )
        return code, buf.getvalue()

    def test_cli_exit_codes_match_the_decision(self):
        ok, _ = self._run_cli(tag_exists="false")
        blocked, _ = self._run_cli(tag_exists="true")
        self.assertEqual((ok, blocked), (0, 1))

    def test_cli_emits_the_decision_as_an_annotation(self):
        _, recovered = self._run_cli(tag_exists="false")
        self.assertIn("::warning::recovering an untagged publish", recovered)
        _, stopped = self._run_cli(tag_exists="true")
        self.assertIn("::error::crumb-kit 0.1.8 is already released", stopped)

    def test_the_cli_helper_leaks_nothing_to_the_real_stdout(self):
        """An annotation printed by a test is indistinguishable from a real one."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self._run_cli(tag_exists="true")
        self.assertEqual(buf.getvalue(), "")

    def test_no_test_calls_the_pre_flight_cli_uncaptured(self):
        """The next test to add must go through `_run_cli`, not `preflight.main`.

        Read from source, because the leak is invisible at runtime: a stray
        direct call passes every assertion and only shows up as a red annotation
        on a release run, days later.
        """
        needle = "preflight" + ".main("  # split so this line is not its own match
        lines = Path(__file__).read_text(encoding="utf-8").splitlines()
        hits = [i for i, ln in enumerate(lines) if needle in ln]
        start = next(i for i, ln in enumerate(lines) if ln.lstrip().startswith("def _run_cli"))
        end = next(i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("def "))
        self.assertEqual(len(hits), 1, f"pre-flight CLI called {len(hits)} times, expected 1")
        self.assertTrue(
            start < hits[0] < end,
            f"line {hits[0] + 1} calls the pre-flight CLI outside the capturing helper",
        )


# --------------------------------------------------------------------------- #
# Publish runs the suite and gates on CI
# --------------------------------------------------------------------------- #
class ReleaseWorkflowChecksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.yml = RELEASE_YML.read_text(encoding="utf-8")

    def test_build_job_runs_the_test_suite(self):
        self.assertTrue(
            "python -m unittest discover -s tests" in self.yml,
            "release.yml never runs the suite",
        )

    def test_suite_runs_in_dry_run_too(self):
        """The suite step must not be conditioned on mode — dry-run must run it."""
        lines = self.yml.splitlines()
        idx = next(i for i, ln in enumerate(lines) if "unittest discover" in ln)
        # walk back to the step's `- name:` and check no `if:` guard in between
        step = []
        for ln in reversed(lines[:idx]):
            step.append(ln)
            if ln.lstrip().startswith("- name:"):
                break
        self.assertFalse(
            any(ln.lstrip().startswith("if:") for ln in step),
            f"the test-suite step is conditional: {step}",
        )

    def test_suite_runs_before_anything_is_published(self):
        self.assertLess(
            self.yml.index("unittest discover"),
            self.yml.index("gh-action-pypi-publish"),
        )

    def test_publish_gates_on_the_ci_workflow_conclusion(self):
        self.assertTrue(
            "actions/workflows/ci.yml/runs?head_sha=" in self.yml, "no CI-conclusion gate"
        )
        self.assertIn("python .github/scripts/ci_gate.py", self.yml)
        step = self.yml.split("- name: CI succeeded on this commit", 1)[1].split("- name:", 1)[0]
        # Fails closed: no `|| true` or `exit 0` way past an unreadable answer.
        self.assertNotIn("|| true", step)
        self.assertNotIn("exit 0", step)
        self.assertIn("exit 1", step)
        self.assertLess(
            self.yml.index("- name: CI succeeded on this commit"),
            self.yml.index("gh-action-pypi-publish"),
        )

    def test_ci_gate_can_read_workflow_runs(self):
        self.assertTrue("actions: read" in self.yml, "the CI gate has no permission to read runs")


SHA = "4606001ad02f6a22cf7bfc1e775cc6d0edad2333"


def _run(event: str, created: str, conclusion: str | None = "success", status="completed"):
    return {
        "id": hash((event, created)) & 0xFFFF,
        "event": event,
        "status": status,
        "conclusion": conclusion,
        "head_sha": SHA,
        "created_at": created,
        "html_url": f"https://example.invalid/{event}/{created}",
    }


def gate(*runs, payload: str | None = None):
    if payload is None:
        payload = json.dumps({"total_count": len(runs), "workflow_runs": list(runs)})
    return ci_gate.decide(payload, SHA)


class CiGateTests(unittest.TestCase):
    """The publish gate on `ci` (review 2026-11-13, §1.1 and §3.4 C1).

    It read only the newest run of any kind and, when the API call failed or
    found no run, published anyway with a warning.
    """

    def test_a_green_push_run_passes(self):
        self.assertTrue(gate(_run("push", "2026-10-14T00:07:59Z")).ok)

    def test_a_red_push_run_blocks(self):
        d = gate(_run("push", "2026-10-14T00:07:59Z", "failure"))
        self.assertFalse(d.ok)
        self.assertIn("CI concluded 'failure'", d.text())

    def test_a_running_push_run_blocks(self):
        d = gate(_run("push", "2026-10-14T00:07:59Z", None, status="in_progress"))
        self.assertFalse(d.ok)
        self.assertIn("still in_progress", d.text())

    def test_later_red_scheduled_runs_warn_but_do_not_block(self):
        """`main` at 4606001 in November 2026: the push run was green, then the
        runner image lost Python 3.9 and the weekly runs went red."""
        d = gate(
            _run("schedule", "2026-11-09T16:17:18Z", "failure"),
            _run("schedule", "2026-11-02T15:50:07Z", "failure"),
            _run("schedule", "2026-10-26T13:01:16Z"),
            _run("push", "2026-10-14T00:07:59Z"),
        )
        self.assertTrue(d.ok, d.text())
        self.assertIn("warning", [level for level, _t in d.messages])

    def test_a_green_scheduled_run_does_not_rescue_a_red_push(self):
        d = gate(
            _run("schedule", "2026-11-09T16:17:18Z"),
            _run("push", "2026-10-14T00:07:59Z", "failure"),
        )
        self.assertFalse(d.ok)

    def test_a_manual_rerun_decides_over_an_older_push(self):
        d = gate(
            _run("workflow_dispatch", "2026-11-10T09:00:00Z"),
            _run("push", "2026-10-14T00:07:59Z", "failure"),
        )
        self.assertTrue(d.ok, d.text())

    def test_no_run_that_tested_the_commit_blocks(self):
        self.assertFalse(gate().ok)
        d = gate(_run("schedule", "2026-11-09T16:17:18Z"))
        self.assertFalse(d.ok)
        self.assertIn("Run workflow", d.text())

    def test_an_unreadable_answer_blocks(self):
        for payload in ("", "not json", "{}", '{"workflow_runs": null}', "[]"):
            with self.subTest(payload=payload):
                self.assertFalse(gate(payload=payload).ok)

    def test_a_run_for_another_commit_is_ignored(self):
        other = dict(_run("push", "2026-11-12T00:00:00Z"), head_sha="0" * 40)
        self.assertFalse(gate(other).ok)

    def test_cli_exit_codes_and_annotations(self):
        ok_payload = json.dumps({"workflow_runs": [_run("push", "2026-10-14T00:07:59Z")]})
        for stdin, code, level in ((ok_payload, 0, "::notice::"), ("", 1, "::error::")):
            out = io.StringIO()
            with (
                mock.patch.object(sys, "stdin", io.StringIO(stdin)),
                contextlib.redirect_stdout(out),
            ):
                self.assertEqual(ci_gate.main(["--sha", SHA]), code)
            self.assertIn(level, out.getvalue())


class PreflightWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.yml = RELEASE_YML.read_text(encoding="utf-8")

    def test_workflow_calls_the_tested_preflight(self):
        self.assertTrue(
            "python .github/scripts/release_preflight.py" in self.yml,
            "release.yml does not call the tested pre-flight",
        )

    def test_workflow_passes_every_input_the_script_requires(self):
        for flag in ("--version", "--on-pypi", "--latest-on-pypi", "--tag-exists", "--mode"):
            self.assertTrue(flag in self.yml, f"pre-flight input {flag} not passed")

    def test_the_old_unconditional_pypi_failure_is_gone(self):
        """The exact line that made a partial publish unrecoverable."""
        self.assertFalse(
            "is already on PyPI (a PyPI version is permanent)" in self.yml,
            "the unconditional 'already on PyPI' failure is still there",
        )

    def test_preflight_is_bundled_nowhere_near_the_package(self):
        """Release tooling must not leak into the wheel."""
        self.assertFalse((REPO_ROOT / "breadcrumbs" / "release_preflight.py").exists())


# --------------------------------------------------------------------------- #
# A transient network failure must not cost a release run
# --------------------------------------------------------------------------- #
class PublishRetryTests(unittest.TestCase):
    """The 0.1.8 publish failed on a 5-second connect timeout to upload.pypi.org.

    The action's Trusted-Publishing token exchange
    (`GET upload.pypi.org/_/oidc/audience`) is its first network call, has a hard
    5-second connect timeout and no internal retry, so a blip on that one request
    sank the run before anything was uploaded. Nothing in the release was wrong;
    the build, the pre-flight and every gate had passed.
    """

    @classmethod
    def setUpClass(cls):
        cls.yml = RELEASE_YML.read_text(encoding="utf-8")

    def _publish_job(self) -> str:
        return self.yml.split("\n  publish-pypi:", 1)[1].split("\n  release-tag:", 1)[0]

    def _tag_job(self) -> str:
        return self.yml.split("\n  release-tag:", 1)[1]

    def _upload_steps(self) -> list[str]:
        """The publish job's steps that invoke the PyPI action, as text blocks."""
        steps, current = [], None
        for ln in self._publish_job().splitlines():
            if ln.startswith("      - "):  # a step begins
                if current is not None:
                    steps.append("\n".join(current))
                current = [ln]
            elif current is not None:
                current.append(ln)
        if current is not None:
            steps.append("\n".join(current))
        return [s for s in steps if "uses: pypa/gh-action-pypi-publish@" in s]

    def test_the_upload_is_attempted_twice(self):
        self.assertEqual(
            len(self._upload_steps()),
            2,
            "the PyPI upload has no retry — one network blip loses the run",
        )

    def test_the_first_attempt_does_not_fail_the_job(self):
        """Without this the retry never runs: a failed step ends the job."""
        self.assertIn("continue-on-error: true", self._upload_steps()[0])

    def test_the_retry_is_conditional_on_the_first_attempt_failing(self):
        """A second unconditional upload would run on every green publish."""
        self.assertIn("if: steps.publish.outcome == 'failure'", self._upload_steps()[1])

    def test_the_retry_itself_can_still_fail_the_job(self):
        """Two failures must leave no tag, so only the first attempt may be soft."""
        self.assertNotIn("continue-on-error:", self._upload_steps()[1])
        soft = [
            ln.strip()
            for ln in self._publish_job().splitlines()
            if ln.strip().startswith("continue-on-error:")  # not the prose in the comments
        ]
        self.assertEqual(
            len(soft),
            1,
            f"more than one step in the publish job swallows its own failure: {soft}",
        )

    def test_every_attempt_uses_skip_existing(self):
        """What makes a retry safe: a re-upload of an accepted file is a no-op."""
        for i, step in enumerate(self._upload_steps()):
            with self.subTest(attempt=i + 1):
                self.assertIn("skip-existing: true", step)

    def test_the_tag_step_still_runs_only_after_a_successful_upload(self):
        """`continue-on-error` on attempt 1 must not let the tag outlive a failure:
        the tag is a job that needs the publish job, which fails when both
        attempts do."""
        self.assertNotIn("gh release create", self._publish_job())
        tag = self._tag_job()
        self.assertIn("gh release create", tag)
        self.assertRegex(tag, r"needs: \[[^\]]*publish-pypi")

    def test_only_the_tag_job_can_write_the_repo(self):
        """The OIDC job held `contents: write` too (review 2026-11-13, C7)."""
        self.assertNotIn("contents: write", self._publish_job())
        self.assertIn("contents: read", self._publish_job())
        self.assertIn("contents: write", self._tag_job())
        self.assertNotIn("id-token", self._tag_job())

    def test_the_retry_clears_attempt_ones_attestations(self):
        """The action refuses a dist/ that already holds them (review C5)."""
        job = self._publish_job()
        clear = job.index("rm -f dist/*.publish.attestation")
        self.assertLess(clear, job.rindex("uses: pypa/gh-action-pypi-publish@"))
        self.assertGreater(clear, job.index("uses: pypa/gh-action-pypi-publish@"))

    def test_no_expression_is_spliced_into_a_shell_script(self):
        """`${{ }}` inside `run:` is code injection waiting for a value (C7)."""
        in_run, indent = False, 0
        for ln in self.yml.splitlines():
            stripped, depth = ln.strip(), len(ln) - len(ln.lstrip())
            if in_run and stripped and depth <= indent:
                in_run = False
            if stripped.startswith("run:"):
                in_run, indent = True, depth
            if in_run:
                self.assertNotIn("${{", ln, stripped)

    def test_the_release_build_tools_are_pinned(self):
        job = self.yml.split("\n  publish-pypi:", 1)[0]
        self.assertIn('"build==', job)
        self.assertIn('"twine==', job)


# --------------------------------------------------------------------------- #
# The tag/PyPI history is documented, since the invariant is violated
# --------------------------------------------------------------------------- #
class TagHistoryDocumentedTests(unittest.TestCase):
    """`tags == published releases` is false for this repo; say so where it bites."""

    @classmethod
    def setUpClass(cls):
        cls.releasing = (REPO_ROOT / "RELEASING.md").read_text(encoding="utf-8")
        cls.changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    def test_dead_tags_are_documented(self):
        self.assertTrue(
            "Tag / PyPI history" in self.releasing, "RELEASING.md has no tag/PyPI history"
        )
        for version in ("v0.1.5", "v0.1.6"):
            self.assertTrue(
                version in self.releasing, f"{version} (tagged, never published) undocumented"
            )

    def test_the_untagged_pypi_version_is_documented(self):
        self.assertTrue("0.1.2" in self.releasing, "0.1.2 (on PyPI, untagged) undocumented")
        self.assertTrue("0.1.2" in self.changelog, "0.1.2 gap missing from CHANGELOG")

    def test_recovery_doc_no_longer_claims_nothing_to_clean_up(self):
        """RELEASING.md:78-81 described a recovery that did not work."""
        self.assertFalse(
            "nothing to clean up — no tag or release was\n  created" in self.releasing,
            "RELEASING.md still describes the old (wrong) partial-publish recovery",
        )

    def test_path_b_names_the_pypi_project_and_its_missing_guardrails(self):
        """Path B said to scope the token to `breadcrumbs`; the project is `crumb-kit`."""
        path_b = self.releasing.split("## Path B")[1]
        self.assertIn("crumb-kit", path_b)
        self.assertNotIn("scope it to the\n   `breadcrumbs` project", path_b)
        self.assertIn("bypasses every guardrail", path_b)


# --------------------------------------------------------------------------- #
# Workflow hygiene — both workflows, read as text
# --------------------------------------------------------------------------- #
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"


class WorkflowHygieneTests(unittest.TestCase):
    """Every workflow-level guarantee the last review round found missing.

    Read as text, like the rest of this file: the suite is stdlib-only, and these
    are presence claims about YAML that a parser would not make clearer.
    """

    @classmethod
    def setUpClass(cls):
        cls.files = {
            "ci.yml": CI_YML.read_text(encoding="utf-8"),
            "release.yml": RELEASE_YML.read_text(encoding="utf-8"),
        }

    def _top_level_block(self, text: str, key: str) -> str | None:
        """The `key:` block at column 0, if present (a job-level one is indented)."""
        lines = text.splitlines()
        for i, ln in enumerate(lines):
            if ln == f"{key}:":
                out = []
                for nxt in lines[i + 1 :]:
                    if nxt and not nxt.startswith((" ", "\t")):
                        break
                    out.append(nxt)
                return "\n".join(out)
        return None

    def test_both_workflows_set_top_level_permissions(self):
        """Without one, a job with no `permissions:` gets the repo-default scope."""
        for name, text in self.files.items():
            with self.subTest(workflow=name):
                block = self._top_level_block(text, "permissions")
                self.assertIsNotNone(block, f"{name} has no top-level permissions block")
                self.assertIn("contents: read", block)

    def test_ci_groups_a_prs_push_and_pull_request_runs_together(self):
        """`github.ref` differs between the two events (review 2026-11-13, C4)."""
        block = self._top_level_block(self.files["ci.yml"], "concurrency")
        group = next(ln for ln in block.splitlines() if "group:" in ln)
        self.assertNotIn("github.ref }}", group)
        self.assertIn("github.head_ref || github.ref_name", group)

    def test_both_workflows_declare_a_concurrency_group(self):
        """ci ran twice per PR (push + pull_request); two publishes could race."""
        for name, text in self.files.items():
            with self.subTest(workflow=name):
                block = self._top_level_block(text, "concurrency")
                self.assertIsNotNone(block, f"{name} has no concurrency group")
                self.assertIn("group:", block)

    def test_release_never_cancels_a_run_in_progress(self):
        """Cancelling mid-publish is how a version lands on PyPI with no tag."""
        block = self._top_level_block(self.files["release.yml"], "concurrency")
        self.assertIn("cancel-in-progress: false", block)

    def test_every_action_is_pinned_to_a_commit_sha(self):
        """`@release/v1` is a moving *branch* on the OIDC-publishing path."""
        import re

        pattern = re.compile(r"uses:\s*([^\s@]+)@(\S+)")
        seen = 0
        for name, text in self.files.items():
            for repo, ref in pattern.findall(text):
                seen += 1
                with self.subTest(workflow=name, action=repo):
                    self.assertRegex(
                        ref,
                        r"^[0-9a-f]{40}$",
                        f"{repo} is pinned to {ref!r}, a mutable ref",
                    )
        self.assertGreater(seen, 0, "no `uses:` steps found — did the parse break?")

    def test_each_pin_records_the_human_readable_version(self):
        """A bare SHA is unreviewable; the trailing comment says what it is."""
        for name, text in self.files.items():
            for ln in text.splitlines():
                if "uses:" in ln and "@" in ln and "docker://" not in ln:
                    with self.subTest(workflow=name, line=ln.strip()):
                        self.assertIn("#", ln.split("@", 1)[1])

    def test_test_matrix_is_exactly_the_supported_range(self):
        """3.10 was exercised only by the `mcp` job; 3.13/3.14 not at all.

        The supported list is the pyproject classifiers, and its floor is
        `requires-python`; the `test` matrix runs exactly that list, so
        dropping or adding a Python is one decision made in one place.
        """
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        supported = re.findall(r'"Programming Language :: Python :: (3\.\d+)"', pyproject)
        floor = re.search(r'requires-python = ">=(3\.\d+)"', pyproject).group(1)
        self.assertTrue(supported, "no per-version classifiers in pyproject.toml")
        self.assertEqual(
            min(supported, key=lambda v: int(v.split(".")[1])), floor, "floor != classifiers"
        )
        text = self.files["ci.yml"]
        matrix = text.split("python-version:", 1)[1].splitlines()[0]
        self.assertEqual(re.findall(r'"(3\.\d+)"', matrix), supported)
        # The native jobs run the floor on Windows and macOS.
        for job in ("\n  native:", "\n  native-full:"):
            body = text.split(job, 1)[1]
            native = body.split("python-version:", 1)[1].splitlines()[0]
            with self.subTest(job=job.strip()):
                self.assertIn(f'"{floor}"', native)

    def test_mcp_job_covers_every_python_the_extra_installs_on(self):
        """The `mcp` job stopped at 3.12 while `test` already ran to 3.14.

        The `[mcp]` extra is marked `python_version >= '3.10'` with no ceiling and
        both SDK majors declare 3.13/3.14 support, so those two legs installed the
        extra in the wild and nothing exercised it — the mirror image of the gap
        already closed for the `test` job.
        """
        text = self.files["ci.yml"]
        # Scope to the `mcp` job, then take its matrix line — the file has several
        # other `python-version:` keys (each job's setup-python step).
        mcp_job = text.split("\n  mcp:", 1)[1].split("\n  package:", 1)[0]
        matrix = next(
            ln for ln in mcp_job.splitlines() if "python-version:" in ln and "matrix" not in ln
        )
        for version in ("3.10", "3.11", "3.12", "3.13", "3.14"):
            with self.subTest(version=version):
                self.assertIn(f'"{version}"', matrix)

    def test_mcp_job_runs_both_sdk_majors(self):
        """A rename in a future major must not pass unnoticed the way 2.0's did."""
        text = self.files["ci.yml"]
        matrix = text.split("mcp-version:", 1)[1].splitlines()[0]
        self.assertIn('"<2"', matrix)
        self.assertIn('">=2,<3"', matrix)

    def test_mcp_job_asserts_the_advertised_resource_count(self):
        """It pinned 10 tools and 6 prompts but never the 8 resources."""
        text = self.files["ci.yml"]
        self.assertIn("list_resources()", text)
        self.assertIn("list_resource_templates()", text)
        from breadcrumbs import mcp_core

        declared = len(mcp_core.STATIC_RESOURCES) + len(mcp_core.TEMPLATE_RESOURCES)
        self.assertIn(f"len(static) + len(templates) == {declared}", text)

    def test_mcp_job_pins_the_registered_tool_count(self):
        """The mcp job's counts are literals, and only that job has the SDK to
        check them, so they went stale unnoticed: WM-03 and WM-21 took the server
        to 13 tools and 14 resources while ci.yml still said 10 and 8, and every
        mcp leg failed. Count the registrations in the source here, where the
        stdlib-only suite runs, so the next new tool fails locally instead."""
        text = self.files["ci.yml"]
        source = (REPO_ROOT / "breadcrumbs" / "mcp_server.py").read_text(encoding="utf-8")
        # Tools register through `read_tool` / `write_tool` (audit WP14: a
        # read-only store's server omits the writers; WP17: both attach the
        # contract's annotations). The CI store is writable, so all count.
        registered = source.count("@read_tool()") + source.count("@write_tool()")
        self.assertGreater(registered, 0)
        self.assertIn(f"assert len(tools) == {registered},", text)

    def test_ci_has_a_lint_job(self):
        text = self.files["ci.yml"]
        self.assertIn("ruff check", text)
        self.assertIn("ruff format --check", text)

    def test_ruff_is_pinned_and_ci_matches_the_dev_extra(self):
        """An unpinned formatter turned `lint` red on an untouched `main`.

        ruff 0.16 began formatting fenced Python inside Markdown; the checked file
        set went from 29 to 234 and prose files that had never been formatter
        input became one. `publish` gates on `ci`, so a floating linter can
        block a release. Both pins must exist and agree — two copies of a version
        is exactly the drift this repo removed for its own version and its
        actions.
        """
        import re

        ci = self.files["ci.yml"]
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        ci_pin = re.search(r'ruff==([0-9][0-9.]*)"', ci)
        extra_pin = re.search(r'"ruff==([0-9][0-9.]*)"', pyproject)
        self.assertIsNotNone(ci_pin, "the `lint` job installs ruff unpinned")
        self.assertIsNotNone(extra_pin, "the `dev` extra declares ruff unpinned")
        self.assertEqual(
            ci_pin.group(1),
            extra_pin.group(1),
            "CI and the `dev` extra pin different ruff versions — bump them together",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
