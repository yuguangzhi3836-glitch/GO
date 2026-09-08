"""Durable replay/idempotency guard contract for HK controlled execution."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib

from .hk_control_protocol import VerifiedControlTask


@dataclass(frozen=True)
class ReplayDecision:
    execute: bool
    duplicate_terminal: bool
    reason: str


class HKReplayGuard:
    """Storage-neutral guard. Repository must persist nonce/task state transactionally.

    Required repository methods:
      get_nonce(node_id, nonce) -> dict|None
      get_task(task_id) -> dict|None
      reserve(node_id, nonce, task_id, candidate_sha256, task_sha256, expires_at) -> bool
    """
    def __init__(self, repository):
        self.repository = repository

    def reserve(self, task: VerifiedControlTask, *, nonce_expires_at: datetime) -> ReplayDecision:
        if nonce_expires_at.tzinfo is None or nonce_expires_at <= datetime.now(timezone.utc):
            raise ValueError("CONTROL_NONCE_EXPIRY_INVALID")
        existing_nonce = self.repository.get_nonce(task.node_id, task.nonce)
        if existing_nonce:
            return ReplayDecision(False, False, "CONTROL_REPLAY_NONCE_REJECTED")
        existing = self.repository.get_task(task.task_id)
        if existing:
            same = (
                existing.get("candidate_sha256") == task.candidate_sha256
                and existing.get("task_sha256") == task.task_sha256
            )
            if not same:
                return ReplayDecision(False, False, "CONTROL_TASK_ID_CONFLICT")
            if existing.get("state") in {"PASS", "HOLD", "FAILED"}:
                return ReplayDecision(False, True, "CONTROL_DUPLICATE_TERMINAL")
            return ReplayDecision(False, False, "CONTROL_TASK_ALREADY_ACTIVE")
        ok = self.repository.reserve(
            task.node_id, task.nonce, task.task_id, task.candidate_sha256,
            task.task_sha256, nonce_expires_at,
        )
        if not ok:
            return ReplayDecision(False, False, "CONTROL_RESERVATION_RACE_LOST")
        return ReplayDecision(True, False, "CONTROL_RESERVED")


def evidence_bundle_digest(manifest_bytes: bytes) -> str:
    return hashlib.sha256(manifest_bytes).hexdigest()
