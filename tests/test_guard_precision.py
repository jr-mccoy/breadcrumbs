"""Tests for guard precision: path extraction (G1) and read-only actions (G2).

G1 — the prefilter of a 310-session field store held 439 "paths", of which 89
existed. `same file(s)` is guard's strongest relevance signal, so a script that
read a JSON file drew a PAUSE from a screenshot-testing trap on the strength of
`json.load`. G2 — `git status`, read-only, was the loudest command measured,
while `npm test`, which executes arbitrary code, was silent.

Run with:  python -m unittest discover -s tests
       or:  python tests/test_guard_precision.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from breadcrumbs import cli as _cli  # noqa: E402

# Every one of these was harvested as a "path" by the lexical extractor, in a
# real store, at review time.
PROSE_NOT_PATHS = [
    "json.load",
    "io.open",
    "f.get",
    "Dispatchers.IO",
    "tests.test",
    "0.47",
    "8.13.2",
    "0.1.10",
    "10.dp",
    "AM/PM",
    "0xDD/255",
    "362/LF",
    "10/15",
    "v0.1.5/v0.1.6",
    "--title/--set",
    "--area/--symptom/--why",
]

REAL_PATHS = [
    "breadcrumbs/cli.py",
    "cli.py",
    "ci.yml",
    ".github/workflows/release.yml",
    "src/auth/middleware.ts",
    "app/src/main/java/Foo.java",
    "docs/architecture.md",
    "package.json",
    "src/v2/api.ts",
    "app/2023/report.md",
    "./gradlew",
]


class PathTokenTests(unittest.TestCase):
    def test_prose_is_not_mistaken_for_paths(self):
        wrong = [t for t in PROSE_NOT_PATHS if _cli._is_path_token(t)]
        self.assertEqual(wrong, [], f"still harvested as paths: {wrong}")

    def test_real_paths_are_still_recognized(self):
        missed = [t for t in REAL_PATHS if not _cli._is_path_token(t)]
        self.assertEqual(missed, [], f"no longer recognized: {missed}")

    def test_extraction_from_a_sentence(self):
        text = (
            "We call json.load on the file, bump to 8.13.2, and the fix lands in "
            "breadcrumbs/cli.py — see also docs/architecture.md (AM/PM handling)."
        )
        self.assertEqual(
            _cli._paths_from_text(text), {"breadcrumbs/cli.py", "docs/architecture.md"}
        )

    def test_a_flag_list_is_never_a_path(self):
        self.assertEqual(_cli._paths_from_text("pass --area/--symptom/--why"), set())


class DeclaredVsMentionedTests(unittest.TestCase):
    """A path the author declared and one the extractor found are not the same claim."""

    def _record(self, body: str, evidence: list[dict] | None = None) -> _cli.Record:
        meta = {
            "id": "dec_20260101_x",
            "title": "a decision",
            "status": "active",
            "tags": [],
            "evidence": evidence or [],
        }
        return _cli.Record(Path("decisions/2026-01-01-x.md"), "decision", meta, body)

    def test_evidence_file_refs_are_declared(self):
        item = _cli._item_from_record(
            self._record("body text", evidence=[{"type": "file", "ref": "src/billing.py"}])
        )
        self.assertIn("src/billing.py", item["files"])
        self.assertNotIn("src/billing.py", item["mentioned_files"])

    def test_prose_paths_are_mentions_not_declarations(self):
        item = _cli._item_from_record(self._record("we touched src/billing.py once"))
        self.assertEqual(item["files"], set())
        self.assertIn("src/billing.py", item["mentioned_files"])

    def test_a_trap_declares_its_files_in_its_area_bullet(self):
        trap = {
            "id": "trap_x",
            "heading": "trap_x: a trap",
            "content": (
                "- Area / files: app/src/Foo.kt\n"
                "- Symptom: it breaks when tools/report.py runs\n"
                "- Safe approach: use ./gradlew test\n"
            ),
            "status": "active",
        }
        item = _cli._item_from_trap(trap)
        self.assertIn("app/src/Foo.kt", item["files"])
        self.assertIn("tools/report.py", item["mentioned_files"])
        self.assertNotIn("app/src/Foo.kt", item["mentioned_files"])
        # The remedy bullet is still excluded from the file signal entirely.
        self.assertNotIn("./gradlew", item["files"] | item["mentioned_files"])

    def test_a_mention_reads_differently_from_a_declaration(self):
        declared = _cli._match_reason("trap", ["file"], ["a/b.py"], [], 0)
        mentioned = _cli._match_reason("trap", ["mention"], [], [], 0, ["a/b.py"])
        self.assertIn("same file(s)", declared)
        self.assertNotIn("same file(s)", mentioned)
        self.assertIn("mentions", mentioned)

    def test_a_mention_alone_cannot_floor_a_verdict(self):
        """Specificity — what lets a match raise the verdict — stays declared-only."""
        mention_only = [
            {
                "id": "trap_x",
                "kind": "trap",
                "signals": ["mention", "keyword"],
                "score": 4.0,
                "stance": "advisory",
            }
        ]
        self.assertEqual(
            _cli._decide_verdict(mention_only, ["routine_edit"], "edit a/b.py"), "PROCEED"
        )


class ReadOnlyActionTests(unittest.TestCase):
    def test_reporting_commands_are_read_only(self):
        for action in ("git status", "git log --oneline", "cat README.md", "ls -la", "grep -r x ."):
            self.assertTrue(_cli._is_read_only_action(action), action)

    def test_anything_that_acts_is_not(self):
        for action in (
            "npm test",
            "./gradlew test",
            "git commit -am wip",
            "git push --force",
            "rm -rf build",
            "edit breadcrumbs/cli.py: rewrite the parser",
        ):
            self.assertFalse(_cli._is_read_only_action(action), action)

    def test_shell_plumbing_forfeits_the_claim(self):
        for action in ("cat x > y", "git status && rm -rf x", "ls; rm -rf x", "cat `rm -rf x`"):
            self.assertFalse(_cli._is_read_only_action(action), action)

    def test_flags_that_make_a_reporter_act_forfeit_it(self):
        self.assertFalse(_cli._is_read_only_action("find . -delete"))
        self.assertFalse(_cli._is_read_only_action("find . -exec rm {} +"))
        self.assertTrue(_cli._is_read_only_action("find . -name '*.py'"))

    def test_a_read_only_action_cannot_reach_pause(self):
        blocking = [
            {
                "id": "att_x",
                "kind": "attempt",
                "signals": ["file", "do-not-retry"],
                "score": 20.0,
                "stance": "blocking",
            }
        ]
        self.assertEqual(_cli._decide_verdict(blocking, ["routine_edit"], "edit a/b.py"), "PAUSE")
        self.assertEqual(
            _cli._decide_verdict(blocking, ["routine_edit"], "git status"), "READ_FIRST"
        )

    def test_an_executing_command_is_still_judged_on_its_matches(self):
        blocking = [
            {
                "id": "att_x",
                "kind": "attempt",
                "signals": ["file", "do-not-retry"],
                "score": 20.0,
                "stance": "blocking",
            }
        ]
        self.assertEqual(_cli._decide_verdict(blocking, ["routine_edit"], "npm test"), "PAUSE")


class HookSurfacingTests(unittest.TestCase):
    """What the agent is *shown* is a tighter bar than what guard *returns*."""

    def _match(self, mid, signals):
        return {"id": mid, "title": mid, "reason": "because", "signals": signals}

    def test_a_keyword_only_match_does_not_ride_along(self):
        result = {
            "verdict": "READ_FIRST",
            "matches": [
                self._match("dec_specific", ["file", "keyword"]),
                self._match("dec_vocabulary", ["keyword"]),
            ],
        }
        shown = _cli._hook_surfacing_matches(result)
        self.assertEqual([m["id"] for m in shown], ["dec_specific"])
        self.assertNotIn("dec_vocabulary", _cli._hook_guard_reason(result, shown))

    def test_tags_titles_and_mentions_all_qualify(self):
        for signal in ("file", "tag", "title", "mention", "do-not-retry", "open-blocker"):
            result = {"verdict": "READ_FIRST", "matches": [self._match("m", [signal, "keyword"])]}
            self.assertEqual(len(_cli._hook_surfacing_matches(result)), 1, signal)

    def test_an_all_keyword_result_is_still_shown(self):
        """A strong keyword-only match escalating through the score band is a
        deliberate behaviour of this tool; the hook does not silence it."""
        result = {"verdict": "READ_FIRST", "matches": [self._match("trap_x", ["keyword"])]}
        self.assertEqual(_cli._hook_surfacing_matches(result), [])
        self.assertIn("trap_x", _cli._hook_guard_reason(result, result["matches"]))


if __name__ == "__main__":
    unittest.main()
