"""Cheaper rebuilds that still compute exactly the same thing (audit WP15: F23).

The pairwise related map and conflict report are now computed from feature
postings, a publication parses each record once, and local capture skips the
publication it never affected. These tests hold each shortcut to the full
computation it replaced:

- the indexed related map and conflict report equal the pairwise oracles
  (`related._compute_related_full`, `lifecycle._find_contradictions_full`) on
  randomized stores, and still equal them after records are added, edited
  and removed;
- a local jot changes no shared view and triggers no publication;
- quality does not collapse at 1,000 or 10,000 records (the related map used
  to be skipped entirely above 2,000);
- the parse cache never serves stale content.

Run with:  python -m unittest discover -s tests -p "test_incremental_equivalence.py"
"""

from __future__ import annotations

import contextlib
import io
import json
import random
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import lifecycle, related  # noqa: E402

AREAS = ["api", "billing", "auth", "search", "ingest", "export", "infra", "web", "mobile", "data"]


def quiet(argv: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, out.getvalue()


def make_store(tmp: str) -> tuple[Path, Path, str]:
    root = Path(tmp)
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "i"], cwd=root, check=True)
    quiet(["init", "--project", str(root), "--session-tracking", "full"])
    mem = root / crumb.MEMORY_DIRNAME
    quiet(
        [
            "remember",
            "decision",
            "--project",
            str(root),
            "--title",
            "Seed decision about the cache",
            "--set",
            "Decision",
            "seed text",
            "--evidence",
            "file",
            "src/api/cache.py",
        ]
    )
    seed = next((mem / "decisions").glob("*.md"))
    template = seed.read_text(encoding="utf-8")
    seed.unlink()
    return root, mem, template


def write_record(mem: Path, template: str, rnd: random.Random, i: int, vocab: list[str]) -> Path:
    """One synthetic decision or attempt: shared files, tags and words, spread dates."""
    area = rnd.choice(AREAS)
    words = rnd.sample(vocab, 5)
    kind = "attempt" if i % 4 == 0 else "decision"
    title = f"{words[0].title()} {words[1]} {words[2]} rule {i} for {area}"
    slug = _cli.slugify(title)
    month, day = 1 + rnd.randrange(9), 1 + rnd.randrange(27)
    stamp = f"2026-{month:02d}-{day:02d}"
    text = template.replace("seed-decision-about-the-cache", slug)
    text = text.replace("Seed decision about the cache", title)
    text = text.replace("src/api/cache.py", f"src/{area}/{words[3]}.py")
    text = text.replace("tags: []", f"tags:\n  - {area}\n  - {words[4]}")
    text = text.replace("2026-09-27", stamp)
    if kind == "attempt":
        text = text.replace("type: decision", "type: attempt").replace("id: dec_", "id: att_")
        text = text.replace(
            "## Decision\nseed text",
            f"## Tried\n{' '.join(words)} in {area}\n\n## Why It Failed / Succeeded\nit broke\n\n"
            f"## Do Not Retry Unless\nthe {words[0]} {words[1]} changes",
        )
        directory = mem / "attempts"
    else:
        text = text.replace("seed text", f"{' '.join(words)} in {area}; also {rnd.choice(vocab)}")
        directory = mem / "decisions"
    path = directory / f"{stamp}-{slug}.md"
    path.write_text(
        text.replace("id: dec_2026", "id: dec_2026").replace(
            f"dec_{stamp.replace('-', '')}", f"dec_{stamp.replace('-', '')}"
        ),
        encoding="utf-8",
    )
    return path


def fix_ids(mem: Path) -> None:
    """Rewrite ids to match filenames (identity is filename-canonical)."""
    for dirname, rtype in (("decisions", "decision"), ("attempts", "attempt")):
        for p in (mem / dirname).glob("*.md"):
            rid, slug = _cli.derive_identity(p.stem, rtype)
            text = p.read_text(encoding="utf-8")
            import re

            text = re.sub(r"(?m)^id: .*$", f"id: {rid}", text, count=1)
            text = re.sub(r"(?m)^slug: .*$", f"slug: {slug}", text, count=1)
            p.write_text(text, encoding="utf-8")


VOCAB = (
    "cache queue router parser session token schema index ledger worker retry timeout "
    "backoff shard replica snapshot migration payload webhook scheduler billing invoice "
    "export import auth cookie tenant quota metrics tracing kafka redis postgres cron "
    "lambda bucket cdn edge proxy gateway grpc graphql rest socket stream batch"
).split()


def oracle_equal(test: unittest.TestCase, mem: Path, label: str) -> None:
    fast = related.compute_related(mem)
    full = related._compute_related_full(mem)
    test.assertNotIn("degraded", fast, label)
    test.assertEqual(fast["related"], full["related"], label)
    test.assertEqual(
        lifecycle.find_contradictions(mem), lifecycle._find_contradictions_full(mem), label
    )
    test.assertEqual(
        lifecycle.near_duplicate_pairs(mem), lifecycle._near_duplicate_pairs_full(mem), label
    )
    # And inside one operation (the memoized path), still equal.
    with _cli.operation():
        test.assertEqual(
            lifecycle.find_contradictions(mem), lifecycle._find_contradictions_full(mem), label
        )


