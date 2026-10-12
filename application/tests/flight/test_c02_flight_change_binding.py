from datetime import date, timedelta

import pytest
from sqlalchemy import select

from go_hotel.db.models import (
    FlightChangeQuoteRow,
    FlightOrderRow,
    OmnichannelMoneyMovementRow as Movement,
    PaymentOrderRootRow as Root,
)
from go_hotel.db.session import SessionLocal
from go_hotel.flight.payment_recovery import payment_snapshot
from go_hotel.flight.service import flight_service as flights
from go_hotel.services.order_supplier_fulfillment import (
    order_supplier_fulfillment_service as supplier,
)
from go_hotel.services.vertical_transaction_bridge import (
    vertical_transaction_bridge as checkout_bridge,
)


def ticketed_order(owner, *, offset=10):
    offer = flights.search("PVG", "NRT", (date.today() + timedelta(days=offset)).isoformat())[0]
    prebook = flights.prebook(offer["offer_id"])
    order = flights.create_order(owner, prebook["prebook_id"], [{"full_name": owner, "type": "ADT"}])
    tx = checkout_bridge.checkout_contract(
        "FLIGHT",
        order["order_id"],
        owner,
        "c02-flight-test",
        f"isolated://{order['order_id']}",
    )
    supplier.record_supplier_fact(
        tx["supplier_fulfillment_id"],
        {
            "state": "SUPPLIER_CONFIRMED",
            "external_operation_id": "c02-" + order["order_id"],
            "supplier_confirmation_reference": "C02PNR",
            "ticket_numbers": ["C02TK"],
            "evidence_reference": "isolated://ticketed",
        },
    )
    return flights.order(owner, order["order_id"])


def quoted_change(owner, *, offset=10):
    order = ticketed_order(owner, offset=offset)
    quote = flights.change_quote(
        owner,
        order["order_id"],
        (date.today() + timedelta(days=offset + 2)).isoformat(),
    )
    return order, quote


def consent(quote):
    return {
        "quote_hash": quote["quote_hash"],
        "expected_total_due_minor": quote["total_due_minor"],
        "currency": quote["currency"],
        "confirmed": True,
    }


def flight_change_roots():
    with SessionLocal() as session:
        return list(session.scalars(select(Root).where(Root.business_type == "FLIGHT_CHANGE")))


@pytest.mark.parametrize("field,value", [("passengers", [{"full_name": "Changed", "type": "ADT"}]), ("itinerary", "2099-12-31")])
def test_current_passenger_or_segment_change_invalidates_quote_without_mutation(field, value):
    owner = "c02-binding-owner"
    order, quote = quoted_change(owner)

    with SessionLocal.begin() as session:
        row = session.get(FlightOrderRow, order["order_id"])
        if field == "passengers":
            row.passengers = value
        else:
            itinerary = list(row.current_itinerary)
            itinerary[0] = {**itinerary[0], "departure_date": value}
            row.current_itinerary = itinerary

    with pytest.raises(ValueError, match="REQUOTE_REQUIRED"):
        flights.execute_change(owner, order["order_id"], quote["quote_id"], consent(quote))

    with SessionLocal() as session:
        order_row = session.get(FlightOrderRow, order["order_id"])
        quote_row = session.get(FlightChangeQuoteRow, quote["quote_id"])
        assert order_row.status == "TICKETED"
        assert quote_row.status == "QUOTED"
    assert not flight_change_roots()


@pytest.mark.parametrize("case", ["expired", "foreign_order"])
def test_expired_or_foreign_quote_is_rejected_without_state_change(case):
    owner = "c02-quote-owner"
    order, quote = quoted_change(owner)
    quote_id = quote["quote_id"]

    if case == "expired":
        with SessionLocal.begin() as session:
            session.get(FlightChangeQuoteRow, quote_id).expires_at -= timedelta(days=1)
    else:
        other_order, other_quote = quoted_change(owner, offset=20)
        quote_id = other_quote["quote_id"]

    with pytest.raises(ValueError, match="FLIGHT_CHANGE_QUOTE_INVALID"):
        flights.execute_change(owner, order["order_id"], quote_id, consent(quote if case == "expired" else other_quote))

    with SessionLocal() as session:
        order_row = session.get(FlightOrderRow, order["order_id"])
        quote_row = session.get(FlightChangeQuoteRow, quote_id)
        assert order_row.status == "TICKETED"
        assert quote_row.status == "QUOTED"
    assert not flight_change_roots()


def test_unknown_supplier_replay_reuses_the_same_change_payment_snapshot():
    owner = "c02-replay-owner"
    order, quote = quoted_change(owner)

    first = flights.execute_change(owner, order["order_id"], quote["quote_id"], consent(quote))
    with SessionLocal() as session:
        order_row = session.get(FlightOrderRow, order["order_id"])
        quote_row = session.get(FlightChangeQuoteRow, quote["quote_id"])
        snapshot_before = payment_snapshot(session, order_row, quote=quote_row)
        movement_ids_before = [m.money_movement_id for m in session.scalars(
            select(Movement).where(Movement.business_id == quote["quote_id"])
        )]

    replay = flights.execute_change(owner, order["order_id"], quote["quote_id"], consent(quote))
    with SessionLocal() as session:
        order_row = session.get(FlightOrderRow, order["order_id"])
        quote_row = session.get(FlightChangeQuoteRow, quote["quote_id"])
        snapshot_after = payment_snapshot(session, order_row, quote=quote_row)
        movement_ids_after = [m.money_movement_id for m in session.scalars(
            select(Movement).where(Movement.business_id == quote["quote_id"])
        )]
        assert order_row.status == "UNKNOWN_EXTERNAL_STATE"
        assert quote_row.status == "PENDING_SUPPLIER"

    assert first["status"] == "UNKNOWN_EXTERNAL_STATE"
    assert replay["status"] == "UNKNOWN_EXTERNAL_STATE"
    assert replay["idempotent_replay"] is True
    assert snapshot_before == snapshot_after
    assert snapshot_before["auth"] is not None
    assert snapshot_before["cap"] is None
    assert snapshot_before["release"] is None
    assert movement_ids_before == movement_ids_after
