import hashlib
import importlib.util
from pathlib import Path
import tempfile
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import unittest

SCRIPT = Path(__file__).with_name("verify_execution_receipt.py")
spec = importlib.util.spec_from_file_location("receipt_verifier", SCRIPT)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class WorkerLivenessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def receipt(self, **changes):
        log = self.root / "worker.log"
        log.write_text("bounded C12 worker output\n")
        value = {
            "cell_id": "C12", "task_id": "V70-R3-C12-01", "agent": "/root/cell_c12",
            "canonical_base": verifier.CANONICAL_BASE,
            "fixed_candidate_sha": verifier.FIXED_CANDIDATE_SHA,
            "application_git_tree": verifier.APPLICATION_GIT_TREE,
            "application_source_fingerprint_sha256": verifier.APPLICATION_SOURCE_FINGERPRINT_SHA256,
            "status": "RUNNING", "acknowledged_at": "2026-09-16T02:00:00Z",
            "started_at": "2026-09-16T02:00:01Z", "heartbeat_at": "2026-09-16T02:04:00Z",
            "execution_evidence": [{"kind": "PROCESS_OUTPUT", "path": log.name,
                                    "sha256": hashlib.sha256(log.read_bytes()).hexdigest()}],
        }
        value.update(changes)
        return value

    def check(self, value, observed="2026-09-16T02:05:00Z"):
        return verifier.verify(value, self.root, expected_cell="C12", expected_task="V70-R3-C12-01",
                               expected_agent="/root/cell_c12", observed_at=observed,
                               max_heartbeat_age_seconds=300)

    def test_fresh_heartbeat_admits_record_without_authentication_or_live_claim(self):
        result = self.check(self.receipt())
        self.assertEqual(result["gate"], "PASS_SCOPED")
        self.assertTrue(result["heartbeat_fresh"])
        self.assertFalse(result["authenticated_worker_identity"])
        self.assertFalse(result["live_worker_liveness_verified"])
        self.assertIsNone(result["required_transition"])

    def test_expired_heartbeat_marks_running_stale_and_holds(self):
        result = self.check(self.receipt(heartbeat_at="2026-09-16T02:00:02Z"), "2026-09-16T02:10:00Z")
        self.assertEqual(result["gate"], "HOLD")
        self.assertTrue(result["stale_running"])
        self.assertEqual(result["required_transition"], "STALE")
        self.assertIn("must not remain RUNNING", " ".join(result["errors"]))

    def test_stale_transition_never_claims_identity_authentication(self):
        result = self.check(self.receipt(heartbeat_at="2026-09-16T02:00:02Z"), "2026-09-16T02:10:00Z")
        self.assertEqual(result["required_transition"], "STALE")
        self.assertFalse(result["authenticated_worker_identity"])
        self.assertFalse(result["live_worker_liveness_verified"])

    def test_future_or_missing_heartbeat_is_not_admitted(self):
        self.assertEqual(self.check(self.receipt(heartbeat_at="2026-09-16T02:06:00Z"))["gate"], "HOLD")
        self.assertEqual(self.check(self.receipt(heartbeat_at=None))["gate"], "HOLD")

    def test_receipt_consistency_still_does_not_authenticate_identity(self):
        result = self.check(self.receipt(agent="claimed-worker"))
        self.assertEqual(result["gate"], "HOLD")
        self.assertFalse(result["authenticated_worker_identity"])


