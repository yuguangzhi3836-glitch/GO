import time
from go_hotel.mobile.push import push_worker

def main():
    while True:
        push_worker.run_once(); time.sleep(1.0)
if __name__=='__main__': main()
