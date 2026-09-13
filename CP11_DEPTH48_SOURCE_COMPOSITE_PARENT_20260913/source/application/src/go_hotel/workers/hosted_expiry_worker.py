"""Deterministic reservation expiry; payment uncertainty remains held for reconciliation."""
import asyncio
import logging
from go_hotel.services.hosted_reservation_operations import hosted_reservation_operations_service

logger = logging.getLogger('go.reservation.expiry')

async def run(interval_seconds=30):
    while True:
        try:
            result=await asyncio.to_thread(hosted_reservation_operations_service.expire_pending,'SYSTEM_EXPIRY_WORKER')
            if result['expired_count'] or result.get('payment_reconciliation_required'):
                logger.info('reservation_expiry_tick',extra={'expired_count':result['expired_count'],
                    'payment_reconciliation_required':result.get('payment_reconciliation_required',0)})
        except asyncio.CancelledError:
            raise
        except Exception:
            # Re-read authoritative state next time; do not invent cancellation success.
            logger.error('reservation_expiry_tick_failed')
        await asyncio.sleep(interval_seconds)