class OracleTests(unittest.TestCase):
    def test_incremental_related_and_conflict_results_match_full_oracle(self):
        for seed, n, vocab in ((1, 60, VOCAB[:12]), (2, 200, VOCAB), (3, 350, VOCAB[:20])):
            with self.subTest(seed=seed, n=n), tempfile.TemporaryDirectory() as tmp:
                root, mem, template = make_store(tmp)
                rnd = random.Random(seed)
                paths = [write_record(mem, template, rnd, i, vocab) for i in range(n)]
                fix_ids(mem)
                # Supersession links and near-duplicates, the cases the rules skip or catch.
                dup = paths[1].read_text(encoding="utf-8")
                (mem / "decisions" / "2026-01-01-near-copy.md").write_text(
                    dup.replace("2026-", "2025-", 1), encoding="utf-8"
                )
                fix_ids(mem)
                conflicts = lifecycle._find_contradictions_full(mem)
                self.assertTrue(conflicts, "the fixture must exercise the conflict rules")
                oracle_equal(self, mem, "initial")

                # Incremental: add, edit and remove records; equal after each.
                for i in range(n, n + 15):
                    write_record(mem, template, rnd, i, vocab)
                fix_ids(mem)
                oracle_equal(self, mem, "after adds")
                victim = next((mem / "decisions").glob("*.md"))
                victim.write_text(
                    victim.read_text(encoding="utf-8").replace("rule", "policy change"),
                    encoding="utf-8",
                )
                oracle_equal(self, mem, "after an edit")
                for p in list((mem / "decisions").glob("*.md"))[:10]:
                    p.unlink()
                oracle_equal(self, mem, "after removals")
                quiet(["reindex", "--project", str(root)])
                published = json.loads((mem / "generated" / "related.json").read_text())["related"]
                self.assertEqual(published, related._compute_related_full(mem)["related"])

    def test_the_parse_cache_never_serves_stale_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem, template = make_store(tmp)
            path = write_record(mem, template, random.Random(4), 1, VOCAB)
            fix_ids(mem)
            with _cli.operation():
                before = _cli.load_records(mem, types=("decision",))
                path.write_text(
                    path.read_text(encoding="utf-8").replace("rule 1", "rule one changed"),
                    encoding="utf-8",
                )
                after = _cli.load_records(mem, types=("decision",))
            self.assertNotEqual(before[0].meta["title"], after[0].meta["title"])
            self.assertIn("rule one changed", after[0].meta["title"])
            # Each caller gets its own frontmatter dict.
            with _cli.operation():
                a = _cli.load_records(mem, types=("decision",))[0]
                a.meta["title"] = "mutated by a caller"
                b = _cli.load_records(mem, types=("decision",))[0]
            self.assertNotEqual(b.meta["title"], "mutated by a caller")

    def test_budget_degrades_visibly_not_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem, template = make_store(tmp)
            rnd = random.Random(5)
            for i in range(80):
                write_record(mem, template, rnd, i, VOCAB[:6])
            fix_ids(mem)
            with mock.patch.object(related, "RELATED_PAIR_BUDGET", 50):
                doc = related.compute_related(mem)
            self.assertIn("degraded", doc)
            self.assertGreater(doc["degraded"]["dropped_features"], 0)
            self.assertIsNone(doc["skipped"])
            # Published, it is in the committed file, and `audit` reports it.
            with mock.patch.object(related, "RELATED_PAIR_BUDGET", 50):
                quiet(["reindex", "--project", str(root)])
            self.assertEqual(related.load_degraded(mem), doc["degraded"])
            code, out = quiet(["audit", "--project", str(root), "--json"])
            self.assertIn("related-degraded", out)
            quiet(["reindex", "--project", str(root)])
            self.assertIsNone(related.load_degraded(mem))
            code, out = quiet(["audit", "--project", str(root), "--json"])
            self.assertNotIn("related-degraded", out)

    def test_duplicate_sweep_covers_every_type_at_any_size(self):
        """The audit sweep used to skip a type above 2,000 items, silently."""
        with tempfile.TemporaryDirectory() as tmp:
            root, mem, template = make_store(tmp)
            rnd = random.Random(9)
            for i in range(2050):
                write_record(mem, template, rnd, i, VOCAB)
            twins = []
            for tag in ("one", "two"):
                p = mem / "decisions" / f"2026-0{len(twins) + 1}-05-quorvex-lattice-twin-{tag}.md"
                p.write_text(
                    template.replace("seed-decision-about-the-cache", f"quorvex-lattice-twin-{tag}")
                    .replace("Seed decision about the cache", "Quorvex lattice flange tessel")
                    .replace("seed text", "quorvex lattice flange tessel marrow"),
                    encoding="utf-8",
                )
                twins.append(p)
            fix_ids(mem)
            ids = sorted(_cli.derive_identity(p.stem, "decision")[0] for p in twins)
            pairs = lifecycle.near_duplicate_pairs(mem)
            self.assertIn(ids, [[q["a"], q["b"]] for q in pairs if q["kind"] == "decision"])


