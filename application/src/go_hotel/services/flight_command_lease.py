"""Keep a local flight command leased while its callback is still running.

This is a liveness aid, not an external payment fence. Recovery still has to
prove the authoritative payment snapshot and every completion checks its token.
"""
from contextlib import contextmanager
from threading import Event, Thread

from go_hotel.repositories.sql import repo


@contextmanager
def flight_command_lease(operation, key, resource_id, token):
    stopped = Event()
    failures = []

    def renew():
        repo.heartbeat_recoverable_idempotency(operation, key, resource_id, token)

    def keep_alive():
        while not stopped.wait(3):
            try:
                renew()
            except Exception as exc:
                failures.append(exc)
                return

    renew()
    worker = Thread(target=keep_alive, name='flight-command-lease', daemon=True)
    worker.start()
    try:
        yield
    finally:
        stopped.set()
        worker.join(timeout=15)
    if worker.is_alive():
        raise ValueError('IDEMPOTENCY_HEARTBEAT_UNAVAILABLE')
    if failures:
        raise ValueError('IDEMPOTENCY_HEARTBEAT_UNAVAILABLE') from failures[0]
    renew()
