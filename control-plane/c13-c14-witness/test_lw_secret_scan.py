"""SECRET_LEAK_SCAN must actually bite, and must not print what it finds."""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import lw_paths  # noqa: E402

lw_paths.install()

import lw_secret_scan  # noqa: E402

# Test vectors are assembled at runtime: the scanner stays strict, and no literal
# credential shape is committed in a source line for it to (correctly) fire on.
FAKE_PAT = "github_pat_" + "11ABCDEFG0XYZaBcDeFgHiJkLmNoPqRsTuVwXyZ01"
FAKE_OAUTH = "gho_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


class ScanTests(unittest.TestCase):
    def _report(self, text, name="planted.txt"):
        directory = tempfile.mkdtemp()
        path = pathlib.Path(directory) / name
        path.write_text(text, encoding="utf-8")
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return lw_secret_scan.scan_paths([str(path)])

    def test_fine_grained_pat_is_caught(self):
        report = self._report(f'token = "{FAKE_PAT}"\n')
        self.assertEqual(report["status"], lw_secret_scan.FAIL)
        self.assertIn("github_fine_grained_pat",
                      [hit["pattern"] for hit in report["hits"]])

    def test_oauth_token_is_caught(self):
        report = self._report(f"Authorization: Bearer {FAKE_OAUTH}\n")
        names = [hit["pattern"] for hit in report["hits"]]
        self.assertIn("github_oauth_token", names)
        self.assertIn("authorization_header", names)

    def test_private_key_block_is_caught(self):
        report = self._report("-----BEGIN " + "PRIVATE KEY-----\nMC4CAQAw\n")
        self.assertIn("private_key_block", [h["pattern"] for h in report["hits"]])

    def test_signed_url_query_is_caught(self):
        report = self._report(
            "https://acct.blob.core.windows.net/c/a.zip?si" + "g=AbCdEf0123456789XyZ\n")
        self.assertIn("query_access_token", [h["pattern"] for h in report["hits"]])

    def test_aws_key_is_caught(self):
        report = self._report("AWS_ACCESS_KEY_ID=" + "AKIA" + "IOSFODNN7EXAMPLE\n")
        self.assertIn("aws_access_key_id", [h["pattern"] for h in report["hits"]])

    def test_clean_text_passes(self):
        report = self._report("cell_id = C14\ncandidate_sha = " + "a" * 40 + "\n")
        self.assertEqual(report["status"], lw_secret_scan.PASS)
        self.assertEqual(report["hit_count"], 0)

    def test_hits_never_echo_the_secret(self):
        """The scanner must not become the leak."""
        report = self._report(f'Authorization: Bearer {FAKE_PAT}\n')
        serialised = json.dumps(report)
        self.assertNotIn(FAKE_PAT, serialised)
        self.assertNotIn(FAKE_PAT[8:40], serialised)
        self.assertFalse(report["secret_values_emitted"])
        for hit in report["hits"]:
            self.assertTrue(hit["match_redacted"])
            self.assertIn("line", hit)

    def test_line_numbers_are_reported(self):
        report = self._report("clean\nclean\nAuthorization: Bearer " + FAKE_PAT + "\n")
        lines = {hit["line"] for hit in report["hits"]}
        self.assertIn(3, lines)

    def test_placeholders_and_prefixes_alone_do_not_trip_the_scan(self):
        report = self._report("set GITHUB_TOKEN=<redacted>\n"
                              "prefix = github_pat_\n"
                              "header = Authorization: Bearer <token>\n")
        self.assertEqual(report["status"], lw_secret_scan.PASS, report["hits"])

    def test_the_scanner_source_is_exempt_from_itself(self):
        report = lw_secret_scan.scan_paths([str(HERE)])
        self.assertNotIn("lw_secret_scan.py",
                         {h["origin"].split("\\")[-1].split("/")[-1]
                          for h in report["hits"]})


if __name__ == "__main__":
    unittest.main(verbosity=2)


class ReviewedExceptionTests(unittest.TestCase):
    """A reviewed exception must be visible, justified, and still exist."""

    def test_every_declared_exception_names_a_file_that_still_exists(self):
        repo_root = HERE.parent.parent
        for (relative_path, pattern), reason in lw_secret_scan.REVIEWED_EXCEPTIONS.items():
            self.assertIn(pattern, {p.name for p in lw_secret_scan.PATTERNS})
            self.assertTrue(reason and len(reason) > 20, f"missing reason: {relative_path}")
            self.assertTrue((repo_root / relative_path).is_file(),
                            f"exception points at a file that is gone: {relative_path}")

    def test_an_exception_is_reported_but_does_not_fail_the_gate(self):
        relative, pattern = next(iter(lw_secret_scan.REVIEWED_EXCEPTIONS))
        if pattern != "private_key_block":
            self.skipTest("no synthetic vector for this pattern")
        directory = tempfile.mkdtemp()
        # Build the same repository-relative path, so the suffix match applies exactly
        # as it would in a real scan.
        target = pathlib.Path(directory) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("KEY_HEADER = '-----BEGIN " + "PRIVATE KEY----- leaked'\n",
                          encoding="utf-8")
        report = lw_secret_scan.scan_paths([str(target)])
        self.assertEqual(report["status"], lw_secret_scan.PASS)
        self.assertEqual(report["hit_count"], 0)
        self.assertEqual(report["reviewed_exception_count"], 1)
        self.assertTrue(report["reviewed_exceptions"][0]["reviewed_reason"])

    def test_a_same_named_pattern_in_another_path_is_not_excused(self):
        directory = tempfile.mkdtemp()
        target = pathlib.Path(directory) / "elsewhere.py"
        target.write_text("KEY_HEADER = '-----BEGIN " + "PRIVATE KEY----- leaked'\n",
                          encoding="utf-8")
        report = lw_secret_scan.scan_paths([str(target)])
        self.assertEqual(report["status"], lw_secret_scan.FAIL)
        self.assertEqual(report["reviewed_exception_count"], 0)
