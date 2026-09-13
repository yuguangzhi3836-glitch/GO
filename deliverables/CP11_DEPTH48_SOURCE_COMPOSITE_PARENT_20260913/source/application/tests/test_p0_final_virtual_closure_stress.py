from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import json
import uuid

import pytest
from sqlalchemy import select

from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    FlightOrderRow,
    OmnichannelPaymentIntentRow,
    OrderSupplierFulfillmentRow,
    ConsumerUnifiedLifecycleRow,
    FinanceScopedCloseBatchRow,
)
from go_hotel.services.vertical_source_runtime import vertical_source_runtime_service as source
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as pay
from go_hotel.services.unified_money_movement import unified_money_movement_service as money
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service as fulfill
from go_hotel.services.p0_design_code_freeze import validate_cancel_refund_transition


@pytest.fixture(params=range(1, 6), ids=lambda n: f"round-{n}")
def stress_round(request):
    """Repeat every stress scenario five times inside one pytest process.

    This validates continuous closed-loop execution while keeping pytest startup/teardown
    to a single lifecycle, which is the failure mode we need to prove clean.
    """
    return request.param


pytestmark = pytest.mark.usefixtures("stress_round")


# This stress module owns one isolated schema for the whole run.  The repository-wide
# function-scoped reset fixture rebuilds hundreds of tables before every test and was
# the source of the historical apparent pytest "teardown hang" under constrained CI.
# Every stress scenario already uses collision-resistant IDs, so a module-scoped schema
# is both isolated and closer to a continuous-run workload.
@pytest.fixture(scope="module", autouse=True)
def reset_db():
    from go_hotel.db.models import Base
    from go_hotel.db.session import engine
    from go_hotel.security.service import identity_service
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    identity_service.bootstrap()
    yield
    engine.dispose()

def uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def seed_flight(amount: int = 10_000, currency: str = "CNY"):
    order_id = uid("stress-flight")
    account = uid("guest")
    with SessionLocal() as s:
        s.add(
            FlightOrderRow(
                order_id=order_id,
                account_id=account,
                prebook_id=uid("pb"),
                status="PENDING_PAYMENT",
                total_amount_minor=amount,
                currency=currency,
                passengers=[],
                payment_method_id=None,
                pnr=None,
                ticket_numbers=[],
                current_itinerary=[],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        s.commit()
    source.decide(
        "FLIGHT",
        order_id,
        [
            {
                "source_id": uid("airline"),
                "source_type": "AIRLINE_OFFICIAL",
                "authorized": True,
                "available": True,
                "evidence_reference": f"evidence://{order_id}",
            }
        ],
    )
    return order_id, account


def create_paid_intent(amount: int = 10_000, currency: str = "CNY"):
    order_id, account = seed_flight(amount=amount, currency=currency)
    intent = pay.create_intent(
        {
            "business_type": "FLIGHT_ORDER",
            "business_id": order_id,
            "channel_priority": ["ALIPAY", "VISA"],
        },
        uid("intent-idem"),
        account,
    )
    pay.select_channel(intent["payment_intent_id"], "ALIPAY", account)
    attempt = pay.execute(intent["payment_intent_id"])
    pay.simulate_result(attempt["payment_attempt_id"], "SUCCEEDED")
    return order_id, account, intent


def authorize_capture(intent, amount: int | None = None):
    amount = amount or int(intent["amount_minor"])
    iid = intent["payment_intent_id"]
    auth = money.create(
        iid,
        {
            "movement_type": "AUTHORIZATION",
            "amount_minor": int(intent["amount_minor"]),
            "evidence": [f"evidence://auth/{iid}"],
            "mode": "CONTRACT_SIMULATOR",
        },
        uid("auth"),
        "stress-finance",
    )
    cap = money.create(
        iid,
        {
            "movement_type": "CAPTURE",
            "parent_movement_id": auth["money_movement_id"],
            "amount_minor": amount,
            "evidence": [f"evidence://capture/{iid}"],
            "mode": "CONTRACT_SIMULATOR",
        },
        uid("capture"),
        "stress-finance",
    )
    return auth, cap


def settle_and_reconcile(intent, amount: int | None = None, bank_amount: int | None = None):
    amount = amount or int(intent["amount_minor"])
    bank_amount = amount if bank_amount is None else bank_amount
    iid = intent["payment_intent_id"]
    ext = uid("psp-tx")
    t = datetime.now(timezone.utc).isoformat()
    pay.ingest_psp_line(
        iid,
        {
            "external_transaction_id": ext,
            "amount_minor": amount,
            "currency": intent["currency"],
            "evidence_reference": f"psp://{ext}",
            "occurred_at": t,
        },
    )
    pay.ingest_bank_line(
        {
            "bank_line_identity": uid("bank-line"),
            "legal_entity_id": "GO_CN" if intent["currency"] == "CNY" else "GO_GLOBAL",
            "amount_minor": bank_amount,
            "currency": intent["currency"],
            "payment_reference": ext,
            "evidence_reference": f"bank://{ext}",
            "booked_at": t,
        }
    )
    return pay.reconcile(iid, {"external_transaction_id": ext})


def fulfillment_id(intent):
    with SessionLocal() as s:
        f = s.scalar(
            select(OrderSupplierFulfillmentRow).where(
                OrderSupplierFulfillmentRow.payment_intent_id == intent["payment_intent_id"]
            )
        )
        assert f is not None
        return f.order_supplier_fulfillment_id


def test_stress_successful_order_forms_closed_loop():
    order_id, _, intent = create_paid_intent()
    authorize_capture(intent)
    rec = settle_and_reconcile(intent)
    assert rec["state"] == "MATCHED"
    fid = fulfillment_id(intent)
    result = fulfill.record_supplier_fact(
        fid,
        {
            "state": "SUPPLIER_CONFIRMED",
            "external_operation_id": uid("supplier-op"),
            "supplier_confirmation_reference": uid("PNR"),
            "evidence_reference": "supplier://stress/confirmed",
        },
    )
    assert result["unified_lifecycle"]["lifecycle_state"] == "CONFIRMED"
    with SessionLocal() as s:
        assert s.get(FlightOrderRow, order_id).status == "TICKETED"
        life = s.scalar(
            select(ConsumerUnifiedLifecycleRow).where(
                ConsumerUnifiedLifecycleRow.vertical == "FLIGHT",
                ConsumerUnifiedLifecycleRow.order_id == order_id,
            )
        )
        assert life is not None and life.payment_state == "PAID"


def test_stress_duplicate_payment_attack_is_blocked():
    order_id, account = seed_flight()
    first = pay.create_intent(
        {"business_type": "FLIGHT_ORDER", "business_id": order_id, "channel_priority": ["ALIPAY"]},
        uid("first"),
        account,
    )
    assert first["business_id"] == order_id
    with pytest.raises(ValueError, match="ORDER_PAYMENT_ROOT_ALREADY_EXISTS"):
        pay.create_intent(
            {"business_type": "FLIGHT_ORDER", "business_id": order_id, "channel_priority": ["VISA"]},
            uid("attack"),
            account,
        )


def test_stress_supplier_timeout_stays_unknown_until_reconciled():
    order_id, _, intent = create_paid_intent()
    authorize_capture(intent)
    fid = fulfillment_id(intent)
    unknown = fulfill.record_supplier_fact(
        fid,
        {
            "state": "UNKNOWN_EXTERNAL_STATE",
            "external_operation_id": uid("supplier-timeout"),
            "evidence_reference": "supplier://timeout/ambiguous",
        },
    )
    assert unknown["unified_lifecycle"]["lifecycle_state"] == "UNKNOWN_EXTERNAL_STATE"
    with SessionLocal() as s:
        assert s.get(FlightOrderRow, order_id).status != "CONFIRMED"
    confirmed = fulfill.record_supplier_fact(
        fid,
        {
            "state": "SUPPLIER_CONFIRMED",
            "external_operation_id": uid("supplier-query"),
            "supplier_confirmation_reference": uid("PNR"),
            "evidence_reference": "supplier://reconciliation/confirmed",
        },
    )
    assert confirmed["unified_lifecycle"]["lifecycle_state"] == "CONFIRMED"


def test_stress_payment_webhook_replay_is_idempotent():
    order_id, account = seed_flight()
    intent = pay.create_intent(
        {"business_type": "FLIGHT_ORDER", "business_id": order_id, "channel_priority": ["ALIPAY"]},
        uid("wh-intent"),
        account,
    )
    pay.select_channel(intent["payment_intent_id"], "ALIPAY", account)
    attempt = pay.execute(intent["payment_intent_id"])
    key = uid("webhook-key")
    import os
    os.environ["GO_PAYMENT_WEBHOOK_KEY_ALIPAY"] = key
    payload = {
        "external_event_id": uid("evt"),
        "payment_attempt_id": attempt["payment_attempt_id"],
        "state": "SUCCEEDED",
        "external_operation_id": uid("ext-pay"),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    signature = hmac.new(key.encode(), raw.encode(), hashlib.sha256).hexdigest()
    first = pay.webhook("ALIPAY", payload, signature)
    replay = pay.webhook("ALIPAY", payload, signature)
    assert first["duplicate"] is False
    assert replay["duplicate"] is True


def test_stress_cancel_refund_full_path_and_terminal_immutability():
    steps = [
        ("CANCEL_REQUESTED", "SUPPLIER_PROCESSING", "SYSTEM", {"cancel_request_evidence": "ev://cancel-request"}),
        ("SUPPLIER_PROCESSING", "CANCEL_CONFIRMED", "SUPPLIER_CALLBACK", {"supplier_cancel_confirmation": "ev://cancel-confirm"}),
        ("CANCEL_CONFIRMED", "REFUND_AMOUNT_CONFIRMED", "RULE_ENGINE", {"refund_quote_evidence": "ev://quote"}),
        ("REFUND_AMOUNT_CONFIRMED", "REFUND_INITIATED", "PAYMENT_SERVICE", {"refund_authorization_evidence": "ev://refund-init"}),
        ("REFUND_INITIATED", "PSP_PROCESSING", "PAYMENT_ADAPTER", {"psp_refund_operation_evidence": "ev://psp-request"}),
        ("PSP_PROCESSING", "REFUND_COMPLETED", "PAYMENT_CALLBACK", {"psp_refund_confirmation": "ev://psp-confirm", "money_movement_evidence": "ev://refund-movement"}),
    ]
    for current, nxt, actor, evidence in steps:
        validate_cancel_refund_transition(current, nxt, actor, evidence, "FULL", 10_000)
    with pytest.raises(ValueError, match="TERMINAL_STATE_IMMUTABLE"):
        validate_cancel_refund_transition(
            "REFUND_COMPLETED", "REFUND_UNKNOWN", "SYSTEM",
            {"timeout_or_ambiguous_external_evidence": "ev://late"}, "FULL", 10_000,
        )


def test_stress_partial_refund_is_bounded_and_can_complete_remaining_refund():
    _, _, intent = create_paid_intent()
    _, cap = authorize_capture(intent)
    first = money.create(
        intent["payment_intent_id"],
        {
            "movement_type": "REFUND",
            "parent_movement_id": cap["money_movement_id"],
            "amount_minor": 3_000,
            "evidence": ["refund://partial/3000"],
            "mode": "CONTRACT_SIMULATOR",
        },
        uid("partial-refund"),
        "stress-refund",
    )
    assert first["amount_minor"] == 3_000
    with pytest.raises(ValueError, match="CUMULATIVE_REFUND_COMPENSATION_EXCEEDS_CAPTURE"):
        money.create(
            intent["payment_intent_id"],
            {
                "movement_type": "REFUND",
                "parent_movement_id": cap["money_movement_id"],
                "amount_minor": 7_001,
                "evidence": ["refund://attack/7001"],
                "mode": "CONTRACT_SIMULATOR",
            },
            uid("over-refund"),
            "stress-refund",
        )
    second = money.create(
        intent["payment_intent_id"],
        {
            "movement_type": "REFUND",
            "parent_movement_id": cap["money_movement_id"],
            "amount_minor": 7_000,
            "evidence": ["refund://remaining/7000"],
            "mode": "CONTRACT_SIMULATOR",
        },
        uid("remaining-refund"),
        "stress-refund",
    )
    assert second["amount_minor"] == 7_000


def test_stress_reconciliation_mismatch_blocks_match_and_close():
    _, _, intent = create_paid_intent()
    authorize_capture(intent)
    rec = settle_and_reconcile(intent, bank_amount=9_900)
    assert rec["state"] == "DIFFERENCE"
    cutoff = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    close = money.prepare_close(
        {
            "legal_entity_id": "GO_CN",
            "currency": "CNY",
            "period_start": datetime.now(timezone.utc).date().isoformat(),
            "period_end": datetime.now(timezone.utc).date().isoformat(),
            "cutoff_at": cutoff,
        },
        "stress-maker",
    )
    assert close["state"] == "BLOCKED"
    assert any(str(x).startswith("RECON:") for x in close["blockers_json"])


def test_stress_close_race_requires_reprepare_after_scope_change():
    _, _, intent = create_paid_intent(currency="USD")
    _, cap = authorize_capture(intent)
    assert settle_and_reconcile(intent)["state"] == "MATCHED"
    cutoff = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    close = money.prepare_close(
        {
            "legal_entity_id": "GO_GLOBAL",
            "currency": "USD",
            "period_start": datetime.now(timezone.utc).date().isoformat(),
            "period_end": datetime.now(timezone.utc).date().isoformat(),
            "cutoff_at": cutoff,
        },
        "stress-maker",
    )
    assert close["state"] == "PENDING_APPROVAL"
    # Interleave a legitimate new financial fact before approval; approval must detect scope drift.
    money.create(
        intent["payment_intent_id"],
        {
            "movement_type": "REFUND",
            "parent_movement_id": cap["money_movement_id"],
            "amount_minor": 1_000,
            "evidence": ["refund://close-race"],
            "mode": "CONTRACT_SIMULATOR",
        },
        uid("close-race-refund"),
        "stress-refund",
    )
    with pytest.raises(ValueError, match="FINANCE_CLOSE_SCOPE_CHANGED_REPREPARE_REQUIRED"):
        money.approve_close(close["finance_scoped_close_batch_id"], "stress-checker")
    with SessionLocal() as s:
        row = s.get(FinanceScopedCloseBatchRow, close["finance_scoped_close_batch_id"])
        assert row.state == "PENDING_APPROVAL"
