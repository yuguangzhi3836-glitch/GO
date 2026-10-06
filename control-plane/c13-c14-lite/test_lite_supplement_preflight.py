"""Synthetic proof of refusal boundaries; never substitutes for live C13 evidence."""
import copy
import json
import unittest

import lite_bundle
import lite_fixtures
from lite_errors import Block, Reject
from lite_supplement_preflight import check_prior, digest


def raw(value):
    return json.dumps(value, sort_keys=True).encode()


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.bundle = lite_fixtures.make_round(c13_verdict="BLOCKED")["c13_bundle"]
        self.bundle["quality_findings"] = [dict(id="C13-EVIDENCE-001", severity="BLOCKER",
                                                statement="synthetic missing scope")]
        self.files = {
            "junit.xml": b'<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="tests.test_prior" name="test_ok"/></testsuite>',
            "stdout.txt": b"synthetic passing test output",
            "test_inventory.txt": b"application/tests/test_prior.py\n",
            "database.json": raw(dict(dialect="postgresql", server_version_num=180004,
                                       candidate_sha=self.bundle["candidate_sha"])),
        }
        self.manifest = dict(candidate_sha=self.bundle["candidate_sha"],
                             application_tree=self.bundle["application_tree"],
                             exit_code=0, docker_used=True, step_outcome="success",
                             inventory="application/tests/test_prior.py", postgres_version="18.4")

    def seal(self):
        for name, field in (("junit.xml", "junit_sha256"), ("stdout.txt", "stdout_sha256"),
                            ("database.json", "database_sha256")):
            if name in self.files:
                self.manifest[field] = digest(self.files[name])
        self.files["manifest.json"] = raw(self.manifest)
        for name, field in (("junit.xml", "junit_sha256"), ("stdout.txt", "stdout_sha256"),
                            ("manifest.json", "manifest_sha256"),
                            ("test_inventory.txt", "test_inventory_sha256")):
            self.bundle["machine_job"][field] = digest(self.files[name])
            if field in self.bundle:
                self.bundle[field] = digest(self.files[name])
        self.bundle = lite_bundle.seal(self.bundle)
        expected = {k: copy.deepcopy(self.bundle[k]) for k in (
            "C13_ROOT", "candidate_sha", "application_tree", "issue_number",
            "github_run_id", "github_run_attempt", "task_id", "ledger_reference")}
        expected["c14_root"] = self.bundle["c14_prerequisite"]["c14_root"]
        return expected

    def test_valid_bound_bytes_are_not_execution_authority(self):
        bundle_raw = self.prepared()
        result = check_prior(bundle_raw, self.files, expected=self.expected)
        self.assertEqual(result["status"], "PRIOR_BYTES_VALIDATED")
        self.assertFalse(result["authorizes_any_action"])
        self.assertEqual(result["prior_passed_cases"], 1)

    def prepared(self):
        self.expected = self.seal()
        return raw(self.bundle)

    def test_service_version_literal_is_not_database_proof(self):
        del self.files["database.json"]
        expected = self.seal()
        with self.assertRaisesRegex(Block, "prior_database_unproven"):
            check_prior(raw(self.bundle), self.files, expected=expected)

    def test_sidecar_added_after_sealing_cannot_upgrade_legacy_evidence(self):
        database = self.files.pop("database.json")
        expected = self.seal()
        self.files["database.json"] = database
        with self.assertRaisesRegex(Block, "prior_database_unproven"):
            check_prior(raw(self.bundle), self.files, expected=expected)

    def test_sqlite_or_wrong_postgres_version_refuses(self):
        for dialect, version in (("sqlite",180004),("postgresql",180003)):
            self.files["database.json"] = raw(dict(dialect=dialect,server_version_num=version,
                                                  candidate_sha=self.bundle["candidate_sha"]))
            expected = self.seal()
            with self.subTest(dialect=dialect,version=version), self.assertRaisesRegex(Block,"not_postgresql_18_4"):
                check_prior(raw(self.bundle),self.files,expected=expected)

    def test_tampered_bytes_refuse(self):
        expected = self.seal()
        self.files["stdout.txt"] += b"new bytes"
        with self.assertRaisesRegex(Reject,"machine_digest_mismatch"):
            check_prior(raw(self.bundle),self.files,expected=expected)

    def test_wrong_run_attempt_candidate_root_or_c14_refuses(self):
        original = self.seal()
        for key in ("github_run_id","github_run_attempt","candidate_sha","C13_ROOT","c14_root"):
            expected = dict(original, **{key:"different"})
            with self.subTest(key=key), self.assertRaises(Reject):
                check_prior(raw(self.bundle),self.files,expected=expected)

    def test_nonzero_exit_or_boolean_zero_refuses(self):
        for code in (1, False):
            self.manifest["exit_code"] = code
            expected = self.seal()
            with self.subTest(code=code), self.assertRaisesRegex(Block,"machine_not_success"):
                check_prior(raw(self.bundle),self.files,expected=expected)

    def test_another_blocker_cannot_be_closed_as_missing_scope(self):
        self.bundle["quality_findings"].append(dict(id="OTHER",severity="BLOCKER",statement="other"))
        expected = self.seal()
        with self.assertRaisesRegex(Block,"not_inventory_only_block"):
            check_prior(raw(self.bundle),self.files,expected=expected)

    def test_skipped_missing_duplicate_or_inconsistent_junit_refuses(self):
        for xml in (
            '<testsuite tests="1" failures="0" errors="0" skipped="1"><testcase classname="x" name="y"><skipped/></testcase></testsuite>',
            '<testsuite tests="1" failures="0" errors="0" skipped="0"/>',
            '<testsuite tests="2" failures="0" errors="0" skipped="0"><testcase classname="x" name="y"/><testcase classname="x" name="y"/></testsuite>',
            '<testsuite tests="2" failures="0" errors="0" skipped="0"><testcase classname="x" name="y"/></testsuite>',
        ):
            self.files["junit.xml"] = xml.encode()
            expected = self.seal()
            with self.subTest(xml=xml), self.assertRaisesRegex(Block,"junit_not_all_pass"):
                check_prior(raw(self.bundle),self.files,expected=expected)


if __name__ == "__main__":
    unittest.main()
