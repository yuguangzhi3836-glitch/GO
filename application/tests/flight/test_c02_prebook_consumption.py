from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from sqlalchemy import select

from go_hotel.db.models import FlightOrderRow, FlightPrebookRow
from go_hotel.db.session import SessionLocal
from go_hotel.flight.service import FlightService, flight_service, now
from tests.test_sprint3a_flight import auth


PEOPLE = [{'full_name': 'ISOLATED TRAVELER', 'type': 'ADT'}]


def prebook():
    offer = flight_service.search('PVG', 'NRT', '2026-10-01')[0]
    return flight_service.prebook(offer['offer_id'])['prebook_id']


def orders(pid):
    with SessionLocal() as session:
        return list(session.scalars(select(FlightOrderRow).where(FlightOrderRow.prebook_id == pid)))


def test_retries_across_service_restart_and_expiry_return_one_order():
    pid = prebook()
    first = flight_service.create_order('owner', pid, PEOPLE)
    with SessionLocal.begin() as session:
        session.get(FlightPrebookRow, pid).expires_at = now() - timedelta(minutes=1)
    replay = FlightService().create_order('owner', pid, PEOPLE)
    assert replay['order_id'] == first['order_id']
    assert len(orders(pid)) == 1


@pytest.mark.parametrize('owner,people', [('other-owner', PEOPLE), ('owner', [{'full_name': 'REPLACEMENT'}])])
def test_consumed_prebook_cannot_be_rebound(owner, people):
    pid = prebook()
    first = flight_service.create_order('owner', pid, PEOPLE)
    with pytest.raises(ValueError, match='FLIGHT_PREBOOK_'):
        flight_service.create_order(owner, pid, people)
    assert [row.order_id for row in orders(pid)] == [first['order_id']]


@pytest.mark.parametrize('owners', [('owner', 'owner'), ('first-owner', 'second-owner')])
def test_concurrent_claims_commit_only_one_order(owners):
    pid = prebook()
    ready = Barrier(2)

    def claim(owner):
        ready.wait(10)
        try:
            return FlightService().create_order(owner, pid, PEOPLE)
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, owners))
    assert len(orders(pid)) == 1
    accepted = [result for result in results if isinstance(result, dict)]
    assert len(accepted) == (2 if owners[0] == owners[1] else 1)
    assert len({result['order_id'] for result in accepted}) == 1


def test_order_evidence_failure_rolls_back_prebook_claim(monkeypatch):
    import go_hotel.flight.service as module
    pid = prebook()
    original = module.append_vertical_evidence

    def fail(*args, **kwargs):
        raise RuntimeError('ISOLATED_EVIDENCE_FAILURE')

    monkeypatch.setattr(module, 'append_vertical_evidence', fail)
    with pytest.raises(RuntimeError, match='ISOLATED_EVIDENCE_FAILURE'):
        flight_service.create_order('owner', pid, PEOPLE)
    assert orders(pid) == []
    with SessionLocal() as session:
        assert session.get(FlightPrebookRow, pid).status == 'CONFIRMED'
    monkeypatch.setattr(module, 'append_vertical_evidence', original)
    assert flight_service.create_order('owner', pid, PEOPLE)['status'] == 'PAYMENT_PENDING'


def test_existing_legacy_order_does_not_allow_a_second_claim():
    pid = prebook()
    first = flight_service.create_order('owner', pid, PEOPLE)
    with SessionLocal.begin() as session:
        session.get(FlightPrebookRow, pid).status = 'CONFIRMED'
    assert FlightService().create_order('owner', pid, PEOPLE)['order_id'] == first['order_id']
    with pytest.raises(ValueError, match='FLIGHT_PREBOOK_'):
        flight_service.create_order('other-owner', pid, PEOPLE)
    assert len(orders(pid)) == 1


def test_http_different_idempotency_keys_share_order_and_conflict_on_party(client):
    headers = auth(client, 'c02-prebook-claim@example.test')
    pid = prebook()
    body = {'prebook_id': pid, 'passengers': PEOPLE}
    first = client.post('/v1/flights/orders', headers={**headers, 'Idempotency-Key': 'first-claim'}, json=body)
    replay = client.post('/v1/flights/orders', headers={**headers, 'Idempotency-Key': 'new-device-claim'}, json=body)
    assert first.status_code == replay.status_code == 200
    assert first.json()['data']['order_id'] == replay.json()['data']['order_id']
    conflict = client.post('/v1/flights/orders', headers=headers,
                           json={**body, 'passengers': [{'full_name': 'CHANGED TRAVELER'}]})
    assert conflict.status_code == 409
    assert len(orders(pid)) == 1
