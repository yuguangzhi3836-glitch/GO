import time
from go_hotel.mobile.orchestration import mobile_engagement
from go_hotel.mobile.push import push_worker

def main():
    while True:
        mobile_engagement.ingest_domain_events()
        mobile_engagement.process_due()
        push_worker.run_once()
        time.sleep(5)
if __name__=='__main__': main()
