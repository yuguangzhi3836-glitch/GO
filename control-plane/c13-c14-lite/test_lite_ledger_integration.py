"""Integration with the existing 14-Cell ledger — no parallel scheduler.

The point of these tests is that Lite V2 feeds ``ci/round2/validate_ledger.py``
**as it already exists in the repository**: the validator is imported from its real
path, never copied, never patched. If Lite V2 had invented its own task/state
model, this file could not pass.
"""
from __future__ import annotations

import copy
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import lite_canonical  # noqa: E402
import lite_chain  # noqa: E402
import lite_errors  # noqa: E402
import lite_execution_record  # noqa: E402
import lite_fixtures as fx  # noqa: E402
import lite_ledger_binding as lb  # noqa: E402

COMPLETED_AT = "2026-09-25T08:05:00Z"


class LedgerAdapterTests(unittest.TestCase):
    def materialise(self, directory, round_):
        path = pathlib.Path(directory)

        def write(relative, raw):
            target = path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            return relative

        return {
            "c14": write("evidence/c14_bundle.json", lite_canonical.canonical(round_["c14_bundle"])),
            "c13": write("evidence/c13_bundle.json", lite_canonical.canonical(round_["c13_bundle"])),
            "junit": write("evidence/junit.xml", round_["artifacts"]["junit"]),
            "stdout": write("evidence/stdout.txt", round_["artifacts"]["stdout"]),
            "manifest": write("evidence/manifest.json", round_["artifacts"]["manifest"]),
        }

    def records(self, round_):
        c14 = lite_execution_record.build(
            round_["c14_bundle"],
            artifact={"name": "c13c14-lite-c14-" + fx.CANDIDATE_SHA, "id": 501, "digest": "sha256:" + "1" * 64},
            evidence_path="evidence/c14_bundle.json",
        )
        c13 = lite_execution_record.build(
            round_["c13_bundle"],
            artifact={"name": "c13c14-lite-c13-" + fx.CANDIDATE_SHA, "id": 502, "digest": "sha256:" + "2" * 64},
            evidence_path="evidence/c13_bundle.json",
        )
        return c14, c13

    def bind(self, directory, round_, ledger=None):
        paths = self.materialise(directory, round_)
        c14_record, c13_record = self.records(round_)
        bound = lb.bind(
            ledger if ledger is not None else fx.synthetic_ledger(),
            evidence_root=pathlib.Path(directory),
            candidate_sha=round_["dispatch"]["candidate_sha"],
            c14_record=c14_record,
            c13_record=c13_record,
            c14_evidence=[(paths["c14"], lite_canonical.canonical(round_["c14_bundle"]))],
            c13_evidence=[(paths["c13"], lite_canonical.canonical(round_["c13_bundle"]))],
            machine_evidence=[
                (paths["junit"], round_["artifacts"]["junit"]),
                (paths["stdout"], round_["artifacts"]["stdout"]),
                (paths["manifest"], round_["artifacts"]["manifest"]),
            ],
            completed_at=COMPLETED_AT,
        )
        return bound, c14_record, c13_record

    # --- the validator we depend on -----------------------------------------
    def test_validator_is_the_repository_module(self):
        path = lb.ledger_validator_path()
        self.assertTrue(path.is_file(), path)
        self.assertIn("ci/round2/validate_ledger.py", path.as_posix())
        module = lb.load_ledger_validator()
        self.assertEqual(module.SOURCE_ANCHOR, lb.source_anchor())
        self.assertEqual(module.GATE_NAMES, ("tests", "evidence", "c14", "c13"))
        self.assertEqual(len(module.CELL_IDS), 14)

    # --- the round feeds it and passes ---------------------------------------
    def test_bound_ledger_passes_the_repository_validator(self):
        round_ = fx.make_round()
        lite_chain.require(**fx.chain_kwargs(round_))
        with tempfile.TemporaryDirectory() as directory:
            bound, _c14_record, _c13_record = self.bind(directory, round_)
            report = lb.validate_with_repository_validator(bound, pathlib.Path(directory))
        self.assertEqual(report["gate"], "PASS_SCOPED", report)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["reassign_cells"], [])

    def test_binding_does_not_create_a_second_ledger(self):
        round_ = fx.make_round()
        ledger = fx.synthetic_ledger()
        with tempfile.TemporaryDirectory() as directory:
            bound, _c14, _c13 = self.bind(directory, round_, ledger=ledger)
        self.assertEqual(set(bound), set(ledger))
        self.assertEqual(len(bound["cells"]), 14)
        self.assertEqual([c["cell_id"] for c in bound["cells"]], [f"C{i:02d}" for i in range(1, 15)])
        # The source ledger is not mutated in place.
        self.assertEqual(ledger["cells"][13]["task"]["status"], "ASSIGNED")
        self.assertEqual(bound["cells"][13]["task"]["status"], "DONE_SCOPED")

    def test_c14_and_c13_gate_reviewers_are_the_two_execution_identities(self):
        round_ = fx.make_round()
        with tempfile.TemporaryDirectory() as directory:
            bound, _c14, _c13 = self.bind(directory, round_)
        c13_cell = [c for c in bound["cells"] if c["cell_id"] == "C13"][0]
        reviewers = {
            c13_cell["task"]["gates"]["c14"]["reviewer"],
            c13_cell["task"]["gates"]["c13"]["reviewer"],
        }
        self.assertEqual(reviewers, {round_["c14_bundle"]["ai_execution_id"], round_["c13_bundle"]["ai_execution_id"]})
        self.assertEqual(len(reviewers), 2)

    # --- the existing validator's own rules still bite -----------------------
    def test_repository_validator_still_demands_two_reviewers(self):
        """Proves we rely on the repository's rule, not on a new one of ours."""
        round_ = fx.make_round()
        with tempfile.TemporaryDirectory() as directory:
            bound, _c14, _c13 = self.bind(directory, round_)
        doctored = copy.deepcopy(bound)
        c13_cell = [c for c in doctored["cells"] if c["cell_id"] == "C13"][0]
        c13_cell["task"]["gates"]["c13"]["reviewer"] = c13_cell["task"]["gates"]["c14"]["reviewer"]
        report = lb.validate_with_repository_validator(doctored, pathlib.Path(directory))
        self.assertEqual(report["gate"], "HOLD")
        self.assertIn("C13: C13 independent reviewer must differ from C14", report["errors"])

    # --- refusals -------------------------------------------------------------
    def test_binding_refuses_a_task_the_scheduler_did_not_dispatch(self):
        round_ = fx.make_round()
        ledger = fx.synthetic_ledger(c13_task_id="C13-a-different-task")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(lite_errors.Reject) as ctx:
                self.bind(directory, round_, ledger=ledger)
        self.assertEqual(ctx.exception.reason, "issue_task_binding_mismatch")

    def test_binding_refuses_identical_execution_ids(self):
        round_ = fx.make_round()
        with tempfile.TemporaryDirectory() as directory:
            paths = self.materialise(directory, round_)
            c14_record, c13_record = self.records(round_)
            c13_record = dict(c13_record, review_execution_id=c14_record["review_execution_id"])
            with self.assertRaises(lite_errors.Reject) as ctx:
                lb.bind(
                    fx.synthetic_ledger(),
                    evidence_root=pathlib.Path(directory),
                    candidate_sha=round_["dispatch"]["candidate_sha"],
                    c14_record=c14_record,
                    c13_record=c13_record,
                    c14_evidence=[(paths["c14"], lite_canonical.canonical(round_["c14_bundle"]))],
                    c13_evidence=[(paths["c13"], lite_canonical.canonical(round_["c13_bundle"]))],
                    machine_evidence=[(paths["junit"], round_["artifacts"]["junit"])],
                    completed_at=COMPLETED_AT,
                )
            self.assertEqual(ctx.exception.reason, "c13_equals_c14_execution")

    def test_binding_refuses_evidence_that_is_not_materialised(self):
        round_ = fx.make_round()
        with tempfile.TemporaryDirectory() as directory:
            self.materialise(directory, round_)
            c14_record, c13_record = self.records(round_)
            with self.assertRaises(lite_errors.Reject) as ctx:
                lb.bind(
                    fx.synthetic_ledger(),
                    evidence_root=pathlib.Path(directory),
                    candidate_sha=round_["dispatch"]["candidate_sha"],
                    c14_record=c14_record,
                    c13_record=c13_record,
                    c14_evidence=[("evidence/not-written.json", b"x")],
                    c13_evidence=[("evidence/c13_bundle.json", lite_canonical.canonical(round_["c13_bundle"]))],
                    machine_evidence=[("evidence/junit.xml", round_["artifacts"]["junit"])],
                    completed_at=COMPLETED_AT,
                )
        self.assertEqual(ctx.exception.reason, "ledger_evidence_not_materialised")


class LedgerContractSurfaceTests(unittest.TestCase):
    def test_adapter_exposes_no_scheduler_of_its_own(self):
        """The adapter's surface is evidence entries and gate records — nothing else."""
        surface = {name for name in dir(lb) if not name.startswith("_")}
        for forbidden in ("Scheduler", "TaskRegistry", "CellRegistry", "StateMachine"):
            self.assertNotIn(forbidden, surface)
        self.assertTrue({"evidence_entry", "gate_record", "bind", "source_anchor"} <= surface)

    def test_gate_status_mapping_matches_the_repository_vocabulary(self):
        self.assertEqual(lb.VERDICT_TO_GATE_STATUS["PASS_SCOPED"], "PASS_SCOPED")
        self.assertEqual(lb.VERDICT_TO_GATE_STATUS["NOT_APPLICABLE"], "PASS_SCOPED")
        self.assertEqual(lb.VERDICT_TO_GATE_STATUS["FAIL"], "FAIL")
        self.assertEqual(lb.VERDICT_TO_GATE_STATUS["BLOCKED"], "HOLD")
        with self.assertRaises(lite_errors.Reject):
            lb.gate_record("UNKNOWN", [], "reviewer", COMPLETED_AT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
