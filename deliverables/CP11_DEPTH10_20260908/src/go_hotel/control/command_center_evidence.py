"""Command Center verifier/state machine for HK evidence responses."""
from __future__ import annotations
import hashlib, json

TERMINAL = {"PASS", "HOLD"}


def _digest(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class CommandCenterEvidenceState:
    def __init__(self): self.tasks = {}

    def accept(self, response: dict, *, expected_task_id: str, expected_candidate_sha256: str,
               expected_task_sha256: str, expected_node_id: str) -> dict:
        required = {"task_id", "status", "candidate_sha256", "task_sha256", "evidence_sha256", "evidence_manifest"}
        if set(response) != required: raise ValueError("EVIDENCE_RESPONSE_SCHEMA_INVALID")
        if response["task_id"] != expected_task_id: raise ValueError("EVIDENCE_TASK_MISMATCH")
        if response["candidate_sha256"] != expected_candidate_sha256: raise ValueError("EVIDENCE_CANDIDATE_MISMATCH")
        if response["task_sha256"] != expected_task_sha256: raise ValueError("EVIDENCE_TASK_SHA_MISMATCH")
        if response["status"] not in TERMINAL: raise ValueError("EVIDENCE_STATUS_INVALID")
        manifest = response["evidence_manifest"]
        if _digest(manifest) != response["evidence_sha256"]: raise ValueError("EVIDENCE_DIGEST_MISMATCH")
        if manifest.get("node_id") != expected_node_id: raise ValueError("EVIDENCE_NODE_MISMATCH")
        if manifest.get("candidate_sha256") != expected_candidate_sha256: raise ValueError("EVIDENCE_MANIFEST_CANDIDATE_MISMATCH")
        if manifest.get("task_sha256") != expected_task_sha256: raise ValueError("EVIDENCE_MANIFEST_TASK_MISMATCH")
        if manifest.get("status") != response["status"]: raise ValueError("EVIDENCE_STATUS_MISMATCH")
        previous = self.tasks.get(expected_task_id)
        if previous and previous["evidence_sha256"] != response["evidence_sha256"]:
            raise ValueError("EVIDENCE_TERMINAL_MUTATION")
        self.tasks[expected_task_id] = dict(response)
        return {"accepted": True, "terminal": True, "status": response["status"],
                "evidence_sha256": response["evidence_sha256"]}
