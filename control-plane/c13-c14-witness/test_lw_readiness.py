"""The round verdict must not be reachable by accident.

These tests pin the two things that went wrong in the two preceding rounds:
"we authenticated" being mistaken for "we can read the repository", and one host's
success being allowed to stand in for the other's.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import lw_paths  # noqa: E402

lw_paths.install()

import lw_readiness  # noqa: E402


def probe(*, present=True, user=200, repository=200, run=200, artifacts=200,
          path="/etc/x/keys/github-witness-reader.token", klass="github_pat_"):
    return {
        "credential": {"present": present, "path": path, "class": klass},
        "endpoints": {"user": user, "repository": repository, "run": run,
                      "run_artifacts": artifacts},
    }


class HostReadinessTests(unittest.TestCase):
    def test_a_fully_ready_host_is_ready(self):
        ready = lw_readiness.host_readiness(probe(), host="cc")
        self.assertTrue(ready["CC_GITHUB_API_CREDENTIAL_READY"])
        self.assertTrue(ready["CC_ARTIFACT_METADATA_VERIFIED"])
        self.assertIsNone(ready["blocked_by"])

    def test_authenticating_without_repository_access_is_not_ready(self):
        """This is the exact CC state observed on 2026-09-25: user=200, all else 404."""
        ready = lw_readiness.host_readiness(
            probe(repository=404, run=404, artifacts=404), host="cc")
        self.assertTrue(ready["authenticates"])
        self.assertFalse(ready["sees_repository"])
        self.assertFalse(ready["CC_GITHUB_API_CREDENTIAL_READY"])
        self.assertEqual(ready["blocked_by"], "credential_repository_scope")

    def test_no_credential_at_all_is_not_ready(self):
        """The exact HK state: there is no GitHub API credential on the host."""
        ready = lw_readiness.host_readiness(
            probe(present=False, user=None, repository=None, run=None, artifacts=None),
            host="hk")
        self.assertFalse(ready["HK_GITHUB_API_CREDENTIAL_READY"])
        self.assertEqual(ready["blocked_by"], "no_github_api_credential_on_host")

    def test_repository_visible_but_actions_denied_is_not_ready(self):
        ready = lw_readiness.host_readiness(probe(run=403, artifacts=403), host="cc")
        self.assertTrue(ready["sees_repository"])
        self.assertFalse(ready["CC_GITHUB_API_CREDENTIAL_READY"])
        self.assertEqual(ready["blocked_by"], "actions_read_not_granted")

    def test_artifact_metadata_verified_needs_both_reads(self):
        self.assertFalse(lw_readiness.host_readiness(
            probe(artifacts=404), host="cc")["CC_ARTIFACT_METADATA_VERIFIED"])
        self.assertFalse(lw_readiness.host_readiness(
            probe(run=404), host="cc")["CC_ARTIFACT_METADATA_VERIFIED"])

    def test_never_reports_a_credential_value(self):
        ready = lw_readiness.host_readiness(probe(), host="cc")
        self.assertTrue(ready["credential_value_redacted"])
        self.assertNotIn("token", " ".join(ready.keys()))


class RoundVerdictTests(unittest.TestCase):
    def test_both_hosts_ready_and_bytes_verified_is_ready(self):
        verdict = lw_readiness.round_verdict(
            cc=lw_readiness.host_readiness(probe(), host="cc"),
            hk=lw_readiness.host_readiness(probe(), host="hk"),
            byte_states={"ARTIFACT_BYTES_VERIFIED": True})
        self.assertEqual(verdict["RESULT"], lw_readiness.RESULT_READY)
        self.assertFalse(verdict["OWNER_ACTION_REQUIRED"])
        self.assertEqual(verdict["CCV1_145_FULL_CHAIN_SIMULATION"], "READY")

    def test_metadata_only_is_a_legal_outcome_not_a_failure(self):
        verdict = lw_readiness.round_verdict(
            cc=lw_readiness.host_readiness(probe(), host="cc"),
            hk=lw_readiness.host_readiness(probe(), host="hk"),
            byte_states={"ARTIFACT_BYTES_AVAILABLE": False,
                         "ARTIFACT_BYTES_VERIFIED": False})
        self.assertEqual(verdict["RESULT"], lw_readiness.RESULT_METADATA_ONLY)
        self.assertTrue(verdict["METADATA_WITNESS_READY"])
        self.assertFalse(verdict["BYTE_LEVEL_WITNESS_READY"])

    def test_cc_ready_alone_does_not_carry_hk(self):
        verdict = lw_readiness.round_verdict(
            cc=lw_readiness.host_readiness(probe(), host="cc"),
            hk=lw_readiness.host_readiness(probe(present=False), host="hk"))
        self.assertEqual(verdict["RESULT"], lw_readiness.RESULT_BLOCKED)
        self.assertFalse(verdict["CC_GITHUB_API_CREDENTIAL_READY"] and
                         verdict["HK_GITHUB_API_CREDENTIAL_READY"])
        self.assertTrue(verdict["OWNER_ACTION_REQUIRED"])
        self.assertEqual([entry["host"] for entry in verdict["blocked"]], ["hk"])

    def test_hk_ready_alone_does_not_carry_cc(self):
        verdict = lw_readiness.round_verdict(
            cc=lw_readiness.host_readiness(probe(repository=404, run=404,
                                                 artifacts=404), host="cc"),
            hk=lw_readiness.host_readiness(probe(), host="hk"))
        self.assertEqual(verdict["RESULT"], lw_readiness.RESULT_BLOCKED)
        self.assertEqual([entry["host"] for entry in verdict["blocked"]], ["cc"])

    def test_blocked_names_the_missing_grant_per_host(self):
        verdict = lw_readiness.round_verdict(
            cc=lw_readiness.host_readiness(probe(repository=404, run=404,
                                                 artifacts=404), host="cc"),
            hk=lw_readiness.host_readiness(probe(present=False), host="hk"))
        reasons = {entry["host"]: entry["blocked_by"] for entry in verdict["blocked"]}
        self.assertEqual(reasons["cc"], "credential_repository_scope")
        self.assertEqual(reasons["hk"], "no_github_api_credential_on_host")
        self.assertEqual(verdict["CCV1_145_FULL_CHAIN_SIMULATION"],
                         "BLOCKED_CREDENTIAL_PERMISSION")

    def test_bytes_verified_cannot_be_claimed_from_metadata(self):
        verdict = lw_readiness.round_verdict(
            cc=lw_readiness.host_readiness(probe(), host="cc"),
            hk=lw_readiness.host_readiness(probe(), host="hk"))
        self.assertFalse(verdict["BYTE_LEVEL_WITNESS_READY"])
        self.assertEqual(verdict["RESULT"], lw_readiness.RESULT_METADATA_ONLY)

    def test_verdict_never_authorises_anything(self):
        for cc, hk in ((probe(), probe()),
                       (probe(repository=404, run=404, artifacts=404), probe())):
            verdict = lw_readiness.round_verdict(
                cc=lw_readiness.host_readiness(cc, host="cc"),
                hk=lw_readiness.host_readiness(hk, host="hk"),
                byte_states={"ARTIFACT_BYTES_VERIFIED": True})
            self.assertFalse(verdict["authorizes_any_action"])
            self.assertIn(verdict["RESULT"], lw_readiness.ROUND_RESULTS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
