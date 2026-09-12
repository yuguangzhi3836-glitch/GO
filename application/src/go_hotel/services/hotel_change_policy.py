"""GO hotel changes: no service fee, one fixed year from original booking.

Original booking/snapshot timestamps remain immutable. A change never renews
the validity period. Cancellation continues to use the accepted refund terms.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

POLICY = 'GO_HOTEL_FREE_CHANGE_365D_V1'


def terms(created_at):
    created = datetime.fromisoformat(created_at) if isinstance(created_at, str) else created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    created = created.astimezone(timezone.utc)
    return {'change_policy': POLICY, 'change_fee_minor': 0,
            'change_validity_days': 365, 'change_valid_from': created.isoformat(),
            'change_valid_until': (created + timedelta(days=365)).isoformat()}


def require_window(created_at, check_in, at, hotel_timezone='UTC', check_in_hour=0):
    policy = terms(created_at)
    expiry = datetime.fromisoformat(policy['change_valid_until'])
    arrival = datetime.fromisoformat(check_in).replace(
        hour=check_in_hour, tzinfo=ZoneInfo(hotel_timezone))
    if at >= expiry or arrival > expiry:
        raise ValueError('HOTEL_CHANGE_ONE_YEAR_VALIDITY_EXCEEDED')
    return policy


def require_zero_fee(rules):
    if rules['change_fee_minor'] != 0:
        raise ValueError('HOTEL_CHANGE_FEE_MUST_BE_ZERO')
