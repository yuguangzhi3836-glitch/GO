"""Isolated scheduler contract tests. Fixtures are NOT production evidence."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("validate_ledger.py")
spec = importlib.util.spec_from_file_location("validate_ledger", SCRIPT)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def fixture():
    return {
        "schema_version": 1, "round_id": "round2-test-only", "source_anchor": validator.SOURCE_ANCHOR,
        "events": [{"event": "TEST_FIXTURE_CREATED", "at": "2026-09-14T00:00:00Z"}],
        "cells": [{
            "cell_id": cid, "executable_gap": True, "next_task": None,
            "domain_completion": None,
            "task": {"id": f"{cid}-fixture-scope1", "description": f"Verify {cid} isolated contract behavior",
                     "scope": "fixture only", "test_plan": "Run isolated contract tests and capture exit code",
                     "status": "ASSIGNED", "completion": {"percent": 0, "definition": "One fixture contract plus tests and two independent reviews"},
                     "evidence": [], "execution_evidence_refs": [],
                     "gates": {name: {"status": "HOLD", "evidence_refs": []} for name in validator.GATE_NAMES}}
        } for cid in sorted(validator.CELL_IDS)]}


def next_task(cid):
    return {"id": f"{cid}-fixture-scope2", "description": "Verify a distinct next fixture contract",
            "scope": "next fixture contract", "completion_definition": "One additional contract, tests, C14 and C13",
            "test_plan": "Exercise recovery after interrupted assignment"}


class SchedulerContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ledger = fixture()

    def check(self, ledger=None):
        return validator.validate(self.ledger if ledger is None else ledger, self.root)

    def evidence(self, cell, name="evidence.txt"):
        (self.root / name).write_text("LOCAL TEST FIXTURE ONLY\n")
        task = cell["task"]
        task["evidence"] = [{"path": name, "sha256": hashlib.sha256((self.root / name).read_bytes()).hexdigest(),
                             "source_anchor": validator.SOURCE_ANCHOR, "task_id": task["id"]}]
        return name

    def done(self, cell):
        path = self.evidence(cell)
        task = cell["task"]
        task["status"] = "DONE_SCOPED"
        task["completion"]["percent"] = 100
        for i, name in enumerate(validator.GATE_NAMES):
            task["gates"][name] = {"status": "PASS_SCOPED", "evidence_refs": [path],
                                     "completed_at": f"2026-09-14T00:00:0{i}Z", "reviewer": name + "-fixture-reviewer"}

    def test_all_cells_assigned_is_consistent_not_running(self):
        self.assertEqual(self.check()["gate"], "PASS_SCOPED")
        self.assertTrue(all(c["task"]["status"] == "ASSIGNED" for c in self.ledger["cells"]))

    def test_locked_source_rejects_different_main(self):
        self.ledger["source_anchor"] = "other-main"
        self.assertIn("source_anchor", " ".join(self.check()["errors"]))

    def test_exactly_fourteen_unique_cells(self):
        self.ledger["cells"][13]["cell_id"] = "C01"
        self.assertIn("exactly one", " ".join(self.check()["errors"]))

    def test_idle_followup_preserves_original_events_and_does_not_fake_ack(self):
        self.ledger["cells"][6]["task"]["status"] = "IDLE"
        before = copy.deepcopy(self.ledger)
        report = self.check()
        self.assertEqual(report["gate"], "SCHEDULER_FAIL")
        self.assertEqual(report["reassign_cells"], ["C07"])
        output = validator.reconcile(self.ledger, report, "2026-09-14T01:00:00Z")
        self.assertEqual(self.ledger, before)
        self.assertEqual(output["events"][:len(before["events"])], before["events"])
        self.assertEqual(output["cells"][6]["task_history"][0], before["cells"][6]["task"])
        self.assertEqual(output["cells"][6]["task"]["status"], "ASSIGNED")
        self.assertIsNone(output["followups"][0]["acknowledged_at"])
        self.assertIsNone(output["followups"][0]["started_at"])
        self.assertEqual(self.check(output)["gate"], "PASS_SCOPED")
        replay = validator.reconcile(output, self.check(output), "2026-09-14T01:01:00Z")
        self.assertEqual(replay, output)

    def test_done_scoped_next_layer_is_assigned_without_rerunning_completed_scope(self):
        cell = self.ledger["cells"][0]
        self.done(cell)
        cell["next_task"] = next_task("C01")
        report = self.check()
        self.assertFalse(report["errors"])
        self.assertEqual(report["reassign_cells"], ["C01"])
        output = validator.reconcile(self.ledger, report)
        self.assertEqual(output["cells"][0]["task"]["id"], "C01-fixture-scope2")
        self.assertEqual(output["cells"][0]["task_history"][0]["completion"]["percent"], 100)
        self.assertIsNone(output["cells"][0]["domain_completion"])

    def test_done_cannot_reassign_same_completed_task(self):
        cell = self.ledger["cells"][0]
        self.done(cell)
        cell["next_task"] = next_task("C01")
        cell["next_task"]["id"] = cell["task"]["id"]
        self.assertIn("inherited PASS", " ".join(self.check()["errors"]))

    def test_external_blocker_with_executable_alternative_is_redispatched(self):
        cell = self.ledger["cells"][2]
        cell["task"]["status"] = "BLOCKED"
        cell["blocked_reason"] = "Original external provider sandbox credentials are unavailable"
        cell["next_task"] = next_task("C03")
        report = self.check()
        self.assertEqual(report["reassign_cells"], ["C03"])
        self.assertFalse(report["errors"])

    def test_blocked_without_executable_gap_requires_specific_reason(self):
        cell = self.ledger["cells"][2]
        cell["task"]["status"] = "BLOCKED"
        cell["executable_gap"] = False
        self.assertIn("blocked_reason", " ".join(self.check()["errors"]))

    def test_running_requires_actual_checksummed_record(self):
        cell = self.ledger["cells"][5]
        cell["task"]["status"] = "RUNNING"
        self.assertIn("RUNNING requires", " ".join(self.check()["errors"]))
        path = self.evidence(cell)
        cell["task"]["execution_evidence_refs"] = [path]
        self.assertFalse(self.check()["errors"])
        (self.root / path).write_text("tampered")
        self.assertIn("checksum mismatch", " ".join(self.check()["errors"]))

    def test_historical_evidence_must_match_task_and_source(self):
        cell = self.ledger["cells"][0]
        self.evidence(cell)
        cell["task"]["evidence"][0]["task_id"] = "previous-task"
        self.assertIn("identity mismatch", " ".join(self.check()["errors"]))

    def test_evidence_cannot_escape_root(self):
        cell = self.ledger["cells"][0]
        self.evidence(cell)
        cell["task"]["evidence"][0]["path"] = "/etc/passwd"
        self.assertIn("outside root", " ".join(self.check()["errors"]))

    def test_completed_scope_requires_full_gate_chain(self):
        cell = self.ledger["cells"][0]
        self.done(cell)
        cell["executable_gap"] = False
        cell["task"]["gates"]["c13"] = {"status": "HOLD", "evidence_refs": []}
        self.assertIn("100% requires", " ".join(self.check()["errors"]))

    def test_c13_cannot_precede_c14_or_use_same_reviewer(self):
        cell = self.ledger["cells"][0]
        self.done(cell)
        cell["executable_gap"] = False
        cell["task"]["gates"]["c13"]["completed_at"] = "2026-09-13T00:00:00Z"
        cell["task"]["gates"]["c13"]["reviewer"] = "c14-fixture-reviewer"
        errors = " ".join(self.check()["errors"])
        self.assertIn("precedes", errors)
        self.assertIn("independent reviewer", errors)

    def test_invalid_next_task_holds_instead_of_inventing_domain_work(self):
        cell = self.ledger["cells"][0]
        self.done(cell)
        report = self.check()
        self.assertEqual(report["gate"], "SCHEDULER_FAIL")
        with self.assertRaises(ValueError):
            validator.reconcile(self.ledger, report)

    def test_cli_reports_failure_and_writes_separate_reconciled_records(self):
        self.ledger["cells"][6]["task"]["status"] = "IDLE"
        source = self.root / "input.json"
        output = self.root / "reconciled.json"
        source.write_text(json.dumps(self.ledger))
        result = subprocess.run([sys.executable, str(SCRIPT), str(source), "--evidence-root", str(self.root), "--reconcile-out", str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["gate"], "SCHEDULER_FAIL")
        self.assertEqual(json.loads(result.stdout)["reconciled_gate"], "PASS_SCOPED")
        self.assertEqual(json.loads(source.read_text()), self.ledger)
        self.assertEqual(json.loads(output.read_text())["followups"][0]["status"], "ASSIGNED")

    def test_cli_refuses_to_overwrite_input(self):
        source = self.root / "input.json"
        source.write_text(json.dumps(self.ledger))
        result = subprocess.run([sys.executable, str(SCRIPT), str(source), "--reconcile-out", str(source)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(source.read_text()), self.ledger)


if __name__ == "__main__":
    unittest.main()
