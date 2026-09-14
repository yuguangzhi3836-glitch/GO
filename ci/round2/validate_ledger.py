#!/usr/bin/env python3
"""Validate/reconcile local development dispatch records. No network or HK authority.

PASS proves the submitted records are internally consistent and referenced bytes
exist. It does not prove a remote worker is alive or turn a review into authority.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

SOURCE_ANCHOR = "fef9c748adb77d37ba5d4dc4fa4662eb668303a1"
CELL_IDS = {f"C{i:02d}" for i in range(1, 15)}
STATUSES = {"ASSIGNED", "RUNNING", "BLOCKED", "IDLE", "DONE_SCOPED", "DONE-SCOPED", "DONE"}
DONE = {"DONE_SCOPED", "DONE-SCOPED", "DONE"}
PASSED = {"PASS", "PASS_SCOPED"}
GATE_NAMES = ("tests", "evidence", "c14", "c13")


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def instant(value):
    if not nonempty(value):
        raise ValueError("timestamp missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp requires timezone")
    return parsed


def followup_template(cell):
    """Use declared next work; IDLE may resume its existing unfinished task."""
    template = cell.get("next_task")
    if isinstance(template, dict):
        return template
    task = cell.get("task", {})
    if task.get("status") == "IDLE":
        return {
            "id": task.get("id"), "description": task.get("description"),
            "scope": task.get("scope"), "test_plan": task.get("test_plan"),
            "completion_definition": task.get("completion", {}).get("definition"),
        }
    return None


def validate(ledger, evidence_root):
    errors, reassign = [], []
    if not isinstance(ledger, dict):
        return {"gate": "HOLD", "errors": ["ledger must be an object"], "reassign_cells": []}
    if ledger.get("schema_version") != 1:
        errors.append("schema_version must equal 1")
    if ledger.get("source_anchor") != SOURCE_ANCHOR:
        errors.append("source_anchor does not match the locked main")
    if not nonempty(ledger.get("round_id")):
        errors.append("round_id must be concrete")
    if not isinstance(ledger.get("events"), list):
        errors.append("events must be an append-preserved list")
    if not isinstance(ledger.get("followups", []), list):
        errors.append("followups must be a list")
    cells = ledger.get("cells")
    if not isinstance(cells, list) or not all(isinstance(c, dict) for c in cells):
        return {"gate": "HOLD", "errors": errors + ["cells must be object list"], "reassign_cells": []}
    ids = [c.get("cell_id") for c in cells]
    if len(ids) != 14 or set(str(i) for i in ids) != CELL_IDS:
        errors.append("exactly one of each C01-C14 is required")
    root = Path(evidence_root).resolve()
    for cell in cells:
        cid = cell.get("cell_id", "UNKNOWN")
        issue = lambda message: errors.append(f"{cid}: {message}")
        task = cell.get("task")
        if not isinstance(task, dict):
            issue("task must be an object")
            continue
        for field in ("id", "description", "scope", "test_plan"):
            if not nonempty(task.get(field)):
                issue(f"task.{field} must be concrete")
        state = task.get("status")
        if not isinstance(state, str) or state not in STATUSES:
            issue("invalid task.status")
            state = "INVALID"
        completion = task.get("completion")
        if not isinstance(completion, dict):
            issue("task.completion must be an object")
            completion = {}
        percent = completion.get("percent")
        if isinstance(percent, bool) or not isinstance(percent, (float, int)) or not 0 <= percent <= 100:
            issue("completion.percent must be 0..100")
        if not nonempty(completion.get("definition")):
            issue("completion.definition must state the scoped denominator")
        if type(cell.get("executable_gap")) is not bool:
            issue("executable_gap must be boolean")
        if "next_task" not in cell:
            issue("next_task is required (null is explicit)")
        if state == "BLOCKED" and not nonempty(cell.get("blocked_reason")):
            issue("BLOCKED requires a concrete blocked_reason")
        evidence = task.get("evidence")
        if not isinstance(evidence, list):
            issue("task.evidence must be a list")
            evidence = []
        verified = set()
        for item in evidence:
            if not isinstance(item, dict):
                issue("evidence entry must be an object")
                continue
            rel = item.get("path")
            if not nonempty(rel):
                issue("evidence path missing")
                continue
            if item.get("source_anchor") != SOURCE_ANCHOR or item.get("task_id") != task.get("id"):
                issue(f"evidence identity mismatch: {rel}")
                continue
            digest = item.get("sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                issue(f"invalid evidence SHA256: {rel}")
                continue
            path = (root / rel).resolve()
            if Path(rel).is_absolute() or not path.is_relative_to(root) or not path.is_file():
                issue(f"evidence missing or outside root: {rel}")
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                issue(f"evidence checksum mismatch: {rel}")
                continue
            verified.add(rel)
        if state == "RUNNING":
            refs = task.get("execution_evidence_refs")
            if not isinstance(refs, list) or not refs or not all(isinstance(r, str) and r in verified for r in refs):
                issue("RUNNING requires verified execution_evidence_refs")
        gates = task.get("gates")
        if not isinstance(gates, dict):
            issue("task.gates must be an object")
            gates = {}
        passed = []
        times = {}
        for name in GATE_NAMES:
            gate = gates.get(name)
            if not isinstance(gate, dict):
                issue(f"gate {name} missing")
                continue
            gate_status = gate.get("status")
            if not isinstance(gate_status, str) or gate_status not in PASSED | {"HOLD", "FAIL"}:
                issue(f"gate {name} status invalid")
                gate_status = "INVALID"
            refs = gate.get("evidence_refs")
            if not isinstance(refs, list):
                issue(f"gate {name} evidence_refs must be a list")
            if gate_status in PASSED:
                passed.append(name)
                if not isinstance(refs, list) or not refs or not all(isinstance(r, str) and r in verified for r in refs):
                    issue(f"gate {name} PASS requires verified evidence_refs")
                try:
                    times[name] = instant(gate.get("completed_at"))
                except (TypeError, ValueError):
                    issue(f"gate {name} PASS requires completed_at with timezone")
                if name in ("c14", "c13") and not nonempty(gate.get("reviewer")):
                    issue(f"gate {name} PASS requires reviewer identity")
        for index, name in enumerate(GATE_NAMES):
            if name in passed:
                if any(predecessor not in passed for predecessor in GATE_NAMES[:index]):
                    issue(f"gate {name} passed before predecessors")
                if index and name in times and GATE_NAMES[index - 1] in times and times[name] < times[GATE_NAMES[index - 1]]:
                    issue(f"gate {name} timestamp precedes predecessor")
        if "c13" in passed and gates.get("c13", {}).get("reviewer") == gates.get("c14", {}).get("reviewer"):
            issue("C13 independent reviewer must differ from C14")
        if percent == 100 and (state not in DONE or len(passed) != 4 or not verified):
            issue("100% requires DONE_SCOPED and verified tests→Evidence→C14→C13")
        if state in DONE and percent != 100:
            issue("DONE_SCOPED requires scoped completion 100")
        if cell.get("executable_gap") is True and (state in DONE or state in {"IDLE", "BLOCKED"}):
            reassign.append(cid)
            template = followup_template(cell)
            if not isinstance(template, dict) or not all(nonempty(template.get(k)) for k in ("id", "description", "scope", "completion_definition", "test_plan")):
                issue("executable gap requires a concrete next_task template before reconciliation")
            elif state in DONE and template["id"] == task["id"]:
                issue("DONE_SCOPED followup must identify new scope; inherited PASS must not be rerun")
    return {"gate": "SCHEDULER_FAIL" if reassign else ("HOLD" if errors else "PASS_SCOPED"),
            "errors": errors, "reassign_cells": reassign,
            "meaning": "Local development ledger consistency only; no remote ACK or runtime authority."}


def reconcile(ledger, report, now=None):
    """Preserve history and create real local ASSIGNED records; never fake an ACK."""
    if report["errors"]:
        raise ValueError("Cannot reconcile invalid ledger; repair input errors first")
    output = copy.deepcopy(ledger)
    timestamp = now or datetime.now(timezone.utc).isoformat()
    instant(timestamp)
    output.setdefault("followups", [])
    for cell in output["cells"]:
        if cell["cell_id"] not in report["reassign_cells"]:
            continue
        old = cell["task"]
        template = followup_template(cell)
        identity = f"{output['round_id']}:{cell['cell_id']}:{old['id']}:{template['id']}:{len(cell.get('task_history', []))}"
        assignment_id = "local-followup-" + hashlib.sha256(identity.encode()).hexdigest()[:20]
        record = {"id": assignment_id, "cell_id": cell["cell_id"], "task_id": template["id"],
                  "status": "ASSIGNED", "assigned_at": timestamp, "source_anchor": SOURCE_ANCHOR,
                  "description": template["description"], "scope": template["scope"],
                  "test_plan": template["test_plan"], "transport": "LOCAL_DEVELOPMENT_RECORD",
                  "acknowledged_at": None, "started_at": None}
        cell.setdefault("task_history", []).append(copy.deepcopy(old))
        cell["task"] = {"id": template["id"], "description": template["description"],
                        "scope": template["scope"], "test_plan": template["test_plan"],
                        "status": "ASSIGNED", "completion": {"percent": 0, "definition": template["completion_definition"]},
                        "evidence": [], "execution_evidence_refs": [],
                        "gates": {name: {"status": "HOLD", "evidence_refs": []} for name in GATE_NAMES}}
        cell["next_task"] = None
        cell.pop("blocked_reason", None)
        output["followups"].append(record)
        output["events"].append({"event": "SCHEDULER_FAIL", "cell_id": cell["cell_id"],
                                  "at": timestamp, "previous_task_id": old["id"], "previous_status": old["status"]})
        output["events"].append({"event": "LOCAL_TASK_ASSIGNED", "cell_id": cell["cell_id"],
                                  "at": timestamp, "assignment_id": assignment_id, "task_id": template["id"], "status": "ASSIGNED"})
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--evidence-root", type=Path, default=Path.cwd())
    parser.add_argument("--report", type=Path)
    parser.add_argument("--reconcile-out", type=Path, help="Write an explicit new ledger; never overwrite source")
    args = parser.parse_args()
    try:
        if args.reconcile_out and args.reconcile_out.resolve() == args.ledger.resolve():
            raise ValueError("Reconciliation output must differ from original ledger")
        ledger = json.loads(args.ledger.read_text())
        report = validate(ledger, args.evidence_root)
        if args.reconcile_out and not report["errors"]:
            output = reconcile(ledger, report)
            post = validate(output, args.evidence_root)
            report["reconciled_gate"] = post["gate"]
            report["reconciled_errors"] = post["errors"]
            with args.reconcile_out.open("x") as file:
                json.dump(output, file, ensure_ascii=False, indent=2)
                file.write("\n")
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.report:
            with args.report.open("x") as file:
                file.write(rendered)
        print(rendered, end="")
        return 0 if report["gate"] == "PASS_SCOPED" else 1
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({"gate": "HOLD", "errors": [str(error)]}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
