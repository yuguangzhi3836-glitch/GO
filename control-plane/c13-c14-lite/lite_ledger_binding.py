"""Adapter: Lite V2 execution records -> the *existing* 14-Cell ledger gates.

This is the module that keeps Lite V2 from becoming a parallel scheduling system.
It does not define a task model, a cell registry or a state machine. It reuses
``ci/round2/validate_ledger.py`` (unmodified) and produces exactly what that
validator already accepts:

    cell.task.evidence[]      -> {"path", "sha256", "source_anchor", "task_id"}
    cell.task.gates.{tests,evidence,c14,c13} -> {"status", "evidence_refs",
                                                 "completed_at", "reviewer"}

The ``reviewer`` on the ``c14`` and ``c13`` gates is the AI execution identity of
the corresponding sealed bundle. The existing validator already requires those two
reviewers to differ, which is the ledger-level expression of "independent review".

DRY RUN ONLY: ``bind`` never writes the ledger and never touches a GitHub Issue.
"""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

from lite_canonical import digest_bytes
from lite_errors import Reject

GATE_NAMES = ("tests", "evidence", "c14", "c13")
VERDICT_TO_GATE_STATUS = {
    "PASS_SCOPED": "PASS_SCOPED",
    "NOT_APPLICABLE": "PASS_SCOPED",  # a sealed NA record is an admissible C14 terminal state
    "FAIL": "FAIL",
    "BLOCKED": "HOLD",
}

_LEDGER_VALIDATOR = None


def ledger_validator_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    return root / "ci" / "round2" / "validate_ledger.py"


