from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import threading
import time
import pytest
import yappi
sys.path.insert(0, str(Path(__file__).parent))
from thread_profile import CpuProbe


def cpu_then_sleep(seconds):
    start = time.thread_time()
    while time.thread_time()-start < seconds:
        sum(range(20))
    time.sleep(.12)


def test_cpu_excludes_waiting_and_separates_concurrent_threads():
    p=CpuProbe();p.start()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(cpu_then_sleep, [.025,.06]))
    finally:
        data=p.stop(Path.cwd())
    matches=[(t,f) for t in data['threads'] for f in t['functions'] if f['function']=='cpu_then_sleep']
    assert len(matches)==2
    assert data['clock']=='cpu'
    used=sorted(f['inclusive_cpu_seconds'] for t,f in matches)
    assert used[0] < .06 and .05 < used[1] < .1
    assert sum(used)<.13 and data['wall_seconds']>.12
    assert len({t['context_id'] for t,f in matches})==2


def test_nested_calls_and_replay_threads_are_included():
    p=CpuProbe();p.start()
    def replay():
        return sum(range(100))
    def actor():
        replay()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _:replay(),range(2)))
    try: actor()
    finally: data=p.stop(Path.cwd())
    rows=[r for r in data['functions'] if r['function']=='replay']
    assert len(rows)==1 and rows[0]['calls']==3
    assert sum(r['calls'] for t in data['threads'] for r in t['functions'] if r['function']=='replay')==3


def test_exception_always_stops_probe():
    p=CpuProbe();p.start()
    with pytest.raises(ValueError):
        try: raise ValueError('synthetic')
        finally: data=p.stop(Path.cwd())
    assert not yappi.is_running() and data['threads']
