import importlib.util
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib import error, request

ROOT = Path(__file__).parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load("runtime_validator_for_orchestrator", "validate_runtime_liveness.py")
orchestrator = load("durable_orchestrator", "durable_orchestrator.py")
NOW = datetime(2026, 9, 16, 17, 0, tzinfo=timezone.utc)
SHA = "a" * 40
EVIDENCE = "b" * 64


class DurableOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = orchestrator.DurableOrchestrator(
            Path(self.directory.name) / "orchestrator.sqlite3", orchestrator_id="test-orchestrator"
        )

    def tearDown(self):
        self.directory.cleanup()

    def enqueue(self, task_id="task-1", cell_id="C01"):
        return self.store.enqueue(task_id, cell_id, SHA, {"scope": task_id}, now=NOW)

    def test_claim_produces_source_bound_live_snapshot(self):
        self.enqueue()
        claim = self.store.claim("worker-1", now=NOW)
        snapshot = self.store.snapshot("challenge-1234567890", now=NOW + timedelta(seconds=1))
        snapshot["observed_at"] = orchestrator.stamp(NOW + timedelta(seconds=1))
        result = validator.validate(snapshot, NOW + timedelta(seconds=1))
        self.assertEqual(result["gate"], "PASS_SCOPED")
        self.assertEqual(snapshot["executors"][0]["attempt_id"], claim["attempt_id"])

    def test_expired_lease_is_atomically_requeued_for_new_attempt(self):
        self.enqueue()
        first = self.store.claim("worker-1", lease_seconds=10, now=NOW)
        second = self.store.claim("worker-2", now=NOW + timedelta(seconds=11))
        self.assertNotEqual(first["lease_id"], second["lease_id"])
        self.assertNotEqual(first["attempt_id"], second["attempt_id"])
        self.assertEqual(second["worker_id"], "worker-2")

    def test_same_cell_cannot_have_two_concurrent_active_leases(self):
        self.enqueue("task-1", "C01")
        self.enqueue("task-2", "C01")
        self.assertIsNotNone(self.store.claim("worker-1", now=NOW))
        self.assertIsNone(self.store.claim("worker-2", now=NOW))

    def test_concurrent_claim_is_serialized_to_one_cell_lease(self):
        self.enqueue("task-1", "C01")
        self.enqueue("task-2", "C01")
        barrier = threading.Barrier(3)
        results = []

        def claim(worker):
            barrier.wait()
            results.append(self.store.claim(worker, now=NOW))

        threads = [threading.Thread(target=claim, args=(f"worker-{index}",)) for index in (1, 2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=2)
        self.assertEqual(sum(result is not None for result in results), 1)

    def test_failure_stays_in_diagnose_fix_retest_loop(self):
        self.enqueue()
        claim = self.store.claim("worker-1", now=NOW)
        args = (claim["task_id"], claim["worker_id"], claim["attempt_id"], claim["lease_id"])
        failed = self.store.fail(*args, "test failed", now=NOW + timedelta(seconds=1))
        self.assertEqual(failed["status"], "DIAGNOSE")
        self.assertEqual(self.store.advance_recovery(*args, now=NOW + timedelta(seconds=2))["status"], "FIX")
        self.assertEqual(self.store.advance_recovery(*args, now=NOW + timedelta(seconds=3))["status"], "RETEST")
        self.assertEqual(self.store.advance_recovery(*args, now=NOW + timedelta(seconds=4))["status"], "RUNNING")

    def test_completion_auto_claims_next_cell_task_without_rerunning_pass(self):
        self.enqueue("task-1", "C01")
        self.enqueue("task-2", "C01")
        claim = self.store.claim("worker-1", now=NOW)
        result = self.store.complete(
            claim["task_id"], claim["worker_id"], claim["attempt_id"], claim["lease_id"],
            EVIDENCE, now=NOW + timedelta(seconds=1)
        )
        self.assertEqual(result["completed"]["status"], "DONE_SCOPED")
        self.assertEqual(result["next_task"]["task_id"], "task-2")
        inherited = self.store.enqueue("task-1", "C01", SHA, {"scope": "task-1"}, now=NOW)
        self.assertEqual(inherited["status"], "DONE_SCOPED")

    def test_idempotency_conflict_is_rejected(self):
        self.enqueue()
        with self.assertRaisesRegex(orchestrator.OrchestratorError, "conflict"):
            self.store.enqueue("task-1", "C01", "c" * 40, {"scope": "task-1"}, now=NOW)

    def test_external_block_requires_evidence_and_leaves_no_executable_cell(self):
        self.enqueue("supplier", "C06")
        blocked = self.store.block_external("supplier", EVIDENCE, "authorized supplier data", now=NOW)
        snapshot = self.store.snapshot("challenge-1234567890", now=NOW)
        self.assertEqual(blocked["status"], "BLOCKED_EXTERNAL")
        self.assertEqual(snapshot["expected_executable_cells"], [])

    def test_stale_worker_cannot_heartbeat_reclaimed_lease(self):
        self.enqueue()
        old = self.store.claim("worker-1", lease_seconds=10, now=NOW)
        self.store.claim("worker-2", now=NOW + timedelta(seconds=11))
        with self.assertRaisesRegex(orchestrator.OrchestratorError, "binding mismatch"):
            self.store.heartbeat(old["task_id"], old["worker_id"], old["attempt_id"], old["lease_id"],
                                 now=NOW + timedelta(seconds=12))

    def test_actual_http_service_integrates_with_probe_and_persists_replay_state(self):
        self.enqueue()
        self.store.claim("worker-1", now=NOW)
        token = "test-token-with-at-least-thirty-two-characters"
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            orchestrator.make_handler(self.store, token, clock=lambda: NOW + timedelta(seconds=1)),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        probe = load("external_probe_for_orchestrator", "probe_external_orchestrator.py")
        try:
            state = Path(self.directory.name) / "probe-state.json"
            result = probe.run_probe(
                f"http://127.0.0.1:{server.server_port}/internal/v1/cell-runtime-snapshot",
                state, now=NOW + timedelta(seconds=1), token=token,
                challenge="network-challenge-1234", allow_http_loopback=True,
            )
            self.assertEqual(result["gate"], "PASS_SCOPED")
            self.assertEqual(json.loads(state.read_text())["sequence"], 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_service_rejects_missing_bearer_token(self):
        token = "test-token-with-at-least-thirty-two-characters"
        server = ThreadingHTTPServer(("127.0.0.1", 0), orchestrator.make_handler(self.store, token))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            req = request.Request(
                f"http://127.0.0.1:{server.server_port}/internal/v1/cell-runtime-snapshot",
                data=b'{"challenge":"challenge-1234567890"}', method="POST",
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(error.HTTPError) as caught:
                request.urlopen(req, timeout=2)
            self.assertEqual(caught.exception.code, 401)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