class LocalCaptureTests(unittest.TestCase):
    def test_local_capture_does_not_rebuild_unaffected_shared_views(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem, template = make_store(tmp)
            rnd = random.Random(6)
            for i in range(30):
                write_record(mem, template, rnd, i, VOCAB)
            fix_ids(mem)
            quiet(["reindex", "--project", str(root)])
            gen = mem / "generated"
            shared = {
                p: (p.read_bytes(), p.stat().st_mtime_ns) for p in gen.iterdir() if p.is_file()
            }
            shared[mem / "index" / "generation.json"] = (
                (mem / "index" / "generation.json").read_bytes(),
                (mem / "index" / "generation.json").stat().st_mtime_ns,
            )
            with mock.patch.object(
                _cli, "_publish_projections", wraps=_cli._publish_projections
            ) as pub:
                code, out = quiet(
                    [
                        "jot",
                        "the quasar cache warms slowly",
                        "--local",
                        "--project",
                        str(root),
                        "--json",
                    ]
                )
            self.assertEqual(code, 0, out)
            self.assertEqual(pub.call_count, 0, "a local jot published the shared views")
            for p, (data, mtime) in shared.items():
                self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), (data, mtime), p.name)
            # Nothing it could have changed is stale: validate passes, and the
            # jot is found by search (local jots are read directly).
            code, out = quiet(["validate", "--project", str(root)])
            self.assertEqual(code, 0, out)
            code, out = quiet(["search", "quasar cache warms", "--project", str(root), "--json"])
            self.assertTrue(json.loads(out)["matches"])
            # A committed jot does change a shared view (the packet's inbox), so it publishes.
            with mock.patch.object(
                _cli, "_publish_projections", wraps=_cli._publish_projections
            ) as pub:
                quiet(["jot", "a committed note about the ledger", "--project", str(root)])
            self.assertEqual(pub.call_count, 1)


class ScaleQualityTests(unittest.TestCase):
    def test_1000_and_10000_record_quality_does_not_collapse(self):
        """Related-ness at 1,000 and 10,000 records: planted pairs are found at
        both sizes, and the map is never skipped (it used to be above 2,000). At
        10,000 dense synthetic records the pair budget may degrade it, visibly."""
        results = {}
        for n in (1000, 10000):
            with tempfile.TemporaryDirectory() as tmp:
                root, mem, template = make_store(tmp)
                rnd = random.Random(7)
                for i in range(n):
                    write_record(mem, template, rnd, i, VOCAB)
                # Two planted records that share a file, a tag and specific words.
                planted = []
                for tag in ("alpha", "beta"):
                    p = mem / "decisions" / f"2026-05-05-zyphon-kestrel-planted-{tag}.md"
                    p.write_text(
                        template.replace(
                            "seed-decision-about-the-cache", f"zyphon-kestrel-planted-{tag}"
                        )
                        .replace("Seed decision about the cache", f"Zyphon kestrel planted {tag}")
                        .replace("src/api/cache.py", "src/planted/zyphon.py")
                        .replace("tags: []", "tags:\n  - zyphon")
                        .replace("seed text", "zyphon kestrel handshake quorum"),
                        encoding="utf-8",
                    )
                    planted.append(p)
                fix_ids(mem)
                started = time.perf_counter()
                with _cli.operation():
                    doc = related.compute_related(mem)
                    conflicts = lifecycle.find_contradictions(mem)
                elapsed = time.perf_counter() - started
                ids = [_cli.derive_identity(p.stem, "decision")[0] for p in planted]
                results[n] = (doc, conflicts, elapsed)
                self.assertIsNone(doc["skipped"], n)
                degraded = doc.get("degraded")
                if n == 1000:
                    self.assertIsNone(degraded, "1,000 records must not need the pair budget")
                elif degraded is not None:
                    # This synthetic store is far denser than a real one (ten area
                    # tags, a 40-word vocabulary), so the budget may apply. When it
                    # does, it says so, and names what it dropped.
                    self.assertTrue(
                        degraded["reason"] and degraded["dropped_features"], degraded["reason"]
                    )
                self.assertTrue(ids[1] in doc["related"].get(ids[0], []), f"{n}: planted pair lost")
                self.assertTrue(ids[0] in doc["related"].get(ids[1], []), f"{n}: planted pair lost")
                self.assertGreater(len(doc["related"]), n * 0.9, n)
                self.assertLess(elapsed, 120, f"{n} records took {elapsed:.1f}s")
        # The share of live items with a related entry does not collapse at scale.
        share = {n: len(results[n][0]["related"]) / n for n in results}
        self.assertGreater(share[10000], share[1000] * 0.9)


if __name__ == "__main__":
    unittest.main()
