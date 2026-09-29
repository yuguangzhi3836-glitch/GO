"""Explicit isolated cancellation contracts; no default commercial tariff.

The default resolver has no approved policy. Tests may supply a server-side,
raw-byte-bound synthetic source. Caller-provided fee terms are never trusted.
"""
from copy import deepcopy
from datetime import datetime, UTC
from hashlib import sha256
import json
import os
from pathlib import Path

from sqlalchemy import select
from go_hotel.autonomy.durable import digest, db_now_ms
from go_hotel.db.models import JourneyRecoveryEvidenceChainRow as Evidence
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence
from go_hotel.services.mobility_refund_consent import verified_records
from go_hotel.services.travel_operational_facts import environment_allowed

KIND = 'RIDE_CANCELLATION_ACCEPTED'
HOLD = {'state': 'POLICY_UNAVAILABLE', 'cancellable': False,
        'reason': 'BOOKING_ACCEPTED_POLICY_REQUIRED', 'external_live': False}
FIELDS = {'version', 'offer_id', 'currency', 'source_reference', 'data_mode',
          'effective_from', 'effective_until', 'cutoff_seconds', 'before_fee_minor',
          'after_fee_minor', 'time_basis'}


def resolve_policy(offer_id):
    """An explicit local fixture file is opt-in, never supplier authorization."""
    path = os.getenv('GO_RIDE_ISOLATED_CANCELLATION_POLICY_FILE')
    if not path:
        return None
    environment_allowed('ENGINEERING')
    try:
        raw = Path(path).read_bytes()
        if len(raw) > 65536:
            raise ValueError()
        rows = json.loads(raw)
        item = rows.get(offer_id)
        if item is None:
            return None
        return {'raw_payload': item['raw_payload'].encode('utf-8'), 'raw_sha256': item['raw_sha256']}
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        raise ValueError('RIDE_CANCELLATION_SOURCE_INVALID') from None


