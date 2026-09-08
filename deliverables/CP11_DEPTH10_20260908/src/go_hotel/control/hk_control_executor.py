"""Allowlisted HK Staging executor with structured evidence return.

No arbitrary shell is accepted. Every task type maps to a fixed application-side
handler. Results are normalized into a hashable evidence manifest suitable for
Command Center verification.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import traceback

from .hk_control_protocol import VerifiedControlTask


def _now():
    return datetime.now(timezone.utc).isoformat()


def _digest(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ExecutionResult:
    manifest: dict
    evidence_sha256: str


class HKControlExecutor:
    def __init__(self, handlers: dict[str, callable]):
        self.handlers = dict(handlers)

    def execute(self, task: VerifiedControlTask) -> ExecutionResult:
        handler = self.handlers.get(task.task_type)
        if handler is None:
            raise ValueError("CONTROL_HANDLER_NOT_REGISTERED")
        started = _now()
        status = "PASS"
        output = None
        error = None
        try:
            output = handler(task.payload)
            if output is None:
                output = {}
            if not isinstance(output, dict):
                output = {"result": output}
        except Exception as exc:
            status = "HOLD"
            error = {
                "type": exc.__class__.__name__,
                "message": str(exc)[:2000],
                "trace": traceback.format_exc(limit=8)[-8000:],
            }
        manifest = {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "environment": task.environment,
            "authority": task.authority,
            "candidate_sha256": task.candidate_sha256,
            "task_sha256": task.task_sha256,
            "node_id": task.node_id,
            "started_at": started,
            "finished_at": _now(),
            "status": status,
            "output": output if status == "PASS" else None,
            "error": error,
        }
        return ExecutionResult(manifest=manifest, evidence_sha256=_digest(manifest))
