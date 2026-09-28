"""Explicit synthetic source for tests that intentionally exercise ride booking.

No autouse fixture and no production import. This is not an approved tariff.
"""
from contextlib import contextmanager
from hashlib import sha256
import json
from unittest.mock import patch


def envelope(offer='ride_standard', *, before=0, after=0, version='synthetic-test-v1', cutoff=3600):
    policy = {'version': version, 'offer_id': offer, 'currency': 'CNY',
              'source_reference': 'isolated://test-fixture/cancellation', 'data_mode': 'ISOLATED_SYNTHETIC',
              'effective_from': '2020-01-01T00:00:00Z', 'effective_until': '2099-01-01T00:00:00Z',
              'cutoff_seconds': cutoff, 'before_fee_minor': before, 'after_fee_minor': after,
              'time_basis': 'BOOKED_PICKUP'}
    raw = json.dumps(policy, sort_keys=True).encode()
    return {'raw_payload': raw, 'raw_sha256': sha256(raw).hexdigest()}


@contextmanager
def synthetic_policy(**kwargs):
    with patch('go_hotel.mobility.ride.cancellation_policy.resolve_policy',
               side_effect=lambda offer: envelope(offer, **kwargs)):
        yield


def accepted_body(service, body):
    body = dict(body)
    quoted = service.search(body['pickup'], body['dropoff'], body['pickup_at'], body.get('currency', 'CNY'))
    offer = next(item for item in quoted if item['offer_id'] == body['offer_id'])
    body['cancellation_policy_hash'] = offer['cancellation']['policy_hash']
    return body


def create_ride(service, owner, body):
    with synthetic_policy():
        return service.create(owner, accepted_body(service, body))


def aware_fixture_body(body):
    """Historical isolated fixtures explicitly mean China local time."""
    from datetime import datetime
    result = dict(body)
    if datetime.fromisoformat(result['pickup_at']).tzinfo is None:
        result['pickup_at'] += '+08:00'
    return result


def post_ride_order(client, *, headers, body):
    from go_hotel.mobility.ride.service import ride_service
    with synthetic_policy():
        accepted = accepted_body(ride_service, aware_fixture_body(body))
        return client.post('/v1/mobility/rides/orders', headers=headers, json=accepted)


def reserve_agent(gateway, ctx, vertical, search, booking, key):
    import asyncio
    from go_hotel.agent_gateway.contracts import OfferRequest, ReserveRequest
    assert vertical == 'RIDE'
    search = aware_fixture_body(search)
    with synthetic_policy():
        offer = asyncio.run(gateway.offers(ctx, OfferRequest(vertical, search))).data['items'][0]
        booking = dict(booking, cancellation_policy_hash=offer['cancellation']['policy_hash'])
        return asyncio.run(gateway.reserve(ctx, ReserveRequest(offer['offer_id'], offer['quote_hash'], search, booking, key))).data