def load_ledger_validator():
    """Load the repository's existing ledger validator (never a copy of it)."""
    global _LEDGER_VALIDATOR
    if _LEDGER_VALIDATOR is not None:
        return _LEDGER_VALIDATOR
    path = ledger_validator_path()
    if not path.is_file():
        raise Reject("ledger_validator_missing", str(path))
    spec = importlib.util.spec_from_file_location("go_round2_validate_ledger", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _LEDGER_VALIDATOR = module
    return module


def source_anchor() -> str:
    """The ledger's own anchor constant — imported, not duplicated."""
    return load_ledger_validator().SOURCE_ANCHOR


def evidence_entry(relative_path: str, raw: bytes, task_id: str) -> dict:
    return {
        "path": relative_path,
        "sha256": digest_bytes(raw),
        "source_anchor": source_anchor(),
        "task_id": task_id,
    }


def gate_record(verdict: str, evidence_refs, reviewer: str, completed_at: str) -> dict:
    if verdict not in VERDICT_TO_GATE_STATUS:
        raise Reject("ledger_gate_verdict_unsupported", verdict)
    record = {
        "status": VERDICT_TO_GATE_STATUS[verdict],
        "evidence_refs": list(evidence_refs),
    }
    if record["status"] == "PASS_SCOPED":
        record["completed_at"] = completed_at
        record["reviewer"] = reviewer
    return record


def _cell(ledger, cell_id):
    for cell in ledger.get("cells", []):
        if cell.get("cell_id") == cell_id:
            return cell
    raise Reject("ledger_cell_missing", cell_id)


def _require_task_id(cell, expected_task_id, expected_cell_id):
    task = cell.get("task")
    if not isinstance(task, dict):
        raise Reject("ledger_task_missing", expected_cell_id)
    if task.get("id") != expected_task_id:
        # A bundle asserting a task the scheduler did not dispatch is a rejection,
        # not a silent rebind.
        raise Reject("issue_task_binding_mismatch", f"{expected_cell_id}:{expected_task_id}")
    return task


def bind(
    ledger,
    *,
    evidence_root: Path,
    candidate_sha: str,
    c14_record: dict,
    c13_record: dict,
    c14_evidence: list,
    c13_evidence: list,
    machine_evidence: list,
    completed_at: str,
    mark_tasks_done: bool = True,
) -> dict:
    """Return a NEW ledger with the C13/C14 cells' gates bound to sealed bundles.

    ``c14_evidence`` / ``c13_evidence`` are lists of ``(relative_path, raw_bytes)``
    for the sealed bundles; ``machine_evidence`` covers the C13 machine-test
    artefacts. Files must already exist under ``evidence_root`` because the
    validator re-reads and re-hashes them.
    """
    if c14_record["candidate_sha"] != candidate_sha or c13_record["candidate_sha"] != candidate_sha:
        raise Reject("ledger_candidate_mismatch")
    if c14_record["root_hash"] == c13_record["root_hash"]:
        raise Reject("c14_and_c13_root_identical")
    if c14_record["review_execution_id"] == c13_record["review_execution_id"]:
        raise Reject("c13_equals_c14_execution")

    output = copy.deepcopy(ledger)
    root = Path(evidence_root).resolve()

    def entries(pairs, task_id):
        """Ledger evidence entries are bound to a task, so the same sealed file is
        re-declared for each cell that references it."""
        result = []
        for relative_path, raw in pairs:
            path = (root / relative_path).resolve()
            if not path.is_file() or path.read_bytes() != raw:
                raise Reject("ledger_evidence_not_materialised", relative_path)
            result.append(evidence_entry(relative_path, raw, task_id))
        return result

    c14_cell = _cell(output, "C14")
    c14_task = _require_task_id(c14_cell, c14_record["task_id"], "C14")
    c13_cell = _cell(output, "C13")
    c13_task = _require_task_id(c13_cell, c13_record["task_id"], "C13")

    c14_paths_for_c14 = entries(c14_evidence, c14_record["task_id"])
    c14_paths_for_c13 = entries(c14_evidence, c13_record["task_id"])
    c13_paths_for_c14 = entries(c13_evidence, c14_record["task_id"])
    c13_paths_for_c13 = entries(c13_evidence, c13_record["task_id"])
    machine = entries(machine_evidence, c13_record["task_id"])
    if not machine or not c13_paths_for_c13:
        raise Reject("c13_evidence_incomplete")

    c14_task["evidence"] = c14_paths_for_c14 + c13_paths_for_c14
    c14_task["gates"] = {
        "tests": gate_record("PASS_SCOPED", [e["path"] for e in c14_paths_for_c14], c14_record["review_execution_id"], completed_at),
        "evidence": gate_record("PASS_SCOPED", [e["path"] for e in c14_paths_for_c14], c14_record["review_execution_id"], completed_at),
        "c14": gate_record(c14_record["verdict"], [e["path"] for e in c14_paths_for_c14], c14_record["review_execution_id"], completed_at),
        # Records that the same frozen candidate also passed independent quality
        # acceptance. It does not claim C13 re-reviewed C14's reasoning.
        "c13": gate_record(c13_record["verdict"], [e["path"] for e in c13_paths_for_c14], c13_record["review_execution_id"], completed_at),
    }

    c13_task["evidence"] = machine + c14_paths_for_c13 + c13_paths_for_c13
    c13_task["gates"] = {
        "tests": gate_record("PASS_SCOPED", [e["path"] for e in machine], c13_record["review_execution_id"], completed_at),
        "evidence": gate_record("PASS_SCOPED", [e["path"] for e in machine], c13_record["review_execution_id"], completed_at),
        # The C13 cell's c14 gate records C14's terminal state for the same candidate.
        "c14": gate_record(c14_record["verdict"], [e["path"] for e in c14_paths_for_c13], c14_record["review_execution_id"], completed_at),
        "c13": gate_record(c13_record["verdict"], [e["path"] for e in c13_paths_for_c13], c13_record["review_execution_id"], completed_at),
    }

    if mark_tasks_done:
        for cell, task in ((c14_cell, c14_task), (c13_cell, c13_task)):
            task["status"] = "DONE_SCOPED"
            task["completion"] = {
                "percent": 100,
                "definition": task["completion"]["definition"],
            }
            # The work is scheduled from the existing cells; no new task is invented
            # here, so there is no executable local gap left on these two cells.
            cell["executable_gap"] = False
            cell["next_task"] = None
    return output


def validate_with_repository_validator(ledger, evidence_root: Path) -> dict:
    """Run the repository's own validator over the rebound ledger."""
    module = load_ledger_validator()
    return module.validate(ledger, Path(evidence_root))
