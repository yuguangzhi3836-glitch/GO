from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import select

from go_hotel.db.models import HostedDirectHotelRow, HostedDirectRoomOfferRow
from go_hotel.db.session import SessionLocal
from go_hotel.services.aoluguya_inventory import configure_aoluguya_legacy_fixture as configure_aoluguya
from go_hotel.services.aoluguya_supply_truth import aoluguya_supply_truth_service as svc
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as booking


def official_body(source_updated_at=None):
    stamp = source_updated_at or datetime.now(timezone.utc).isoformat()
    return {
        "supplier_legal_name": "哈尔滨敖麓谷雅酒店",
        "property_key": "aoluguya-harbin",
        "source_type": "HOTEL_OFFICIAL_SUPPLIER_CONSOLE",
        "source_updated_at": stamp,
        "evidence_reference": "hotel-official://aoluguya/supplier-console/approved",
        "rooms": [
            {
                "room_key": "ROUND_DREAM_KING", "room_name": "摄罗子·圆梦大床房", "inventory": 48,
                "rates": [
                    {"rate_plan_key": "RDK-RO", "rate_name": "官方直连｜无早餐", "price_minor": 72800, "currency": "CNY", "breakfast_count": 0, "breakfast": {"count": 0}, "cancellation_policy": "酒店确认后30分钟内免费取消", "taxes_fees": {"included_in_total": True}, "sell_state": "OPEN"},
                    {"rate_plan_key": "RDK-B1", "rate_name": "官方直连｜单早", "price_minor": 82800, "currency": "CNY", "breakfast_count": 1, "breakfast": {"count": 1}, "cancellation_policy": "酒店确认后30分钟内免费取消", "taxes_fees": {"included_in_total": True}, "sell_state": "OPEN"},
                    {"rate_plan_key": "RDK-B2", "rate_name": "官方直连｜双早", "price_minor": 92800, "currency": "CNY", "breakfast_count": 2, "breakfast": {"count": 2}, "cancellation_policy": "酒店确认后30分钟内免费取消", "taxes_fees": {"included_in_total": True}, "sell_state": "OPEN"},
                ],
            },
            {
                "room_key": "ROUND_DREAM_TWIN", "room_name": "摄罗子·圆梦双床房", "inventory": 47,
                "rates": [
                    {"rate_plan_key": "RDT-RO", "rate_name": "官方直连｜无早餐", "price_minor": 72800, "currency": "CNY", "breakfast_count": 0, "breakfast": {"count": 0}, "cancellation_policy": "酒店确认后30分钟内免费取消", "taxes_fees": {"included_in_total": True}, "sell_state": "OPEN"},
                    {"rate_plan_key": "RDT-B1", "rate_name": "官方直连｜单早", "price_minor": 82800, "currency": "CNY", "breakfast_count": 1, "breakfast": {"count": 1}, "cancellation_policy": "酒店确认后30分钟内免费取消", "taxes_fees": {"included_in_total": True}, "sell_state": "OPEN"},
                    {"rate_plan_key": "RDT-B2", "rate_name": "官方直连｜双早", "price_minor": 92800, "currency": "CNY", "breakfast_count": 2, "breakfast": {"count": 2}, "cancellation_policy": "酒店确认后30分钟内免费取消", "taxes_fees": {"included_in_total": True}, "sell_state": "OPEN"},
                ],
            },
            {"room_key": "PILLOW_MOON_KING", "room_name": "摄罗子·枕月大床房", "inventory": 50, "rates": [
                {"rate_plan_key": "PMK-B2", "rate_name": "官方直连｜双早", "price_minor": 102800, "currency": "CNY", "breakfast_count": 2, "breakfast": {"count": 2}, "cancellation_policy": "酒店确认后30分钟内免费取消", "taxes_fees": {"included_in_total": True}, "sell_state": "OPEN"}
            ]},
            {"room_key": "PILLOW_MOON_TWIN", "room_name": "摄罗子·枕月双床房", "inventory": 50, "rates": [
                {"rate_plan_key": "PMT-B2", "rate_name": "官方直连｜双早", "price_minor": 102800, "currency": "CNY", "breakfast_count": 2, "breakfast": {"count": 2}, "cancellation_policy": "酒店确认后30分钟内免费取消", "taxes_fees": {"included_in_total": True}, "sell_state": "OPEN"}
            ]},
            {"room_key": "SLEEPING_CLOUD_TWIN", "room_name": "摄罗子·卧云双床房", "inventory": 46, "rates": [
                {"rate_plan_key": "SCT-B2", "rate_name": "官方直连｜双早", "price_minor": 122800, "currency": "CNY", "breakfast_count": 2, "breakfast": {"count": 2}, "cancellation_policy": "酒店确认后30分钟内免费取消", "taxes_fees": {"included_in_total": True}, "sell_state": "OPEN"}
            ]},
        ],
    }


