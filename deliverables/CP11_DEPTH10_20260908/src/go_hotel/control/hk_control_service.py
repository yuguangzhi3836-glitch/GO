"""Composed fail-closed HK Staging control service.

Transport adapters call this service after TLS termination. Verification, authority,
replay reservation, execution and evidence hashing remain independent of HTTP framework.
"""
from __future__ import annotations

from .hk_control_protocol import verify_envelope
from .hk_control_executor import HKControlExecutor
from .hk_authority_gate import enforce_hk_authority
from go_hotel.services.production_bindings import production_authorities


class HKControlService:
    def __init__(self, *, secret: bytes, node_id: str, replay_guard, handlers: dict[str, callable]):
        self.secret = secret
        self.node_id = node_id
        self.replay_guard = replay_guard
        self.executor = HKControlExecutor(handlers)

    def submit(self, envelope: dict) -> dict:
        task = verify_envelope(envelope, secret=self.secret, expected_node_id=self.node_id)
        enforce_hk_authority(
            task_type=task.task_type,
            environment=task.environment,
            authority=task.authority,
            production_authorities=production_authorities(),
        )
        reservation = self.replay_guard.reserve(
            task_id=task.task_id,
            nonce=task.nonce,
            task_sha256=task.task_sha256,
            candidate_sha256=task.candidate_sha256,
        )
        if reservation.get("terminal"):
            return reservation["response"]
        result = self.executor.execute(task)
        response = {
            "task_id": task.task_id,
            "status": result.manifest["status"],
            "candidate_sha256": task.candidate_sha256,
            "task_sha256": task.task_sha256,
            "evidence_sha256": result.evidence_sha256,
            "evidence_manifest": result.manifest,
        }
        self.replay_guard.complete(task_id=task.task_id, response=response)
        return response
