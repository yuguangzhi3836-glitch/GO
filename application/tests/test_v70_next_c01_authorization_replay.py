import pytest
from sqlalchemy import select

from go_hotel.db.models import (
    AlipayAuthorizationRow as Authorization,
    HostedDirectReservationRow as Reservation,
    OmnichannelMoneyMovementRow as Movement,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services.alipay_safeguarded_settlement import (
    alipay_safeguarded_settlement_service as payment,
)
from tests.test_depth08_hosted_change import apply, change_quote, rate, summary
from tests.test_depth08_hosted_fare import booked


def test_same_authorization_key_replays_original_after_lawful_fare_change(client, monkeypatch):
    r, account, _headers, original, _policy = booked(client, monkeypatch)
    rid = r['hosted_reservation_id']
    key = 'direct-authorization:' + rid + ':0'

    quote = change_quote(r, account)
    rate(r, quote['check_in'], quote['check_out'], 100000)
    quote = change_quote(r, account)
    changed = apply(r, account, quote)

    assert changed['amount_minor'] == 200000
    assert original['amount_minor'] == 162000
    before = summary(r)

    with SessionLocal() as s:
        authorization_count = len(s.scalars(select(Authorization)).all())
        movement_count = len(s.scalars(select(Movement)).all())
        other_reservation_id = s.scalar(
            select(Reservation.hosted_reservation_id)
            .where(Reservation.hosted_reservation_id != rid)
            .order_by(Reservation.created_at)
        )
        assert other_reservation_id

    replay = payment.authorize(rid, {'mode': 'CONTRACT_DRY_RUN'}, key)
    assert replay['authorization_id'] == original['authorization_id']
    assert replay['hosted_reservation_id'] == rid
    assert replay['amount_minor'] == original['amount_minor'] == 162000
    assert replay['currency'] == original['currency'] == 'CNY'
    assert summary(r) == before

    with SessionLocal() as s:
        assert len(s.scalars(select(Authorization)).all()) == authorization_count
        assert len(s.scalars(select(Movement)).all()) == movement_count

    with pytest.raises(ValueError, match='PAYMENT_RECONCILIATION_REQUIRED'):
        payment.authorize(rid, {'mode': 'CONTRACT_DRY_RUN'}, 'new-key-after-fare-change')

    with pytest.raises(ValueError, match='AUTHORIZATION_IDEMPOTENCY_CONFLICT'):
        payment.authorize(other_reservation_id, {'mode': 'CONTRACT_DRY_RUN'}, key)