def instant(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            raise ValueError()
        return int(dt.timestamp() * 1000)
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise ValueError('RIDE_CANCELLATION_TIME_INVALID') from None


def validate_policy(policy):
    environment_allowed('ENGINEERING')
    if not isinstance(policy, dict) or set(policy) != FIELDS:
        raise ValueError('RIDE_CANCELLATION_POLICY_INVALID')
    if (policy['data_mode'] != 'ISOLATED_SYNTHETIC' or policy['currency'] != 'CNY'
        or policy['offer_id'] not in {'ride_standard', 'ride_premium'}
        or not isinstance(policy['version'], str) or not policy['version'].strip()
        or not isinstance(policy['source_reference'], str)
        or not policy['source_reference'].startswith('isolated://')
        or policy['time_basis'] not in {'BOOKED_PICKUP', 'CURRENT_CONFIRMED_PICKUP'}):
        raise ValueError('RIDE_CANCELLATION_POLICY_INVALID')
    for key in ('cutoff_seconds', 'before_fee_minor', 'after_fee_minor'):
        if type(policy[key]) is not int or policy[key] < 0:
            raise ValueError('RIDE_CANCELLATION_POLICY_INVALID')
    if instant(policy['effective_from']) >= instant(policy['effective_until']):
        raise ValueError('RIDE_CANCELLATION_POLICY_INVALID')
    return deepcopy(policy)


def offer_terms(offer_id, total, currency, pickup, dropoff, pickup_at, current_ms, session=None):
    from . import policy_operations
    if policy_operations.enabled():
        try:
            envelope = policy_operations.resolve_in(session, offer_id) if session is not None else policy_operations.resolve(offer_id)
        except ValueError as exc:
            return dict(HOLD, reason=str(exc))
    else:
        envelope = resolve_policy(offer_id)
    if session is not None:
        current_ms = db_now_ms(session)
    if envelope is None:
        return dict(HOLD)
    if not isinstance(envelope, dict) or set(envelope) != {'raw_payload', 'raw_sha256'}:
        raise ValueError('RIDE_CANCELLATION_SOURCE_INVALID')
    raw = envelope['raw_payload']
    if not isinstance(raw, bytes) or sha256(raw).hexdigest() != envelope['raw_sha256']:
        raise ValueError('RIDE_CANCELLATION_SOURCE_INVALID')
    try:
        policy = validate_policy(json.loads(raw))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError('RIDE_CANCELLATION_SOURCE_INVALID') from None
    if policy_operations.enabled() and not instant(policy['effective_from']) <= current_ms < instant(policy['effective_until']):
        return dict(HOLD, reason='POLICY_NOT_EFFECTIVE')
    if (policy['offer_id'] != offer_id or policy['currency'] != currency
        or max(policy['before_fee_minor'], policy['after_fee_minor']) > total
        or not instant(policy['effective_from']) <= current_ms < instant(policy['effective_until'])):
        raise ValueError('RIDE_CANCELLATION_POLICY_INVALID')
    instant(pickup_at)
    terms = {'policy': policy, 'source_sha256': envelope['raw_sha256'],
             'offer_id': offer_id, 'total_amount_minor': total, 'currency': currency,
             'pickup': pickup, 'dropoff': dropoff, 'booked_pickup_at': pickup_at}
    return {'state': 'POLICY_AVAILABLE', 'cancellable': True, 'external_live': False,
            'terms': terms, 'policy_hash': digest(terms)}


def freeze_in(s, order, offer_id, accepted_hash):
    quoted = offer_terms(offer_id, order.total_amount_minor, order.currency,
                         order.pickup, order.dropoff, order.pickup_at, db_now_ms(s), session=s)
    if quoted['state'] != 'POLICY_AVAILABLE':
        raise ValueError('RIDE_CANCELLATION_POLICY_UNAVAILABLE')
    if not isinstance(accepted_hash, str) or accepted_hash != quoted['policy_hash']:
        raise ValueError('RIDE_CANCELLATION_POLICY_ACCEPTANCE_REQUIRED')
    payload = {'account_id': order.account_id, 'order_id': order.order_id,
               'terms': quoted['terms'], 'accepted_hash': accepted_hash,
               'accepted_ms': db_now_ms(s)}
    append_vertical_evidence(s, 'RIDE', order.order_id, KIND, order.status, payload, source='C05_BOOKING_CONSENT')
    return quoted


def accepted_in(s, order):
    # The policy is already present in the validated chain. A second SELECT
    # adds a round trip and can observe a different snapshot under READ COMMITTED.
    rows = [row for row in verified_records(s, order, 'RIDE') if row.evidence_kind == KIND]
    if not rows:
        raise ValueError('RIDE_CANCELLATION_BOOKING_POLICY_REQUIRED')
    if len(rows) != 1:
        raise ValueError('RIDE_CANCELLATION_POLICY_INTEGRITY_INVALID')
    payload = rows[0].evidence_json['payload']
    terms = payload.get('terms', {})
    policy = validate_policy(terms.get('policy'))
    if (payload.get('account_id') != order.account_id or payload.get('order_id') != order.order_id
        or payload.get('accepted_hash') != digest(terms)
        or terms.get('currency') != order.currency or terms.get('total_amount_minor') != order.total_amount_minor
        or terms.get('pickup') != order.pickup or terms.get('dropoff') != order.dropoff
        or terms.get('offer_id') != policy['offer_id'] or type(payload.get('accepted_ms')) is not int):
        raise ValueError('RIDE_CANCELLATION_POLICY_INTEGRITY_INVALID')
    return payload


def refund_terms_in(s, order):
    accepted = accepted_in(s, order)
    terms = accepted['terms']; policy = terms['policy']
    pickup = terms['booked_pickup_at'] if policy['time_basis'] == 'BOOKED_PICKUP' else order.pickup_at
    cutoff = instant(pickup) - policy['cutoff_seconds'] * 1000
    fee = policy['before_fee_minor'] if db_now_ms(s) < cutoff else policy['after_fee_minor']
    if not 0 <= fee <= order.total_amount_minor:
        raise ValueError('RIDE_CANCELLATION_POLICY_INTEGRITY_INVALID')
    return {'fee_minor': fee, 'refund_amount_minor': order.total_amount_minor - fee,
            'cancellation_policy_hash': accepted['accepted_hash'],
            'cancellation_policy_version': policy['version'],
            'cancellation_source_reference': policy['source_reference'], 'cutoff_ms': cutoff}


def projection(s, order):
    if s is None:
        return dict(HOLD)
    try:
        accepted = accepted_in(s, order)
    except ValueError:
        return dict(HOLD)
    return {'state': 'BOOKING_ACCEPTED', 'policy_hash': accepted['accepted_hash'],
            'terms': deepcopy(accepted['terms']), 'external_live': False,
            'cancellable': order.status == 'CONFIRMED'}
