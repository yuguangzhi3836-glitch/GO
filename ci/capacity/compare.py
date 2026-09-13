"""Controlled middleware/metrics experiment; never a live HK capacity gate."""
import argparse
import asyncio
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tracemalloc
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
BASE = '286e294d92df4b7d1c0073116a8e628734abec6c'
MAIN = 'application/src/go_hotel/main.py'
METRICS = 'application/src/go_hotel/observability/metrics.py'
BASE_BLOBS = {MAIN: '2dd998a2f12692c55339f595056bf39fc747ef25',
              METRICS: '36b87f2d77ffbe50e2d3c1c9ed16deb44a8221b6'}


def source(path, baseline_root=None):
    data = ((baseline_root / path).read_bytes() if baseline_root else
            subprocess.check_output(['git', 'show', f'{BASE}:{path}'], cwd=ROOT))
    digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    if digest != BASE_BLOBS[path]:
        raise ValueError(f'baseline blob mismatch: {path}')
    return data


def module(name, data, path):
    result = ModuleType(name)
    result.__file__ = str(ROOT / path)
    exec(compile(data, result.__file__, 'exec'), result.__dict__)
    return result


async def request_experiment(runtime, registry, users):
    import httpx
    from fastapi import FastAPI
    runtime.metrics = registry()
    # Deliberately injected synchronous I/O delay. No real DB or provider call.
    def active(scope):
        time.sleep(0.003)
        return False
    runtime.incident_service = SimpleNamespace(active=active)
    app = FastAPI()
    app.add_middleware(runtime.Sprint1RAuditMiddleware)
    app.add_middleware(runtime.Sprint1USecurityMiddleware)
    app.add_middleware(runtime.Sprint1VObservabilityMiddleware)
    @app.post('/v1/search/probe')
    async def search():
        return {'ok': True}
    delays, latencies, statuses = [], [], []
    complete = False
    async def heartbeat():
        while not complete:
            start = time.perf_counter()
            await asyncio.sleep(0.005)
            delays.append(max(0, (time.perf_counter() - start - 0.005) * 1000))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://isolated') as client:
        async def request():
            start = time.perf_counter()
            response = await client.post('/v1/search/probe')
            latencies.append((time.perf_counter() - start) * 1000)
            statuses.append(response.status_code)
        monitor = asyncio.create_task(heartbeat())
        await asyncio.sleep(0)
        start = time.perf_counter()
        try:
            await asyncio.gather(*(request() for _ in range(users)))
        finally:
            complete = True
            await monitor
        elapsed = time.perf_counter() - start
    ordered = sorted(latencies)
    return {'simultaneous_probe_requests': users, 'injected_sync_io_ms': 3,
            'elapsed_seconds': elapsed, 'p95_ms': ordered[math.ceil(len(ordered) * .95) - 1],
            'max_event_loop_lag_ms': max(delays), 'http_errors': sum(x != 200 for x in statuses)}


def metrics_experiment(registry):
    tracemalloc.start()
    instance = registry()
    for i in range(200000):
        instance.observe('latency', (i * 97) % 100000)
    retained_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    start = time.perf_counter()
    instance.prometheus()
    scrape_ms = (time.perf_counter() - start) * 1000
    return {'observations': 200000, 'retained_samples': len(instance.histogram_values('latency')),
            'traced_retained_bytes': retained_bytes, 'traced_peak_bytes': peak_bytes,
            'scrape_ms': scrape_ms}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--baseline-root', type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / 'application/src'))
    # Override ambient DB configuration before importing application modules.
    with tempfile.TemporaryDirectory(prefix='go-capacity-compare-') as directory:
        os.environ['DATABASE_URL'] = 'sqlite+pysqlite:///' + str(Path(directory) / 'unused.db')
        import go_hotel.main as candidate
        from go_hotel.observability.metrics import MetricsRegistry
        before_metrics = module('capacity_before_metrics', source(METRICS, args.baseline_root), METRICS)
        before = module('capacity_before_main', source(MAIN, args.baseline_root), MAIN)
        logging.disable(logging.CRITICAL)
        report = {'scope': 'SYNTHETIC_ASGI_MIDDLEWARE_NOT_HK_CAPACITY', 'base_commit': BASE,
                  'candidate_files_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in (MAIN, METRICS)},
                  'experiments': {}, 'live_hk_1000_gate': 'NOT_EXECUTED'}
        for label, runtime, registry in [('baseline', before, before_metrics.MetricsRegistry),
                                         ('candidate', candidate, MetricsRegistry)]:
            report['experiments'][label] = {
                'requests': [asyncio.run(request_experiment(runtime, registry, n)) for n in (500, 1000)],
                'metrics': metrics_experiment(registry)}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report))


if __name__ == '__main__':
    main()
