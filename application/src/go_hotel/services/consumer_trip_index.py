"""Read-only trip navigation over owned orders, including unprojected orders.

Lifecycle projections remain evidence records. This view never repairs a ledger,
infers a successful payment from fulfillment, or trusts a projected detail URL.
"""
from datetime import datetime, timezone
import re

from sqlalchemy import select

from go_hotel.core.production_truth_gate import production_truth_required
from go_hotel.db.models import (
    OrderRow, FlightOrderRow, RailOrderRow, MobilityRideOrderRow,
    MobilityRentalOrderRow, AttractionOrderRow, HostedDirectReservationRow,
    HostedReservationStayRow, ConsumerUnifiedLifecycleRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services.consumer_unified_lifecycle import out


SOURCES = (
    ('HOTEL', 'HOTEL_CATALOG', OrderRow),
    ('FLIGHT', 'FLIGHT', FlightOrderRow),
    ('RAIL', 'RAIL', RailOrderRow),
    ('RIDE', 'RIDE', MobilityRideOrderRow),
    ('RENTAL', 'RENTAL', MobilityRentalOrderRow),
    ('ATTRACTION', 'ATTRACTION', AttractionOrderRow),
)
LABELS = dict(HOTEL='酒店预订', FLIGHT='机票行程', RAIL='火车行程',
              RIDE='接送行程', RENTAL='租车行程', ATTRACTION='景点与体验')


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None
            else value.astimezone(timezone.utc))


def list_trips(account_id):
    with SessionLocal() as session:
        projections = session.scalars(select(ConsumerUnifiedLifecycleRow).where(
            ConsumerUnifiedLifecycleRow.account_id == account_id)).all()
        items = {(row.vertical, row.order_id): out(row) | {'navigation': None}
                 for row in projections}
        seen = set()

        def add(vertical, kind, row, order_id, native_status, amount):
            key = (vertical, order_id)
            if key in seen:
                # Ambiguous canonical identities must never route to either order.
                items[key]['navigation'] = None
                items[key]['reconciliation_required'] = True
                return
            seen.add(key)
            current = items.get(key)
            fresh = current and utc(current['source_updated_at']) >= utc(row.updated_at)
            if current is None:
                current = dict(vertical=vertical, order_id=order_id,
                    title=LABELS[vertical], lifecycle_state='PENDING',
                    payment_state='UNKNOWN', refund_state='UNKNOWN',
                    change_allowed=False, cancel_allowed=False,
                    facts_json={}, source_updated_at=utc(row.updated_at).isoformat())
                items[key] = current
            current.update(native_status=native_status, total_amount_minor=amount,
                           currency=row.currency, updated_at=utc(row.updated_at).isoformat(),
                           projection_current=bool(fresh))
            if not fresh:
                # An old aggregate must not claim a later payment/refund succeeded.
                current['projected_lifecycle_state'] = current['lifecycle_state']
                current['lifecycle_state'] = 'UNKNOWN_EXTERNAL_STATE'
                current['payment_state'] = 'UNKNOWN'
                current['refund_state'] = 'UNKNOWN'
                current['change_allowed'] = current['cancel_allowed'] = False
            current['navigation'] = ({'kind': kind, 'order_id': order_id}
                if re.fullmatch(r'[A-Za-z0-9_-]{1,100}', order_id) else None)
            if kind == 'HOTEL_DIRECT':
                current['payment_state'] = row.payment_state
            elif native_status in {'PAYMENT_PENDING', 'PAYMENT_AUTHORIZED'}:
                current['payment_state'] = native_status

        for vertical, kind, model in SOURCES:
            rows = session.scalars(select(model).where(model.account_id == account_id)).all()
            if rows and vertical != 'HOTEL':
                production_truth_required(vertical, 'TRIPS_READ')
            for row in rows:
                add(vertical, kind, row, row.order_id, row.status, row.total_amount_minor)

        direct = session.scalars(select(HostedDirectReservationRow).join(
            HostedReservationStayRow,
            HostedDirectReservationRow.hosted_reservation_id == HostedReservationStayRow.hosted_reservation_id
        ).where(HostedReservationStayRow.created_by == account_id)).all()
        for row in direct:
            add('HOTEL', 'HOTEL_DIRECT', row, row.hosted_reservation_id,
                row.reservation_state, row.amount_minor)

        return sorted(items.values(), key=lambda x: (
            max(utc(x.get('updated_at') or x['source_updated_at']), utc(x['source_updated_at'])),
            x['vertical'], x['order_id']), reverse=True)
