import os, time, threading
from go_hotel.queue.durable_regional import RegionalLeaseLost, processing
from go_hotel.services.regional_hotel_build import TOPIC, _queue, regional_hotel_build_service


def run_once(timeout_seconds: int = 1):
    q=_queue()
    msg=q.claim(TOPIC)
    if not msg:
        if timeout_seconds: time.sleep(min(max(timeout_seconds, 0), 1))
        return None
    stop=threading.Event()
    def renew():
        while not stop.wait(q.lease_ms / 3000):
            try: q.heartbeat(msg)
            except Exception:
                stop.set()
                return
    heartbeat=threading.Thread(target=renew,daemon=True,name='regional-lease-renewal')
    heartbeat.start()
    try:
        with processing(q, msg):
            q.heartbeat(msg)
            result=regional_hotel_build_service.process_message(msg.payload)
            if isinstance(result,dict) and result.get('state') == 'FAILED':
                q.fail(msg,result.get('code') or 'REGIONAL_TASK_FAILED',retryable=result.get('retryable') is True)
            else:
                q.ack(msg, result)
        return msg.message_id
    except RegionalLeaseLost:
        raise
    except Exception as exc:
        q.fail(msg, type(exc).__name__)
        raise
    finally:
        stop.set()
        heartbeat.join(timeout=1)


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
