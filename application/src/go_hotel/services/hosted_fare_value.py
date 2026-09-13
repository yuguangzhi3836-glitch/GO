"""Separate dated accommodation value from irreversibly forfeited change value.

Reservation.amount_minor remains the gross funding obligation. Current dated
nights carry the accommodation value; their difference is never a reusable
balance. Cash forfeiture has its own capture, outside ordinary refund sources.
"""
from datetime import date
from sqlalchemy import select
from go_hotel.db.models import HostedReservationNightRow as Night, HostedCreditAllocationRow as Allocation

POLICY = 'CURRENT_ROOM_VALUE_WITH_IRREVERSIBLE_FORFEITURE_V1'
FORFEITURE_KEY = 'direct-change-forfeiture:'


def basis(s, reservation):
    rows = list(s.scalars(select(Night).where(
        Night.hosted_reservation_id == reservation.hosted_reservation_id,
        Night.stay_date >= reservation.check_in, Night.stay_date < reservation.check_out)))
    # Historical undated reservations have no changeable dated inventory.
    current = reservation.amount_minor
    if rows:
        expected = (date.fromisoformat(reservation.check_out) - date.fromisoformat(reservation.check_in)).days
        if len(rows) != expected or any(type(n.price_minor) is not int or n.price_minor < 0 for n in rows):
            raise ValueError('HOSTED_FARE_VALUE_INTEGRITY_INVALID')
        current = sum(n.price_minor for n in rows)
    if type(reservation.amount_minor) is not int or not 0 <= current <= reservation.amount_minor:
        raise ValueError('HOSTED_FARE_VALUE_INTEGRITY_INVALID')
    forfeited = reservation.amount_minor - current
    allocation = s.get(Allocation, reservation.hosted_reservation_id)
    prepaid_forfeiture = min(forfeited, allocation.applied_minor) if allocation else 0
    return {'fare_value_policy': POLICY, 'gross_funded_value_minor': reservation.amount_minor,
            'current_room_value_minor': current, 'forfeited_change_value_minor': forfeited,
            'prepaid_forfeiture_minor': prepaid_forfeiture,
            'cash_forfeiture_minor': forfeited - prepaid_forfeiture}


def is_forfeiture(movement):
    return movement.idempotency_key.startswith(FORFEITURE_KEY)


def capture_forfeiture(s, reservation, authorization, evidence):
    from go_hotel.services import hosted_money as funds
    from go_hotel.services.unified_money_movement import unified_money_movement_service as money
    value = basis(s, reservation)
    amount = value['cash_forfeiture_minor']
    if not amount:
        return None
    payment = funds.root(s, authorization)
    auth = next((m for m in funds.active_movements(s, authorization)
                 if m.movement_type == 'AUTHORIZATION' and m.state == 'CONFIRMED'), None)
    if not payment or not auth:
        raise ValueError('CONFIRMED_AUTHORIZATION_REQUIRED')
    return money.create_in_session(s, payment.payment_intent_id,
        {'movement_type': 'CAPTURE', 'amount_minor': amount,
         'parent_movement_id': auth.money_movement_id, 'mode': 'CONTRACT_SIMULATOR',
         'evidence': [*evidence, {'policy': POLICY, 'forfeited_change_value_minor': amount}]},
        FORFEITURE_KEY + reservation.hosted_reservation_id, 'hosted-fare')
