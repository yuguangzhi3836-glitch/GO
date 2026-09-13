"""Regression checks for shared request-loop blocking and bounded telemetry."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread, get_ident
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from go_hotel.observability.metrics import MetricsRegistry

pytestmark = pytest.mark.no_db


def test_histogram_storage_is_bounded_and_totals_are_not_truncated():
    registry = MetricsRegistry()
    for value in range(10000):
        registry.observe('latency', value, method='POST')
    retained = registry.histogram_values('latency', method='POST')
    assert len(retained) <= 4096
    assert retained[-1] == 9999
    output = registry.prometheus()
    assert 'latency_count{method="POST"} 10000' in output
    assert 'latency_sum{method="POST"} 49995000.0' in output
    assert 'most recent' in output


def test_counter_lookup_does_not_copy_unrelated_histograms(monkeypatch):
    registry = MetricsRegistry()
    registry.inc('requests', 7)
    registry.observe('latency', 2)
    def forbidden_snapshot():
        raise AssertionError('counter lookup copied the entire registry')
    monkeypatch.setattr(registry, 'snapshot', forbidden_snapshot)
    assert registry.counter_value('requests') == 7
    assert registry.counter_value('missing') == 0


def test_histogram_totals_survive_concurrent_recording():
    registry = MetricsRegistry()
    def observe_batch(_):
        for _ in range(2000):
            registry.observe('latency', 1, kind='hotel')
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(observe_batch, range(8)))
    assert len(registry.histogram_values('latency', kind='hotel')) <= 4096
    output = registry.prometheus()
    assert 'latency_count{kind="hotel"} 16000' in output
    assert 'latency_sum{kind="hotel"} 16000.0' in output


@pytest.fixture
def runtime(monkeypatch):
    import go_hotel.main as module
    monkeypatch.setattr(module, 'metrics', MetricsRegistry())
    return module


def probe_app(middleware, *, status=200, principal=None):
    app = FastAPI()
    app.add_middleware(middleware)
    @app.get('/health')
    async def health():
        return {'status': 'ok'}
    @app.post('/v1/orders/probe')
    async def write(request: Request):
        request.state.principal = principal
        return JSONResponse({'executed': True}, status_code=status)
    return app


@pytest.mark.asyncio
async def test_incident_database_wait_does_not_block_health(runtime, monkeypatch):
    entered, release, healthy = Event(), Event(), Event()
    state = {}
    loop_thread = get_ident()
    def active(scope):
        state['worker_thread'] = get_ident()
        entered.set()
        assert release.wait(5), 'watchdog did not release the database probe'
        return False
    def watchdog():
        entered.wait(5)
        state['health_while_database_waiting'] = healthy.wait(2)
        release.set()
    monkeypatch.setattr(runtime.incident_service, 'active', active)
    watcher = Thread(target=watchdog, daemon=True)
    watcher.start()
    app = probe_app(runtime.Sprint1VObservabilityMiddleware)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            write = asyncio.create_task(client.post('/v1/orders/probe'))
            await asyncio.to_thread(entered.wait, 5)
            health = await client.get('/health')
            healthy.set()
            assert health.status_code == 200
            assert (await write).status_code == 200
    finally:
        release.set()
        watcher.join(timeout=5)
    assert state['worker_thread'] != loop_thread
    assert state['health_while_database_waiting'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('blocked', ['GLOBAL_WRITES', 'BOOKING_WRITES'])
async def test_incident_controls_still_deny_writes_with_correlated_metrics(runtime, monkeypatch, blocked):
    monkeypatch.setattr(runtime.incident_service, 'active', lambda scope: scope == blocked)
    app = probe_app(runtime.Sprint1VObservabilityMiddleware)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/v1/orders/probe', headers={'X-Request-ID': 'capacity-denied'})
        assert response.status_code == 503
        assert response.json()['detail'] == 'INCIDENT_CONTROL_ACTIVE'
        assert response.headers['X-Request-ID'] == 'capacity-denied'
        assert runtime.metrics.counter_value('go_http_status_total', status=503) == 1
        assert runtime.metrics.counter_value('go_http_requests_5xx_total') == 1
        assert (await client.get('/health')).status_code == 200


@pytest.mark.asyncio
async def test_incident_lookup_failure_does_not_allow_a_write(runtime, monkeypatch):
    def unavailable(scope):
        raise RuntimeError('isolated database unavailable')
    monkeypatch.setattr(runtime.incident_service, 'active', unavailable)
    app = probe_app(runtime.Sprint1VObservabilityMiddleware)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        with pytest.raises(RuntimeError, match='isolated database unavailable'):
            await client.post('/v1/orders/probe')
        assert (await client.get('/health')).status_code == 200


@pytest.mark.asyncio
async def test_audit_commit_is_awaited_off_the_event_loop(runtime, monkeypatch):
    calls = []
    loop_thread = get_ident()
    monkeypatch.setattr(runtime.audit_service, 'append', lambda *a, **kw: calls.append((get_ident(), kw)))
    app = probe_app(runtime.Sprint1RAuditMiddleware, principal=SimpleNamespace(user_id='test-user'))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/v1/orders/probe', headers={'X-Request-ID': 'capacity-audit'})
    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0][0] != loop_thread
    assert calls[0][1]['request_id'] == 'capacity-audit'


@pytest.mark.asyncio
async def test_security_signal_is_awaited_off_the_event_loop(runtime, monkeypatch):
    calls = []
    loop_thread = get_ident()
    monkeypatch.setattr(runtime.incident_service, 'active', lambda scope: False)
    monkeypatch.setattr(runtime.incident_service, 'record_security_signal', lambda *a, **kw: calls.append(get_ident()))
    app = probe_app(runtime.Sprint1VObservabilityMiddleware, status=403)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.post('/v1/orders/probe')).status_code == 403
    assert calls and calls[0] != loop_thread


@pytest.mark.asyncio
@pytest.mark.parametrize('valid_csrf', [True, False])
async def test_cookie_authentication_and_csrf_still_complete_before_write(runtime, monkeypatch, valid_csrf):
    calls = []
    loop_thread = get_ident()
    def authenticate(token):
        calls.append(('authenticate', get_ident()))
        return SimpleNamespace(session_id='test-session')
    def verify(session_id, token):
        calls.append(('csrf', get_ident()))
        return valid_csrf
    monkeypatch.setattr(runtime.identity_service, 'authenticate', authenticate)
    monkeypatch.setattr(runtime.identity_service, 'verify_csrf', verify)
    app = probe_app(runtime.Sprint1USecurityMiddleware)
    cookies = {runtime.settings.access_cookie_name: 'isolated-test-token', runtime.settings.csrf_cookie_name: 'isolated-csrf'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', cookies=cookies) as client:
        response = await client.post('/v1/orders/probe', headers={runtime.settings.csrf_header_name: 'isolated-csrf'})
    assert response.status_code == (200 if valid_csrf else 403)
    if not valid_csrf:
        assert response.json()['detail'] == 'CSRF_SESSION_MISMATCH'
    assert [name for name, _ in calls] == ['authenticate', 'csrf']
    assert all(thread != loop_thread for _, thread in calls)
