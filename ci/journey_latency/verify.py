"""Verify raw persistent-worker evidence before accepting any comparison round."""
from pathlib import Path
import hashlib
import json
import math
import sys

sys.path.insert(0, str(Path(__file__).parent))
from measure import summarize


def read(path):
    return json.loads(path.read_text())


def verify_journey(folder, head, tree, expected_instances=2, expected_pool=5, *, collect_shortfalls=False):
    folder = Path(folder)
    manifest = read(folder / 'SHA256.json')
    assert manifest and all(hashlib.sha256((folder / p).read_bytes()).hexdigest() == digest
                            for p, digest in manifest.items()), 'JOURNEY_DIGEST'
    binding = read(folder / 'binding.json')
    result = read(folder / 'result.json')
    assert read(folder / 'exit.json')['exit_code'] == 0
    assert binding['head'] == head and binding['application_tree'] == tree
    assert binding['tiers'] == [20, 100] and binding['batches_per_operation'] == 4
    assert expected_instances in (2, 4) and expected_pool in (4, 5)
    assert binding['instances_per_operation'] == expected_instances
    assert binding['pool_per_instance'] == expected_pool and binding['max_overflow'] == 0
    assert binding['original_formal_p95_ms'] == 5000 and binding['original_formal_p99_ms'] == 10000
    assert result['status'] == 'MEASUREMENT_COMPLETE_NOT_CAPACITY_ACCEPTANCE'
    expected = {(n, op) for n in (20, 100) for op in
                ('create_order', 'payment_confirm', 'order_query', 'full_transaction')}
    assert len(result['operations']) == 8
    assert {(x['concurrency'], x['operation']) for x in result['operations']} == expected
    all_orders = set()
    metrics = []
    shortfalls = []
    for item in result['operations']:
        n, operation = item['concurrency'], item['operation']
        directory = folder / f'tier-{n}' / operation
        startups = read(directory / 'startups.json')
        pids = sorted(s['pid'] for s in startups)
        assert len(set(pids)) == expected_instances
        for s in startups:
            assert s['initial_pool_connections'] == s['initial_configured_mappers'] == 0
            assert s['ready_ns'] >= s['child_entry_ns'] >= s['launch_ns']
            assert math.isfinite(s['import_cpu_seconds']) and s['import_cpu_seconds'] > 0
        assert len(item['batches']) == 4
        for batch, summary in enumerate(item['batches']):
            rows = read(directory / f'batch-{batch}-raw.json')
            assert summary == read(directory / f'batch-{batch}-summary.json')
            assert len(rows) == n and len({r['owner'] for r in rows}) == n
            assert all(r['ok'] and r['batch'] == batch and r['operation'] == operation for r in rows)
            assert all(r['start_ns'] >= summary['release_ns'] for r in rows)
            assert all(math.isclose(r['duration_ms'], (r['end_ns']-r['start_ns'])/1e6) for r in rows)
            assert summarize(rows) == {key: summary[key] for key in summarize(rows)}
            assert summary['pids'] == pids and summary['requested_concurrency'] == n
            if summary['observed_peak_inflight'] != n:
                shortfalls.append({'concurrency': n, 'operation': operation, 'batch': batch,
                                   'observed_peak_inflight': summary['observed_peak_inflight']})
            assert summary['mode'] == ('PROCESS_COLD_FIRST_BATCH' if batch == 0 else 'CONTINUED_PROCESS')
            counters = [read(directory / f'worker-{i}/batch-{batch}.json') for i in range(expected_instances)]
            assert sorted(r['owner'] for c in counters for r in c['rows']) == sorted(r['owner'] for r in rows)
            assert summary['process_cpu_seconds'] == sum(c['process_cpu_seconds'] for c in counters)
            for field in ('process_cpu_seconds', 'p95_ms', 'p99_ms', 'max_worker_rss_kib'):
                assert math.isfinite(summary[field]) and summary[field] > 0
            if operation in ('create_order', 'full_transaction'):
                ids = {r['value']['order_id'] for r in rows}
                assert len(ids) == n and not ids.intersection(all_orders)
                all_orders.update(ids)
            metrics.append({'concurrency': n, 'operation': operation, **summary})
    facts = read(folder / 'tier-100/ledger-facts.json')
    assert len(all_orders) == len(facts) == 960
    assert {f['order_id'] for f in facts} == all_orders
    assert len(result['checks']) == 2 and all(c['sql'] == c['ownership_denial'] == 'PASS' for c in result['checks'])
    for f in facts:
        assert f['order_status'] == f['trips_state'] == 'COMPLETED'
        assert f['attempts'] == 1 and f['ledger_entries'] == 2
        assert f['capture_amount_minor'] == f['ledger_debit_minor'] == f['ledger_credit_minor'] == 16800
    if not collect_shortfalls:
        assert not shortfalls, 'JOURNEY_CONCURRENCY_SHORTFALL'
    return {'concurrency_valid': not shortfalls, 'concurrency_shortfalls': shortfalls, 'metrics': metrics, 'schema': binding['schema'], 'head': head, 'application_tree': tree,
            'orders_verified': len(facts), 'environment': {k: binding[k] for k in
            ('cpu_count', 'cpu_model', 'python', 'platform', 'packages', 'postgresql')},
            'scope': 'Cold batch plus three continued bursts; not sustained capacity or HTTP latency'}
