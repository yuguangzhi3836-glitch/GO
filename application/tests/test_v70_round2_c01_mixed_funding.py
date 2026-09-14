"""C01: lower then higher mixed credit/cash funding survives settlement failure."""
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedFareQuoteRow, HostedStayCreditRow, HostedCreditAllocationRow
from go_hotel.services import hosted_credit_value as value
from tests.test_depth09_stay_credit import issued, redemption, redeem
from tests.test_depth48_hosted_forfeiture import reprice
from tests.test_depth08_hosted_fare import quote as cancel_quote, execute as cancel
from tests.test_depth07_hosted_money import summary


@pytest.mark.parametrize('fault', ['none', 'after_credit_release'])
def test_mixed_funding_lower_then_higher_cancel_preserves_forfeiture_and_original_expiry(client, monkeypatch, fault):
    original, owner, _, _, _, credit = issued(client, monkeypatch)
    quoted = redemption(original, owner, credit, 100000)
    redeemed = redeem(original, owner, credit, quoted)
    order = {**original, 'hosted_reservation_id': redeemed['reservation_id'],
             'check_in': quoted['check_in'], 'check_out': quoted['check_out']}
    order, lower = reprice(order, owner, 70000)
    order, higher = reprice(order, owner, 90000)
    assert lower['change_fee_minor'] == higher['change_fee_minor'] == 0
    assert lower['additional_amount_minor'] == 0 and higher['additional_amount_minor'] == 40000
    funds = summary(order)
    assert funds['current_room_value_minor'] == 180000
    assert funds['forfeited_change_value_minor'] == 60000
    assert funds['prepaid_credit_minor'] == 162000 and funds['held_minor'] == 78000
    q = cancel_quote(order, owner)
    assert q['fee_minor'] == 0 and q['restored_credit_minor'] == 102000
    original_cancel = value.return_unused
    if fault == 'after_credit_release':
        def lost(*args, **kwargs):
            original_cancel(*args, **kwargs)
            raise RuntimeError('AFTER_MIXED_CREDIT_RELEASE')
        monkeypatch.setattr(value, 'return_unused', lost)
        with pytest.raises(RuntimeError, match='AFTER_MIXED_CREDIT_RELEASE'):
            cancel(order, owner, q)
        assert summary(order) == funds
        with SessionLocal() as session:
            assert session.get(HostedFareQuoteRow, q['quote_id']).state == 'QUOTED'
            assert session.get(HostedStayCreditRow, credit['credit_id']).available_minor == 0
        monkeypatch.setattr(value, 'return_unused', original_cancel)
    result = cancel(order, owner, q)
    assert cancel(order, owner, q) == result
    assert result['prepaid_forfeiture_minor'] == 60000
    assert result['restored_credit_minor'] == 102000
    assert result['authorization_released_minor'] == 78000
    settled = summary(order)
    assert settled['held_minor'] == settled['capture_minor'] == settled['refund_minor'] == 0
    with SessionLocal() as session:
        checked = value.checked(session, credit['credit_id'], owner)
        assert checked.available_minor == 102000
        assert checked.expires_at.isoformat().startswith(credit['expires_at'][:19])
        allocation = session.get(HostedCreditAllocationRow, order['hosted_reservation_id'])
        assert allocation.restored_minor == 102000
