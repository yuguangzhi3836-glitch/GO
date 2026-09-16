import importlib.util
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).parent
spec = importlib.util.spec_from_file_location("validate_runtime_liveness", ROOT / "validate_runtime_liveness.py")
validator = importlib.util.module_from_spec(spec); spec.loader.exec_module(validator)
sys.modules["validate_runtime_liveness"] = validator
spec = importlib.util.spec_from_file_location("external_probe", ROOT / "probe_external_orchestrator.py")
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
NOW = datetime(2026, 9, 16, 13, 30, tzinfo=timezone.utc)


def payload(challenge="challenge", sequence=1, snapshot_id="snapshot-1"):
    return {"schema": probe.SCHEMA, "orchestrator_id": "orchestrator-a",
            "snapshot_id": snapshot_id, "sequence": sequence, "challenge": challenge,
            "generated_at": "2026-09-16T13:29:59Z",
            "expected_executable_cells": ["C01"],
            "executors": [{"cell_id": "C01", "status": "RUNNING", "task_id": "task-C01",
                           "source_sha": "a" * 40, "attempt_id": "attempt-C01", "lease_id": "lease-C01",
                           "heartbeat_at": "2026-09-16T13:29:30Z", "lease_expires_at": "2026-09-16T13:34:30Z"}]}


class ExternalProbeTests(unittest.TestCase):
    def test_real_loopback_http_challenge_response_path(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                request_body = json.loads(self.rfile.read(length))
                response = json.dumps(payload(request_body["challenge"])).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                result = probe.run_probe(
                    f"http://127.0.0.1:{server.server_port}/snapshot",
                    Path(directory) / "state.json", now=NOW,
                    challenge="network-challenge", allow_http_loopback=True,
                )
            self.assertEqual(result["gate"], "PASS_SCOPED")
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_live_external_snapshot_persists_monotonic_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            with mock.patch.object(probe, "fetch_snapshot", return_value=payload()):
                result = probe.run_probe("https://orchestrator.example/snapshot", state, now=NOW,
                                         challenge="challenge")
            self.assertEqual(result["gate"], "PASS_SCOPED")
            self.assertEqual(json.loads(state.read_text())["sequence"], 1)

    def test_static_or_cached_challenge_is_rejected(self):
        with self.assertRaisesRegex(probe.ProbeError, "challenge mismatch"):
            probe.verify_envelope(payload("old"), challenge="new", now=NOW, previous=None,
                                  max_snapshot_age_seconds=30)

    def test_remote_probe_requires_bearer_token(self):
        with self.assertRaisesRegex(probe.ProbeError, "bearer token"):
            probe.fetch_snapshot("https://orchestrator.example/snapshot", challenge="challenge",
                                 timeout_seconds=1, token=None)

    def test_sequence_replay_is_rejected(self):
        previous = {"orchestrator_id": "orchestrator-a", "snapshot_id": "snapshot-0", "sequence": 2}
        with self.assertRaisesRegex(probe.ProbeError, "replay or rollback"):
            probe.verify_envelope(payload(sequence=2), challenge="challenge", now=NOW,
                                  previous=previous, max_snapshot_age_seconds=30)

    def test_corrupt_durable_state_fails_closed(self):
        previous = {"orchestrator_id": "orchestrator-a", "snapshot_id": "snapshot-0", "sequence": "2"}
        with self.assertRaisesRegex(probe.ProbeError, "durable probe state"):
            probe.verify_envelope(payload(sequence=3), challenge="challenge", now=NOW,
                                  previous=previous, max_snapshot_age_seconds=30)

    def test_stale_snapshot_is_rejected_before_liveness(self):
        item = payload(); item["generated_at"] = "2026-09-16T13:20:00Z"
        with self.assertRaisesRegex(probe.ProbeError, "snapshot is stale"):
            probe.verify_envelope(item, challenge="challenge", now=NOW, previous=None,
                                  max_snapshot_age_seconds=30)

    def test_product_failure_state_stays_live_with_fresh_lease(self):
        item = payload(); item["executors"][0]["status"] = "RETEST"
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(probe, "fetch_snapshot", return_value=item):
                result = probe.run_probe("https://orchestrator.example/snapshot", Path(directory) / "state.json",
                                         now=NOW, challenge="challenge")
        self.assertEqual(result["gate"], "PASS_SCOPED")

    def test_no_live_executor_is_scheduler_fail_and_state_is_recorded(self):
        item = payload(); item["executors"] = []
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            with mock.patch.object(probe, "fetch_snapshot", return_value=item):
                result = probe.run_probe("https://orchestrator.example/snapshot", state, now=NOW,
                                         challenge="challenge")
            self.assertEqual(result["reason"], "ALL_CELLS_EXITED")
            self.assertTrue(state.exists())


if __name__ == "__main__":
    unittest.main()
