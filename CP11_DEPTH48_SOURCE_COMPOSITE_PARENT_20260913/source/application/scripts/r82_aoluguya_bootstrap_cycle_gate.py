#!/usr/bin/env python3
"""Isolated Staging lifecycle gate for AOLUGUYA Hosted Direct bootstrap."""
import asyncio
import importlib.util
import os
import tempfile
from pathlib import Path

# Must be set before importing application configuration/session modules.
db_path = Path(tempfile.gettempdir()) / f"go_r82_aoluguya_gate_{os.getpid()}.db"
try:
    db_path.unlink()
except FileNotFoundError:
    pass
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
os.environ["APP_ENV"] = "staging"
os.environ.setdefault("SAGA_RETRY_SECONDS", "0")

from fastapi import FastAPI
import httpx
from sqlalchemy import func, select
from go_hotel.db.models import Base, HostedDirectHotelRow, HostedDirectInventoryPoolRow, HostedDirectRoomOfferRow
from go_hotel.db.session import SessionLocal, engine
from go_hotel.api.routes.hosted_direct_booking import router as hosted_direct_router
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service, now

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("r82_bootstrap_cycle", ROOT / "scripts" / "staging_aoluguya_hosted_direct_bootstrap.py")
boot = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(boot)

Base.metadata.create_all(engine)


def counts():
    with SessionLocal() as s:
        h = s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug == boot.SLUG))
        if not h:
            return (0, 0, 0, 0, None)
        return (
            s.scalar(select(func.count()).select_from(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug == boot.SLUG)),
            s.scalar(select(func.count()).select_from(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.hosted_hotel_id == h.hosted_hotel_id)),
            s.scalar(select(func.count()).select_from(HostedDirectRoomOfferRow).where(HostedDirectRoomOfferRow.hosted_hotel_id == h.hosted_hotel_id)),
            s.scalar(select(func.count()).select_from(HostedDirectRoomOfferRow).where(HostedDirectRoomOfferRow.hosted_hotel_id == h.hosted_hotel_id, HostedDirectRoomOfferRow.state == "ACTIVE")),
            h.state,
        )


async def http_status():
    app = FastAPI()
    app.include_router(hosted_direct_router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://r82.test") as client:
        response = await client.get("/v1/direct/aoluguya-harbin")
        return response.status_code, response.json()


assert boot.inspect()["exists"] is False
first = boot.create()["status"]
assert counts() == (1, 5, 9, 9, "PUBLISHED_REQUEST_ONLY"), counts()
assert first["payment_available"] is False
status, body = asyncio.run(http_status())
assert status == 200, (status, body)
assert body["data"]["payment_available"] is False

boot.disable()
assert counts() == (1, 5, 9, 0, "DRAFT"), counts()
status, _ = asyncio.run(http_status())
assert status == 409, status

boot.create()
assert counts() == (1, 5, 9, 9, "PUBLISHED_REQUEST_ONLY"), counts()
status, body = asyncio.run(http_status())
assert status == 200, (status, body)

# A normal repeat must remain idempotent too.
boot.create()
assert counts() == (1, 5, 9, 9, "PUBLISHED_REQUEST_ONLY"), counts()

# Hard rollback is allowed only before any reservation references this graph.
rolled = boot.rollback()
assert rolled["changed"] is True
assert boot.inspect()["exists"] is False

# Recreate, make a no-charge reservation request, then prove rollback is refused.
boot.create()
with SessionLocal() as s:
    offer_id = s.scalar(select(HostedDirectRoomOfferRow.hosted_offer_id).where(HostedDirectRoomOfferRow.hosted_hotel_id == s.scalar(select(HostedDirectHotelRow.hosted_hotel_id).where(HostedDirectHotelRow.page_slug == boot.SLUG))).limit(1))
reservation = hosted_direct_booking_service.reserve(
    boot.SLUG,
    {
        "hosted_offer_id": offer_id,
        "guest_name": "Staging Bootstrap Gate",
        "guest_contact": "staging-gate@example.invalid",
        "check_in": "2026-08-24",
        "check_out": "2026-08-25",
    },
    "r82-bootstrap-cycle-gate-reservation",
)
assert reservation["payment_state"] == "ALIPAY_APPLICATION_PENDING_NO_CHARGE"
try:
    boot.rollback()
except SystemExit as exc:
    assert "REFUSED_ROLLBACK_RESERVATIONS_EXIST" in str(exc)
else:
    raise AssertionError("rollback must refuse referenced bootstrap graph")
boot.disable()
assert counts()[3] == 0

# A manually-added offer must never be silently activated, disabled, or deleted by the
# controlled bootstrap lifecycle.
with SessionLocal() as s:
    h = s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug == boot.SLUG))
    s.add(HostedDirectRoomOfferRow(
        hosted_offer_id="unexpected-r82-bootstrap-offer",
        hosted_hotel_id=h.hosted_hotel_id,
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
try:
    boot.create()
except SystemExit as exc:
    assert "REFUSED_UNEXPECTED_BOOTSTRAP_GRAPH" in str(exc)
else:
    raise AssertionError("bootstrap must refuse an unexpected offer graph")

print("R8.2_AOLUGUYA_BOOTSTRAP_CYCLE_GATE: PASS")
print("create=1 hotel / 5 pools / 9 active offers / reservation-request-only / payment_available=false")
print("disable=DRAFT / 0 active offers / HTTP 409")
print("recreate=same graph / 9 active offers / HTTP 200 / no duplicates")
print("rollback=allowed before references; refused after reservation reference")
print("unexpected_offer=refused; no non-bootstrap offer mutation")

engine.dispose()
try:
    db_path.unlink()
except FileNotFoundError:
    pass
