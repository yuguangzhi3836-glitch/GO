import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import unittest

SCRIPT = Path(__file__).with_name("validate_runtime_liveness.py")
spec = importlib.util.spec_from_file_location("runtime_liveness", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
NOW = datetime(2026, 9, 16, 13, 30, tzinfo=timezone.utc)


def executor(cell_id, status="RUNNING"):
    return {"cell_id": cell_id, "status": status, "task_id": f"task-{cell_id}",
            "source_sha": "a" * 40, "attempt_id": f"attempt-{cell_id}",
            "lease_id": f"lease-{cell_id}", "heartbeat_at": "2026-09-16T13:29:30Z",
            "lease_expires_at": "2026-09-16T13:34:30Z"}


class RuntimeLivenessTests(unittest.TestCase):
    def snapshot(self, executors):
        return {"observed_at": "2026-09-16T13:30:00Z",
                "expected_executable_cells": ["C01", "C02"], "executors": executors}

    def test_fresh_leases_pass(self):
        self.assertEqual(gate.validate(self.snapshot([executor("C01"), executor("C02")]), NOW)["gate"], "PASS_SCOPED")

    def test_assigned_records_are_not_live(self):
        result = gate.validate(self.snapshot([]), NOW)
        self.assertEqual(result["reason"], "ALL_CELLS_EXITED")
        self.assertEqual(result["affected_cells"], ["C01", "C02"])

    def test_expired_lease_is_scheduler_fail(self):
        item = executor("C01"); item["lease_expires_at"] = "2026-09-16T13:29:59Z"
        result = gate.validate(self.snapshot([item, executor("C02")]), NOW)
        self.assertEqual(result["gate"], "SCHEDULER_FAIL")
        self.assertIn("C01", result["stale_cells"])

    def test_historical_done_is_not_liveness(self):
        self.assertTrue(gate.validate(self.snapshot([executor("C01", "DONE_SCOPED")]), NOW)["all_cells_exited"])

    def test_active_requires_full_lease_binding(self):
        for field in ("source_sha", "task_id", "attempt_id", "lease_id"):
            item = executor("C01"); item.pop(field)
            result = gate.validate(self.snapshot([item, executor("C02")]), NOW)
            self.assertEqual(result["gate"], "SCHEDULER_FAIL")
            self.assertIn("C01", result["affected_cells"])

    def test_old_heartbeat_fails_even_when_lease_is_future(self):
        item = executor("C01"); item["heartbeat_at"] = "2026-09-16T13:20:00Z"
        item["lease_expires_at"] = "2026-09-16T14:00:00Z"
        result = gate.validate(self.snapshot([item, executor("C02")]), NOW)
        self.assertEqual(result["gate"], "SCHEDULER_FAIL")
        self.assertIn("C01", result["stale_cells"])

    def test_duplicate_lease_fails_closed(self):
        one, two = executor("C01"), executor("C02")
        two["lease_id"] = one["lease_id"]
        result = gate.validate(self.snapshot([one, two]), NOW)
        self.assertEqual(result["gate"], "SCHEDULER_FAIL")
        self.assertIn("C02", result["stale_cells"])

    def test_noncanonical_source_identity_fails_closed(self):
        item = executor("C01"); item["source_sha"] = "ASSIGNED"
        result = gate.validate(self.snapshot([item, executor("C02")]), NOW)
        self.assertEqual(result["gate"], "SCHEDULER_FAIL")
        self.assertIn("source_sha", " ".join(result["errors"]))


if __name__ == "__main__":
    unittest.main()
