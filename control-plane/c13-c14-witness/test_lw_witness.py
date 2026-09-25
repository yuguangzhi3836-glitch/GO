"""Witness key hygiene, the witness record, and first-seen semantics."""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lw_paths  # noqa: E402

lw_paths.install()

import lite_errors  # noqa: E402
import lw_fixtures as fx  # noqa: E402
import lw_witness  # noqa: E402


class WitnessKeyTests(unittest.TestCase):
    def test_key_is_ed25519_with_an_explicit_purpose(self):
        key = fx.cc_key()
        self.assertEqual(key.purpose, lw_witness.CC_PURPOSE)
        self.assertTrue(key.public_pem.startswith("-----BEGIN PUBLIC KEY-----"))
        self.assertEqual(len(key.key_id), 16)

    def test_same_seed_gives_the_same_identity_and_different_seeds_do_not(self):
        self.assertEqual(fx.cc_key("a").key_id, fx.cc_key("a").key_id)
        self.assertNotEqual(fx.cc_key("a").key_id, fx.cc_key("b").key_id)

    def test_cc_and_hk_keys_are_different_keys_with_different_purposes(self):
        cc, hk = fx.cc_key(), fx.hk_key()
        self.assertNotEqual(cc.key_id, hk.key_id)
        self.assertNotEqual(cc.purpose, hk.purpose)
        self.assertNotEqual(lw_witness.CC_PURPOSE, lw_witness.HK_PURPOSE)

    def test_key_never_exposes_private_material(self):
        key = fx.cc_key()
        text = repr(key)
        self.assertIn("<redacted>", text)
        self.assertNotIn("PRIVATE", key.public_pem)
        self.assertFalse(hasattr(key, "private_pem"))
        self.assertFalse(hasattr(key, "private_key_pem"))
        # The public surface is exactly purpose / key_id / public_pem / sign / verify.
        self.assertNotIn("BEGIN PRIVATE KEY", json.dumps(
            {"key_id": key.key_id, "public_key_pem": key.public_pem, "purpose": key.purpose}
        ))

    def test_signature_verification_round_trip(self):
        key = fx.cc_key()
        payload = lw_witness.lite_canonical.canonical({"a": 1})
        signature = key.sign(payload)
        self.assertTrue(lw_witness.WitnessKey.verify(key.public_pem, payload, signature))
        self.assertFalse(lw_witness.WitnessKey.verify(key.public_pem, payload + b" ", signature))


class WitnessRecordTests(unittest.TestCase):
    def test_cc_witness_verifies_and_never_authorises(self):
        verification = fx.verify_round()
        record = fx.cc_witness_record(verification)
        lw_witness.verify_witness(record)
        self.assertIs(record["authorizes_any_action"], False)
        self.assertEqual(record["witness_role"], "CC")
        self.assertEqual(record["C14_ROOT"], verification["c14_root"])
        self.assertEqual(record["first_seen"]["candidate_sha"], record["candidate_sha"])

    def test_tampering_with_any_witnessed_field_breaks_the_signature(self):
        for field, value in (("candidate_sha", "0" * 40), ("C14_ROOT", "0" * 64),
                             ("C13_ROOT", "0" * 64), ("issued_at", "2030-01-01T00:00:00Z")):
            record = fx.cc_witness_record()
            record[field] = value
            with self.assertRaises(lite_errors.Reject) as ctx:
                lw_witness.verify_witness(record)
            self.assertEqual(ctx.exception.reason, "witness_signature_invalid", field)

    def test_witness_cannot_authorise_an_action(self):
        record = fx.cc_witness_record()
        record["authorizes_any_action"] = True
        with self.assertRaises(lite_errors.Reject) as ctx:
            lw_witness.verify_witness(record)
        self.assertEqual(ctx.exception.reason, "authorizes_any_action_must_be_false")

    def test_first_seen_candidate_must_match_the_witness(self):
        record = fx.cc_witness_record()
        record["first_seen"] = dict(record["first_seen"], candidate_sha="1" * 40)
        with self.assertRaises(lite_errors.Reject) as ctx:
            lw_witness.verify_witness(record)
        self.assertIn(ctx.exception.reason, ("witness_signature_invalid", "witness_first_seen_candidate_mismatch"))

    def test_a_non_accepted_verification_cannot_be_witnessed(self):
        verification = fx.verify_round()
        verification["decision"] = "BLOCK"
        with self.assertRaises(lite_errors.Reject) as ctx:
            fx.cc_witness_record(verification)
        self.assertEqual(ctx.exception.reason, "cannot_witness_a_non_accepted_verification")


class FirstSeenLedgerTests(unittest.TestCase):
    def test_first_seen_then_unchanged_then_conflict(self):
        ledger = lw_witness.FirstSeenLedger()
        entry = fx.first_seen()
        self.assertEqual(ledger.observe(entry), "FIRST_SEEN")
        self.assertEqual(ledger.observe(dict(entry)), "UNCHANGED")
        rewritten = dict(entry, c14_root="0" * 64)
        self.assertEqual(ledger.observe(rewritten), "CONFLICT")
        # A conflict is never applied.
        self.assertEqual(len(ledger.entries), 1)
        self.assertEqual(ledger.entries[0]["c14_root"], entry["c14_root"])

    def test_a_different_execution_is_a_new_first_seen(self):
        ledger = lw_witness.FirstSeenLedger()
        entry = fx.first_seen()
        ledger.observe(entry)
        other = dict(entry, c14_run_id=999999)
        self.assertEqual(ledger.observe(other), "FIRST_SEEN")
        self.assertEqual(len(ledger.entries), 2)

    def test_ledger_round_trip_and_rewrite_detection(self):
        ledger = lw_witness.FirstSeenLedger()
        ledger.observe(fx.first_seen())
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "ledger.json"
            payload = ledger.dump(path)
            reloaded = lw_witness.FirstSeenLedger.load(path)
            self.assertEqual(reloaded.root(), ledger.root())
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["entries"][0]["c14_root"] = "0" * 64
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(lite_errors.Reject) as ctx:
                lw_witness.FirstSeenLedger.load(path)
            self.assertEqual(ctx.exception.reason, "first_seen_ledger_root_mismatch")
            self.assertIn("LEDGER_ROOT", payload)

    def test_incomplete_entry_is_refused(self):
        ledger = lw_witness.FirstSeenLedger()
        with self.assertRaises(lite_errors.Reject):
            ledger.observe({"candidate_sha": "x"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
