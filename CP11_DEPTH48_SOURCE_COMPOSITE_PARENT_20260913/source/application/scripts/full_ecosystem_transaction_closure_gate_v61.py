#!/usr/bin/env python3
from __future__ import annotations
import argparse, asyncio, json, os, sys, tempfile
from pathlib import Path

# Must be set before database modules import.
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:////tmp/go_v61_full_ecosystem_closure_{os.getpid()}.db")

from go_hotel.db.models import Base
from go_hotel.db.session import engine
from go_hotel.payments.mock import payment_provider
from go_hotel.services.booking import booking_service
from go_hotel.fare.service import fare_service
from go_hotel.truth.service import truth_service
from go_hotel.flight.service import flight_service
from go_hotel.rail.service import rail_service
from go_hotel.mobility.service import mobility_service
from go_hotel.attractions.service import attraction_service
from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service

VERTICALS = ("HOTEL", "FLIGHT", "RAIL", "RIDE", "RENTAL", "ATTRACTION")


def reset_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    payment_provider.reset()


def check(cond, message):
    if not cond:
        raise AssertionError(message)


def project_trip(vertical, order_id, account="gate-account", state="CONFIRMED", payment="CAPTURED", refund="NONE"):
    return consumer_unified_lifecycle_service.project({
        "account_id": account,
        "vertical": vertical,
        "order_id": order_id,
        "title": f"{vertical} closure gate item",
        "lifecycle_state": state,
        "payment_state": payment,
        "refund_state": refund,
        "evidence_reference": f"gate://{vertical.lower()}/{order_id}",
        "source_updated_at": "2026-08-22T00:00:00+00:00",
        "facts": {"gate": "V6.1"},
    })


async def hotel_contract():
    offers = await booking_service.search("TYO", "2026-09-15", "2026-09-17", "CNY")
    check(bool(offers), "HOTEL_SEARCH_EMPTY")
    pb = await booking_service.prebook(offers[0].offer_id)
    order = await booking_service.create_order(pb.prebook_id, "gate-account")
    payment = await booking_service.pay(order.order_id, order.total_amount_minor, order.currency, "pm_success")
    confirmed = await booking_service.confirm(order.order_id)
    check(confirmed.status.value == "CONFIRMED", "HOTEL_CONFIRM_FAILED")
    check(payment_provider.capture_calls >= 1, "HOTEL_CAPTURE_NOT_EXECUTED")
    trip = project_trip("HOTEL", order.order_id)
    check(trip["lifecycle_state"] == "CONFIRMED", "HOTEL_TRIP_PROJECTION_FAILED")

    # Cancellation/refund branch on the confirmed order.
    q = fare_service.cancellation_quote(order.order_id)
    cancelled = await fare_service.cancel(order.order_id, q["quote_id"])
    check(cancelled["status"] == "CANCELLED", "HOTEL_CANCEL_FAILED")
    check(cancelled["refund"] is not None and cancelled["refund"]["status"] == "COMPLETED", "HOTEL_REFUND_FAILED")

    # Separate fulfilled/review branch: confirmed booking -> verified review -> published.
    offers2 = await booking_service.search("TYO", "2026-10-15", "2026-10-17", "CNY")
    pb2 = await booking_service.prebook(offers2[0].offer_id)
    order2 = await booking_service.create_order(pb2.prebook_id, "gate-account")
    await booking_service.pay(order2.order_id, order2.total_amount_minor, order2.currency, "pm_success")
    confirmed2 = await booking_service.confirm(order2.order_id)
    review = truth_service.create_eligibility(confirmed2.order_id, True, "FULFILLMENT_COMPLETED_GATE")
    done = truth_service.submit_star(review["review_id"], 5)
    check(done["status"] == "COMPLETED" and done["public_status"] == "PUBLISHED", "HOTEL_REVIEW_NOT_PUBLISHED")
    return {
        "search": "PASS", "prebook": "PASS", "order": "PASS", "payment": "SIMULATED_CAPTURE_PASS",
        "supplier_confirmation": "PASS", "go_trips": "PASS", "cancel": "PASS", "refund": "SIMULATED_ORIGINAL_METHOD_PASS",
        "fulfillment_review": "PASS",
    }


