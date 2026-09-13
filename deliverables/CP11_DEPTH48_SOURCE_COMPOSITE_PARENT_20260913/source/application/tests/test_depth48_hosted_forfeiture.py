"""Business regressions: discarded room-price value never becomes spendable again."""
import pytest
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedDirectReservationRow as Reservation, HostedFareQuoteRow as Quote
from go_hotel.services import hosted_fare_change as change, hosted_stay_credit as credit, hosted_credit_value as value
from tests.test_depth08_hosted_fare import booked, RULES, quote as cancel_quote, execute as cancel
from tests.test_depth08_hosted_change import rate, change_quote, apply
from tests.test_depth07_hosted_money import summary, guest, payment, PROOF, approve, after
from tests.test_depth09_stay_credit import issued, redemption, redeem


def reprice(reservation, account, nightly):
    q = change_quote(reservation, account)
    rate(reservation, q['check_in'], q['check_out'], nightly)
    q = change_quote(reservation, account)
    result = apply(reservation, account, q)
    assert apply(reservation, account, q) == result
    return {**reservation, **result}, q


@pytest.mark.parametrize('prices,dues,forfeited', [
    ([70000, 75000], [0, 10000], 22000),
    ([100000, 70000, 80000], [38000, 0, 20000], 60000),
    ([70000, 60000, 85000], [0, 0, 50000], 42000),
])
def test_each_positive_difference_uses_current_room_value(client, monkeypatch, prices, dues, forfeited):
    r, owner, *_ = booked(client, monkeypatch)
    for nightly, due in zip(prices, dues):
        r, q = reprice(r, owner, nightly)
        assert q['additional_amount_minor'] == due
        assert q['change_fee_minor'] == 0
    funds = summary(r)
    assert funds['current_room_value_minor'] == prices[-1] * 2
    assert funds['forfeited_change_value_minor'] == forfeited
    assert funds['held_minor'] == prices[-1] * 2 + forfeited
    assert funds['capture_minor'] == funds['refund_minor'] == 0


def test_lower_then_credit_has_separate_nonrefundable_capture(client, monkeypatch):
    r, owner, *_ = booked(client, monkeypatch, rules={**RULES, 'credit_terms': value.TERMS})
    r, _ = reprice(r, owner, 70000)
    q = credit.conversion_quote(r['hosted_reservation_id'], owner)
    assert q['retained_value_minor'] == 140000 and q['funding_capture_minor'] == 162000
    result = credit.convert(r['hosted_reservation_id'], owner, q['quote_id'], 140000, 'CNY')
    assert credit.convert(r['hosted_reservation_id'], owner, q['quote_id'], 140000, 'CNY') == result
    with SessionLocal() as s:
        c = value.checked(s, result['credit']['credit_id'], owner)
        assert c.available_minor == c.issued_minor == 140000
    funds = summary(r)
    assert funds['capture_minor'] == 162000 and funds['refundable_capture_minor'] == 140000
    assert funds['cash_forfeiture_minor'] == 22000 and funds['held_minor'] == 0


@pytest.mark.parametrize('fee_bps', [0, 5000])
def test_cancellation_retains_forfeiture_outside_refundable_fee(client, monkeypatch, fee_bps):
    rules = {**RULES, 'cancellation_tiers': [{'min_hours': 0, 'fee_basis_points': fee_bps}]}
    r, owner, *_ = booked(client, monkeypatch, rules=rules)
    r, _ = reprice(r, owner, 70000)
    q = cancel_quote(r, owner)
    fee = 140000 * fee_bps // 10000
    assert q['fee_minor'] == fee and q['cash_forfeiture_minor'] == 22000
    result = cancel(r, owner, q)
    assert result['fee_captured_minor'] == fee
    assert result['authorization_released_minor'] == 140000 - fee
    funds = summary(r)
    assert funds['capture_minor'] == fee + 22000 and funds['held_minor'] == 0
    assert funds['refundable_capture_minor'] == fee
    if fee:
        from go_hotel.db.models import GuestStayLifecycleRow
        with SessionLocal() as s:
            sid = s.scalar(select(GuestStayLifecycleRow).where(GuestStayLifecycleRow.hosted_reservation_id == r['hosted_reservation_id'])).stay_lifecycle_id
        _, eligibility = approve(sid, fee)
        after.retry_refund(owner, r['hosted_reservation_id'], eligibility['refund_eligibility_id'])
        assert summary(r)['refund_minor'] == fee


def checkin(r):
    sid = guest.create(r['hosted_reservation_id'], 'hotel')['stay_lifecycle_id']
    guest.identity(sid, {'identity_evidence_hash': 'a'*64, 'verification_method':'HOTEL_DESK_DOCUMENT_CHECK'}, 'hotel')
    guest.arrive(sid, 'hotel'); guest.assign_room(sid, {'room_reference':'SIM-101'}, 'hotel')
    guest.check_in(sid, {'registration_evidence_reference':'test://reg'}, 'hotel')
    return sid


