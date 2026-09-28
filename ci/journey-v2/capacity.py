"""Bounded real HTTP baseline against the disposable journey runtime only.

No production capacity claim: one process, SQLite, synthetic accounts, read path.
The result records observed latency and errors without inventing a business SLA.
"""
import asyncio
from collections import Counter
import json
import math
from pathlib import Path
import platform
import sys
import time

import httpx

ORIGIN = 'http://127.0.0.1:4186'


async def main(state, evidence):
    binding = json.loads((evidence / 'source-binding.json').read_text())
    credentials = json.loads((state / 'credentials.private.json').read_text())['consumer']
    report = {'source_binding': binding, 'environment': 'DISPOSABLE_SQLITE_HTTP',
              'python': platform.python_version(), 'stages': [],
              'production_capacity': 'NOT_ESTABLISHED', 'write_capacity': 'NOT_TESTED'}
    async with httpx.AsyncClient(base_url=ORIGIN, trust_env=False, timeout=30,
                               limits=httpx.Limits(max_connections=64)) as client:
        response = await client.post('/v1/mobile/auth/login', json={
            'email': credentials['username'], 'password': credentials['password']})
        response.raise_for_status()
        token = response.json()['data']['access_token']
        for concurrency in [1, 8, 32, 64]:
            semaphore = asyncio.Semaphore(concurrency)
            async def request():
                async with semaphore:
                    started = time.perf_counter()
                    try:
                        r = await client.get('/v1/consumer/unified-trips',
                                             headers={'Authorization': 'Bearer ' + token})
                        code = r.status_code
                        if code == 200 and not isinstance(r.json().get('data', {}).get('items'), list):
                            code = 'INVALID_RESPONSE'
                    except (httpx.HTTPError, ValueError):
                        code = 'REQUEST_FAILED'
                    return code, (time.perf_counter() - started) * 1000
            started = time.perf_counter()
            results = await asyncio.gather(*(request() for _ in range(concurrency * 4)))
            elapsed = time.perf_counter() - started
            latencies = sorted(ms for _, ms in results)
            stage = {'concurrency': concurrency, 'requests': len(results),
                     'status_counts': dict(Counter(str(code) for code, _ in results)),
                     'errors': sum(code != 200 for code, _ in results),
                     'elapsed_seconds': round(elapsed, 3), 'requests_per_second': round(len(results) / elapsed, 2),
                     'p50_ms': round(latencies[math.ceil(len(latencies) * .50) - 1], 2),
                     'p95_ms': round(latencies[math.ceil(len(latencies) * .95) - 1], 2),
                     'p99_ms': round(latencies[math.ceil(len(latencies) * .99) - 1], 2)}
            report['stages'].append(stage)
    report['status'] = 'FAIL' if any(s['errors'] for s in report['stages']) else 'PASS_SCOPED'
    (evidence / 'capacity.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return report['status'] != 'PASS_SCOPED'


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2]))))
