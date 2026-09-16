"""Trusted persisted authority for an isolated coupon plan.

This module deliberately does not expose HTTP or execute supplier/payment work.
It turns an already-built plan into an authenticated, immutable execution contract.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import hmac
import json


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def _money(value):
    return type(value) is int


def _semantic(plan):
    if not isinstance(plan, dict) or not isinstance(plan.get("plan_hash"), str):
        raise ValueError("COUPON_AUTHORITY_PLAN_INVALID")
    changes = plan.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ValueError("COUPON_AUTHORITY_PLAN_INVALID")
    charge = credit = 0
    departures = {}
    for row in changes:
        if not isinstance(row, dict):
            raise ValueError("COUPON_AUTHORITY_PLAN_INVALID")
        delta, fee = row.get("fare_difference_minor"), row.get("change_fee_minor")
        if not _money(delta) or not _money(fee) or fee < 0:
            raise ValueError("COUPON_AUTHORITY_AMOUNT_INVALID")
        charge += max(delta, 0) + fee
        credit += max(-delta, 0)
        instant = row.get("new_departure_at")
        if instant is not None:
            try:
                parsed = datetime.fromisoformat(instant)
            except (TypeError, ValueError):
                raise ValueError("COUPON_AUTHORITY_DEPARTURE_INVALID") from None
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("COUPON_AUTHORITY_DEPARTURE_INVALID")
            departures.setdefault(row.get("passenger_index"), []).append(
                (row.get("leg_index"), parsed))
    for rows in departures.values():
        rows.sort()
        if any(b[1] <= a[1] for a, b in zip(rows, rows[1:])):
            raise ValueError("COUPON_AUTHORITY_ITINERARY_ORDER_INVALID")
    return charge, credit


def persist(plan, store, *, key_id, authority_key):
    """Persist one immutable authenticated plan; no overwrite is allowed."""
    if not isinstance(store, dict) or not key_id or not isinstance(authority_key, bytes):
        raise ValueError("COUPON_AUTHORITY_CONFIG_INVALID")
    charge, credit = _semantic(plan)
    plan_id = plan["plan_hash"]
    record = {"schema_version": 1, "plan_id": plan_id, "key_id": key_id,
              "plan": deepcopy(plan), "charge_minor": charge,
              "credit_minor": credit, "negative_fare_treatment": "CREDIT_NOT_NETTED"}
    record["authority_mac"] = hmac.new(authority_key, _json(record), hashlib.sha256).hexdigest()
    if plan_id in store and store[plan_id] != record:
        raise ValueError("COUPON_AUTHORITY_IMMUTABLE")
    store[plan_id] = deepcopy(record)
    return deepcopy(record)


def authorize(store, plan_id, consent, allocations, *, authority_key):
    """Verify storage authority, exact consent and charge-only C11 allocation."""
    record = deepcopy(store.get(plan_id)) if isinstance(store, dict) else None
    if not record or not isinstance(authority_key, bytes):
        raise ValueError("COUPON_AUTHORITY_NOT_FOUND")
    mac = record.pop("authority_mac", None)
    expected_mac = hmac.new(authority_key, _json(record), hashlib.sha256).hexdigest()
    if not isinstance(mac, str) or not hmac.compare_digest(mac, expected_mac):
        raise ValueError("COUPON_AUTHORITY_MAC_INVALID")
    expected = {"plan_id": plan_id, "authority_mac": mac,
                "charge_minor": record["charge_minor"],
                "credit_minor": record["credit_minor"],
                "currency": record["plan"].get("order", {}).get("currency"),
                "negative_fare_treatment": "CREDIT_NOT_NETTED", "confirmed": True}
    if consent != expected or type(consent.get("confirmed")) is not bool:
        raise ValueError("COUPON_AUTHORITY_CONSENT_INVALID")
    if (not isinstance(allocations, list)
            or any(not isinstance(x, dict) or set(x) != {"source_id", "amount_minor"}
                   or not isinstance(x["source_id"], str) or not x["source_id"]
                   or not _money(x["amount_minor"]) or x["amount_minor"] < 0
                   for x in allocations)
            or len({x["source_id"] for x in allocations}) != len(allocations)
            or sum(x["amount_minor"] for x in allocations) != record["charge_minor"]):
        raise ValueError("COUPON_AUTHORITY_ALLOCATION_INVALID")
    return {"plan_id": plan_id, "authority_mac": mac,
            "payment_intent": {"currency": expected["currency"],
                               "amount_minor": record["charge_minor"],
                               "allocations": deepcopy(allocations)},
            "credit_instruction": {"amount_minor": record["credit_minor"],
                                   "mode": "CREDIT_NOT_NETTED"}}