def flight_contract():
    items = flight_service.search("PVG", "NRT", "2026-09-15")
    pb = flight_service.prebook(items[0]["offer_id"])
    o = flight_service.create_order("gate-account", pb["prebook_id"], [{"full_name":"CHEN TEST","type":"ADT"}])
    ticketed = flight_service.checkout("gate-account", o["order_id"], "pm_test_token")
    check(ticketed["status"] == "TICKETED" and ticketed["ticket_numbers"], "FLIGHT_TICKETING_FAILED")
    project_trip("FLIGHT", o["order_id"])
    q = flight_service.change_quote("gate-account", o["order_id"], "2026-09-17")
    changed = flight_service.execute_change("gate-account", o["order_id"], q["quote_id"])
    check(changed["ticket_numbers"][0].endswith("R"), "FLIGHT_REISSUE_FAILED")
    rq = flight_service.refund_quote("gate-account", o["order_id"])
    check(rq["refund_to"] == "ORIGINAL_PAYMENT_METHOD", "FLIGHT_REFUND_ROUTE_INVALID")
    rr = flight_service.refund("gate-account", o["order_id"])
    check(rr["status"] == "REFUND_COMPLETED", "FLIGHT_REFUND_FAILED")
    return {"search":"PASS","prebook":"PASS","order":"PASS","payment":"DETERMINISTIC_SIMULATOR_PASS","ticket":"PASS","go_trips":"PASS","change_reissue":"PASS","refund":"SIMULATED_ORIGINAL_METHOD_PASS"}


def rail_contract():
    items = rail_service.search("SHA", "HZH", "2026-09-15")
    pb = rail_service.prebook(items[0]["offer_id"])
    o = rail_service.create_order("gate-account", pb["prebook_id"], [{"full_name":"CHEN TEST","type":"ADT"}])
    ticketed = rail_service.checkout("gate-account", o["order_id"], "pm_test_token")
    check(ticketed["status"] == "TICKETED" and ticketed["ticket_numbers"], "RAIL_TICKETING_FAILED")
    project_trip("RAIL", o["order_id"])
    q = rail_service.change_quote("gate-account", o["order_id"], "2026-09-17", "SECOND_CLASS")
    changed = rail_service.execute_change("gate-account", o["order_id"], q["quote_id"])
    check(changed["ticket_numbers"][0].endswith("R"), "RAIL_REISSUE_FAILED")
    rq = rail_service.refund_quote("gate-account", o["order_id"])
    check(rq["refund_to"] == "ORIGINAL_PAYMENT_METHOD", "RAIL_REFUND_ROUTE_INVALID")
    rr = rail_service.refund("gate-account", o["order_id"])
    check(rr["status"] == "REFUND_COMPLETED", "RAIL_REFUND_FAILED")
    return {"search":"PASS","prebook":"PASS","order":"PASS","payment":"DETERMINISTIC_SIMULATOR_PASS","ticket":"PASS","go_trips":"PASS","change_reissue":"PASS","refund":"SIMULATED_ORIGINAL_METHOD_PASS"}


def ride_contract():
    items = mobility_service.ride_search("PVG", "Lujiazui", "2026-09-15T20:00:00")
    o = mobility_service.create_ride("gate-account", {"offer_id":items[0]["offer_id"],"pickup":"PVG","dropoff":"Lujiazui","pickup_at":"2026-09-15T20:00:00","flight_no":"MU510"})
    check(o["status"] == "CONFIRMED", "RIDE_ORDER_FAILED")
    project_trip("RIDE", o["order_id"])
    changed = mobility_service.modify("gate-account", o["order_id"], "2026-09-15T21:00:00")
    check(changed["pickup_at"] == "2026-09-15T21:00:00", "RIDE_MODIFY_FAILED")
    rq = mobility_service.refund_quote("gate-account", o["order_id"])
    check(rq["refund_to"] == "ORIGINAL_PAYMENT_METHOD", "RIDE_REFUND_ROUTE_INVALID")
    rr = mobility_service.cancel("gate-account", o["order_id"])
    check(rr["status"] == "REFUND_COMPLETED", "RIDE_REFUND_FAILED")
    return {"search":"PASS","order":"PASS","payment":"NOT_YET_DEDICATED_VERTICAL_PSP","confirmation":"PASS","go_trips":"PASS","modify":"PASS","cancel_refund":"CONTRACT_LEDGER_PASS"}


def rental_contract():
    items = mobility_service.rental_search("NRT", "NRT", "2026-09-15T09:00:00", "2026-09-18T09:00:00")
    o = mobility_service.create_rental("gate-account", {"offer_id":items[0]["offer_id"],"pickup_location":"NRT","return_location":"NRT","pickup_at":"2026-09-15T09:00:00","return_at":"2026-09-18T09:00:00"})
    check(o["status"] == "CONFIRMED", "RENTAL_ORDER_FAILED")
    project_trip("RENTAL", o["order_id"])
    changed = mobility_service.modify("gate-account", o["order_id"], "2026-09-15T10:00:00")
    check(changed["pickup_at"] == "2026-09-15T10:00:00", "RENTAL_MODIFY_FAILED")
    rq = mobility_service.refund_quote("gate-account", o["order_id"])
    check(rq["refund_to"] == "ORIGINAL_PAYMENT_METHOD", "RENTAL_REFUND_ROUTE_INVALID")
    rr = mobility_service.cancel("gate-account", o["order_id"])
    check(rr["status"] == "REFUND_COMPLETED", "RENTAL_REFUND_FAILED")
    return {"search":"PASS","order":"PASS","payment":"NOT_YET_DEDICATED_VERTICAL_PSP","confirmation":"PASS","go_trips":"PASS","modify":"PASS","cancel_refund":"CONTRACT_LEDGER_PASS"}


