"""Qualify measurement scope and normal-only calls without changing business code."""
import copy
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from measure import summarize
from operations import Operations


def test_tail_latency_includes_errors_and_observed_overlap():
    rows = [{'pid': i % 2, 'start_ns': i * 1_000_000,
             'end_ns': (i + i + 1) * 1_000_000, 'ok': i < 99} for i in range(100)]
    stats = summarize(rows)
    assert stats['requests'] == 100 and stats['errors'] == 1
    assert stats['p50_ms'] == 50 and stats['p95_ms'] == 95
    assert stats['p99_ms'] == 99 and stats['max_ms'] == 100
    assert stats['observed_peak_inflight'] == 50
    assert stats['successful_per_second_in_burst'] == pytest.approx(99 / .199)


@pytest.mark.parametrize('rows', [[], [{'start_ns': 2, 'end_ns': 1}]])
def test_invalid_timing_is_rejected(rows):
    with pytest.raises(AssertionError, match='INVALID_TIMING'):
        summarize(rows)


def fixture_operations():
    operations = Operations.__new__(Operations)
    calls = []
    def book(body, principal, key):
        calls.append(('book', principal.user_id, key, body))
        return {'data': {'order_id': 'order-1', 'status': 'PAYMENT_PENDING',
                         'total_amount_minor': 16800, 'currency': 'CNY'}}
    def pay(*args):
        calls.append(('pay', args))
        return {'state': 'PAYMENT_CONFIRMED_AWAITING_SUPPLIER', 'capture_id': 'cap-1',
                'supplier_fulfillment_id': 'fill-1'}
    def query(oid, principal):
        calls.append(('query', oid, principal.user_id))
        return {'data': {'order_id': oid, 'status': 'COMPLETED',
                         'total_amount_minor': 16800, 'currency': 'CNY'}}
    operations.book = book; operations.body_type = lambda **kw: kw
    operations.bridge = SimpleNamespace(checkout_contract=pay); operations.query = query
    return operations, calls


def test_each_normal_operation_calls_existing_entry_once_and_keeps_owner():
    operations, calls = fixture_operations()
    task = {'owner': 'owner-1', 'body': {'passengers': [{'full_name': 'synthetic'}]}, 'key': 'key-1'}
    before = copy.deepcopy(task)
    created = operations.execute('create_order', task)
    assert task == before
    paid = operations.execute('payment_confirm', created)
    read = operations.execute('order_query', paid)
    assert [c[0] for c in calls] == ['book', 'pay', 'query']
    assert calls[0][1:3] == ('owner-1', 'key-1')
    assert calls[1][1][:3] == ('RIDE', 'order-1', 'owner-1')
    assert calls[2] == ('query', 'order-1', 'owner-1')
    assert read['state'] == 'COMPLETED'


def test_operation_exception_is_not_retried_or_hidden():
    operations, calls = fixture_operations()
    def rejected(*args):
        calls.append('attempt')
        raise ValueError('BUSINESS_REJECTION')
    operations.query = rejected
    with pytest.raises(ValueError, match='BUSINESS_REJECTION'):
        operations.execute('order_query', {'owner': 'owner', 'order_id': 'order'})
    assert calls == ['attempt']


@pytest.mark.parametrize('operation', ['create_order', 'payment_confirm', 'order_query'])
def test_incomplete_business_result_cannot_count_as_success(operation):
    operations, _ = fixture_operations()
    operations.book = lambda *a: {'data': {'status': 'UNKNOWN'}}
    operations.bridge.checkout_contract = lambda *a: {'state': 'PENDING'}
    operations.query = lambda *a: {'data': {'order_id': 'order', 'status': 'UNKNOWN'}}
    with pytest.raises(AssertionError):
        operations.execute(operation, {'owner': 'owner', 'order_id': 'order', 'body': {}, 'key': 'key'})


def test_full_transaction_uses_original_actor_once(monkeypatch):
    operations, _ = fixture_operations()
    calls = []
    def transaction(index):
        calls.append(index)
        return {'outcome': 'SUCCESS', 'owner': 'mi-load-abc', 'order_id': 'one'}
    monkeypatch.setitem(sys.modules, 'ride_workload', SimpleNamespace(transaction=transaction))
    assert operations.execute('full_transaction', {'owner': 'mi-load-abc', 'index': 'abc'})['order_id'] == 'one'
    assert calls == ['abc']
    with pytest.raises(AssertionError):
        operations.execute('full_transaction', {'owner': 'wrong', 'index': 'abc'})


def test_shared_release_admits_both_workers_only_after_coordinator(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import time
    from measure import synchronized_batch, wait
    calls = []
    lock = threading.Lock()
    release = tmp_path / 'shared.start'
    def invoke(task):
        with lock:
            calls.append((task, time.monotonic_ns()))
        return task
    def worker(i):
        with ThreadPoolExecutor(max_workers=10) as pool:
            return synchronized_batch(pool, list(range(i * 10, i * 10 + 10)), invoke,
                                      tmp_path / f'{i}.ready', release)
    with ThreadPoolExecutor(max_workers=2) as coordinators:
        jobs = [coordinators.submit(worker, i) for i in range(2)]
        for i in range(2):
            wait(tmp_path / f'{i}.ready', timeout=5)
        assert calls == []
        released_ns = time.monotonic_ns()
        release.touch()
        assert sorted(x for job in jobs for x in job.result(timeout=5)) == list(range(20))
    assert len(calls) == 20 and all(t >= released_ns for _, t in calls)


def test_failed_release_never_calls_application(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import measure
    calls = []
    def timeout(*args):
        raise TimeoutError('injected coordinator loss')
    monkeypatch.setattr(measure, 'wait', timeout)
    with ThreadPoolExecutor(max_workers=2) as pool:
        with pytest.raises(TimeoutError):
            measure.synchronized_batch(pool, [1, 2], calls.append,
                                       tmp_path / 'ready', tmp_path / 'start')
    assert calls == []
