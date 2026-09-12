from __future__ import annotations
import asyncio, time
from go_hotel.services.reconciliation import reconciliation_service

def main():
    while True:
        asyncio.run(reconciliation_service.run_once(100)); time.sleep(30)
if __name__ == "__main__": main()
