import tempfile
import time
import unittest
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from runtime import Runtime, RuntimeErrorInvariant

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rt = Runtime(Path(self.tmp.name) / "runtime.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_bootstraps_14_domains_and_safe_permissions(self):
        snap = self.rt.snapshot()
        self.assertEqual(14, len(snap["agents"]))
        self.assertEqual("ALLOW", self.rt.authorize("C1", "RUN_ISOLATED_TEST"))
        self.assertEqual("REQUIRE_HUMAN", self.rt.authorize("C13", "PRODUCTION"))
        self.assertEqual("DENY", self.rt.authorize("C14", "READ_PRIVATE_KEYS"))
        self.assertEqual("DENY", self.rt.authorize("C14", "UNKNOWN_ACTION"))

    def test_durable_state_and_idempotent_enqueue(self):
        self.rt.set_state("C2", "cursor", {"sha": "abc"})
        self.assertEqual({"sha": "abc"}, self.rt.get_state("C2", "cursor"))
        a = self.rt.enqueue("C2", "SCAN", {"n": 1}, idempotency_key="same")
        b = self.rt.enqueue("C2", "SCAN", {"n": 1}, idempotency_key="same")
        self.assertEqual(a, b)

    def test_claim_complete_and_lease_owner_guard(self):
        task_id = self.rt.enqueue("C3", "CHECK", {"x": 1})
        claimed = self.rt.claim("C3", worker_id="worker-a", lease_s=10)
        self.assertEqual(task_id, claimed.task_id)
        with self.assertRaises(RuntimeErrorInvariant):
            self.rt.complete("C3", task_id, worker_id="worker-b", expected_attempt=claimed.attempts, success=True)
        self.rt.complete("C3", task_id, worker_id="worker-a", expected_attempt=claimed.attempts, success=True)
        self.assertEqual(1, self.rt.snapshot()["task_counts"]["SUCCEEDED"])

    def test_cross_c_message_and_wake(self):
        self.rt.send_message("C4", "C5", "REVIEW_REQUIRED", {"sha": "123"})
        inbox = self.rt.inbox("C5", mark_read=True)
        self.assertEqual("C4", inbox[0]["from_c"])
        self.rt.enqueue("C5", "REVIEW", {"sha": "123"})
        self.assertEqual(["C5"], self.rt.wake_candidates())

    def test_stale_task_requeues_then_escalates(self):
        task_id = self.rt.enqueue("C6", "WORK", {}, max_attempts=2)
        self.rt.claim("C6", worker_id="w1", lease_s=1)
        out = self.rt.recover_stale(now=time.time() + 5)
        self.assertEqual(1, out["requeued"])
        self.rt.claim("C6", worker_id="w2", lease_s=1)
        out = self.rt.recover_stale(now=time.time() + 10)
        self.assertEqual(1, out["escalated"])
        self.assertEqual(1, self.rt.snapshot()["open_escalations"])

    def test_evidence_chain_is_append_only_verifiable(self):
        self.rt.heartbeat("C7")
        task_id = self.rt.enqueue("C7", "AUDIT", {})
        claimed = self.rt.claim("C7", worker_id="w")
        self.rt.complete("C7", task_id, worker_id="w", expected_attempt=claimed.attempts, success=True, result={"ok": True})
        self.assertTrue(self.rt.verify_evidence_chain())

if __name__ == "__main__":
    unittest.main()
