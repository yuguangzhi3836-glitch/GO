"""Isolated lifecycle runner. Probe tasks only; no model or external worker adapter."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import threading
import time
import uuid
from runtime import Runtime
from supervisor import Supervisor, NoopWorker
from watchdog import Watchdog
from topology import load_topology

@contextmanager
def singleton(db: Path):
    # Never unlink the lock inode: old/new processes must contend on the same file.
    with db.with_suffix(db.suffix+'.runner.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('runner already active for this database') from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)

def write_health(path: Path, document: dict) -> None:
    temporary = path.with_suffix(path.suffix+'.tmp')
    with temporary.open('w') as out:
        json.dump(document,out,sort_keys=True);out.flush();os.fsync(out.fileno())
    os.replace(temporary,path)

def run(db: str, *, tick_s: float = 5.0, watchdog_every: int = 12,
        isolated_validation: bool = False, stop: threading.Event | None = None,
        topology_path: Path | None = None) -> None:
    if isolated_validation is not True:
        raise ValueError('persistent activation HOLD; explicit isolated validation required')
    if isinstance(tick_s,bool) or not math.isfinite(tick_s) or tick_s <= 0:
        raise ValueError('tick must be finite and positive')
    if type(watchdog_every) is not int or watchdog_every < 1:
        raise ValueError('watchdog interval must be a positive integer')
    topology = load_topology(topology_path or Path(__file__).with_name('topology.v1.json'))
    path=Path(db).resolve()
    stop=stop if stop is not None else threading.Event()
    run_id=uuid.uuid4().hex
    with singleton(path):
        rt=Runtime(path)
        sup=Supervisor(rt,NoopWorker(),worker_prefix='runner:'+run_id,
                       task_kinds=tuple(topology['services'][0]['task_kinds']))
        wd=Watchdog(rt)
        health=path.with_suffix(path.suffix+'.health.json')
        n=0
        state={'run_id':run_id,'pid':os.getpid(),'status':'STARTING',
               'topology_id':topology['topology_id'],'adapter':'noop',
               'authorizes_any_action':False,'ticks':0,'updated_at':time.time()}
        write_health(health,state)
        try:
            while not stop.is_set():
                if not rt.verify_evidence_chain():
                    raise RuntimeError('evidence chain invalid; runner stopped')
                sup.tick(); n+=1
                if n % watchdog_every == 0: wd.inspect()
                state.update(status='RUNNING',ticks=n,updated_at=time.time())
                write_health(health,state)
                stop.wait(tick_s)
        except Exception:
            state.update(status='FAILED',updated_at=time.time())
            write_health(health,state)
            raise
        else:
            state.update(status='STOPPED',updated_at=time.time())
            write_health(health,state)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',required=True)
    p.add_argument('--isolated-validation',action='store_true')
    p.add_argument('--topology',type=Path)
    p.add_argument('--tick',type=float,default=5.0)
    p.add_argument('--watchdog-every',type=int,default=12)
    a=p.parse_args()
    stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):
        signal.signal(sig,lambda *_: stop.set())
    run(a.db,tick_s=a.tick,watchdog_every=a.watchdog_every,
        isolated_validation=a.isolated_validation,stop=stop,topology_path=a.topology)

if __name__=='__main__':main()
