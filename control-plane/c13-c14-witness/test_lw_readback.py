"""The readback record: four separate artifact states, and refusals that never
collapse into a PASS.

The state model is the deliverable here. The task forbids a single ambiguous
``ARTIFACT_VERIFIED``, so every test below asserts the *combination* of the four
booleans rather than one summary value.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import lw_paths  # noqa: E402

lw_paths.install()

import lw_fake_github  # noqa: E402
import lw_readback  # noqa: E402
import lite_artifact_fetch  # noqa: E402

REPOSITORY = "yuguangzhi3836-glitch/GO"
CANDIDATE = "f" * 40
WORKFLOW = ".github/workflows/c14-rule-compliance.yml"
HEAD = "c" * 40


class ReadbackTests(unittest.TestCase):
    def _run(self, fake, **kwargs):
        options = dict(repository=REPOSITORY, role="c14", candidate_sha=CANDIDATE,
                       workflow_path=WORKFLOW, run_id=fake.run_id, token=fake.token,
                       expected_head_sha=HEAD, api_root=fake.urls["api_root"])
        options.update(kwargs)
        return lw_readback.readback_role(**options)

    def test_happy_path_sets_all_four_states(self):
        payload = lw_fake_github.make_zip({"c14_bundle.json": b"{}"})
        with lw_fake_github.FakeGitHub(zip_bytes=payload) as fake:
            record = self._run(fake)
        self.assertTrue(record["run_metadata_read"])
        self.assertTrue(record["artifact_metadata_read"])
        self.assertTrue(record["artifact_metadata_verified"])
        self.assertTrue(record["artifact_bytes_available"])
        self.assertTrue(record["artifact_bytes_hashed"])
        self.assertTrue(record["artifact_bytes_verified"])
        self.assertEqual(record["refusals"], [])
        self.assertEqual(record["artifact_identity"]["digest"],
                         "sha256:" + hashlib.sha256(payload).hexdigest())
        self.assertFalse(record["authorizes_any_action"])

    def test_metadata_verified_with_bytes_unavailable_is_a_legal_state(self):
        """Matching the task's explicit example: metadata YES, bytes NO."""
        with lw_fake_github.FakeGitHub(signed_ok=False) as fake:
            record = self._run(fake)
        self.assertTrue(record["artifact_metadata_verified"])
        self.assertFalse(record["artifact_bytes_available"])
        self.assertFalse(record["artifact_bytes_hashed"])
        self.assertFalse(record["artifact_bytes_verified"])
        self.assertEqual(record["bytes_failure_class"],
                         lite_artifact_fetch.STORAGE_REJECTED_CREDENTIAL)
        self.assertIn("bytes_ARTIFACT_BYTES_STORAGE_REJECTED_CREDENTIAL",
                      record["refusals"])
        # a byte failure must not become a false PASS anywhere in the record
        self.assertNotIn("verified", [k for k, v in record.items()
                                      if k.startswith("artifact_bytes") and v is True])

    def test_unreadable_repository_is_refused_at_the_first_read(self):
        """The real CC symptom: 404 on the run, because the repo is not in scope."""
        with lw_fake_github.FakeGitHub(run_lookup_http=404) as fake:
            record = self._run(fake)
        self.assertFalse(record["run_metadata_read"])
        self.assertFalse(record["artifact_metadata_verified"])
        self.assertIn("run_metadata_http_404", record["refusals"])

    def test_run_head_is_not_compared_against_the_candidate(self):
        """The run head is the workflow ref commit. Comparing it to the candidate is
        the exact error this round fixes; a mismatch against expected_head_sha is a
        refusal, and the candidate never appears in that comparison."""
        with lw_fake_github.FakeGitHub() as fake:
            record = self._run(fake, expected_head_sha=HEAD)
            self.assertNotIn("run_head_sha_mismatch", record["refusals"])
            wrong = self._run(fake, expected_head_sha="d" * 40)
            self.assertIn("run_head_sha_mismatch", wrong["refusals"])
            # and the candidate is carried verbatim, separately from the head
            self.assertEqual(wrong["candidate_sha"], CANDIDATE)
            self.assertEqual(wrong["run"]["head_sha"], HEAD)

    def test_artifact_from_another_run_is_refused(self):
        with lw_fake_github.FakeGitHub(artifact_run_id=999) as fake:
            record = self._run(fake)
        self.assertFalse(record["artifact_metadata_verified"])
        self.assertIn("artifact_artifact_run_identity_mismatch", record["refusals"])

    def test_expired_artifact_is_refused(self):
        with lw_fake_github.FakeGitHub(artifact_expired=True) as fake:
            record = self._run(fake)
        self.assertFalse(record["artifact_metadata_verified"])
        self.assertIn("artifact_artifact_expiry_mismatch", record["refusals"])

    def test_missing_artifact_is_refused_with_the_expected_name(self):
        with lw_fake_github.FakeGitHub(artifact_name="some-other-name") as fake:
            record = self._run(fake)
        self.assertIn("artifact_not_found", record["refusals"])
        self.assertEqual(record["expected_artifact_name"],
                         f"c13c14-lite-c14-{CANDIDATE}")

    def test_failed_run_is_refused(self):
        with lw_fake_github.FakeGitHub(run_conclusion="failure") as fake:
            record = self._run(fake)
        self.assertIn("run_conclusion_not_success", record["refusals"])

    def test_digest_tamper_after_metadata_read_is_caught_by_the_bytes(self):
        """Metadata can agree while the bytes disagree: the byte level is what binds."""
        payload = lw_fake_github.make_zip({"a": b"1"})
        with lw_fake_github.FakeGitHub(zip_bytes=payload,
                                       artifact_digest="sha256:" + "0" * 64) as fake:
            record = self._run(fake)
        self.assertTrue(record["artifact_metadata_verified"])
        self.assertTrue(record["artifact_bytes_available"])
        self.assertTrue(record["artifact_bytes_hashed"])
        self.assertFalse(record["artifact_bytes_verified"])
        self.assertEqual(record["bytes_failure_class"],
                         lite_artifact_fetch.BYTES_DIGEST_MISMATCH)
        self.assertTrue(record["artifact_bytes_sha256"].startswith("sha256:"))

    def test_metadata_only_mode_never_claims_bytes(self):
        with lw_fake_github.FakeGitHub() as fake:
            record = self._run(fake, fetch_bytes=False)
        self.assertTrue(record["artifact_metadata_verified"])
        self.assertFalse(record["artifact_bytes_available"])
        self.assertFalse(record["artifact_bytes_verified"])
        self.assertIsNone(record["artifact_bytes_sha256"])

    def test_workflow_identity_mismatch_is_refused(self):
        with lw_fake_github.FakeGitHub() as fake:
            record = self._run(fake, workflow_path=".github/workflows/other.yml")
        self.assertIn("run_workflow_identity_mismatch", record["refusals"])

    def test_the_record_contains_no_signed_url(self):
        with lw_fake_github.FakeGitHub() as fake:
            record = self._run(fake)
        serialised = json.dumps(record)
        self.assertNotIn("sig=", serialised)
        self.assertNotIn(fake.token, serialised)
        self.assertEqual(record["redirect_host_category"], "other")


class CapabilityProbeTests(unittest.TestCase):
    def test_probe_reports_each_endpoint_separately(self):
        with lw_fake_github.FakeGitHub() as fake:
            probe = lw_readback.capability_probe(
                repository=REPOSITORY, token=fake.token, run_id=fake.run_id,
                api_root=fake.urls["api_root"])
        self.assertTrue(probe["user"]["ok"])
        self.assertTrue(probe["run"]["ok"])
        self.assertTrue(probe["run_artifacts"]["ok"])

    def test_probe_records_a_404_rather_than_raising(self):
        with lw_fake_github.FakeGitHub(run_lookup_http=404) as fake:
            probe = lw_readback.capability_probe(
                repository=REPOSITORY, token=fake.token, run_id=fake.run_id,
                api_root=fake.urls["api_root"])
        self.assertEqual(probe["run"], {"http": 404, "ok": False})
        self.assertTrue(probe["user"]["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