class SignedWorkerIdentityAssertionTests(unittest.TestCase):
    KEY = b"c12-isolated-test-trust-key-32-bytes-minimum"
    EXPECTED = {
        "worker_id": "worker-c12-01",
        "task_id": "V70-R4-C12-03",
        "candidate_sha": "9b3f3b023e7e67fad39b105b72811f2952c62689",
    }

    def assertion(self, **changes):
        value = {
            "algorithm": verifier.IDENTITY_ASSERTION_ALGORITHM,
            "key_id": "c12-test-key",
            **self.EXPECTED,
            "nonce": "nonce-c12-00000001",
            "issued_at": "2026-09-16T09:00:00Z",
            "expires_at": "2026-09-16T09:05:00Z",
        }
        value.update(changes)
        value["signature"] = verifier.sign_identity_assertion(value, self.KEY)
        return value

    def check(self, assertion, seen=None, observed="2026-09-16T09:02:00Z"):
        return verifier.verify_identity_assertion(
            assertion,
            trusted_keys={"c12-test-key": self.KEY},
            expected_worker_id=self.EXPECTED["worker_id"],
            expected_task_id=self.EXPECTED["task_id"],
            expected_candidate_sha=self.EXPECTED["candidate_sha"],
            observed_at=observed,
            seen_nonces=seen,
        )

    def test_valid_signature_authenticates_assertion_but_not_live_process(self):
        result = self.check(self.assertion())
        self.assertEqual(result["gate"], "PASS_SCOPED")
        self.assertTrue(result["authenticated_worker_identity"])
        self.assertTrue(result["assertion_signature_verified"])
        self.assertFalse(result["live_worker_liveness_verified"])

    def test_tampered_identity_or_candidate_fails_closed(self):
        assertion = self.assertion()
        assertion["worker_id"] = "other-worker"
        result = self.check(assertion)
        self.assertEqual(result["gate"], "HOLD")
        self.assertFalse(result["authenticated_worker_identity"])
        self.assertIn("signature mismatch", " ".join(result["errors"]))

    def test_unknown_key_and_malformed_signature_are_rejected(self):
        assertion = self.assertion(key_id="untrusted")
        result = self.check(assertion)
        self.assertEqual(result["gate"], "HOLD")
        assertion = self.assertion()
        assertion["signature"] = "not-a-signature"
        self.assertEqual(self.check(assertion)["gate"], "HOLD")

    def test_expired_future_and_overlong_assertions_are_rejected(self):
        self.assertEqual(self.check(
            self.assertion(expires_at="2026-09-16T09:01:00Z"))["gate"], "HOLD")
        self.assertEqual(self.check(
            self.assertion(issued_at="2026-09-16T09:03:00Z"))["gate"], "HOLD")
        self.assertEqual(self.check(
            self.assertion(expires_at="2026-09-16T09:10:00Z"))["gate"], "HOLD")

    def test_nonce_replay_is_rejected_after_first_success(self):
        seen = set()
        assertion = self.assertion()
        self.assertEqual(self.check(assertion, seen)["gate"], "PASS_SCOPED")
        replay = self.check(assertion, seen)
        self.assertEqual(replay["gate"], "HOLD")
        self.assertTrue(replay["replay_detected"])
        self.assertFalse(replay["authenticated_worker_identity"])


    def durable_check(self, assertion, store, observed="2026-09-16T09:02:00Z"):
        return verifier.verify_identity_assertion(
            assertion, trusted_keys={"c12-test-key": self.KEY},
            expected_worker_id=self.EXPECTED["worker_id"],
            expected_task_id=self.EXPECTED["task_id"],
            expected_candidate_sha=self.EXPECTED["candidate_sha"],
            observed_at=observed, nonce_store=store)

    def test_durable_nonce_survives_store_restart(self):
        path = self.root / "nonces.sqlite3"
        assertion = self.assertion()
        self.assertEqual(self.durable_check(assertion, verifier.DurableNonceStore(path))["gate"], "PASS_SCOPED")
        replay = self.durable_check(assertion, verifier.DurableNonceStore(path))
        self.assertEqual(replay["gate"], "HOLD")
        self.assertTrue(replay["replay_detected"])

    def test_concurrent_consumption_allows_exactly_one(self):
        path = self.root / "concurrent.sqlite3"
        assertion = self.assertion()
        def attempt(_):
            return self.durable_check(assertion, verifier.DurableNonceStore(path))["gate"]
        with ThreadPoolExecutor(max_workers=8) as pool:
            gates = list(pool.map(attempt, range(16)))
        self.assertEqual(gates.count("PASS_SCOPED"), 1)
        self.assertEqual(gates.count("HOLD"), 15)

    def test_expired_rows_are_cleaned_without_reopening_nonce(self):
        path = self.root / "cleanup.sqlite3"
        store = verifier.DurableNonceStore(path)
        old = self.assertion(nonce="nonce-c12-old-000001",
                             issued_at="2026-09-16T08:55:00Z",
                             expires_at="2026-09-16T09:00:00Z")
        self.assertEqual(self.durable_check(old, store, "2026-09-16T08:59:00Z")["gate"], "PASS_SCOPED")
        current = self.assertion(nonce="nonce-c12-new-000001")
        self.assertEqual(self.durable_check(current, store)["gate"], "PASS_SCOPED")
        with sqlite3.connect(path) as db:
            nonces = {row[0] for row in db.execute("SELECT nonce FROM identity_nonce")}
        self.assertNotIn("nonce-c12-old-000001", nonces)
        self.assertIn("nonce-c12-new-000001", nonces)

    def test_storage_failure_fails_closed(self):
        class BrokenStore:
            def consume(self, *_):
                raise sqlite3.OperationalError("disk unavailable")
        result = self.durable_check(self.assertion(), BrokenStore())
        self.assertEqual(result["gate"], "HOLD")
        self.assertFalse(result["authenticated_worker_identity"])
        self.assertIn("storage unavailable", " ".join(result["errors"]))


if __name__ == "__main__":
    unittest.main()
