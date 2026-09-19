from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import select

from go_hotel.db.models import RailChangeQuoteRow, PaymentOrderRootRow
from go_hotel.db.session import SessionLocal
from test_depth21_refund_recovery import booked


def quotes():
    service, owner, order_id = booked('RAIL')
    first = service.change_quote(owner, order_id, '2026-10-02')
    other = service.change_quote(owner, order_id, '2026-10-03', 'FIRST_CLASS')
    return service, owner, order_id, first['quote_id'], other['quote_id']


@pytest.mark.parametrize('decision', ['TICKETED', 'FAILED'])
def test_unselected_quote_cannot_execute_after_a_supplier_decision(decision):
    service, owner, oid, selected, stale = quotes()
    service.execute_change(owner, oid, selected)
    service.admin_external_state(oid, decision, 'isolated://c03-choice', 'isolated-admin',
                                 'NEW-BOOKING' if decision == 'TICKETED' else None,
                                 ['NEW-A', 'NEW-B'] if decision == 'TICKETED' else [], selected)
    with pytest.raises(ValueError, match='RAIL_CHANGE_QUOTE_INVALID'):
        service.execute_change(owner, oid, stale)
    with SessionLocal() as session:
        assert session.get(RailChangeQuoteRow, stale).status == 'SUPERSEDED'
        assert session.scalar(select(PaymentOrderRootRow).where(PaymentOrderRootRow.business_id == stale)) is None
    fresh = service.change_quote(owner, oid, '2026-10-04')
    assert service.execute_change(owner, oid, fresh['quote_id'])['status'] == 'UNKNOWN_EXTERNAL_STATE'


def test_authorization_interruption_preserves_selected_quote_only(monkeypatch):
    from go_hotel.services.vertical_money_bridge import vertical_money_bridge
    service, owner, oid, selected, stale = quotes()
    original = vertical_money_bridge.prepare_adjustment

    def offline(*args, **kwargs):
        raise RuntimeError('ISOLATED_AUTHORIZATION_INTERRUPTION')

    monkeypatch.setattr(vertical_money_bridge, 'prepare_adjustment', offline)
    with pytest.raises(RuntimeError, match='ISOLATED_AUTHORIZATION_INTERRUPTION'):
        service.execute_change(owner, oid, selected)
    with SessionLocal() as session:
        assert session.get(RailChangeQuoteRow, stale).status == 'SUPERSEDED'
        assert session.get(RailChangeQuoteRow, selected).status == 'PREPARING'
    monkeypatch.setattr(vertical_money_bridge, 'prepare_adjustment', original)
    assert service.execute_change(owner, oid, selected)['status'] == 'UNKNOWN_EXTERNAL_STATE'
    assert service.execute_change(owner, oid, selected)['status'] == 'UNKNOWN_EXTERNAL_STATE'
    with pytest.raises(ValueError, match='RAIL_CHANGE_QUOTE_INVALID'):
        service.execute_change(owner, oid, stale)


def test_invalid_selection_does_not_supersede_valid_quotes():
    service, owner, oid, selected, other = quotes()
    with pytest.raises(ValueError, match='RAIL_CHANGE_QUOTE_INVALID'):
        service.execute_change('other-owner', oid, selected)
    with SessionLocal() as session:
        assert session.get(RailChangeQuoteRow, selected).status == 'QUOTED'
        assert session.get(RailChangeQuoteRow, other).status == 'QUOTED'


def test_quote_created_concurrently_with_selection_is_also_superseded(monkeypatch):
    service, owner, oid, selected, _ = quotes()
    entered = Event()
    finish = Event()
    original = service._terms

    def pause(*args):
        result = original(*args)
        entered.set()
        assert finish.wait(10)
        return result

    monkeypatch.setattr(service, '_terms', pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        new_quote = pool.submit(service.change_quote, owner, oid, '2026-10-06')
        assert entered.wait(10)
        selected_result = pool.submit(service.execute_change, owner, oid, selected)
        finish.set()
        new_id = new_quote.result(15)['quote_id']
        assert selected_result.result(15)['status'] == 'UNKNOWN_EXTERNAL_STATE'
    with SessionLocal() as session:
        assert session.get(RailChangeQuoteRow, new_id).status == 'SUPERSEDED'
