"""Compatibility dispatch facade for Ride and Rental.

C04 and C05 business rules live in their isolated owned paths:
- C04 / RENTAL: go_hotel.mobility.rental
- C05 / RIDE: go_hotel.mobility.ride

This module contains routing only and must not own supplier prices, policies, or
state-machine business truth.
"""
from __future__ import annotations

from go_hotel.db.models import MobilityRentalOrderRow, MobilityRideOrderRow
from go_hotel.db.session import SessionLocal
from go_hotel.mobility.rental.service import rental_service
from go_hotel.mobility.ride.service import ride_service


class MobilityService:
    def ride_search(self, **kwargs):
        return ride_service.search(**kwargs)

    def create_ride(self, account, body):
        return ride_service.create(account, body)

    def rental_search(self, **kwargs):
        return rental_service.search(**kwargs)

    def create_rental(self, account, body):
        return rental_service.create(account, body)

    def _vertical(self, order_id: str) -> str:
        with SessionLocal() as s:
            if s.get(MobilityRideOrderRow, order_id):
                return "RIDE"
            if s.get(MobilityRentalOrderRow, order_id):
                return "RENTAL"
        raise ValueError("MOBILITY_ORDER_NOT_FOUND")

    def get_order(self, account, order_id):
        return (ride_service if self._vertical(order_id) == "RIDE" else rental_service).get(account, order_id)

    def trips(self, account):
        return ride_service.trips(account) + rental_service.trips(account)

    def modify(self, account, order_id, new_time):
        return (ride_service if self._vertical(order_id) == "RIDE" else rental_service).modify(account, order_id, new_time)

    def refund_quote(self, account, order_id):
        return (ride_service if self._vertical(order_id) == "RIDE" else rental_service).refund_quote(account, order_id)

    def cancel(self, account, order_id, accepted_hash=None):
        return (ride_service if self._vertical(order_id) == "RIDE" else rental_service).cancel(account, order_id, accepted_hash)

    def fulfill(self, account, order_id, action, evidence_reference):
        return (ride_service if self._vertical(order_id) == "RIDE" else rental_service).fulfill(account, order_id, action, evidence_reference)

    def admin_external_state(self, order_id, state, evidence_reference, actor):
        return (ride_service if self._vertical(order_id) == "RIDE" else rental_service).admin_external_state(order_id, state, evidence_reference, actor)


mobility_service = MobilityService()
