"""CCV1-145 full-chain simulation tests.

The chain under test: real candidate -> local C14/C13 records -> CC ReviewVerifier ->
CC witness -> HK witness -> FinalAcceptanceAggregator -> FINAL_ROOT -> human gate.

Two properties get most of the attention here:

* the human gate cannot be stepped over, and ``FINAL_ROOT`` moves if any leaf moves;
* "this execution carrier has no GitHub artifact" is a state the data must state
  plainly, and cannot be dressed up as "verified".
"""
from __future__ import annotations

import base64
import hashlib
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

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

import lite_fixtures  # noqa: E402
from lite_errors import Reject  # noqa: E402

import lw_aggregate  # noqa: E402
import lw_chain  # noqa: E402
import lw_hk  # noqa: E402
import lw_host_witness  # noqa: E402
import lw_witness  # noqa: E402


def key_file(directory, name, seed):
    private = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(seed.encode()).digest())
    path = pathlib.Path(directory) / name
    path.write_bytes(private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    return path


def synthetic_package(**overrides) -> dict:
    candidate = {
        "sha": lite_fixtures.CANDIDATE_SHA,
        "application_tree": lite_fixtures.APPLICATION_TREE,
        "source": "synthetic-fixture",
        "is_real_commit": False,
    }
    round_ = lite_fixtures.make_round(**overrides)
    return lw_chain.build_task_package(round_, candidate=candidate)


def reseal_witness(record, key):
    """Re-sign a mutated witness so a test reaches the check it means to reach."""
    clone = dict(record)
    clone.pop("signature", None)
    clone["signature"] = key.sign(lw_witness._body(clone))
    return clone


class ChainTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.package = synthetic_package()
        self.verification = lw_chain.verify_from_package(self.package)
        self.cc_key_path = key_file(self.directory, "cc.pem", "chain-test-cc")
        self.hk_key_path = key_file(self.directory, "hk.pem", "chain-test-hk")

    def witnessed(self):
        cc, _ = lw_host_witness.run(role="cc", package=self.package,
                                    private_key_path=self.cc_key_path)
        hk, _ = lw_host_witness.run(role="hk", package=self.package,
                                    private_key_path=self.hk_key_path, cc_witness=cc)
        return cc, hk

    # --- the positive chain --------------------------------------------------
    def test_the_verification_is_accepted(self):
        self.assertEqual(self.verification["decision"], "ACCEPT", self.verification["rejects"])

    def test_chain_reaches_the_human_gate_with_both_witnesses(self):
        cc, hk = self.witnessed()
        record = lw_chain.finalise(verification=self.verification, cc_witness=cc, hk_witness=hk)
        self.assertEqual(record["status"], lw_aggregate.ACCEPTED)
        self.assertEqual(record["gate"], lw_aggregate.HUMAN_GATE)
        self.assertTrue(record["human_authorization_required"])
        self.assertIs(record["authorizes_any_action"], False)
        self.assertIs(record["auto_deploy"], False)
        self.assertRegex(record["FINAL_ROOT"], r"^[0-9a-f]{64}$")

    def test_the_two_hosts_sign_with_distinct_keys(self):
        cc, hk = self.witnessed()
        self.assertNotEqual(cc["key_id"], hk["key_id"])
        self.assertEqual(cc["witness_purpose"], lw_witness.CC_PURPOSE)
        self.assertEqual(hk["witness_purpose"], lw_witness.HK_PURPOSE)

    def test_one_key_used_for_both_roles_is_visible_as_such(self):
        cc, _ = lw_host_witness.run(role="cc", package=self.package,
                                    private_key_path=self.cc_key_path)
        hk, _ = lw_host_witness.run(role="hk", package=self.package,
                                    private_key_path=self.cc_key_path, cc_witness=cc)
        summary = lw_chain.summary(package=self.package, verification=self.verification,
                                   cc_witness=cc, hk_witness=hk)
        self.assertFalse(summary["cc_hk_keys_distinct"])

    def test_final_root_moves_when_any_leaf_moves(self):
        cc, hk = self.witnessed()
        record = lw_chain.finalise(verification=self.verification, cc_witness=cc, hk_witness=hk)

        mutated = json.loads(json.dumps(record))
        mutated["C14_ROOT"] = "0" * 64
        with self.assertRaises(Reject) as ctx:
            lw_aggregate.verify_final_root(mutated)
        self.assertEqual(ctx.exception.reason, "final_root_recompute_mismatch")

        mutated = json.loads(json.dumps(record))
        mutated["candidate_sha"] = lite_fixtures.OTHER_CANDIDATE_SHA
        with self.assertRaises(Reject):
            lw_aggregate.verify_final_root(mutated)

    # --- the artifact binding is stated, not glossed -------------------------
    def test_artifact_binding_is_not_applicable_and_empty(self):
        cc, hk = self.witnessed()
        for witness in (cc, hk):
            for role in ("c14", "c13"):
                meta = witness["artifact_metadata"][role]
                self.assertEqual(meta["binding"], lw_witness.ARTIFACT_BINDING_NOT_APPLICABLE)
                self.assertTrue(meta["reason"])
                for field in ("artifact_id", "artifact_name", "artifact_digest", "run_id"):
                    self.assertIsNone(meta[field], f"{role}.{field}")

    def test_no_artifact_means_no_verified_claim(self):
        cc, hk = self.witnessed()
        record = lw_chain.finalise(verification=self.verification, cc_witness=cc, hk_witness=hk)
        self.assertFalse(record["artifact_metadata_verified"])
        self.assertFalse(record["artifact_bytes_verified"])

    def test_a_github_binding_without_an_identity_is_rejected(self):
        cc, _ = self.witnessed()
        key = lw_witness.WitnessKey.from_private_pem(self.cc_key_path, lw_witness.CC_PURPOSE)
        broken = json.loads(json.dumps(cc))
        broken["artifact_metadata"]["c14"]["binding"] = lw_witness.ARTIFACT_BINDING_GITHUB
        with self.assertRaises(Reject) as ctx:
            lw_witness.verify_witness(reseal_witness(broken, key))
        self.assertEqual(ctx.exception.reason, "witness_github_binding_incomplete")

    def test_a_not_applicable_binding_carrying_an_identity_is_rejected(self):
        cc, _ = self.witnessed()
        key = lw_witness.WitnessKey.from_private_pem(self.cc_key_path, lw_witness.CC_PURPOSE)
        broken = json.loads(json.dumps(cc))
        broken["artifact_metadata"]["c13"]["artifact_digest"] = "sha256:" + "a" * 64
        with self.assertRaises(Reject) as ctx:
            lw_witness.verify_witness(reseal_witness(broken, key))
        self.assertEqual(ctx.exception.reason, "witness_not_applicable_must_be_empty")

    def test_an_unknown_binding_is_rejected(self):
        cc, _ = self.witnessed()
        key = lw_witness.WitnessKey.from_private_pem(self.cc_key_path, lw_witness.CC_PURPOSE)
        broken = json.loads(json.dumps(cc))
        broken["artifact_metadata"]["c14"]["binding"] = "PROBABLY_FINE"
        with self.assertRaises(Reject) as ctx:
            lw_witness.verify_witness(reseal_witness(broken, key))
        self.assertEqual(ctx.exception.reason, "witness_artifact_binding_unknown")

    def test_hk_refuses_when_cc_says_not_applicable_but_hk_verified_an_artifact(self):
        """A CC witness cannot excuse HK from checking for itself."""
        import lw_fixtures

        cc, _ = self.witnessed()
        verified = lw_fixtures.verify_round()
        self.assertTrue(verified["artifact_metadata_verified"])
        with self.assertRaises(Reject) as ctx:
            lw_hk.compare_with_cc(cc, verified)
        self.assertEqual(ctx.exception.reason, "hk_cc_artifact_binding_disagreement")

    # --- tampering -----------------------------------------------------------
    def test_tampered_opinion_bytes_are_caught_by_the_backend(self):
        package = json.loads(json.dumps(self.package))
        other = lite_witness_opinion()
        package["artifacts"]["c14_opinion"] = base64.b64encode(other).decode("ascii")
        verification = lw_chain.verify_from_package(package)
        self.assertEqual(verification["decision"], "REJECT")
        self.assertIn("artifact_digest_tamper",
                      [r["reason"] for r in verification["rejects"]])

    def test_tampered_machine_evidence_is_caught_by_the_backend(self):
        package = json.loads(json.dumps(self.package))
        package["artifacts"]["junit"] = base64.b64encode(b"<testsuite/>").decode("ascii")
        verification = lw_chain.verify_from_package(package)
        self.assertEqual(verification["decision"], "REJECT")

    def test_tampered_bundle_root_is_caught(self):
        package = json.loads(json.dumps(self.package))
        package["c14_bundle"]["C14_ROOT"] = "0" * 64
        verification = lw_chain.verify_from_package(package)
        self.assertEqual(verification["decision"], "REJECT")

    def test_a_witness_over_a_different_candidate_is_rejected(self):
        cc, hk = self.witnessed()
        verification = dict(self.verification)
        verification["candidate_sha"] = lite_fixtures.OTHER_CANDIDATE_SHA
        with self.assertRaises(Reject) as ctx:
            lw_chain.finalise(verification=verification, cc_witness=cc, hk_witness=hk)
        self.assertEqual(ctx.exception.reason, "cc_witness_verification_mismatch")

    def test_a_tampered_cc_witness_is_rejected(self):
        cc, hk = self.witnessed()
        broken = json.loads(json.dumps(cc))
        broken["C13_ROOT"] = "0" * 64
        with self.assertRaises(Reject) as ctx:
            lw_chain.finalise(verification=self.verification, cc_witness=broken, hk_witness=hk)
        self.assertEqual(ctx.exception.reason, "witness_signature_invalid")

    def test_a_tampered_hk_witness_is_rejected(self):
        cc, hk = self.witnessed()
        broken = json.loads(json.dumps(hk))
        broken["C14_ROOT"] = "0" * 64
        with self.assertRaises(Reject) as ctx:
            lw_chain.finalise(verification=self.verification, cc_witness=cc, hk_witness=broken)
        self.assertEqual(ctx.exception.reason, "witness_signature_invalid")

    def test_an_hk_witness_from_a_different_round_is_rejected(self):
        cc, hk = self.witnessed()
        # A different round: new nonces move both roots. Without that the two rounds
        # would be byte-identical and this test would pass for the wrong reason.
        other = synthetic_package(c14_nonce="other-c14-nonce-00000001",
                                  c13_nonce="other-c13-nonce-00000001")
        other_cc, _ = lw_host_witness.run(role="cc", package=other,
                                          private_key_path=self.cc_key_path)
        other_hk, _ = lw_host_witness.run(role="hk", package=other,
                                          private_key_path=self.hk_key_path,
                                          cc_witness=other_cc)
        self.assertNotEqual(other_hk["C14_ROOT"], cc["C14_ROOT"])
        self.assertEqual(other_hk["candidate_sha"], cc["candidate_sha"])
        with self.assertRaises(Reject) as ctx:
            lw_chain.finalise(verification=self.verification, cc_witness=cc,
                              hk_witness=other_hk)
        self.assertEqual(ctx.exception.reason, "hk_witness_cc_witness_mismatch")

    def test_final_root_rejects_a_forged_acceptance_that_skipped_the_gate(self):
        cc, hk = self.witnessed()
        record = lw_chain.finalise(verification=self.verification, cc_witness=cc, hk_witness=hk)
        forged = json.loads(json.dumps(record))
        forged["gate"] = "DEPLOY"
        with self.assertRaises(Reject) as ctx:
            lw_aggregate.verify_final_root(forged)
        self.assertEqual(ctx.exception.reason, "accepted_must_stop_at_the_human_gate")

    # --- the package ---------------------------------------------------------
    def test_a_package_whose_candidate_disagrees_with_the_bundles_is_refused(self):
        round_ = lite_fixtures.make_round()
        with self.assertRaises(Reject) as ctx:
            lw_chain.build_task_package(round_, candidate={
                "sha": lite_fixtures.OTHER_CANDIDATE_SHA,
                "application_tree": lite_fixtures.APPLICATION_TREE,
                "source": "synthetic",
                "is_real_commit": False,
            })
        self.assertEqual(ctx.exception.reason, "task_package_candidate_mismatch")

    def test_an_incomplete_package_is_refused(self):
        broken = json.loads(json.dumps(self.package))
        del broken["dispatch"]
        path = pathlib.Path(self.directory) / "broken.json"
        path.write_text(json.dumps(broken), encoding="utf-8")
        with self.assertRaises(Reject) as ctx:
            lw_chain.load_package(path)
        self.assertEqual(ctx.exception.reason, "task_package_incomplete")

    def test_the_package_carries_every_artifact_the_root_binds(self):
        self.assertEqual(self.package["artifact_names"],
                         sorted(self.package["artifacts"]))
        for name in ("c14_opinion", "c13_opinion", "junit", "stdout", "manifest"):
            self.assertIn(name, self.package["artifacts"])
        self.assertEqual(self.package["machine_evidence_names"], ["junit", "stdout", "manifest"])
        self.assertEqual(self.package["opinion_artifact_names"], ["c14_opinion", "c13_opinion"])

    def test_the_package_declares_what_is_simulated(self):
        labels = self.package["labels"]
        self.assertEqual(labels["C13_C14_BUNDLE_SOURCE"], lw_chain.EXECUTION_CARRIER_LOCAL)
        self.assertEqual(labels["REAL_C13_C14_VERDICT"], "NOT_TESTED")
        self.assertIs(labels["C13_PRODUCTION_WORKFLOW_DISPATCHED"], False)
        self.assertIs(labels["C14_PRODUCTION_WORKFLOW_DISPATCHED"], False)
        self.assertIs(labels["PR247_IS_EVIDENCE"], False)

    def test_first_seen_digests_are_over_real_bundle_bytes(self):
        entry = self.package["first_seen"]
        self.assertEqual(entry["artifact_digest_binding"], "SEALED_BUNDLE_BYTES")
        self.assertEqual(entry["execution_identity_binding"], "SIMULATED_LOCAL_BACKEND")
        from lite_canonical import canonical

        expected = "sha256:" + hashlib.sha256(canonical(self.package["c14_bundle"])).hexdigest()
        self.assertEqual(entry["c14_artifact_digest"], expected)

    def test_an_expired_round_does_not_reach_the_gate(self):
        late = lite_chain_instant(self.package, hours=3)
        package = json.loads(json.dumps(self.package))
        package["now"] = late
        verification = lw_chain.verify_from_package(package)
        self.assertEqual(verification["decision"], "REJECT")
        record = lw_chain.aggregate_round(verification=verification, cc_witness=None)
        self.assertEqual(record["status"], lw_aggregate.REJECTED)
        self.assertEqual(record["gate"], "NOT_ACCEPTED")

    def test_a_missing_cc_witness_blocks_acceptance(self):
        record = lw_chain.aggregate_round(verification=self.verification, cc_witness=None)
        self.assertEqual(record["status"], lw_aggregate.BLOCKED)
        self.assertEqual(record["gate"], "CC_WITNESS_MISSING")

    def test_final_root_alone_cannot_detect_a_recomputed_forgery(self):
        """The root algorithm is public, so integrity is not authenticity.

        An attacker who edits a witness can recompute FINAL_ROOT and satisfy the
        integrity check. Only the signatures, which need the hosts' private keys, can
        tell a forged record from a real one. This test pins both halves so that a
        future consumer cannot quietly start trusting the root alone.
        """
        cc, hk = self.witnessed()
        record = lw_chain.finalise(verification=self.verification, cc_witness=cc, hk_witness=hk)
        forged = json.loads(json.dumps(record))
        forged["CC_WITNESS"]["C13_ROOT"] = "0" * 64
        forged["FINAL_ROOT"] = lw_aggregate._final_root(forged)

        lw_aggregate.verify_final_root(forged)  # integrity layer is satisfied

        with self.assertRaises(Reject) as ctx:
            lw_aggregate.verify_record(forged)
        self.assertEqual(ctx.exception.reason, "witness_signature_invalid")

    def test_verify_record_rejects_a_record_without_a_cc_witness(self):
        cc, hk = self.witnessed()
        record = lw_chain.finalise(verification=self.verification, cc_witness=cc, hk_witness=hk)
        forged = json.loads(json.dumps(record))
        forged["CC_WITNESS"] = None
        forged["FINAL_ROOT"] = lw_aggregate._final_root(forged)
        lw_aggregate.verify_final_root(forged)  # still internally consistent
        with self.assertRaises(Reject) as ctx:
            lw_aggregate.verify_record(forged)
        self.assertEqual(ctx.exception.reason, "cc_witness_missing")

    def test_verify_record_checks_the_hk_witness_against_cc(self):
        """A valid HK witness from another round must not be able to replace this one."""
        cc, hk = self.witnessed()
        record = lw_chain.finalise(verification=self.verification, cc_witness=cc, hk_witness=hk)
        other = synthetic_package(c14_nonce="other-c14-nonce-00000002",
                                  c13_nonce="other-c13-nonce-00000002")
        other_cc, _ = lw_host_witness.run(role="cc", package=other,
                                          private_key_path=self.cc_key_path)
        other_hk, _ = lw_host_witness.run(role="hk", package=other,
                                          private_key_path=self.hk_key_path,
                                          cc_witness=other_cc)
        self.assertNotEqual(other_hk["C14_ROOT"], cc["C14_ROOT"])

        forged = json.loads(json.dumps(record))
        forged["HK_WITNESS"] = other_hk
        forged["FINAL_ROOT"] = lw_aggregate._final_root(forged)
        lw_aggregate.verify_final_root(forged)  # internally consistent again
        with self.assertRaises(Reject) as ctx:
            lw_aggregate.verify_record(forged)
        self.assertEqual(ctx.exception.reason, "hk_witness_cc_witness_mismatch")


def lite_witness_opinion() -> bytes:
    import lite_canonical

    return lite_canonical.canonical({"role": "c14", "verdict": "PASS_SCOPED",
                                     "forged": True})


def lite_chain_instant(package, *, hours):
    from datetime import timedelta

    return lw_chain.iso(lw_chain.parse_instant(package["now"]) + timedelta(hours=hours))


if __name__ == "__main__":
    unittest.main(verbosity=2)
