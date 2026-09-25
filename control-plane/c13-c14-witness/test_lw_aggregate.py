"""FinalAcceptanceAggregator: statuses, FINAL_ROOT, and the human gate."""
from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lw_paths  # noqa: E402

lw_paths.install()

import lite_errors  # noqa: E402
import lw_aggregate  # noqa: E402
import lw_fixtures as fx  # noqa: E402


class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.verification = fx.verify_round()
        self.cc = fx.cc_witness_record(self.verification)
        self.hk = fx.hk_witness_record(self.verification, self.cc)

    def test_accepted_stops_at_the_human_gate_and_never_auto_deploys(self):
        record = lw_aggregate.aggregate(verification=self.verification, cc_witness=self.cc, hk_witness=self.hk)
        self.assertEqual(record["status"], lw_aggregate.ACCEPTED)
        self.assertEqual(record["gate"], lw_aggregate.HUMAN_GATE)
        self.assertTrue(record["human_authorization_required"])
        self.assertIs(record["authorizes_any_action"], False)
        self.assertIs(record["auto_deploy"], False)
        lw_aggregate.verify_final_root(record)

    def test_hk_witness_is_optional_but_changes_the_final_root(self):
        without = lw_aggregate.aggregate(verification=self.verification, cc_witness=self.cc)
        with_hk = lw_aggregate.aggregate(verification=self.verification, cc_witness=self.cc, hk_witness=self.hk)
        self.assertEqual(without["status"], lw_aggregate.ACCEPTED)
        self.assertIsNone(without["HK_WITNESS"])
        self.assertNotEqual(without["FINAL_ROOT"], with_hk["FINAL_ROOT"])

    def test_a_non_accepted_verification_never_produces_accepted(self):
        rejected = dict(self.verification, decision="REJECT")
        blocked = dict(self.verification, decision="BLOCK")
        self.assertEqual(lw_aggregate.aggregate(verification=rejected, cc_witness=self.cc)["status"],
                         lw_aggregate.REJECTED)
        self.assertEqual(lw_aggregate.aggregate(verification=blocked, cc_witness=self.cc)["status"],
                         lw_aggregate.BLOCKED)

    def test_a_missing_cc_witness_blocks(self):
        record = lw_aggregate.aggregate(verification=self.verification, cc_witness=None)
        self.assertEqual(record["status"], lw_aggregate.BLOCKED)
        self.assertEqual(record["gate"], "CC_WITNESS_MISSING")

    def test_cc_witness_must_agree_with_the_verification(self):
        other_verification = fx.verify_round(fx.bundles())
        other_verification = dict(other_verification, c14_root="0" * 64)
        with self.assertRaises(lite_errors.Reject) as ctx:
            lw_aggregate.aggregate(verification=other_verification, cc_witness=self.cc)
        self.assertEqual(ctx.exception.reason, "cc_witness_verification_mismatch")

    def test_tampering_with_the_aggregate_is_visible_in_the_final_root(self):
        record = lw_aggregate.aggregate(verification=self.verification, cc_witness=self.cc, hk_witness=self.hk)
        for field, value in (("candidate_sha", "0" * 40), ("C14_ROOT", "0" * 64), ("C13_ROOT", "0" * 64)):
            tampered = dict(record)
            tampered[field] = value
            with self.assertRaises(lite_errors.Reject) as ctx:
                lw_aggregate.verify_final_root(tampered)
            self.assertEqual(ctx.exception.reason, "final_root_recompute_mismatch", field)

    def test_swapping_the_cc_witness_for_another_key_changes_the_root(self):
        other_cc = fx.cc_witness_record(self.verification, key=fx.cc_key("another-cc-key"))
        first = lw_aggregate.aggregate(verification=self.verification, cc_witness=self.cc)
        second = lw_aggregate.aggregate(verification=self.verification, cc_witness=other_cc)
        self.assertNotEqual(first["FINAL_ROOT"], second["FINAL_ROOT"])

    def test_the_human_gate_cannot_be_removed(self):
        record = lw_aggregate.aggregate(verification=self.verification, cc_witness=self.cc)
        record["gate"] = "DEPLOY"
        with self.assertRaises(lite_errors.Reject) as ctx:
            lw_aggregate.verify_final_root(record)
        self.assertEqual(ctx.exception.reason, "accepted_must_stop_at_the_human_gate")

    def test_auto_deploy_cannot_be_turned_on(self):
        record = lw_aggregate.aggregate(verification=self.verification, cc_witness=self.cc)
        record["auto_deploy"] = True
        with self.assertRaises(lite_errors.Reject) as ctx:
            lw_aggregate.verify_final_root(record)
        self.assertEqual(ctx.exception.reason, "auto_deploy_must_be_false")

    def test_final_root_is_reproducible(self):
        first = lw_aggregate.aggregate(verification=self.verification, cc_witness=self.cc, hk_witness=self.hk)
        second = lw_aggregate.aggregate(verification=self.verification, cc_witness=self.cc, hk_witness=self.hk)
        self.assertEqual(first["FINAL_ROOT"], second["FINAL_ROOT"])


