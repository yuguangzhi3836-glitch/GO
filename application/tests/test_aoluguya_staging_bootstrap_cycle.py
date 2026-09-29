import asyncio
import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI
import httpx
from sqlalchemy import func, select

from go_hotel.db.models import (
    Base,
    HostedDirectHotelRow,
    HostedDirectInventoryPoolRow,
    HostedDirectReservationRow,
    HostedDirectRoomOfferRow,
)
from go_hotel.db.session import SessionLocal, engine
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service, now
from go_hotel.api.routes.hosted_direct_booking import router as hosted_direct_router

pytestmark = pytest.mark.no_db


@pytest.fixture(autouse=True)
def reset_bootstrap_database():
    """Keep this lifecycle suite isolated from the broad application bootstrap."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield
    finally:
        engine.dispose()


def _bootstrap_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "staging_aoluguya_hosted_direct_bootstrap.py"
    spec = importlib.util.spec_from_file_location("staging_aoluguya_bootstrap_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _counts():
    with SessionLocal() as s:
        h = s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug == "aoluguya-harbin"))
        if not h:
            return {"hotels": 0, "pools": 0, "offers": 0, "active_offers": 0, "state": None}
        return {
            "hotels": s.scalar(select(func.count()).select_from(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug == "aoluguya-harbin")),
            "pools": s.scalar(select(func.count()).select_from(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.hosted_hotel_id == h.hosted_hotel_id)),
            "offers": s.scalar(select(func.count()).select_from(HostedDirectRoomOfferRow).where(HostedDirectRoomOfferRow.hosted_hotel_id == h.hosted_hotel_id)),
            "active_offers": s.scalar(select(func.count()).select_from(HostedDirectRoomOfferRow).where(HostedDirectRoomOfferRow.hosted_hotel_id == h.hosted_hotel_id, HostedDirectRoomOfferRow.state == "ACTIVE")),
            "state": h.state,
        }


def _page():
    app = FastAPI()
    app.include_router(hosted_direct_router)
    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://r82.test") as client:
            response = await client.get("/v1/direct/aoluguya-harbin")
            return response.status_code, response.json()
    return asyncio.run(request())


def test_create_disable_create_cycle_is_idempotent_and_requires_publication_review(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    boot = _bootstrap_module()

    assert boot.inspect()["exists"] is False

    created = boot.create()["status"]
    assert created["state"] == "DRAFT"
    assert created["pools"] == 5
    assert created["offers"] == 9
    assert created["active_offers"] == 9
    assert created["payment_available"] is False
    assert _counts() == {"hotels": 1, "pools": 5, "offers": 9, "active_offers": 9, "state": "DRAFT"}

    status, page = _page()
    assert status == 409

    disabled = boot.disable()["status"]
    assert disabled["state"] == "DRAFT"
    assert disabled["active_offers"] == 0
    assert _page()[0] == 409

    recreated = boot.create()["status"]
    assert recreated["state"] == "DRAFT"
    assert recreated["pools"] == 5
    assert recreated["offers"] == 9
    assert recreated["active_offers"] == 9
    assert recreated["payment_available"] is False
    assert _counts() == {"hotels": 1, "pools": 5, "offers": 9, "active_offers": 9, "state": "DRAFT"}
    assert _page()[0] == 409

    # Third create proves no duplicate graph is created on a normal repeat either.
    boot.create()
    assert _counts() == {"hotels": 1, "pools": 5, "offers": 9, "active_offers": 9, "state": "DRAFT"}


def test_rollback_refuses_when_reservation_references_bootstrap_offer(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    boot = _bootstrap_module()
    boot.create()
    with SessionLocal() as s:
        offer_id = s.scalar(select(HostedDirectRoomOfferRow.hosted_offer_id).limit(1))

    # Historical reference fixture: blocked drafts cannot accept a new request.
    with SessionLocal.begin() as session:
        session.add(HostedDirectReservationRow(hosted_reservation_id='historic-bootstrap-request',
            hosted_offer_id=offer_id,idempotency_key='historic-bootstrap-request',guest_name='Synthetic',
            guest_contact='synthetic@example.invalid',check_in='2026-08-24',check_out='2026-08-25',
            amount_minor=1,currency='CNY',reservation_state='CANCELLED',
            payment_state='NO_PAYMENT_NO_REFUND_REQUIRED',created_at=now(),updated_at=now()))
    with pytest.raises(SystemExit, match="REFUSED_ROLLBACK_RESERVATIONS_EXIST"):
        boot.rollback()
    assert _counts()["hotels"] == 1
    boot.disable()
    assert _counts()["active_offers"] == 0


def test_rollback_deletes_unused_bootstrap_graph(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    boot = _bootstrap_module()
    boot.create()
    rolled = boot.rollback()
    assert rolled["changed"] is True
    assert boot.inspect()["exists"] is False
    assert _counts()["hotels"] == 0


def test_bootstrap_refuses_an_unexpected_offer_graph(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    boot = _bootstrap_module()
    boot.create()
    with SessionLocal() as s:
        hotel_id = s.scalar(select(HostedDirectHotelRow.hosted_hotel_id).where(HostedDirectHotelRow.page_slug == "aoluguya-harbin"))
        s.add(HostedDirectRoomOfferRow(
            hosted_offer_id="unexpected-bootstrap-offer",
            hosted_hotel_id=hotel_id,
            room_name="Unexpected test offer",
            rate_name="Manual offer",
            price_minor=1,
            currency="CNY",
            inventory=1,
            cancellation_policy="Not part of bootstrap",
            state="INACTIVE",
            updated_at=now(),
        ))
        s.commit()
    with pytest.raises(SystemExit, match="REFUSED_UNEXPECTED_BOOTSTRAP_GRAPH"):
        boot.create()
