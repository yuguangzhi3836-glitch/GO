"""Bounded, restartable unpaid reservation expiration worker."""
import asyncio
import json
import logging
from go_hotel.services.vertical_reservation_expiry import expire_due

logger = logging.getLogger('go.vertical.expiry')


async def run(interval_seconds=30):
    while True:
        try:
            result = await asyncio.to_thread(expire_due)
            if result['scanned']:
                logger.info('vertical_expiry_tick', extra={'expiry_result': result})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('vertical_expiry_tick_failed')
        await asyncio.sleep(interval_seconds)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    if args.once:
        result = expire_due()
        print(json.dumps(result))
        raise SystemExit(1 if result['errors'] else 0)
    asyncio.run(run())
