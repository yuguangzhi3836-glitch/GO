import os, time, threading
from go_hotel.queue.redis_queue import RedisQueue
from go_hotel.services.regional_hotel_build import TOPIC, regional_hotel_build_service


def run_once(timeout_seconds: int = 1):
    q=RedisQueue(url=os.getenv('REDIS_URL'), namespace='go')
    msg=q.dequeue(TOPIC,timeout_seconds=timeout_seconds)
    if not msg:return None
    regional_hotel_build_service.process_message(msg.payload)
    return msg.message_id


def _loop(worker_no: int):
    while True:
        try:
            run_once(1)
        except Exception as exc:
            print('REGIONAL_HOTEL_BUILD_WORKER_ERROR',worker_no,str(exc),flush=True)
            time.sleep(1)


if __name__=='__main__':
    concurrency=max(1,min(int(os.getenv('GO_HOTEL_REGION_WORKER_CONCURRENCY','6')),32))
    print('REGIONAL_HOTEL_BUILD_WORKER_START',{'concurrency':concurrency},flush=True)
    threads=[]
    for i in range(concurrency):
        t=threading.Thread(target=_loop,args=(i+1,),daemon=True,name=f'regional-hotel-{i+1}')
        t.start(); threads.append(t)
    while True:
        time.sleep(60)
