from datetime import UTC, datetime

import pytest

from go_hotel.attractions import service
from go_hotel.attractions.service import CATALOG, attraction_service as svc
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as supplier
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge


POLICY = {
    "destination_timezone": "Asia/Tokyo",
    "opens_minutes_before_session": 30,
    "closes_minutes_after_session": 120,
    "policy_reference": "isolated-supplier://replay-policy/v86",
}


def booked_confirmed_attraction(monkeypatch, owner="replay-owner"):
    monkeypatch.setitem(CATALOG["tokyo_skytree"], "supplier_validity_policy", POLICY)
    quote = svc.prebook("tokyo_skytree", "2026-09-15", 2)
    order = svc.create_order(
        owner,
        {
            "prebook_id": quote["prebook_id"],
            "offer_id": "tokyo_skytree",
            "visit_date": "2026-09-15",
            "quantity": 2,
            "attendees": [{"full_name": "A"}, {"full_name": "B"}],
        },
    )
    tx = vertical_transaction_bridge.checkout_contract(
        "ATTRACTION", order["order_id"], owner, "test-source", "isolated://replay-setup"
    )
    supplier.record_supplier_fact(
        tx["supplier_fulfillment_id"],
        {
            "state": "SUPPLIER_CONFIRMED",
            "external_operation_id": "op-" + order["order_id"],
            "supplier_confirmation_reference": "booking-" + order["order_id"],
            "ticket_numbers": ["T-A", "T-B"],
            "voucher_code": "V-" + order["order_id"],
            "evidence_reference": "isolated://confirmed",
        },
    )
    monkeypatch.setattr(
        service,
        "db_now_ms",
        lambda session: int(datetime(2026, 9, 15, 8, 0, tzinfo=UTC).timestamp() * 1000),
        raising=False,
    )
    return order["order_id"]


def redeemed_evidence(account, order_id):
    return [x for x in svc.get(account, order_id)["evidence"] if x["kind"] == "VOUCHER_REDEEMED"]


def test_same_account_same_evidence_replay_returns_same_fulfilled_fact_once(monkeypatch):
    owner = "replay-owner"
    order_id = booked_confirmed_attraction(monkeypatch, owner)
    first = svc.redeem(owner, order_id, "isolated://gate-scan")
    second = svc.redeem(owner, order_id, "isolated://gate-scan")
    assert first == second
    assert second["status"] == "FULFILLED"
    evidence = redeemed_evidence(owner, order_id)
    assert len(evidence) == 1
    assert evidence[0]["payload"]["evidence_reference"] == "isolated://gate-scan"


def test_replay_cannot_be_impersonated_by_other_evidence_or_other_account(monkeypatch):
    owner = "replay-owner"
    order_id = booked_confirmed_attraction(monkeypatch, owner)
    svc.redeem(owner, order_id, "isolated://gate-scan")
    with pytest.raises(ValueError, match="ATTRACTION_ILLEGAL_STATE_TRANSITION"):
        svc.redeem(owner, order_id, "isolated://other-scan")
    with pytest.raises(ValueError, match="ATTRACTION_ORDER_NOT_FOUND"):
        svc.redeem("other-owner", order_id, "isolated://gate-scan")
    evidence = redeemed_evidence(owner, order_id)
    assert len(evidence) == 1
    assert evidence[0]["payload"]["evidence_reference"] == "isolated://gate-scan"


def test_legacy_untrimmed_receipt_replay_preserves_original_evidence(monkeypatch):
    owner = "legacy-replay-owner"
    order_id = booked_confirmed_attraction(monkeypatch, owner)
    original_append = service.append_vertical_evidence
    legacy_reference = "  isolated://legacy-gate-scan  "

    def legacy_append(session, vertical, oid, kind, status, payload):
        # The pre-523 writer accepted whitespace but persisted the original text.
        # Use the genuine appender so the old receipt's evidence hash is valid.
        if kind == "VOUCHER_REDEEMED":
            payload = {**payload, "evidence_reference": legacy_reference}
        return original_append(session, vertical, oid, kind, status, payload)

    with monkeypatch.context() as old_writer:
        old_writer.setattr(service, "append_vertical_evidence", legacy_append)
        first = svc.redeem(owner, order_id, legacy_reference)
    before = svc.get(owner, order_id)["evidence"]
    assert svc.redeem(owner, order_id, legacy_reference) == first
    assert svc.redeem(owner, order_id, legacy_reference.strip()) == first
    assert svc.get(owner, order_id)["evidence"] == before
    assert redeemed_evidence(owner, order_id)[0]["payload"]["evidence_reference"] == legacy_reference
    with pytest.raises(ValueError, match="ATTRACTION_ILLEGAL_STATE_TRANSITION"):
        svc.redeem(owner, order_id, "isolated://different-scan")
    with pytest.raises(ValueError, match="FULFILLMENT_EVIDENCE_REQUIRED"):
        svc.redeem(owner, order_id, "   ")
    with pytest.raises(ValueError, match="ATTRACTION_ORDER_NOT_FOUND"):
        svc.redeem("other-owner", order_id, legacy_reference)
    assert svc.get(owner, order_id)["evidence"] == before
