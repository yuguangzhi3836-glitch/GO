from __future__ import annotations
import time
from go_hotel.journey.recovery_reconciliation import recovery_reconciliation_service

def main():
    while True:
        recovery_reconciliation_service.run_once(50)
        time.sleep(15)
if __name__=='__main__':main()
