"""Release-process regression tests (MF-11 … MF-13).

The release workflow had no tests at all, which is how it shipped a pre-flight
that made a partial publish unrecoverable (MF-11) and a publish path that never
ran the suite (MF-12). The decision logic now lives in
`.github/scripts/release_preflight.py` — a plain stdlib module — so the rules can
be exercised here instead of during a release. The rest of this file pins the
workflow-level guarantees by reading the YAML as text (the suite is stdlib-only;
there is no YAML parser to lean on, and these are presence/ordering claims).

Run with:  python -m unittest discover -s tests
       or:  python tests/test_release_process.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

RELEASE_YML = REPO_ROOT / ".github" / "workflows" / "release.yml"
PREFLIGHT_PY = REPO_ROOT / ".github" / "scripts" / "release_preflight.py"


def _load_preflight():
    """Import the script by path — `.github/scripts` is not an importable package."""
    spec = importlib.util.spec_from_file_location("release_preflight", PREFLIGHT_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preflight = _load_preflight()


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
# MF-11 — a partial publish must be recoverable by re-run
# --------------------------------------------------------------------------- #
class PreflightRecoveryTests(unittest.TestCase):
    def test_MF11_published_but_untagged_continues(self):
        """The whole point: PyPI accepted the upload, the tag step did not run."""
        d = decide(on_pypi=preflight.ON_PYPI_YES, latest_on_pypi="0.1.8", tag_exists=False)
        self.assertTrue(d.ok, d.reason())
        self.assertIn("recovering an untagged publish", d.reason())

    def test_MF11_recovery_warns_that_the_tag_follows_this_run(self):
        d = decide(on_pypi=preflight.ON_PYPI_YES, latest_on_pypi="0.1.8", tag_exists=False)
        self.assertTrue(
            any("main has not advanced" in text for _, text in d.messages),
            d.messages,
        )

    def test_MF11_recovery_also_allowed_in_dry_run(self):
        d = decide(
            on_pypi=preflight.ON_PYPI_YES, latest_on_pypi="0.1.8",
            tag_exists=False, mode="dry-run",
        )
        self.assertTrue(d.ok, d.reason())
        self.assertTrue(
            any("dry-run publishes nothing" in text for _, text in d.messages), d.messages
        )

    def test_MF11_published_and_tagged_still_stops(self):
        """A forgotten version bump must still fail fast, before anything is built."""
        d = decide(on_pypi=preflight.ON_PYPI_YES, latest_on_pypi="0.1.8", tag_exists=True)
        self.assertFalse(d.ok)
        self.assertIn("already released", d.reason())

    def test_MF11_recovery_is_not_a_way_to_retag_an_old_version(self):
        """0.1.2 is on PyPI and untagged forever; re-running it must not tag today."""
        d = decide(version="0.1.2", on_pypi=preflight.ON_PYPI_YES, latest_on_pypi="0.1.7")
        self.assertFalse(d.ok)
        self.assertIn("version regression", d.reason())

    def test_MF11_unknown_latest_blocks_the_recovery_path(self):
        d = decide(on_pypi=preflight.ON_PYPI_YES, latest_on_pypi=None, tag_exists=False)
        self.assertFalse(d.ok)
        self.assertIn("could not be determined", d.reason())

    def test_MF11_dead_tag_without_a_publish_stops(self):
        """v0.1.5 / v0.1.6: tagged, never published. Re-using a tag is never right."""
        d = decide(on_pypi=preflight.ON_PYPI_NO, tag_exists=True)
        self.assertFalse(d.ok)
        self.assertIn("dead tag", d.reason())

    def test_MF11_clean_version_proceeds(self):
        d = decide()
        self.assertTrue(d.ok, d.reason())
        self.assertIn("good to publish", d.reason())

    def test_MF11_unreachable_pypi_warns_but_proceeds(self):
        d = decide(on_pypi=preflight.ON_PYPI_UNKNOWN)
        self.assertTrue(d.ok, d.reason())
        self.assertTrue(
            any(level == preflight.WARNING for level, _ in d.messages), d.messages
        )

    def test_MF11_cli_exit_codes_match_the_decision(self):
        ok = preflight.main([
            "--version", "0.1.8", "--on-pypi", "yes", "--latest-on-pypi", "0.1.8",
            "--tag-exists", "false", "--mode", "publish",
        ])
        blocked = preflight.main([
            "--version", "0.1.8", "--on-pypi", "yes", "--latest-on-pypi", "0.1.8",
            "--tag-exists", "true", "--mode", "publish",
        ])
        self.assertEqual((ok, blocked), (0, 1))


# --------------------------------------------------------------------------- #
# MF-12 — publish runs the suite and gates on CI
# --------------------------------------------------------------------------- #
class ReleaseWorkflowChecksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.yml = RELEASE_YML.read_text(encoding="utf-8")

    def test_MF12_build_job_runs_the_test_suite(self):
        self.assertTrue(
            "python -m unittest discover -s tests" in self.yml,
            "release.yml never runs the suite",
        )

    def test_MF12_suite_runs_in_dry_run_too(self):
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

    def test_MF12_suite_runs_before_anything_is_published(self):
        self.assertLess(
            self.yml.index("unittest discover"),
            self.yml.index("gh-action-pypi-publish"),
        )

    def test_MF12_publish_gates_on_the_ci_workflow_conclusion(self):
        self.assertTrue(
            "actions/workflows/ci.yml/runs?head_sha=" in self.yml, "no CI-conclusion gate"
        )
        self.assertTrue("CI concluded" in self.yml, "the CI gate never fails on a red run")

    def test_MF12_ci_gate_can_read_workflow_runs(self):
        self.assertTrue("actions: read" in self.yml, "the CI gate has no permission to read runs")


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
# MF-13 — the tag/PyPI history is documented, since the invariant is violated
# --------------------------------------------------------------------------- #
class TagHistoryDocumentedTests(unittest.TestCase):
    """`tags == published releases` is false for this repo; say so where it bites."""

    @classmethod
    def setUpClass(cls):
        cls.releasing = (REPO_ROOT / "RELEASING.md").read_text(encoding="utf-8")
        cls.changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    def test_MF13_dead_tags_are_documented(self):
        self.assertTrue(
            "Tag / PyPI history" in self.releasing, "RELEASING.md has no tag/PyPI history"
        )
        for version in ("v0.1.5", "v0.1.6"):
            self.assertTrue(
                version in self.releasing, f"{version} (tagged, never published) undocumented"
            )

    def test_MF13_the_untagged_pypi_version_is_documented(self):
        self.assertTrue("0.1.2" in self.releasing, "0.1.2 (on PyPI, untagged) undocumented")
        self.assertTrue("0.1.2" in self.changelog, "0.1.2 gap missing from CHANGELOG")

    def test_MF13_recovery_doc_no_longer_claims_nothing_to_clean_up(self):
        """RELEASING.md:78-81 described a recovery that did not work."""
        self.assertFalse(
            "nothing to clean up — no tag or release was\n  created" in self.releasing,
            "RELEASING.md still describes the old (wrong) partial-publish recovery",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
