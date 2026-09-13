"""Managed dated stays must not recover forfeited value when night facts vanish."""
import pytest
from sqlalchemy import delete, select

from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    HostedReservationNightRow as Night,
    HostedReservationStayRow as Stay,
    OmnichannelMoneyMovementRow as Movement,
)
from go_hotel.services import hosted_credit_value, hosted_stay_credit
from go_hotel.services.hosted_direct_booking import hosted_direct_booking_service
from tests.test_depth08_hosted_fare import RULES, booked, quote as cancel_quote
from tests.test_depth07_hosted_money import summary
from tests.test_depth48_hosted_forfeiture import reprice


def money_facts():
    with SessionLocal() as session:
        return sorted(
            (row.money_movement_id, row.state, row.amount_minor)
            for row in session.scalars(select(Movement))
        )


@pytest.mark.parametrize('operation', ['summary', 'cancel_quote', 'credit_quote'])
def test_missing_current_nights_cannot_restore_forfeited_room_value(client, monkeypatch, operation):
    reservation, owner, *_ = booked(
        client, monkeypatch, rules={**RULES, 'credit_terms': hosted_credit_value.TERMS}
    )
    reservation, _ = reprice(reservation, owner, 70000)
    before = summary(reservation)
    assert before['current_room_value_minor'] == 140000
    assert before['forfeited_change_value_minor'] == 22000
    rid = reservation['hosted_reservation_id']
    with SessionLocal.begin() as session:
        assert session.get(Stay, rid) is not None
        # Fault injection is confined to the isolated per-test SQLite database.
        session.execute(delete(Night).where(
            Night.hosted_reservation_id == rid,
            Night.stay_date >= reservation['check_in'],
            Night.stay_date < reservation['check_out'],
        ))
    movements_before = money_facts()
    readers = {
        'summary': lambda: summary(reservation),
        'cancel_quote': lambda: cancel_quote(reservation, owner),
        'credit_quote': lambda: hosted_stay_credit.conversion_quote(rid, owner),
    }
    with pytest.raises(ValueError, match='HOSTED_FARE_VALUE_INTEGRITY_INVALID'):
        readers[operation]()
    assert money_facts() == movements_before


def test_legacy_without_dated_stay_preserves_original_face_value(client, monkeypatch):
    reservation, _, *_ = booked(client, monkeypatch)
    body = {key: reservation[key] for key in (
        'hosted_offer_id', 'check_in', 'check_out', 'guest_name', 'guest_contact'
    )}
    legacy = hosted_direct_booking_service.reserve('aoluguya-harbin', body, 'legacy-no-dated-stay')
    from go_hotel.db.models import HostedDirectReservationRow
    from go_hotel.services.hosted_fare_value import basis
    with SessionLocal() as session:
        rid = legacy['hosted_reservation_id']
        assert session.get(Stay, rid) is None
        assert list(session.scalars(select(Night).where(Night.hosted_reservation_id == rid))) == []
        value = basis(session, session.get(HostedDirectReservationRow, rid))
    assert value['current_room_value_minor'] == legacy['amount_minor']
    assert value['forfeited_change_value_minor'] == 0
