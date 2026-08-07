"""Tests for `scan-secrets` and the audit secret sub-check.

Covers Fixture 6 (token-like string fails), the individual secret shapes, the
false-positive controls (git shas, record ids, the `?token=` query-string text that
must NOT trip), and the skip rules (private/index/generated are not scanned).

Run with:  python -m unittest discover -s tests
       or:  python tests/test_secrets.py
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
from breadcrumbs import cli as _cli  # noqa: E402  (patch target for module-level lookups)

FIXTURES = REPO_ROOT / "fixtures"


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = crumb.main(argv)
    return code, buf.getvalue()


def fresh_store(tmp: str) -> Path:
    crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
    return Path(tmp) / crumb.MEMORY_DIRNAME


def patterns_hit(mem: Path) -> set[str]:
    return {h["pattern"] for h in crumb.scan_secrets(mem)}


# --------------------------------------------------------------------------- #
# Fixture 6 — the canonical secret leak
# --------------------------------------------------------------------------- #
class Fixture6Tests(unittest.TestCase):
    def test_scan_secrets_command_fails_nonzero(self):
        code, out = run(["scan-secrets", "--project", str(FIXTURES / "fixture-06-secret-leak")])
        self.assertEqual(code, 1, out)
        self.assertIn("possible secret", out)

    def test_scan_secrets_points_at_offending_record_and_line(self):
        mem = FIXTURES / "fixture-06-secret-leak" / ".project-memory"
        hits = crumb.scan_secrets(mem)
        self.assertTrue(hits)
        for h in hits:
            self.assertTrue(h["path"].startswith("sessions/"))
            self.assertIsInstance(h["line"], int)
            self.assertGreater(h["line"], 0)

    def test_secret_value_is_not_echoed(self):
        """We report the pattern NAME + location, never the matched secret value."""
        _, out = run(
            ["scan-secrets", "--project", str(FIXTURES / "fixture-06-secret-leak"), "--json"]
        )
        payload = json.loads(out)
        blob = json.dumps(payload)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", blob)
        self.assertNotIn("hunter2hunter2", blob)

    def test_audit_treats_secret_as_blocking(self):
        code, out = run(["audit", "--project", str(FIXTURES / "fixture-06-secret-leak"), "--json"])
        self.assertEqual(code, 1, out)
        payload = json.loads(out)
        self.assertFalse(payload["ok"])
        self.assertGreaterEqual(payload["failed"], 1)
        self.assertTrue(any(f["check"] == "secret" for f in payload["findings"]))


# --------------------------------------------------------------------------- #
# Each secret shape is detected
# --------------------------------------------------------------------------- #
class SecretShapeTests(unittest.TestCase):
    def _scan_line(self, line: str) -> set[str]:
        with tempfile.TemporaryDirectory() as tmp:
            mem = fresh_store(tmp)
            (mem / "decisions" / "2026-06-25-x.md").write_text(line + "\n", encoding="utf-8")
            return patterns_hit(mem)

    def test_aws_access_key_id(self):
        self.assertIn("aws-access-key-id", self._scan_line("key=AKIAIOSFODNN7EXAMPLE"))

    def test_github_token(self):
        self.assertIn("github-token", self._scan_line("ghp_" + "a" * 36))

    def test_pem_private_key(self):
        self.assertIn("pem-private-key", self._scan_line("-----BEGIN RSA PRIVATE KEY-----"))

    def test_bearer_token(self):
        self.assertIn(
            "bearer-token", self._scan_line("Authorization: Bearer abcdef0123456789abcdef")
        )

    def test_assignment_pattern(self):
        self.assertIn("secret-assignment", self._scan_line("password=correcthorsebattery123"))

    def test_jwt(self):
        jwt = "eyJhbGciOiJIUzI1Ni.eyJzdWIiOiIxMjM0NTY3.SflKxwRJSMeKKF2QT4f"
        self.assertIn("jwt", self._scan_line(jwt))

    def test_labeled_hex_secret(self):
        """Long hex IS flagged when it sits behind a credential label (issue #5)."""
        hex40 = "a" * 8 + "b" * 8 + "c" * 8 + "d" * 8 + "e" * 8  # 40 lowercase-hex
        for line in (
            f"token: {hex40}",
            f"Authorization: {hex40}",
            f"X-Api-Key: {hex40}",
            f"x-auth-token={hex40}",
        ):
            self.assertIn("labeled-hex-secret", self._scan_line(line), line)


# --------------------------------------------------------------------------- #
# Issue #5 — the labeled-hex pattern must not reopen the bare-sha tradeoff
# --------------------------------------------------------------------------- #
class LabeledHexTradeoffTests(unittest.TestCase):
    def _scan_line(self, line: str) -> set[str]:
        with tempfile.TemporaryDirectory() as tmp:
            mem = fresh_store(tmp)
            (mem / "decisions" / "2026-06-25-h.md").write_text(line + "\n", encoding="utf-8")
            return patterns_hit(mem)

    def test_bare_hex_and_sha_labels_are_still_not_flagged(self):
        """A standalone sha — and the sha-bearing labels memory uses — stay quiet."""
        sha40 = "a" * 8 + "b" * 8 + "c" * 8 + "d" * 8 + "e" * 8
        for line in (
            sha40,  # bare hex on its own line
            f"commit: {sha40}",  # commit ref
            f"inputs_hash: {sha40}",  # generated header stamp
            f"ref: {sha40}",  # evidence ref
        ):
            self.assertNotIn("labeled-hex-secret", self._scan_line(line), line)

    def test_query_string_token_prose_is_not_flagged(self):
        """`?token=` followed by prose (not hex) must not trip the labeled pattern."""
        self.assertNotIn(
            "labeled-hex-secret",
            self._scan_line("Send the auth token as a ?token= query parameter."),
        )


# --------------------------------------------------------------------------- #
# False-positive controls — the scanner must stay quiet on normal memory
# --------------------------------------------------------------------------- #
class FalsePositiveTests(unittest.TestCase):
    def test_clean_fixtures_have_no_secrets(self):
        for name in (
            "fixture-01-fresh-resume",
            "fixture-02-guard-true-positive",
            "fixture-03-guard-false-positive",
            "fixture-04-stale-handoff",
            "fixture-05-superseded-decision",
        ):
            mem = FIXTURES / name / ".project-memory"
            self.assertEqual(crumb.scan_secrets(mem), [], name)

    def test_query_string_token_text_is_not_a_secret(self):
        """fixture-05's '?token= query parameter' prose must not trip the scanner."""
        mem = FIXTURES / "fixture-05-superseded-decision" / ".project-memory"
        self.assertEqual(crumb.scan_secrets(mem), [])

    def test_git_shas_and_record_ids_are_not_high_entropy_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = fresh_store(tmp)
            body = (
                "commit: 7c6b5a4 a1b2c3def0123456789\n"
                "id: dec_20260605_markdown-source-of-truth\n"
                "see att_20260512_sqlite-store-too-heavy for context\n"
            )
            (mem / "decisions" / "2026-06-25-y.md").write_text(body, encoding="utf-8")
            self.assertEqual(patterns_hit(mem), set())

    def test_high_entropy_token_is_caught(self):
        """A genuinely random mixed-class 40-char blob IS flagged."""
        token = "aB3xYz9QdE7Lm2Pq8Rt6Vw1Nc4Kf0Gh5Js7Tb2Zx"  # mixed upper/lower/digit
        with tempfile.TemporaryDirectory() as tmp:
            mem = fresh_store(tmp)
            (mem / "decisions" / "2026-06-25-z.md").write_text(token + "\n", encoding="utf-8")
            self.assertIn("high-entropy-string", patterns_hit(mem))

    def test_camelcase_paths_and_identifiers_are_not_secrets(self):
        """Path- and dotted-identifier-shaped tokens are allowlisted."""
        allowlisted = (
            "app/src/main/java/com/MigrationV14ToV15Test",
            "com.example.config.DatabaseMigrationHelperV2Factory",
            "src/test/AndroidManifestV2InstrumentationRunner",
        )
        for tok in allowlisted:
            self.assertFalse(crumb._looks_high_entropy(tok), f"{tok} should not read as a secret")
            with tempfile.TemporaryDirectory() as tmp:
                mem = fresh_store(tmp)
                (mem / "decisions" / "2026-06-25-p.md").write_text(tok + "\n", encoding="utf-8")
                self.assertNotIn("high-entropy-string", patterns_hit(mem), tok)

    def test_allowlist_does_not_launder_real_blobs(self):
        """The allowlist must not weaken detection — these still flag."""
        # A separatorless blob, a base64 blob with embedded '/' and a long random
        # segment, and a base64 token with '=' padding all stay flagged.
        still_secret = (
            "aB3xYz9QdE7Lm2Pq8Rt6Vw1Nc4Kf0Gh5Js7Tb2Zx",
            "abc/aB3xYz9QdE7Lm2Pq8Rt6Vw1Nc4Kf0Gh5Js7Tb2Zx",
            "aB3xYz9QdE7Lm2Pq8Rt6Vw1Nc4Kf0Gh5Js7Tb2Zx==",
        )
        for tok in still_secret:
            self.assertTrue(crumb._looks_high_entropy(tok), f"{tok} must still read as a secret")


# --------------------------------------------------------------------------- #
# Skip rules — private/index/generated are not scanned
# --------------------------------------------------------------------------- #
class SkipRuleTests(unittest.TestCase):
    def test_private_and_index_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = fresh_store(tmp)
            (mem / "private").mkdir(exist_ok=True)
            (mem / "private" / "notes.md").write_text(
                "key=AKIAIOSFODNN7EXAMPLE\n", encoding="utf-8"
            )
            (mem / "index").mkdir(exist_ok=True)
            (mem / "index" / "dump.md").write_text(
                "password=correcthorsebattery123\n", encoding="utf-8"
            )
            self.assertEqual(crumb.scan_secrets(mem), [])


class UndecodableFileTests(unittest.TestCase):
    """One bad byte used to fail open.

    Before the fix, a single `\\xff` in committed memory silently exempted the
    whole file from the secret scan, aborted `audit` with a path-less error, and
    left `validate` reporting OK.
    """

    def _store_with_bad_byte(self, tmp: str) -> Path:
        mem = fresh_store(tmp)
        p = mem / "known-traps.md"
        p.write_bytes(p.read_bytes() + b"\n## trap_bad: \xff bad byte\n")
        return mem

    def test_scan_secrets_blocks_and_names_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._store_with_bad_byte(tmp)
            code, out = run(["scan-secrets", "--project", tmp])
            self.assertEqual(code, 1, out)
            self.assertIn("unscannable-file", out)
            self.assertIn("known-traps.md", out)

    def test_audit_blocks_and_names_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._store_with_bad_byte(tmp)
            code, out = run(["audit", "--project", tmp])
            self.assertEqual(code, 1, out)
            self.assertIn("known-traps.md", out)
            self.assertNotIn("codec can't decode", out)

    def test_validate_reports_the_unreadable_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._store_with_bad_byte(tmp)
            fails = [f for f in crumb.run_validate(mem) if f["status"] == "fail"]
            self.assertTrue(
                any(f["path"] == "known-traps.md" and "UTF-8" in f["message"] for f in fails),
                f"expected an unreadable-file finding; got {fails}",
            )

    def test_readable_lines_are_still_scanned(self):
        """The bad byte must not exempt the rest of the file from the scan."""
        with tempfile.TemporaryDirectory() as tmp:
            mem = fresh_store(tmp)
            p = mem / "known-traps.md"
            p.write_bytes(
                p.read_bytes() + b"\n## trap_bad: \xff bad byte\n- aws key: AKIAIOSFODNN7EXAMPLE\n"
            )
            self.assertIn("unscannable-file", patterns_hit(mem))
            self.assertTrue(
                patterns_hit(mem) - {"unscannable-file"},
                "a secret next to the bad byte must still be found",
            )

    def test_resume_and_reindex_survive_an_undecodable_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = fresh_store(tmp)
            p = mem / "handoff.md"
            p.write_bytes(p.read_bytes().replace(b"# Project Handoff", b"# Project H\xffndoff"))
            ok, problem = crumb.try_reindex_projections(mem, Path(tmp))
            self.assertTrue(ok, problem)
            packet = crumb.build_resume_packet(mem, Path(tmp))
            self.assertTrue(
                any("handoff.md" in w for w in packet["warnings"]),
                f"the packet should warn about the unreadable handoff; got {packet['warnings']}",
            )

    def test_reindex_failure_names_the_cause(self):
        """`crumb reindex` printed 'Reindex failed' with no cause."""
        with tempfile.TemporaryDirectory() as tmp:
            mem = fresh_store(tmp)
            real = _cli.build_resume_packet

            def boom(*a, **kw):
                raise RuntimeError("packet exploded")

            _cli.build_resume_packet = boom
            try:
                code, out = run(["reindex", "--project", tmp])
            finally:
                _cli.build_resume_packet = real
            self.assertEqual(code, 1, out)
            self.assertIn("packet exploded", out)
            self.assertTrue(mem.is_dir())


class UrlEmbeddedCredentialTests(unittest.TestCase):
    """A password inside a connection string is a secret the scanner missed.

    Nothing in the keyword list could see these: the password follows a bare `:`
    inside a URL, with no `password=`-style label anywhere, and the standalone
    entropy heuristic never fires on short mixed-case passwords. A "how do I run
    this" note carrying a `DATABASE_URL` is one of the likeliest secrets to land
    in project memory, and `scan-secrets` reported OK on every one of them.
    """

    NAME = "url-embedded-credentials"

    def _scan_line(self, line: str) -> set[str]:
        with tempfile.TemporaryDirectory() as tmp:
            mem = fresh_store(tmp)
            (mem / "decisions" / "2026-06-25-x.md").write_text(line + "\n", encoding="utf-8")
            return patterns_hit(mem)

    def test_flags_real_connection_strings(self):
        for line in (
            "postgres://app:s3cr3tp4ss@db.example.com:5432/prod",
            "DATABASE_URL=postgresql://admin:Hunter2Hunter2@10.0.0.4/main",
            "mongodb+srv://root:pw123456@cluster0.mongodb.net/test",
            "redis://:MyR3disPass@cache.internal:6379/0",  # empty username
            "https://user:tok3nv4lue@internal.example.com/repo.git",
            "mysql://svc_acct:p%40ssw0rd@prod-db/app",
        ):
            with self.subTest(line=line):
                self.assertIn(self.NAME, self._scan_line(line))

    def test_does_not_flag_ordinary_urls_and_placeholders(self):
        """The scanner's posture is conservative: a false positive blocks a commit."""
        for line in (
            "https://example.com:8080/path",  # port, not a password
            "git@github.com:org/repo.git",  # scp-style, no scheme
            "see https://pypi.org/pypi/crumb-kit/json",
            "https://user@host.example.com/x",  # username only
            "[link](https://a.example.com/b@c)",  # @ after the path starts
            "mailto:someone@example.com",
            "postgres://user:password@localhost/db",  # doc placeholder
            "postgres://app:${DB_PASS}@db/prod",  # interpolation
            "postgres://app:$DB_PASS@db/prod",
            "postgres://app:<your-password>@db/prod",
            "amqp://guest:guest@rabbit:5672/",  # well-known default, under the floor
        ):
            with self.subTest(line=line):
                self.assertNotIn(self.NAME, self._scan_line(line))

    def test_the_repos_own_docs_do_not_trip_it(self):
        """The pattern was accepted only after a zero-hit sweep of this tree.

        This is also why the docs describing the pattern write their examples in
        `<placeholder>` form: prose about a secret shape should not itself contain
        a secret-shaped string. The one exception is this module, which needs real
        positives to test against and is skipped below.
        """
        pat = dict(_cli.SECRET_PATTERNS)[self.NAME]
        root = Path(__file__).resolve().parent.parent
        offenders = []
        for path in root.rglob("*"):
            if not path.is_file() or ".git/" in str(path) or "__pycache__" in str(path):
                continue
            if path.suffix not in (".md", ".py", ".yml", ".yaml", ".json", ".toml", ".txt"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                # This test file itself carries the positive cases on purpose.
                if path.name == "test_secrets.py":
                    continue
                if pat.search(line):
                    offenders.append(f"{path.relative_to(root)}:{i}")
        self.assertEqual(offenders, [], f"url-credential pattern false-positives: {offenders}")


class CleanStoreTests(unittest.TestCase):
    def test_scan_secrets_ok_on_fresh_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            fresh_store(tmp)
            code, out = run(["scan-secrets", "--project", tmp])
            self.assertEqual(code, 0, out)
            self.assertIn("OK", out)

    def test_missing_store_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _ = run(["scan-secrets", "--project", tmp])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
