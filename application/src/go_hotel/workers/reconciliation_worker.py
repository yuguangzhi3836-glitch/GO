from __future__ import annotations
import asyncio, time, logging
from go_hotel.services.reconciliation import reconciliation_service
from go_hotel.services.registration_privacy import cleanup_once


def main():
    first_cycle=True
    while True:
        try:
            cleanup_once(invalidate_challenges=first_cycle)
            first_cycle=False
        except Exception:
            # Never log database parameters/PII. Stale heartbeat blocks new signup.
            logging.getLogger(__name__).error('REGISTRATION_PRIVACY_CLEANUP_FAILED')
        try:
            asyncio.run(reconciliation_service.run_once(100))
        except Exception:
            logging.getLogger(__name__).error('RECONCILIATION_CYCLE_FAILED')
        time.sleep(30)
if __name__ == "__main__": main()
