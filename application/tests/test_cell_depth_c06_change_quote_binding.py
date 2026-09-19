"""C06 local engineering checks; synthetic supplier facts are not external evidence."""
import pytest
from sqlalchemy import select
from go_hotel.db.models import AttractionChangeQuoteRow, AttractionOrderRow
from go_hotel.db.session import SessionLocal
from go_hotel.attractions.service import CATALOG
from test_depth21_refund_recovery import booked


def test_sibling_quote_cannot_be_replayed_after_another_change_completes():
    svc, owner, oid = booked('ATTRACTION')
    stale = svc.change_quote(owner, oid, '2026-09-16')
    current = svc.change_quote(owner, oid, '2026-09-17')
    svc.execute_change(owner, oid, current['quote_id'])
    svc.admin_external_state(oid, 'CONFIRMED', 'isolated://changed', 'ops', 'SUP-NEW', 'VOUCHER-NEW')
    with pytest.raises(ValueError, match='ATTRACTION_CHANGE_QUOTE_NOT_FOUND'):
        svc.execute_change(owner, oid, stale['quote_id'])
    assert svc.get(owner, oid)['visit_date'] == '2026-09-17'
    assert svc.get(owner, oid)['status'] == 'CONFIRMED'
    with SessionLocal() as session:
        assert session.get(AttractionChangeQuoteRow, stale['quote_id']).status == 'SUPERSEDED'
    fresh = svc.change_quote(owner, oid, '2026-09-18')
    assert svc.execute_change(owner, oid, fresh['quote_id'])['status'] == 'UNKNOWN_EXTERNAL_STATE'


@pytest.mark.parametrize('day,clock', [('2026-03-08', '02:30'), ('2026-11-01', '01:30')])
def test_change_cannot_quote_ambiguous_or_nonexistent_frozen_supplier_session(monkeypatch, day, clock):
    monkeypatch.setitem(CATALOG['tokyo_skytree'], 'supplier_validity_policy', {
        'destination_timezone': 'America/New_York', 'opens_minutes_before_session': 30,
        'closes_minutes_after_session': 120, 'policy_reference': 'isolated://new-york-policy'})
    svc, owner, oid = booked('ATTRACTION')
    monkeypatch.setitem(CATALOG['tokyo_skytree'], 'sessions', ['16:00', clock])
    with pytest.raises(ValueError, match='ATTRACTION_SUPPLIER_LOCAL_TIME_REVIEW_REQUIRED'):
        svc.change_quote(owner, oid, day, clock)
    with SessionLocal() as session:
        assert not list(session.scalars(select(AttractionChangeQuoteRow)))
        assert session.get(AttractionOrderRow, oid).status == 'CONFIRMED'


def test_failed_change_does_not_supersede_other_quotes(monkeypatch):
    from go_hotel.attractions import service
    svc, owner, oid = booked('ATTRACTION')
    first = svc.change_quote(owner, oid, '2026-09-16')
    second = svc.change_quote(owner, oid, '2026-09-17')
    def fail(*args, **kwargs):
        raise ValueError('ATTRACTION_INVENTORY_CHANGED')
    monkeypatch.setattr(service.capacity, 'prepare_change_in', fail)
    with pytest.raises(ValueError, match='ATTRACTION_INVENTORY_CHANGED'):
        svc.execute_change(owner, oid, second['quote_id'])
    with SessionLocal() as session:
        assert session.get(AttractionOrderRow, oid).status == 'CONFIRMED'
        assert all(session.get(AttractionChangeQuoteRow, q['quote_id']).status == 'QUOTED' for q in (first, second))
