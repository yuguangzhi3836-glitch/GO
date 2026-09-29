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


def _currency(plan):
    currency = plan.get("order", {}).get("currency") if isinstance(plan.get("order"), dict) else None
    if (not isinstance(currency, str) or len(currency) != 3
            or not currency.isascii() or not currency.isalpha()
            or currency != currency.upper()):
        raise ValueError("COUPON_AUTHORITY_CURRENCY_INVALID")
    return currency


def _semantic(plan):
    if not isinstance(plan, dict) or not isinstance(plan.get("plan_hash"), str):
        raise ValueError("COUPON_AUTHORITY_PLAN_INVALID")
    _currency(plan)
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
    if (not isinstance(store, dict) or not isinstance(key_id, str) or not key_id.strip()
            or not isinstance(authority_key, bytes)):
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


def _resolve_key(record, authority_keys, retired_key_ids):
    if not isinstance(authority_keys, dict):
        raise ValueError("COUPON_AUTHORITY_KEYRING_INVALID")
    key_id = record.get("key_id")
    retired = retired_key_ids if retired_key_ids is not None else frozenset()
    if not isinstance(retired, (set, frozenset)) or any(not isinstance(x, str) for x in retired):
        raise ValueError("COUPON_AUTHORITY_KEYRING_INVALID")
    if key_id in retired:
        raise ValueError("COUPON_AUTHORITY_KEY_RETIRED")
    key = authority_keys.get(key_id)
    if not isinstance(key, bytes):
        raise ValueError("COUPON_AUTHORITY_KEY_UNKNOWN")
    return key


def authorize(store, plan_id, consent, allocations, *, authority_keys,
              retired_key_ids=None):
    """Verify keyed storage authority, exact consent and charge-only allocation.

    The record's immutable key_id selects its verification key. Callers cannot
    substitute an unscoped raw key; rotation keeps old records verifiable only
    while their exact key_id remains explicitly trusted and non-retired.
    """
    record = deepcopy(store.get(plan_id)) if isinstance(store, dict) else None
    if not record:
        raise ValueError("COUPON_AUTHORITY_NOT_FOUND")
    authority_key = _resolve_key(record, authority_keys, retired_key_ids)
    mac = record.pop("authority_mac", None)
    expected_mac = hmac.new(authority_key, _json(record), hashlib.sha256).hexdigest()
    if not isinstance(mac, str) or not hmac.compare_digest(mac, expected_mac):
        raise ValueError("COUPON_AUTHORITY_MAC_INVALID")
    expected = {"plan_id": plan_id, "authority_mac": mac,
                "charge_minor": record["charge_minor"],
                "credit_minor": record["credit_minor"],
                "currency": _currency(record["plan"]),
                "negative_fare_treatment": "CREDIT_NOT_NETTED", "confirmed": True}
    if (not isinstance(consent, dict) or consent != expected
            or type(consent.get("confirmed")) is not bool):
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


def _partial_party_contract(record, selection):
    """Return a canonical partial-party selection bound to the frozen plan."""
    if not isinstance(selection, list) or not selection:
        raise ValueError("COUPON_AUTHORITY_PARTIAL_SELECTION_INVALID")
    available = {
        (row.get("passenger_index"), row.get("leg_index"))
        for row in record["plan"]["changes"]
        if isinstance(row, dict)
    }
    canonical = []
    seen = set()
    for row in selection:
        if (not isinstance(row, dict)
                or set(row) != {"passenger_index", "leg_index"}
                or type(row["passenger_index"]) is not int
                or type(row["leg_index"]) is not int
                or row["passenger_index"] < 0 or row["leg_index"] < 0):
            raise ValueError("COUPON_AUTHORITY_PARTIAL_SELECTION_INVALID")
        pair = (row["passenger_index"], row["leg_index"])
        if pair in seen or pair not in available:
            raise ValueError("COUPON_AUTHORITY_PARTIAL_SELECTION_INVALID")
        seen.add(pair)
        canonical.append({"passenger_index": pair[0], "leg_index": pair[1]})
    canonical.sort(key=lambda item: (item["passenger_index"], item["leg_index"]))
    return canonical


def authorize_partial_party(store, plan_id, consent, allocations, selection, *,
                            idempotency_key, execution_store, authority_keys,
                            retired_key_ids=None):
    """Authorize one exact traveler/coupon subset without provider side effects.

    The idempotency record is written only after the underlying immutable plan,
    exact consent, allocation and selection have all passed. Exact replay
    returns the same contract; key reuse with different authority fails closed.
    """
    if (not isinstance(execution_store, dict)
            or not isinstance(idempotency_key, str)
            or not idempotency_key.strip()):
        raise ValueError("COUPON_AUTHORITY_IDEMPOTENCY_INVALID")
    record = deepcopy(store.get(plan_id)) if isinstance(store, dict) else None
    if not record:
        raise ValueError("COUPON_AUTHORITY_NOT_FOUND")
    canonical = _partial_party_contract(record, selection)
    selection_digest = hashlib.sha256(_json(canonical)).hexdigest()
    authority = authorize(
        store, plan_id, consent, allocations, authority_keys=authority_keys,
        retired_key_ids=retired_key_ids)
    contract = {
        "plan_id": plan_id,
        "authority_mac": authority["authority_mac"],
        "selection": canonical,
        "selection_digest": selection_digest,
        "payment_intent": authority["payment_intent"],
        "credit_instruction": authority["credit_instruction"],
    }
    existing = execution_store.get(idempotency_key)
    if existing is not None:
        if existing != contract:
            raise ValueError("COUPON_AUTHORITY_IDEMPOTENCY_CONFLICT")
        return deepcopy(existing)
    execution_store[idempotency_key] = deepcopy(contract)
    return deepcopy(contract)
