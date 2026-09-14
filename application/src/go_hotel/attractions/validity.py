"""Validate and freeze a trusted supplier's session-relative validity policy.

No product supplies a default policy. Missing facts remain LEGACY_UNVERIFIED;
the compatibility path does not establish a supplier validity window.
"""
from datetime import datetime, UTC, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def freeze(policy, visit_date, session_time):
    if policy is None:
        return {'state': 'LEGACY_UNVERIFIED'}
    keys = {'destination_timezone', 'opens_minutes_before_session',
            'closes_minutes_after_session', 'policy_reference'}
    if (not isinstance(policy, dict) or set(policy) != keys
        or not isinstance(policy['destination_timezone'], str)
        or not isinstance(policy['policy_reference'], str)
        or not policy['policy_reference'].strip()
        or type(policy['opens_minutes_before_session']) is not int
        or not 0 <= policy['opens_minutes_before_session'] <= 1440
        or type(policy['closes_minutes_after_session']) is not int
        or not 1 <= policy['closes_minutes_after_session'] <= 2880):
        raise ValueError('ATTRACTION_SUPPLIER_VALIDITY_POLICY_INVALID')
    try:
        zone = ZoneInfo(policy['destination_timezone'])
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('ATTRACTION_SUPPLIER_VALIDITY_POLICY_INVALID') from None
    try:
        local = datetime.fromisoformat(visit_date + 'T' + session_time)
        if local.tzinfo is not None:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError('ATTRACTION_SUPPLIER_LOCAL_TIME_REVIEW_REQUIRED') from None
    instants = set()
    for fold in (0, 1):
        aware = local.replace(tzinfo=zone, fold=fold)
        utc = aware.astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) == local:
            instants.add(utc)
    if len(instants) != 1:
        raise ValueError('ATTRACTION_SUPPLIER_LOCAL_TIME_REVIEW_REQUIRED')
    session = instants.pop()
    return {'state': 'FROZEN_SUPPLIER_WINDOW', 'destination_timezone': policy['destination_timezone'],
            'opens_at': (session - timedelta(minutes=policy['opens_minutes_before_session'])).isoformat(),
            'closes_at': (session + timedelta(minutes=policy['closes_minutes_after_session'])).isoformat(),
            'boundary': '[opens_at,closes_at)', 'policy': dict(policy)}


def for_order(terms, visit_date, session_time):
    window = terms.get('redemption_window')
    if window is None or window == {'state': 'LEGACY_UNVERIFIED'}:
        return {'state': 'LEGACY_UNVERIFIED'}
    if not isinstance(window, dict) or window.get('state') != 'FROZEN_SUPPLIER_WINDOW':
        raise ValueError('ATTRACTION_SUPPLIER_VALIDITY_INTEGRITY_INVALID')
    # Check the original frozen UTC result, then apply its *frozen policy* to
    # the supplier-confirmed date/session after a date change, never live catalog.
    if freeze(window.get('policy'), terms['visit_date'], terms['session_time']) != window:
        raise ValueError('ATTRACTION_SUPPLIER_VALIDITY_INTEGRITY_INVALID')
    return freeze(window['policy'], visit_date, session_time)


def guard(window, current_ms):
    if window['state'] == 'LEGACY_UNVERIFIED':
        return
    opened = datetime.fromisoformat(window['opens_at'])
    closed = datetime.fromisoformat(window['closes_at'])
    current = datetime.fromtimestamp(current_ms / 1000, UTC)
    if not opened <= current < closed:
        raise ValueError('ATTRACTION_OUTSIDE_SUPPLIER_VALIDITY_WINDOW')