def setup_bootstrap():
    booking.create_hotel({"supplier_name": "哈尔滨敖麓谷雅酒店", "page_slug": "aoluguya-harbin", "contact": {"environment_marker": "STAGING_TEST_NOT_OFFICIAL"}}, "admin")
    configure_aoluguya()
    with SessionLocal() as s:
        h = s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug == "aoluguya-harbin"))
        for o in s.scalars(select(HostedDirectRoomOfferRow).where(HostedDirectRoomOfferRow.hosted_hotel_id == h.hosted_hotel_id)).all():
            o.rate_name = "Staging测试｜" + o.rate_name
        c = dict(h.contact_json or {})
        c.update({"environment_marker": "STAGING_TEST_NOT_OFFICIAL", "inventory_status": "STAGING_TEST_INVENTORY", "quote_status": "STAGING_TEST_QUOTE_NOT_OFFICIAL"})
        h.contact_json = c
        s.commit()


def test_aoluguya_official_truth_gate_and_projection_replaces_test_truth():
    setup_bootstrap()
    r = svc.ingest_official_truth(official_body(), "hotel-operator")
    assert r["state"] == "HOTEL_OFFICIAL_TRUTH_RECEIVED"
    gate = svc.evaluate()
    assert gate["state"] == "PASS" and all(gate["checks"].values())
    projected = svc.project_to_hosted_direct("go-admin")
    assert projected["active_offers"] == 9 and projected["payment_available"] is False
    status = svc.status()
    assert status["hosted_page"]["official_projection"] is True
    assert status["hosted_page"]["no_test_truth"] is True
    page = booking.page("aoluguya-harbin")
    assert page["payment_available"] is False
    assert all("Staging测试" not in x["rate_name"] for x in page["offers"])
    assert {x["price_minor"] for x in page["offers"]} >= {72800, 82800, 92800, 102800, 122800}


def test_stale_or_test_truth_is_rejected():
    setup_bootstrap()
    stale = official_body((datetime.now(timezone.utc) - timedelta(hours=2)).isoformat())
    with pytest.raises(ValueError, match="STALE_SUPPLY_TRUTH_REJECTED"):
        svc.ingest_official_truth(stale, "hotel")
    bad = official_body()
    bad["rooms"][0]["rates"][0]["rate_name"] = "Staging测试｜官方价"
    with pytest.raises(ValueError, match="TEST_OR_SIMULATED_TRUTH_FORBIDDEN"):
        svc.ingest_official_truth(bad, "hotel")


def test_direct_first_and_unverified_fallback_fail_closed():
    setup_bootstrap()
    svc.ingest_official_truth(official_body(), "hotel")
    direct = svc.route({"business_id": "aoluguya-harbin", "official_available": True, "fallback_candidates": [{"provider_code": "CTRIP", "available": True, "evidence_reference": "contract://ctrip"}]})
    assert direct["route"] == "OFFICIAL_DIRECT" and direct["fallback_used"] is False
    fb = svc.route({"business_id": "hotel-without-direct", "official_available": False, "fallback_candidates": [{"provider_code": "CTRIP", "available": True, "evidence_reference": "contract://ctrip"}, {"provider_code": "MEITUAN", "available": True, "evidence_reference": "contract://meituan"}]})
    assert fb["route"] == "UNAVAILABLE" and fb["fail_closed"] is True
    gov = svc.fallback_governance()
    assert gov["fallback_tier_1"] == ["CTRIP", "MEITUAN"]
    assert gov["providers"]["CTRIP"]["state"] == "NOT_EXTERNALLY_VERIFIED"
    assert gov["providers"]["MEITUAN"]["state"] == "NOT_EXTERNALLY_VERIFIED"
