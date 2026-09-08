"""Background lease heartbeat guard for long-running durable tasks."""
from __future__ import annotations

from contextlib import AbstractContextManager
import threading

from .chain_task_lease import chain_task_lease_service


class LeaseHeartbeat(AbstractContextManager):
    def __init__(self, *, task_id: str, worker_id: str, lease_seconds: int, actor: str = "SYSTEM"):
        if lease_seconds < 15:
            raise ValueError("LEASE_HEARTBEAT_LEASE_TOO_SHORT")
        self.task_id = task_id
        self.worker_id = worker_id
        self.lease_seconds = int(lease_seconds)
        self.actor = actor
        self.interval = max(5, min(60, self.lease_seconds // 3))
        self.stop_event = threading.Event()
        self.thread = None
        self.error = None

    def _run(self):
        while not self.stop_event.wait(self.interval):
            try:
                chain_task_lease_service.heartbeat(
                    task_id=self.task_id,
                    worker_id=self.worker_id,
                    lease_seconds=self.lease_seconds,
                    actor=self.actor,
                )
            except Exception as exc:  # fail closed after current operation returns
                self.error = exc
                self.stop_event.set()
                return

    def __enter__(self):
        self.thread = threading.Thread(target=self._run, name=f"lease-heartbeat-{self.task_id[:12]}", daemon=True)
        self.thread.start()
        return self

    def assert_healthy(self):
        if self.error is not None:
            raise RuntimeError(f"LEASE_HEARTBEAT_FAILED:{self.error}") from self.error

    def __exit__(self, exc_type, exc, tb):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=max(2, self.interval + 1))
        if exc_type is None:
            self.assert_healthy()
        return False
