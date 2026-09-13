#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
fd, dbpath = tempfile.mkstemp(prefix="go_rc15_", suffix=".db")
os.close(fd)
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{dbpath}"

from sqlalchemy import select
from go_hotel.db.models import Base, HostedDirectHotelRow, HostedDirectRoomOfferRow
from go_hotel.db.session import engine, SessionLocal
from go_hotel.services.aoluguya_inventory import configure_aoluguya
from go_hotel.services.aoluguya_supply_truth import aoluguya_supply_truth_service as svc
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service as booking


def body():
    def rate(key, name, price, breakfast):
        return {
            "rate_plan_key": key, "rate_name": name, "price_minor": price, "currency": "CNY",
            "breakfast_count": breakfast, "breakfast": {"count": breakfast},
            "cancellation_policy": "酒店确认后30分钟内免费取消",
            "taxes_fees": {"included_in_total": True}, "sell_state": "OPEN",
        }
    return {
        "supplier_legal_name": "哈尔滨敖麓谷雅酒店",
        "property_key": "aoluguya-harbin",
        "source_type": "HOTEL_OFFICIAL_SUPPLIER_CONSOLE",
        "source_updated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_reference": "hotel-official://aoluguya/supplier-console/approved",
        "rooms": [
            {"room_key":"ROUND_DREAM_KING","room_name":"摄罗子·圆梦大床房","inventory":48,"rates":[rate("RDK-RO","官方直连｜无早餐",72800,0),rate("RDK-B1","官方直连｜单早",82800,1),rate("RDK-B2","官方直连｜双早",92800,2)]},
            {"room_key":"ROUND_DREAM_TWIN","room_name":"摄罗子·圆梦双床房","inventory":47,"rates":[rate("RDT-RO","官方直连｜无早餐",72800,0),rate("RDT-B1","官方直连｜单早",82800,1),rate("RDT-B2","官方直连｜双早",92800,2)]},
            {"room_key":"PILLOW_MOON_KING","room_name":"摄罗子·枕月大床房","inventory":50,"rates":[rate("PMK-B2","官方直连｜双早",102800,2)]},
            {"room_key":"PILLOW_MOON_TWIN","room_name":"摄罗子·枕月双床房","inventory":50,"rates":[rate("PMT-B2","官方直连｜双早",102800,2)]},
            {"room_key":"SLEEPING_CLOUD_TWIN","room_name":"摄罗子·卧云双床房","inventory":46,"rates":[rate("SCT-B2","官方直连｜双早",122800,2)]},
        ],
    }

checks = {}

# Fallback provider templates must remain incomplete until signed supplier docs arrive.
import json
for fn, code in (("ctrip_fallback_sandbox_template.json", "CTRIP"), ("meituan_fallback_sandbox_template.json", "MEITUAN")):
    tp = ROOT / "specs" / "provider_adapters" / fn
    raw = json.loads(tp.read_text(encoding="utf-8")) if tp.is_file() else {}
    checks[f"fallback_template_exists:{code}"] = bool(raw)
    checks[f"fallback_template_tier1:{code}"] = (raw.get("provider") or {}).get("provider_code") == code and (raw.get("go_routing") or {}).get("priority_tier") == 1
    checks[f"fallback_template_no_invented_endpoint:{code}"] = str((raw.get("transport") or {}).get("base_url") or "").startswith("__REQUIRED_")
    checks[f"fallback_template_fail_closed:{code}"] = (raw.get("error_mapping") or {}).get("unknown_error_policy") == "FAIL_CLOSED"
try:
    Base.metadata.create_all(engine)
    booking.create_hotel({"supplier_name":"哈尔滨敖麓谷雅酒店","page_slug":"aoluguya-harbin","contact":{"environment_marker":"STAGING_TEST_NOT_OFFICIAL"}}, "gate")
    configure_aoluguya()
    with SessionLocal() as s:
        h=s.scalar(select(HostedDirectHotelRow).where(HostedDirectHotelRow.page_slug=="aoluguya-harbin"))
        for o in s.scalars(select(HostedDirectRoomOfferRow).where(HostedDirectRoomOfferRow.hosted_hotel_id==h.hosted_hotel_id)).all():
            o.rate_name="Staging测试｜"+o.rate_name
        c=dict(h.contact_json or {})
        c.update({"environment_marker":"STAGING_TEST_NOT_OFFICIAL","inventory_status":"STAGING_TEST_INVENTORY","quote_status":"STAGING_TEST_QUOTE_NOT_OFFICIAL"})
        h.contact_json=c
        s.commit()

    template=svc.official_snapshot_template()
    ing=svc.ingest_official_truth(body(), "hotel-operator")
    gate=svc.evaluate()
    projection=svc.project_to_hosted_direct("go-admin")
    status=svc.status()
    page=booking.page("aoluguya-harbin")
    direct=svc.route({"business_id":"aoluguya-harbin","official_available":True,"fallback_candidates":[{"provider_code":"CTRIP","available":True,"evidence_reference":"contract://ctrip"}]})
    fb=svc.route({"business_id":"other-hotel","official_available":False,"fallback_candidates":[{"provider_code":"CTRIP","available":True,"evidence_reference":"contract://ctrip"},{"provider_code":"MEITUAN","available":True,"evidence_reference":"contract://meituan"}]})
    gov=svc.fallback_governance()
    rollback=svc.rollback_cutover("go-admin")
    restored=booking.page("aoluguya-harbin")

    checks.update({
        "official_template_5_rooms_9_rates": template["required_room_count"] == 5 and template["required_rate_variant_count"] == 9 and len(template["rooms"]) == 5 and sum(len(x["rates"]) for x in template["rooms"]) == 9,
        "named_hotel_connector": ing["state"] == "HOTEL_OFFICIAL_TRUTH_RECEIVED",
        "all_supply_truth_checks": gate["state"] == "PASS" and all(gate["checks"].values()),
        "official_projection_9_offers": projection["active_offers"] == 9,
        "no_test_truth_after_projection": status["hosted_page"]["no_test_truth"] is True,
        "reservation_request_only": page["booking_mode"] == "RESERVATION_REQUEST_ONLY",
        "payment_stays_disconnected": page["payment_available"] is False,
        "direct_first": direct["route"] == "OFFICIAL_DIRECT" and direct["fallback_used"] is False,
        "unverified_fallback_fail_closed": fb["route"] == "UNAVAILABLE" and fb["fail_closed"] is True,
        "ctrip_meituan_tier1": gov["fallback_tier_1"] == ["CTRIP","MEITUAN"],
        "ctrip_not_externally_verified": gov["providers"]["CTRIP"]["state"] == "NOT_EXTERNALLY_VERIFIED",
        "meituan_not_externally_verified": gov["providers"]["MEITUAN"]["state"] == "NOT_EXTERNALLY_VERIFIED",
        "cutover_rollback_available": rollback["state"] == "AOLUGUYA_CUTOVER_ROLLED_BACK",
        "rollback_restores_test_baseline": restored["payment_available"] is False,
    })
finally:
    try:
        engine.dispose()
        os.remove(dbpath)
    except Exception:
        pass

for k,v in checks.items():
    print(f"{k}={'PASS' if v else 'FAIL'}")
if not checks or not all(checks.values()):
    raise SystemExit(1)
print("R8.2_RC15_SUPPLY_TRUTH_GATE: PASS")
