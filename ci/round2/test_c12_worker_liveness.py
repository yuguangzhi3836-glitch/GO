import hashlib
import importlib.util
from pathlib import Path
import tempfile
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

    def test_expired_heartbeat_marks_running_stale_and_holds(self):
        result = self.check(self.receipt(heartbeat_at="2026-09-16T02:00:02Z"), "2026-09-16T02:10:00Z")
        self.assertEqual(result["gate"], "HOLD")
        self.assertTrue(result["stale_running"])
        self.assertIn("must not remain RUNNING", " ".join(result["errors"]))

    def test_future_or_missing_heartbeat_is_not_admitted(self):
        self.assertEqual(self.check(self.receipt(heartbeat_at="2026-09-16T02:06:00Z"))["gate"], "HOLD")
        self.assertEqual(self.check(self.receipt(heartbeat_at=None))["gate"], "HOLD")

    def test_receipt_consistency_still_does_not_authenticate_identity(self):
        result = self.check(self.receipt(agent="claimed-worker"))
        self.assertEqual(result["gate"], "HOLD")
        self.assertFalse(result["authenticated_worker_identity"])


if __name__ == "__main__":
    unittest.main()
