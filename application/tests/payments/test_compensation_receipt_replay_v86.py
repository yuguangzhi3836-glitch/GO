import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from go_hotel.compensation.service import compensation_service as finance
from go_hotel.db.models import (
    CatalogFaultRecoveryRow as Recovery,
    SupplierFinancialAccountRow as Account,
    SupplierLiabilityRow as Liability,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services import catalog_fault_funding as funding, catalog_supplier_remedy as remedy

EVIDENCE = {'reference': 'test://independent-stock-file', 'sha256': 'a' * 64, 'type': 'HOTEL_RECORD'}


def booked_order(client, idem, account_id='acct_demo'):
    check_in = (datetime.now(timezone.utc) + timedelta(days=20)).date().isoformat()
    check_out = (datetime.now(timezone.utc) + timedelta(days=24)).date().isoformat()
    search = client.post('/v1/search/hotels', json={
        'destination': {'city_code': 'TYO'},
        'stay': {'check_in': check_in, 'check_out': check_out},
        'occupancy': {'rooms': 1, 'adults': 2, 'children': 0},
        'currency': 'CNY',
    })
    offer = search.json()['data']['hotels'][0]['best_offer']
    prebook = client.post(f"/v1/offers/{offer['offer_id']}/prebook", json={'currency': 'CNY'}).json()['data']
    order = client.post('/v1/orders', headers={'Idempotency-Key': f'ord-{idem}'}, json={
        'prebook_id': prebook['prebook_id'],
        'account_id': account_id,
    }).json()['data']
    client.post(f"/v1/orders/{order['order_id']}/payments", headers={'Idempotency-Key': f'pay-{idem}'}, json={
        'payment_method_token': 'pm_success',
        'amount_minor': order['total_amount_minor'],
        'currency': 'CNY',
    })
    confirmed = client.post(f"/internal/v1/orders/{order['order_id']}/confirm")
    assert confirmed.status_code == 200 and confirmed.json()['data']['status'] == 'CONFIRMED'
    return order['order_id'], order['total_amount_minor']


def approved_fault(client, idem, reason='OVERBOOKING'):
    order_id, paid = booked_order(client, idem)
    case = remedy.request(order_id, 'sup_mock', reason, ['unverified-reference'], 'maker')
    case = remedy.add_evidence(case['case_id'], EVIDENCE, 'maker')
    decision = remedy.review(case['case_id'], reason, case['evidence_ids'], f'test://decision-{idem}', 'checker', case['evidence_hash'])
    return paid, decision


def create_negative_balance(client, idem):
    paid, decision = approved_fault(client, idem)
    finance.configure_supplier_finance('sup_mock', 0, 0, 0, False)
    finance.configure_supplier_finance(funding.PROTECTION_ACCOUNT, 0, paid, 0, False)
    result = asyncio.run(remedy.execute(decision['case_id'], decision['decision_hash']))
    assert result['state'] == 'COMPLETED'
    with SessionLocal() as s:
        liability = s.scalar(select(Liability).where(Liability.case_id == decision['case_id']))
        assert liability is not None and liability.negative_balance_minor == paid
    return paid


def finance_snapshot(*supplier_ids):
    from go_hotel.db.models import HostedFaultRecoveryRow, ProtectionFundLedgerRow, OmnichannelMoneyMovementRow, CompensationPaymentRow
    with SessionLocal() as s:
        return {
            'durable_records': {
                model.__tablename__: [
                    {column.name: getattr(row, column.name) for column in model.__table__.columns}
                    for row in s.scalars(select(model).order_by(*model.__table__.primary_key.columns)).all()
                ]
                for model in (Recovery, HostedFaultRecoveryRow, ProtectionFundLedgerRow, OmnichannelMoneyMovementRow, CompensationPaymentRow)
            },
            'accounts': {
                supplier_id: {
                    'settlement': s.get(Account, supplier_id).settlement_available_minor,
                    'reserve': s.get(Account, supplier_id).reserve_available_minor,
                    'bank': s.get(Account, supplier_id).bank_available_minor,
                    'negative': s.get(Account, supplier_id).negative_balance_minor,
                }
                for supplier_id in supplier_ids
            },
            'recoveries': [
                (
                    row.supplier_id,
                    row.request_json['amount_minor'],
                    row.request_json['settlement_reference'],
                    row.result_json['recovered_minor'],
                    row.result_json['new_available_minor'],
                )
                for row in s.scalars(select(Recovery).order_by(Recovery.created_at, Recovery.recovery_id)).all()
            ],
            'liabilities': [
                (
                    row.supplier_id,
                    row.negative_balance_minor,
                    row.status,
                    row.settlement_offset_minor,
                )
                for row in s.scalars(select(Liability).order_by(Liability.created_at, Liability.liability_id)).all()
            ],
        }


def error_code(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        if isinstance(exc.detail, dict):
            return str(exc.detail.get('code'))
        return str(exc.detail)
    return str(exc)


def test_future_settlement_exact_replay_returns_original_result_after_later_balance_changes(client):
    paid = create_negative_balance(client, 'v86-replay')
    amount = paid + 50_000
    reference = 'test://verified-settlement-replay'
    key = 'verified-settlement-key'

    first = finance.apply_future_settlement('sup_mock', amount, reference, key, 'finance')
    assert first['recovered_minor'] == paid
    assert first['new_available_minor'] == 50_000
    assert first['remaining_available_minor'] == 50_000

    with SessionLocal.begin() as s:
        s.get(Account, 'sup_mock').settlement_available_minor += 999
    before_replay = finance_snapshot('sup_mock', funding.PROTECTION_ACCOUNT)

    replay = finance.apply_future_settlement('sup_mock', amount, reference, key, 'finance')

    assert replay == first
    assert finance_snapshot('sup_mock', funding.PROTECTION_ACCOUNT) == before_replay


def test_future_settlement_rejects_conflicting_amount_receipt_and_supplier_without_side_effects(client):
    paid = create_negative_balance(client, 'v86-conflict')
    amount = paid + 10_000
    reference = 'test://verified-settlement-conflict'
    key = 'verified-settlement-conflict-key'

    first = finance.apply_future_settlement('sup_mock', amount, reference, key, 'finance')
    assert first['recovered_minor'] == paid
    finance.configure_supplier_finance('sup_alt', 0, 0, 0, False)
    before = finance_snapshot('sup_mock', 'sup_alt', funding.PROTECTION_ACCOUNT)

    for args in [
        ('sup_mock', amount + 1, reference, key, 'finance'),
        ('sup_mock', amount, reference + '-other', key, 'finance'),
        ('sup_alt', amount, reference, key, 'finance'),
    ]:
        with pytest.raises(Exception) as rejected:
            finance.apply_future_settlement(*args)
        assert error_code(rejected.value) == 'RECOVERY_RECEIPT_IDEMPOTENCY_CONFLICT'

    assert finance_snapshot('sup_mock', 'sup_alt', funding.PROTECTION_ACCOUNT) == before


def test_nonzero_opening_balance_and_two_receipts_keep_original_balance_snapshot():
    finance.configure_supplier_finance('receipt-owner', 100, 0, 0, False)
    first = finance.apply_future_settlement('receipt-owner', 50, 'receipt-a', 'key-a', 'finance')
    assert first['new_available_minor'] == 50
    assert first['remaining_available_minor'] == 150
    second = finance.apply_future_settlement('receipt-owner', 30, 'receipt-b', 'key-b', 'finance')
    assert second['remaining_available_minor'] == 180
    before = finance_snapshot('receipt-owner')
    assert finance.apply_future_settlement('receipt-owner', 50, 'receipt-a', 'key-a', 'finance') == first
    assert finance_snapshot('receipt-owner') == before


@pytest.mark.parametrize('first_route', ['catalog', 'hosted'])
def test_shared_recovery_rejects_cross_supplier_receipt_in_either_table(first_route):
    from go_hotel.services import hosted_fault_funding
    finance.configure_supplier_finance('receipt-owner', 100, 0, 0, False)
    finance.configure_supplier_finance('receipt-other', 200, 0, 0, False)
    original = funding if first_route == 'catalog' else hosted_fault_funding
    other = hosted_fault_funding if first_route == 'catalog' else funding
    first = original.recover('receipt-owner', 50, 'shared-receipt', 'first-key', 'finance')
    before = finance_snapshot('receipt-owner', 'receipt-other')
    with pytest.raises(ValueError, match='^RECOVERY_RECEIPT_IDEMPOTENCY_CONFLICT$'):
        other.recover('receipt-other', 50, 'shared-receipt', 'other-key', 'finance')
    assert finance_snapshot('receipt-owner', 'receipt-other') == before
    assert other.recover('receipt-owner', 50, 'shared-receipt', 'another-key', 'finance') == first


def test_receipt_committed_between_public_entry_and_recovery_is_rechecked(monkeypatch):
    finance.configure_supplier_finance('receipt-owner', 100, 0, 0, False)
    finance.configure_supplier_finance('receipt-other', 200, 0, 0, False)
    real_recover = funding.recover
    def interleaved(supplier_id, amount, reference, key, actor):
        real_recover('receipt-other', amount, reference, 'winning-key', actor)
        return real_recover(supplier_id, amount, reference, key, actor)
    monkeypatch.setattr(funding, 'recover', interleaved)
    with pytest.raises(ValueError, match='^RECOVERY_RECEIPT_IDEMPOTENCY_CONFLICT$'):
        finance.apply_future_settlement('receipt-owner', 50, 'interleaved', 'losing-key', 'finance')
    snapshot = finance_snapshot('receipt-owner', 'receipt-other')
    assert snapshot['accounts']['receipt-owner']['settlement'] == 100
    assert snapshot['accounts']['receipt-other']['settlement'] == 250
    assert len(snapshot['recoveries']) == 1


def test_legacy_receipt_without_balance_snapshot_refuses_to_invent_one():
    finance.configure_supplier_finance('receipt-owner', 100, 0, 0, False)
    first = finance.apply_future_settlement('receipt-owner', 50, 'legacy-receipt', 'legacy-key', 'finance')
    with SessionLocal.begin() as session:
        receipt = session.get(Recovery, first['recovery_id'])
        receipt.result_json = {k: v for k, v in receipt.result_json.items() if k != 'remaining_available_minor'}
        session.get(Account, 'receipt-owner').settlement_available_minor += 999
    before = finance_snapshot('receipt-owner')
    with pytest.raises(HTTPException) as rejected:
        finance.apply_future_settlement('receipt-owner', 50, 'legacy-receipt', 'legacy-key', 'finance')
    assert error_code(rejected.value) == 'RECOVERY_BALANCE_SNAPSHOT_REQUIRED'
    assert finance_snapshot('receipt-owner') == before


def test_recovery_rollback_does_not_consume_receipt_or_credit_balance():
    from go_hotel.services.supplier_fault_funding import recover_in_session
    from go_hotel.services.alipay_safeguarded_settlement import transaction
    finance.configure_supplier_finance('receipt-owner', 100, 0, 0, False)
    before = finance_snapshot('receipt-owner')
    with pytest.raises(RuntimeError, match='rollback-before-commit'):
        with transaction() as session:
            recover_in_session(session, 'receipt-owner', 50, 'rollback-receipt', 'rollback-key', 'finance', Recovery, 'supplier_id')
            session.flush()
            raise RuntimeError('rollback-before-commit')
    assert finance_snapshot('receipt-owner') == before
    result = finance.apply_future_settlement('receipt-owner', 50, 'rollback-receipt', 'rollback-key', 'finance')
    assert result['remaining_available_minor'] == 150