def attraction_contract():
    items = attraction_service.search("东京", "2026-09-15")
    p = attraction_service.prebook(items[0]["offer_id"], "2026-09-15", 1)
    check(p["inventory_confirmed"] is True, "ATTRACTION_PREBOOK_FAILED")
    o = attraction_service.create_order("gate-account", {"offer_id":items[0]["offer_id"],"visit_date":"2026-09-15","quantity":1,"attendees":[{"name":"CHEN TEST"}]})
    check(o["status"] == "CONFIRMED" and o["voucher_code"], "ATTRACTION_ORDER_FAILED")
    project_trip("ATTRACTION", o["order_id"])
    q = attraction_service.change_quote("gate-account", o["order_id"], "2026-09-16", "17:00")
    changed = attraction_service.execute_change("gate-account", o["order_id"], q["quote_id"])
    check(changed["visit_date"] == "2026-09-16", "ATTRACTION_CHANGE_FAILED")
    rq = attraction_service.refund_quote("gate-account", o["order_id"])
    check(rq["refund_to"] == "ORIGINAL_PAYMENT_METHOD", "ATTRACTION_REFUND_ROUTE_INVALID")
    rr = attraction_service.refund("gate-account", o["order_id"])
    check(rr["status"] == "REFUND_COMPLETED", "ATTRACTION_REFUND_FAILED")
    return {"search":"PASS","prebook":"PASS","order_voucher":"PASS","payment":"NOT_YET_DEDICATED_VERTICAL_PSP","go_trips":"PASS","change":"PASS","refund":"CONTRACT_LEDGER_PASS"}


PRODUCTION_BLOCKERS = {
    "HOTEL": ["REAL_PSP_CAPTURE_AND_REFUND_RECEIPT_REQUIRED", "REAL_SUPPLIER_LIVE_CONFIRMATION_REQUIRED"],
    "FLIGHT": ["REAL_AIRLINE_OR_GDS_TICKETING_REQUIRED", "REAL_PSP_CAPTURE_AND_REFUND_RECEIPT_REQUIRED"],
    "RAIL": ["REAL_RAIL_TICKETING_PROVIDER_REQUIRED", "REAL_PSP_CAPTURE_AND_REFUND_RECEIPT_REQUIRED"],
    "RIDE": ["DEDICATED_PSP_CAPTURE_REQUIRED", "REAL_MOBILITY_SUPPLIER_CONFIRMATION_REQUIRED", "REAL_REFUND_RECEIPT_REQUIRED"],
    "RENTAL": ["DEDICATED_PSP_CAPTURE_REQUIRED", "REAL_RENTAL_SUPPLIER_CONFIRMATION_REQUIRED", "REAL_DEPOSIT_SETTLEMENT_REQUIRED", "REAL_REFUND_RECEIPT_REQUIRED"],
    "ATTRACTION": ["DEDICATED_PSP_CAPTURE_REQUIRED", "REAL_TICKETING_PROVIDER_VOUCHER_REQUIRED", "REAL_REFUND_RECEIPT_REQUIRED"],
}


async def run_gate():
    reset_db()
    result = {}
    result["HOTEL"] = await hotel_contract()
    result["FLIGHT"] = flight_contract()
    result["RAIL"] = rail_contract()
    result["RIDE"] = ride_contract()
    result["RENTAL"] = rental_contract()
    result["ATTRACTION"] = attraction_contract()
    trips = consumer_unified_lifecycle_service.list("gate-account")
    present = {x["vertical"] for x in trips}
    check(set(VERTICALS).issubset(present), f"UNIFIED_GO_TRIPS_MISSING={set(VERTICALS)-present}")
    return result, trips


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("contract", "production"), default="contract")
    ap.add_argument("--json-out")
    args = ap.parse_args()
    report = {
        "schema": "go.full-ecosystem-transaction-closure-gate.v1",
        "control_version": "V6.1",
        "gate_name": "Full Ecosystem Transaction Closure Gate",
        "required_verticals": list(VERTICALS),
        "contract_gate": {},
        "production_gate": {"status": "BLOCKED", "blockers": PRODUCTION_BLOCKERS},
        "truth_rule": "Contract/simulator closure must never be represented as external production settlement or supplier execution.",
    }
    if args.mode == "production":
        # Production is a truth gate, not a simulator rerun. The contract gate is executed separately first.
        report["contract_gate"] = {"status": "NOT_RERUN_IN_PRODUCTION_MODE", "required_precondition": "contract gate PASS"}
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    try:
        matrix, trips = asyncio.run(run_gate())
        report["contract_gate"] = {"status": "PASS", "verticals": matrix, "unified_go_trips_verticals": sorted({x["vertical"] for x in trips})}
    except Exception as exc:
        report["contract_gate"] = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["contract_gate"].get("status") != "PASS":
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
