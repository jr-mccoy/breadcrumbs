"""The continuity replays (audit WP19) reproduce their published verdicts.

`evals/task_replays/results.json` is what `docs/benchmarks/continuity-results.md`
reports. This reruns the replays on the `fresh` host and holds every oracle
verdict to it, so a change that moves a published result fails here and must
be re-published on purpose. Token counts and ids are not compared: ids carry
the run's date, and the packet stamps the time.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPLAYS = ROOT / "evals" / "task_replays"
sys.path.insert(0, str(REPLAYS))

VERDICTS = (
    "by_start",
    "at_action",
    "by_action",
    "pointer_by_start",
    "pointer_at_action",
    "stale_presented",
    "groups_delivered",
    "groups_total",
)


class TaskReplayTests(unittest.TestCase):
    def test_rerun_reproduces_the_published_verdicts(self):
        import run as replays

        published = json.loads((REPLAYS / "results.json").read_text(encoding="utf-8"))
        key = lambda r: (r["scenario"], r["host"], r["baseline"])  # noqa: E731
        expected = {key(r): r for r in published["rows"] if r["host"] == "fresh"}
        actual = {key(r): r for r in replays.run(["fresh"])["rows"]}
        self.assertEqual(set(actual), set(expected))
        for k, row in actual.items():
            with self.subTest(k):
                self.assertEqual(
                    {v: row[v] for v in VERDICTS}, {v: expected[k][v] for v in VERDICTS}
                )
                if k[2] == "breadcrumbs":
                    # Every surfaced record can be inspected at the revision served.
                    for rec in row["surfaced"]:
                        self.assertTrue(rec["file"] and rec["sha256"], rec)

    def test_the_oracle_needs_nothing_from_breadcrumbs(self):
        source = (REPLAYS / "oracle.py").read_text(encoding="utf-8")
        self.assertNotIn("breadcrumbs", source.split('"""', 2)[-1])
        import oracle

        verdict = oracle.judge(
            {
                "must_deliver": [["stale prices"]],
                "pointer": [["lru cache"]],
                "stale_as_current": [["three times"]],
            },
            {
                "start": "Tried an LRU cache: stale prices.",
                "prompt": "",
                "action": "retry three times",
            },
        )
        self.assertTrue(verdict["by_start"])
        self.assertFalse(verdict["at_action"])
        self.assertTrue(verdict["pointer_by_start"])
        self.assertTrue(verdict["stale_presented"])


if __name__ == "__main__":
    unittest.main()