@pytest.mark.parametrize('fulfilled', [None, 100000])
def test_checkout_partial_release_and_refund_never_return_forfeiture(client, monkeypatch, fulfilled):
    r, owner, _, authorization, _ = booked(client, monkeypatch)
    r, _ = reprice(r, owner, 70000)
    sid = checkin(r)
    evidence = PROOF if fulfilled is None else {**PROOF, 'fulfilled_amount_minor':fulfilled}
    guest.checkout(sid, evidence, 'hotel')
    payment.fulfill(authorization['authorization_id'], PROOF, 'hotel')
    payment.capture(authorization['authorization_id'], {'mode':'CONTRACT_DRY_RUN'})
    amount = 140000 if fulfilled is None else fulfilled
    funds = summary(r)
    assert funds['capture_minor'] == amount + 22000 and funds['held_minor'] == 0
    assert funds['refundable_capture_minor'] == amount
    _, eligibility = approve(sid, amount)
    after.retry_refund(owner, r['hosted_reservation_id'], eligibility['refund_eligibility_id'])
    assert summary(r)['refund_minor'] == amount


def prepaid_order(client, monkeypatch):
    r, owner, _, _, _, c = issued(client, monkeypatch)
    q = redemption(r, owner, c)
    new = redeem(r, owner, c, q)
    return {**r, 'hosted_reservation_id':new['reservation_id'], 'check_in':q['check_in'], 'check_out':q['check_out']}, owner, c


def test_prepaid_lower_change_cancellation_restores_only_current_value(client, monkeypatch):
    r, owner, c = prepaid_order(client, monkeypatch)
    r, _ = reprice(r, owner, 70000)
    result = cancel(r, owner, cancel_quote(r, owner))
    assert result['prepaid_forfeiture_minor'] == 22000
    assert result['restored_credit_minor'] == 140000
    with SessionLocal() as s:
        assert value.checked(s, c['credit_id'], owner).available_minor == 140000
    assert summary(r)['credit']['applied_credit']['fee_consumed_minor'] == 0


def test_prepaid_partial_checkout_restores_unused_room_value_only(client, monkeypatch):
    r, owner, c = prepaid_order(client, monkeypatch)
    r, _ = reprice(r, owner, 70000)
    sid = checkin(r)
    guest.checkout(sid, {**PROOF, 'fulfilled_amount_minor':100000}, 'hotel')
    from go_hotel.db.models import AlipayAuthorizationRow
    with SessionLocal() as s:
        aid = s.scalar(select(AlipayAuthorizationRow).where(AlipayAuthorizationRow.hosted_reservation_id == r['hosted_reservation_id'])).authorization_id
    payment.fulfill(aid, PROOF, 'hotel'); payment.capture(aid, {'mode':'CONTRACT_DRY_RUN'})
    with SessionLocal() as s:
        assert value.checked(s, c['credit_id'], owner).available_minor == 40000
    _, eligibility = approve(sid, 100000)
    after.retry_refund(owner, r['hosted_reservation_id'], eligibility['refund_eligibility_id'])
    assert summary(r)['credit_refund_minor'] == 100000
    with SessionLocal() as s:
        value.checked(s, c['credit_id'], owner)


def test_conversion_failure_after_credit_capture_rolls_back_both_sources(client, monkeypatch):
    from go_hotel.services import hosted_fare_value
    r, owner, *_ = booked(client, monkeypatch, rules={**RULES, 'credit_terms':value.TERMS})
    r, _ = reprice(r, owner, 70000)
    q = credit.conversion_quote(r['hosted_reservation_id'], owner)
    original = hosted_fare_value.capture_forfeiture
    def lost(*args):
        original(*args)
        raise RuntimeError('AFTER_FORFEITURE_CAPTURE')
    monkeypatch.setattr(hosted_fare_value, 'capture_forfeiture', lost)
    with pytest.raises(RuntimeError, match='AFTER_FORFEITURE_CAPTURE'):
        credit.convert(r['hosted_reservation_id'], owner, q['quote_id'], 140000, 'CNY')
    assert summary(r)['capture_minor'] == 0 and summary(r)['held_minor'] == 162000
    with SessionLocal() as s:
        assert s.get(Quote, q['quote_id']).state == 'QUOTED'
    monkeypatch.setattr(hosted_fare_value, 'capture_forfeiture', original)
    result = credit.convert(r['hosted_reservation_id'], owner, q['quote_id'], 140000, 'CNY')
    assert result['credit']['available_minor'] == 140000
    assert summary(r)['capture_minor'] == 162000


@pytest.mark.parametrize('kind', ['REFUND', 'COMPENSATION'])
def test_generic_money_endpoint_cannot_refund_forfeiture(client, monkeypatch, kind):
    from go_hotel.services import hosted_money, hosted_fare_value
    from go_hotel.db.models import AlipayAuthorizationRow
    r, owner, *_ = booked(client, monkeypatch, rules={**RULES, 'credit_terms':value.TERMS})
    r, _ = reprice(r, owner, 70000)
    q = credit.conversion_quote(r['hosted_reservation_id'], owner)
    credit.convert(r['hosted_reservation_id'], owner, q['quote_id'], 140000, 'CNY')
    with SessionLocal() as s:
        a = s.scalar(select(AlipayAuthorizationRow).where(AlipayAuthorizationRow.hosted_reservation_id == r['hosted_reservation_id']))
        forfeiture = next(m for m in hosted_money.movements(s, a) if hosted_fare_value.is_forfeiture(m))
        iid, mid = forfeiture.root_payment_intent_id, forfeiture.money_movement_id
    with pytest.raises(ValueError, match='FORFEITURE_NOT_REFUNDABLE'):
        hosted_money.money.create(iid, {'movement_type':kind, 'amount_minor':1, 'parent_movement_id':mid,
            'mode':'CONTRACT_SIMULATOR', 'evidence':['isolated://cannot-restore-forfeiture']}, 'forfeit-bypass', owner)
    assert summary(r)['refund_minor'] == 0
