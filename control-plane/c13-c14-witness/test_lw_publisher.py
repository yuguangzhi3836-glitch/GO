"""Controlled publisher: it must refuse far more often than it writes."""
from __future__ import annotations

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
import lw_publisher  # noqa: E402

COMPLETED_AT = "2026-09-25T09:20:00Z"


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.round = fx.bundles()
        self.c14_record, self.c13_record = fx.execution_records(self.round)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name)
        self.paths = fx.materialise(self.root, self.round)
        self.evidence = {
            "c14": (self.paths["c14"], (self.root / self.paths["c14"]).read_bytes()),
            "c13": (self.paths["c13"], (self.root / self.paths["c13"]).read_bytes()),
        }

    def expectation(self, **overrides):
        base = {
            "cell_id": "C14",
            "task_id": fx.C14_TASK,
            "candidate_sha": fx.CANDIDATE_SHA,
            "ledger_reference": self.round["c14_contract"]["ledger_reference"],
            "issue_number": fx.ISSUE_NUMBER,
        }
        base.update(overrides)
        return base

    def plan(self, **kwargs):
        kwargs.setdefault("ledger", fx.synthetic_ledger())
        kwargs.setdefault("records", {"c14": self.c14_record})
        kwargs.setdefault("evidence", {"c14": self.evidence["c14"]})
        kwargs.setdefault("evidence_root", self.root)
        kwargs.setdefault("expectation", self.expectation())
        kwargs.setdefault("completed_at", COMPLETED_AT)
        return lw_publisher.plan(**kwargs)

    # --- the happy paths -----------------------------------------------------
    def test_c14_writeback_is_allowed_and_satisfies_the_repository_validator(self):
        plan = self.plan()
        self.assertTrue(plan["allowed"], plan["refusals"])
        self.assertTrue(plan["applied"])
        report = lw_publisher.validate_with_repository_validator(plan["new_ledger"], self.root)
        self.assertIn(report["gate"], ("PASS_SCOPED", "HOLD"), report)
        self.assertEqual(report["errors"], [])
        cell = [c for c in plan["new_ledger"]["cells"] if c["cell_id"] == "C14"][0]
        self.assertEqual(cell["task"]["status"], "RUNNING")
        self.assertEqual(cell["task"]["gates"]["tests"]["status"], "PASS_SCOPED")

    def test_c13_writeback_closes_the_pair_and_passes(self):
        plan = self.plan(
            records={"c14": self.c14_record, "c13": self.c13_record},
            evidence={"c14": self.evidence["c14"], "c13": self.evidence["c13"]},
            expectation=self.expectation(cell_id="C13", task_id=fx.C13_TASK,
                                         ledger_reference=self.round["c13_contract"]["ledger_reference"]),
        )
        self.assertTrue(plan["allowed"], plan["refusals"])
        report = lw_publisher.validate_with_repository_validator(plan["new_ledger"], self.root)
        self.assertEqual(report["gate"], "PASS_SCOPED", report)
        cell = [c for c in plan["new_ledger"]["cells"] if c["cell_id"] == "C13"][0]
        self.assertEqual(cell["task"]["status"], "DONE_SCOPED")
        self.assertEqual(cell["task"]["completion"]["percent"], 100)
        reviewers = {cell["task"]["gates"]["c14"]["reviewer"], cell["task"]["gates"]["c13"]["reviewer"]}
        self.assertEqual(len(reviewers), 2)

    def test_c13_writeback_without_the_c14_record_is_refused(self):
        with self.assertRaises(lite_errors.Reject) as ctx:
            self.plan(
                records={"c13": self.c13_record},
                evidence={"c13": self.evidence["c13"]},
                expectation=self.expectation(cell_id="C13", task_id=fx.C13_TASK,
                                             ledger_reference=self.round["c13_contract"]["ledger_reference"]),
            )
        self.assertEqual(ctx.exception.reason, "c13_writeback_requires_the_c14_record")

    def test_a_record_without_its_evidence_is_refused(self):
        with self.assertRaises(lite_errors.Reject) as ctx:
            self.plan(records={"c14": self.c14_record, "c13": self.c13_record},
                      evidence={"c14": self.evidence["c14"]})
        self.assertEqual(ctx.exception.reason, "evidence_missing_for_recorded_cell")

    # --- the refusals --------------------------------------------------------
    def test_wrong_cell_task_candidate_or_ledger_reference_is_refused(self):
        cases = {
            # expectation says C14 while the record is a C13 record
            "expected_cell_equals_bundle_cell": (
                {"c14": self.c13_record}, {"cell_id": "C14"}),
            "expected_task_equals_bundle_task": ({}, {"task_id": "C14-something-else"}),
            "expected_candidate_equals_bundle_candidate": ({}, {"candidate_sha": "0" * 40}),
            "expected_ledger_reference_equals_bundle_reference": (
                {}, {"ledger_reference": {"round_id": "OTHER", "cell_id": "C14", "task_id": fx.C14_TASK}}),
        }
        for reason, (records, override) in cases.items():
            plan = self.plan(records=records or {"c14": self.c14_record},
                             expectation=self.expectation(**override))
            self.assertFalse(plan["allowed"], reason)
            self.assertIn(reason, plan["refusals"], reason)
            self.assertIsNone(plan["new_ledger"])

    def test_a_stale_task_is_refused(self):
        ledger = fx.synthetic_ledger(c14_task_id="C14-a-replacement-task")
        plan = self.plan(ledger=ledger)
        self.assertIn("task_is_not_replaced_or_stale", plan["refusals"])

    def test_repeating_an_identical_result_is_idempotent(self):
        first = self.plan()
        second = self.plan(ledger=first["new_ledger"])
        self.assertFalse(second["allowed"])
        self.assertTrue(second["idempotent"], second["refusals"])
        self.assertIn("duplicate_identical_result", second["refusals"])

    def test_a_conflicting_result_for_the_same_execution_is_refused(self):
        first = self.plan()
        conflicting = dict(self.c14_record, root_hash="0" * 64, verdict="FAIL")
        plan = self.plan(ledger=first["new_ledger"], records={"c14": conflicting})
        self.assertIn("no_duplicate_conflicting_result", plan["refusals"])

    def test_an_older_result_cannot_overwrite_a_newer_first_seen(self):
        first = self.plan()
        older = dict(self.c14_record, issued_at="2020-01-01T00:00:00Z")
        plan = self.plan(ledger=first["new_ledger"], records={"c14": older})
        self.assertFalse(plan["allowed"])
        self.assertIn("no_older_result_overwriting_newer_first_seen", plan["refusals"])

    def test_no_cross_cell_write(self):
        plan = self.plan(expectation=self.expectation(cell_id="C13"))
        self.assertIn("no_cross_cell_write", plan["refusals"])
        self.assertIn("record_for_expected_cell_missing", plan["refusals"])

    def test_evidence_that_was_not_materialised_is_refused(self):
        with self.assertRaises(lite_errors.Reject) as ctx:
            self.plan(evidence={"c14": ("evidence/not-there.json", b"x")})
        self.assertEqual(ctx.exception.reason, "ledger_evidence_not_materialised")

    # --- the Issue payload is prepared, never posted -------------------------
    def test_issue_comment_is_prepared_and_marked_unposted(self):
        plan = self.plan()
        payload = plan["issue_comment"]
        self.assertIsNotNone(payload)
        self.assertFalse(payload["posted"])
        self.assertIn("no issue write scope", payload["note"])
        body = "\n".join(payload["body_lines"])
        for expected in ("cell_id: C14", f"candidate_sha: {fx.CANDIDATE_SHA}",
                         f"ai_execution_id: {self.c14_record['ai_execution_id']}",
                         "authorizes_any_action: false"):
            self.assertIn(expected, body)

    def test_the_publisher_exposes_no_scheduler_of_its_own(self):
        surface = {name for name in dir(lw_publisher) if not name.startswith("_")}
        for forbidden in ("Scheduler", "TaskRegistry", "CellRegistry", "create_task"):
            self.assertNotIn(forbidden, surface)


if __name__ == "__main__":
    unittest.main(verbosity=2)
