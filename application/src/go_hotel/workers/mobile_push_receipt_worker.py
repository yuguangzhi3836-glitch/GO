import time
from go_hotel.mobile.push import push_receipt_worker


def main():
    while True:
        push_receipt_worker.run_once()
        time.sleep(10)

if __name__ == "__main__":
    main()
