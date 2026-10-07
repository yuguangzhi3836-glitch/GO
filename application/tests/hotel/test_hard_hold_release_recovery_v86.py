"""Rebuilt for #545; not recovered bytes from the terminated Builder."""
import asyncio

import pytest
from sqlalchemy import select

from go_hotel.agent_gateway.contracts import AgentContext, AgentProtocol, OfferRequest, ReserveRequest
from go_hotel.agent_gateway.lifecycle_core import GoTransactionCore
from go_hotel.agent_gateway.service import AgentTransactionGateway
from go_hotel.connectors.mock_hotel import connector
from go_hotel.db.models import EventRow, OutboxRow
from go_hotel.db.session import SessionLocal


def run(awaitable):
    return asyncio.run(awaitable)


def prepare():
    connector.prebook_hold_type = 'HARD'
    scopes = frozenset({'offers:read', 'reserve:write', 'payments:write',
                        'commit:write', 'orders:read', 'aftersales:write'})
    ctx = AgentContext('rebuild-r', 'rebuild-t', 'rebuild-agent', AgentProtocol.REST,
                       'manage-travel', scopes, 'rebuild-owner')
    gw = AgentTransactionGateway(GoTransactionCore())
    search = {'city_code': 'TYO', 'check_in': '2026-11-11',
              'check_out': '2026-11-12', 'currency': 'CNY'}
    offer = run(gw.offers(ctx, OfferRequest('HOTEL', search))).data['items'][0]
    reservation = run(gw.reserve(ctx, ReserveRequest(
        offer['offer_id'], offer['quote_hash'], search,
        {'fare_confirmed': True, 'simulation_fixture': True}, 'rebuilt-reserve'))).data
    return gw, ctx, reservation['reserve_id']


def cancellation_rows(reserve_id):
    order_id = reserve_id.split(':', 1)[1]
    with SessionLocal() as session:
        return tuple(tuple(session.scalars(select(row.event_id).where(
            row.aggregate_id == order_id,
            row.event_type == 'UNPAID_ORDER_CANCELLED')).all())
            for row in (EventRow, OutboxRow))


@pytest.mark.parametrize('release_result', ['TIMEOUT', 'UNKNOWN'])
def test_unknown_then_confirmed_release_recovers_without_duplicate_side_effects(monkeypatch, release_result):
    gw, ctx, reserve_id = prepare()
    confirmed = False
    calls = {'release': 0, 'lookup': 0}

    async def release(prebook_id, key):
        calls['release'] += 1
        if release_result == 'TIMEOUT':
            raise TimeoutError('CONTROLLED_RELEASE_TIMEOUT')
        return 'UNKNOWN'

    async def lookup(prebook_id, key):
        calls['lookup'] += 1
        return 'RELEASED' if confirmed else 'UNKNOWN'

    monkeypatch.setattr(connector, 'release_prebook_hold', release)
    monkeypatch.setattr(connector, 'lookup_prebook_hold', lookup)
    with pytest.raises(ValueError, match='RECONCILIATION_REQUIRED'):
        run(gw.release(ctx, reserve_id, 'rebuilt-release'))
    assert run(gw.order(ctx, reserve_id)).data['status'] == 'PAYMENT_PENDING'
    assert cancellation_rows(reserve_id) == ((), ())
    assert calls['release'] == 1

    confirmed = True
    first = run(gw.release(ctx, reserve_id, 'rebuilt-release')).data
    assert first['state'] == 'RELEASED'
    assert first['order_truth']['status'] == 'CANCELLED'
    assert calls['release'] == 1
    events, outbox = cancellation_rows(reserve_id)
    assert len(events) == 1 and events == outbox
    calls_before_replay = calls.copy()
    assert run(gw.release(ctx, reserve_id, 'rebuilt-release')).data == first
    assert calls == calls_before_replay
    assert cancellation_rows(reserve_id) == (events, outbox)


def test_already_released_supplier_hold_does_not_issue_release_again(monkeypatch):
    gw, ctx, reserve_id = prepare()

    async def lookup(prebook_id, key):
        return 'RELEASED'

    async def forbidden_release(prebook_id, key):
        pytest.fail('confirmed released hold must not be released again')

    monkeypatch.setattr(connector, 'lookup_prebook_hold', lookup)
    monkeypatch.setattr(connector, 'release_prebook_hold', forbidden_release)
    result = run(gw.release(ctx, reserve_id, 'already-released')).data
    assert result['order_truth']['status'] == 'CANCELLED'
    events, outbox = cancellation_rows(reserve_id)
    assert len(events) == 1 and events == outbox
