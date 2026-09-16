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


def authorize_once(store, plan_id, consent, allocations, *, authority_keys,
                   consent_subject, now, replay_store, retired_key_ids=None):
    """Authorize exact consent with subject, expiry and one-time replay binding.

    replay_store is caller-owned durable state. Production callers must make
    its read/claim operation transactional; this isolated contract uses the
    mapping's single-threaded claim semantics and performs the claim only after
    every authority, consent and allocation check has passed.
    """
    if (not isinstance(consent_subject, str) or not consent_subject.strip()
            or not isinstance(now, datetime) or now.tzinfo is None
            or now.utcoffset() is None or not isinstance(replay_store, dict)):
        raise ValueError("COUPON_AUTHORITY_CONSENT_CONTEXT_INVALID")
    if not isinstance(consent, dict):
        raise ValueError("COUPON_AUTHORITY_CONSENT_CONTEXT_INVALID")
    context_keys = {"consent_subject", "consent_nonce", "consent_expires_at"}
    base_keys = {"plan_id", "authority_mac", "charge_minor", "credit_minor",
                 "currency", "negative_fare_treatment", "confirmed"}
    if set(consent) != base_keys | context_keys:
        raise ValueError("COUPON_AUTHORITY_CONSENT_CONTEXT_INVALID")
    subject = consent.get("consent_subject")
    nonce = consent.get("consent_nonce")
    expires_at = consent.get("consent_expires_at")
    if (subject != consent_subject or not isinstance(nonce, str) or not nonce.strip()
            or not isinstance(expires_at, str)):
        raise ValueError("COUPON_AUTHORITY_CONSENT_CONTEXT_INVALID")
    try:
        expiry = datetime.fromisoformat(expires_at)
    except (TypeError, ValueError):
        raise ValueError("COUPON_AUTHORITY_CONSENT_EXPIRY_INVALID") from None
    if expiry.tzinfo is None or expiry.utcoffset() is None:
        raise ValueError("COUPON_AUTHORITY_CONSENT_EXPIRY_INVALID")
    if now >= expiry:
        raise ValueError("COUPON_AUTHORITY_CONSENT_EXPIRED")
    result = authorize(
        store, plan_id, {key: consent[key] for key in base_keys}, allocations,
        authority_keys=authority_keys, retired_key_ids=retired_key_ids)
    if nonce in replay_store:
        raise ValueError("COUPON_AUTHORITY_CONSENT_REPLAY")
    replay_store[nonce] = {
        "plan_id": plan_id,
        "consent_subject": subject,
        "authority_mac": consent["authority_mac"],
        "consent_expires_at": expires_at,
    }
    result["consent_receipt"] = deepcopy(replay_store[nonce])
    result["consent_receipt"]["consent_nonce"] = nonce
    return result
