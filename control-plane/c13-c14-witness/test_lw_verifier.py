"""CC ReviewVerifier: binding, artifact levels, and the run-head lesson."""
from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lw_paths  # noqa: E402

lw_paths.install()

import lw_fixtures as fx  # noqa: E402

import lite_errors  # noqa: E402
import lw_artifact  # noqa: E402


class VerificationTests(unittest.TestCase):
    def test_round_is_accepted_and_metadata_is_verified(self):
        record = fx.verify_round()
        self.assertEqual(record["decision"], "ACCEPT")
        self.assertTrue(record["artifact_metadata_verified"])
        self.assertFalse(record["artifact_bytes_verified"])
        self.assertIs(record["authorizes_any_action"], False)
        for role in ("c14", "c13"):
            self.assertEqual(record["artifact"][role]["level_1"], lw_artifact.ARTIFACT_METADATA_VERIFIED)

    def test_bytes_level_is_unavailable_without_a_capable_downloader(self):
        record = fx.verify_round()
        for role in ("c14", "c13"):
            entry = record["artifact"][role]
            self.assertEqual(entry["level_2"], lw_artifact.ARTIFACT_BYTES_UNAVAILABLE)
            self.assertEqual(entry["bytes_failure_class"], lw_artifact.ARTIFACT_BYTES_UNAVAILABLE)
            self.assertFalse(entry["bytes_verified"])
            self.assertTrue(entry["bytes_reason"])

    def test_bytes_level_passes_when_a_downloader_can_read_the_endpoint(self):
        def downloader(artifact):
            return fx.artifact_bytes("c14" if "-c14-" in artifact["name"] else "c13")

        record = fx.verify_round(downloader=downloader)
        self.assertTrue(record["artifact_bytes_verified"])
        for role in ("c14", "c13"):
            self.assertEqual(record["artifact"][role]["level_2"], lw_artifact.ARTIFACT_BYTES_VERIFIED)
            self.assertTrue(record["artifact"][role]["bytes_verified"])

    def test_bytes_download_that_returns_wrong_bytes_is_not_a_pass(self):
        record = fx.verify_round(downloader=lambda artifact: b"not the artifact")
        self.assertFalse(record["artifact_bytes_verified"])
        self.assertEqual(record["artifact"]["c14"]["level_2"], lw_artifact.ARTIFACT_BYTES_UNAVAILABLE)
        self.assertIn("artifact_bytes_digest_mismatch", record["artifact"]["c14"]["bytes_reason"])

    def test_run_head_is_the_workflow_ref_not_the_candidate(self):
        """The lesson from PR #248: asserting head_sha == candidate_sha can never hold."""
        record = fx.verify_round()
        self.assertEqual(record["artifact"]["c14"]["run"]["head_sha"], fx.WORKFLOW_REF_SHA)
        self.assertNotEqual(record["artifact"]["c14"]["run"]["head_sha"], fx.CANDIDATE_SHA)
        with self.assertRaises(lite_errors.Reject) as ctx:
            fx.verify_round(c14_run=fx.run_payload("c14", head_sha=fx.CANDIDATE_SHA))
        self.assertEqual(ctx.exception.reason, "run_head_sha_mismatch")

    def test_run_identity_and_workflow_path_are_checked(self):
        with self.assertRaises(lite_errors.Reject) as ctx:
            fx.verify_round(c14_run=dict(fx.run_payload("c14"), path=".github/workflows/other.yml"))
        self.assertEqual(ctx.exception.reason, "run_workflow_identity_mismatch")
        with self.assertRaises(lite_errors.Reject) as ctx:
            fx.verify_round(c14_run=dict(fx.run_payload("c14"), id=424242))
        self.assertEqual(ctx.exception.reason, "run_id_mismatch")

    def test_artifact_name_and_digest_are_checked(self):
        with self.assertRaises(lite_errors.Reject) as ctx:
            fx.verify_round(c14_artifact=fx.artifact_payload("c14", name="c13c14-lite-c13-" + fx.CANDIDATE_SHA))
        self.assertEqual(ctx.exception.reason, "artifact_name_mismatch")
        with self.assertRaises(lite_errors.Reject) as ctx:
            fx.verify_round(c14_expectation=fx.expectation("c14", digest="sha256:" + "9" * 64))
        self.assertEqual(ctx.exception.reason, "artifact_digest_altered")
        with self.assertRaises(lite_errors.Reject) as ctx:
            fx.verify_round(c14_artifact=fx.artifact_payload("c14", run_id=1))
        self.assertEqual(ctx.exception.reason, "artifact_run_identity_mismatch")

    def test_artifact_expiry_is_checked(self):
        with self.assertRaises(lite_errors.Reject) as ctx:
            fx.verify_round(c13_artifact=fx.artifact_payload("c13", expired=True))
        self.assertEqual(ctx.exception.reason, "artifact_expiry_mismatch")

    def test_incomplete_artifact_payload_is_a_hard_reject_not_a_soft_note(self):
        """A metadata mismatch is evidence of a wrong identity, so it refuses outright.

        Only a *bytes* level failure is a capability boundary and is merely recorded.
        """
        with self.assertRaises(lite_errors.Reject) as ctx:
            fx.verify_round(c13_artifact={"id": 1})
        self.assertIn(
            ctx.exception.reason,
            ("artifact_run_identity_mismatch", "artifact_name_mismatch", "artifact_digest_mismatch"),
        )


class MissingArtifactPayloadTests(unittest.TestCase):
    def test_no_payload_means_no_metadata_claim(self):
        import lw_verifier

        round_ = fx.bundles()
        record = lw_verifier.verify(
            c14_bundle=round_["c14_bundle"], c13_bundle=round_["c13_bundle"],
            c14_contract=round_["c14_contract"], c13_contract=round_["c13_contract"],
            dispatch=round_["dispatch"],
            implementation_execution_id=round_["implementation_execution_id"],
            artifacts=round_["artifacts"], now=round_["now"],
        )
        self.assertFalse(record["artifact_metadata_verified"])
        self.assertFalse(record["artifact_bytes_verified"])
        self.assertEqual(record["artifact"]["c14"]["bytes_reason"], "artifact_payload_not_supplied")


if __name__ == "__main__":
    unittest.main(verbosity=2)