class ArtifactLevelReportingTests(unittest.TestCase):
    def test_bytes_unavailable_is_reported_not_hidden(self):
        verification = fx.verify_round()
        cc = fx.cc_witness_record(verification)
        record = lw_aggregate.aggregate(verification=verification, cc_witness=cc)
        self.assertTrue(record["artifact_metadata_verified"])
        self.assertFalse(record["artifact_bytes_verified"])

    def test_bytes_verified_when_a_downloader_succeeds(self):
        def downloader(artifact):
            return fx.artifact_bytes("c14" if "-c14-" in artifact["name"] else "c13")

        verification = fx.verify_round(downloader=downloader)
        cc = fx.cc_witness_record(verification)
        record = lw_aggregate.aggregate(verification=verification, cc_witness=cc)
        self.assertTrue(record["artifact_metadata_verified"])
        self.assertTrue(record["artifact_bytes_verified"])


class HkWitnessTests(unittest.TestCase):
    def test_hk_witness_must_use_the_hk_purpose_and_key(self):
        import lw_hk
        import lw_witness

        verification = fx.verify_round()
        cc = fx.cc_witness_record(verification)
        record = fx.hk_witness_record(verification, cc)
        self.assertEqual(record["witness_purpose"], lw_witness.HK_PURPOSE)
        self.assertEqual(record["witness_role"], "HK")
        self.assertNotEqual(record["key_id"], cc["key_id"])
        self.assertIn("sign_hk_witness", lw_hk.HK_CAPABILITIES)
        for refusal in ("run_docker", "run_postgresql", "run_c13_or_c14_ai", "authorize_any_action"):
            self.assertIn(refusal, lw_hk.HK_REFUSALS)

    def test_hk_recomputes_the_roots_it_can(self):
        import lw_hk

        round_ = fx.bundles()
        result = lw_hk.recompute_available_hashes(bundles={"c14": round_["c14_bundle"], "c13": round_["c13_bundle"]},
                                                 first_seen=fx.first_seen(round_))
        for role in ("c14", "c13"):
            self.assertTrue(result[role]["root_matches"], role)

    def test_hk_refuses_a_cc_witness_that_disagrees(self):
        import lw_hk

        verification = fx.verify_round()
        cc = fx.cc_witness_record(verification)
        broken = dict(verification, c14_root="0" * 64)
        with self.assertRaises(lite_errors.Reject) as ctx:
            lw_hk.witness(verification=broken, cc_witness=cc, key=fx.hk_key(),
                          first_seen=fx.first_seen(), issued_at="2026-09-25T09:30:00Z")
        self.assertEqual(ctx.exception.reason, "hk_cc_witness_disagreement")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class WitnessSchemaTests(unittest.TestCase):
    def test_schema_files_are_up_to_date(self):
        import lw_schemas

        self.assertEqual(lw_schemas.check(lw_schemas.SCHEMA_DIR), [])

    def test_final_acceptance_schema_cannot_deploy(self):
        import lw_schemas

        schema = lw_schemas.final_acceptance_schema()
        self.assertEqual(schema["properties"]["auto_deploy"], {"const": False})
        self.assertEqual(schema["properties"]["authorizes_any_action"], {"const": False})
        self.assertEqual(schema["properties"]["human_authorization_required"], {"const": True})
