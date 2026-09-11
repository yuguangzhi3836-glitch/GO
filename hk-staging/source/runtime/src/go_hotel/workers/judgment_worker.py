from __future__ import annotations
import time
from go_hotel.judgment.service import judgment_service

def main():
    while True:
        judgment_service.process_pending(100)
        time.sleep(5)

if __name__ == "__main__":
    main()
