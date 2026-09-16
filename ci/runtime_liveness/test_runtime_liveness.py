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
            "source_sha": "a" * 40, "heartbeat_at": "2026-09-16T13:29:30Z",
            "lease_expires_at": "2026-09-16T13:34:30Z"}


class RuntimeLivenessTests(unittest.TestCase):
    def snapshot(self, executors):
        return {"observed_at": "2026-09-16T13:30:00Z",
                "expected_executable_cells": ["C01", "C02"], "executors": executors}

    def test_fresh_leases_pass(self):
        result = gate.validate(self.snapshot([executor("C01"), executor("C02")]), NOW)
        self.assertEqual(result["gate"], "PASS_SCOPED")

    def test_assigned_records_are_not_live(self):
        result = gate.validate(self.snapshot([]), NOW)
        self.assertEqual(result["reason"], "ALL_CELLS_EXITED")
        self.assertEqual(result["affected_cells"], ["C01", "C02"])

    def test_expired_lease_is_scheduler_fail(self):
        item = executor("C01")
        item["lease_expires_at"] = "2026-09-16T13:29:59Z"
        result = gate.validate(self.snapshot([item, executor("C02")]), NOW)
        self.assertEqual(result["gate"], "SCHEDULER_FAIL")
        self.assertIn("C01", result["stale_cells"])

    def test_historical_done_is_not_liveness(self):
        result = gate.validate(self.snapshot([executor("C01", "DONE_SCOPED")]), NOW)
        self.assertTrue(result["all_cells_exited"])

    def test_active_requires_task_and_source_binding(self):
        item = executor("C01")
        item.pop("source_sha")
        result = gate.validate(self.snapshot([item, executor("C02")]), NOW)
        self.assertEqual(result["gate"], "SCHEDULER_FAIL")
        self.assertIn("C01", result["affected_cells"])


if __name__ == "__main__":
    unittest.main()
