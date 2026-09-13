"""Diagnostic only: distinguish coroutine cancellation from TestClient teardown."""
import asyncio
from threading import Event, Thread

from fastapi.testclient import TestClient
from go_hotel import main
from go_hotel.workers import vertical_expiry_worker


def test_cancelled_worker_coroutine_does_not_stop_inflight_thread(monkeypatch):
    started, release, finished = Event(), Event(), Event()

    def blocked_tick():
        started.set()
        try:
            assert release.wait(3), "diagnostic release missing"
            return {"scanned": 0}
        finally:
            finished.set()

    monkeypatch.setattr(vertical_expiry_worker, "expire_due", blocked_tick)

    async def scenario():
        task = asyncio.create_task(vertical_expiry_worker.run())
        try:
            assert await asyncio.to_thread(started.wait, 2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            assert task.cancelled()
            assert not finished.is_set()
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 2)

    asyncio.run(scenario())


def test_normal_testclient_exit_waits_for_default_executor_thread(monkeypatch):
    started, release, leave_context, closed = Event(), Event(), Event(), Event()
    errors = []

    def blocked_tick():
        started.set()
        assert release.wait(3), "diagnostic release missing"
        return {"scanned": 0}

    monkeypatch.setattr(vertical_expiry_worker, "expire_due", blocked_tick)
    monkeypatch.setattr(main.identity_service, "bootstrap", lambda: None)
    monkeypatch.setattr(main.settings, "vertical_reservation_expiry_worker_enabled", True)
    monkeypatch.setattr(main.settings, "hosted_reservation_expiry_worker_enabled", False)

    def own_client():
        try:
            with TestClient(main.app):
                assert leave_context.wait(3)
        except BaseException as exc:
            errors.append(exc)
        finally:
            closed.set()

    owner = Thread(target=own_client, name="C12-owned-client")
    owner.start()
    try:
        assert started.wait(2)
        leave_context.set()
        assert not closed.wait(0.1), "TestClient exited while default-executor work remained"
    finally:
        leave_context.set()
        release.set()
        owner.join(timeout=3)
    assert closed.is_set()
    assert not errors
