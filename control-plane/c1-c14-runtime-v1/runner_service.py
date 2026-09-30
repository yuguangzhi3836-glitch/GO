"""Safe runner service wrapper.

The runner only drives Supervisor + Watchdog. External worker adapters may be
plugged in later; Noop remains default to prove service lifecycle safely.
"""
from __future__ import annotations
import argparse,time
from pathlib import Path
from runtime import Runtime
from supervisor import Supervisor,NoopWorker
from watchdog import Watchdog

def run(db: str, *, tick_s: float=5.0, watchdog_every: int=12) -> None:
    rt=Runtime(Path(db))
    sup=Supervisor(rt,NoopWorker(),worker_prefix="runner")
    wd=Watchdog(rt)
    n=0
    while True:
        sup.tick()
        n+=1
        if n % watchdog_every == 0:
            wd.inspect()
        time.sleep(tick_s)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db",default="/var/lib/go-c-runtime/runtime.db")
    p.add_argument("--tick",type=float,default=5.0)
    p.add_argument("--watchdog-every",type=int,default=12)
    a=p.parse_args()
    run(a.db,tick_s=a.tick,watchdog_every=a.watchdog_every)

if __name__=="__main__":
    main()
