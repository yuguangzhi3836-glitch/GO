"""Publication diagnostics must not alter review truth or weaken secret guards."""
import argparse
import hashlib
import json
import pathlib
import tempfile
import unittest

import lite_cli
import lite_errors


class PublicationTests(unittest.TestCase):
    def run_publication(self, facts, outcome=None):
        root = pathlib.Path(self.tmp.name)
        source = root / "facts.json"
        source.write_text(json.dumps(facts), encoding="utf-8")
        args = argparse.Namespace(out=str(root / "out"), facts=str(source),
            spec=None, contract=None, outcome=None, scope=None, review_brief=None,
            seal_result=None, seal_stdout=None, seal_stderr=None)
        if outcome is not None:
            p = root / "outcome.json"
            p.write_text(json.dumps(outcome), encoding="utf-8")
            args.outcome = str(p)
        original = source.read_bytes()
        lite_cli.cmd_raw_evidence(args)
        self.assertEqual(source.read_bytes(), original)
        return root / "out", original

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_removed_added_context_tokens_preserve_diff_and_original_binding(self):
        token = "Bearer " + "syntheticA12345678901234567890"
        diff = "diff --git a/a b/a\n@@ -1,2 +1,2 @@\n-" + token + "\n+" + token + "\n context " + token + "\n+assert denied\n"
        facts = {"candidate_sha": "a" * 40, "candidate_diff": diff, "changed_paths": ["a"]}
        out, original = self.run_publication(facts, {"verdict": "BLOCKED", "failure_class": "AI_QUOTA_EXHAUSTED"})
        self.assertFalse((out / "facts.json").exists())
        public = (out / "facts_redacted_projection.json").read_bytes()
        projected = json.loads(public)
        self.assertEqual(projected["candidate_diff"], diff.replace(token, "Bearer [REDACTED]"))
        self.assertEqual(projected["changed_paths"], facts["changed_paths"])
        self.assertEqual(json.loads((out / "outcome.json").read_text())["verdict"], "BLOCKED")
        manifest = json.loads((out / "raw_evidence_manifest.json").read_text())
        receipt = manifest["redacted_projections"][0]
        self.assertEqual(receipt["original_bytes_sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(receipt["projection_bytes_sha256"], hashlib.sha256(public).hexdigest())
        self.assertEqual(receipt["redaction_count"], 3)
        self.assertEqual(receipt["redacted_line_numbers"], [3, 4, 5])
        self.assertFalse(manifest["authorizes_any_action"])
        for p in out.iterdir():
            self.assertNotIn(token.encode(), p.read_bytes())

    def test_clean_facts_remain_byte_identical(self):
        out, original = self.run_publication({"candidate_diff": "+assert denied\n"})
        self.assertEqual((out / "facts.json").read_bytes(), original)

    def test_bearer_in_other_field_still_refused_without_partial_output(self):
        with self.assertRaises(SystemExit):
            self.run_publication({"candidate_diff": "+safe", "summary": "Bearer " + "A" * 30})
        self.assertFalse((pathlib.Path(self.tmp.name) / "out").exists())

    def test_other_secret_shapes_in_diff_still_refused(self):
        with self.assertRaises(SystemExit):
            self.run_publication({"candidate_diff": "+Bearer " + "A" * 30 + "\n+sk-" + "B" * 30})
        self.assertFalse((pathlib.Path(self.tmp.name) / "out").exists())

    def test_opinion_secret_still_refused(self):
        with self.assertRaises(SystemExit):
            self.run_publication({"candidate_diff": "+Bearer " + "A" * 30}, {"detail": "Bearer " + "B" * 30})
        self.assertFalse((pathlib.Path(self.tmp.name) / "out").exists())

    def test_multiline_bearer_not_silently_removing_diff_lines(self):
        with self.assertRaises(SystemExit):
            self.run_publication({"candidate_diff": "+Bearer\n" + "A" * 30})


class ProviderClassificationTests(unittest.TestCase):
    def test_explicit_quota_remains_blocked(self):
        for body in ('{"error":{"code":"insufficient_quota"}}', "You have no credits remaining"):
            result = lite_errors.classify_ai_failure(429, body)
            self.assertEqual(result, "AI_QUOTA_EXHAUSTED")
            self.assertEqual(lite_errors.FAILURE_CLASS_VERDICT[result], "BLOCKED")

    def test_rate_limit_and_unknown_429_do_not_claim_credit_exhaustion(self):
        for body in ('{"error":{"code":"rate_limit_exceeded"}}', "", "Too many requests"):
            result = lite_errors.classify_ai_failure(429, body)
            self.assertEqual(result, "AI_PROVIDER_FAILURE")
            self.assertEqual(lite_errors.FAILURE_CLASS_VERDICT[result], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
