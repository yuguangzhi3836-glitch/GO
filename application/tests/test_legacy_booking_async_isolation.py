"""Actual booking routes/dependencies must let unrelated ASGI work progress."""
import asyncio
import threading
from types import SimpleNamespace
import httpx
import pytest
from fastapi import FastAPI, HTTPException, Depends
from go_hotel.api.routes import booking
from go_hotel.security import deps
from go_hotel.services.booking import booking_service

pytestmark = [pytest.mark.no_db, pytest.mark.asyncio]


class BlockedCall:
    def __init__(self, value=None, error=None):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.progress = threading.Event()
        self.value, self.error = value, error
        self.worker_thread = None

    def __call__(self, *args, **kwargs):
        self.worker_thread = threading.get_ident()
        self.entered.set()
        if not self.release.wait(3):
            raise AssertionError('WATCHDOG_FAILED')
        if self.error: raise self.error
        return self.value

    def watchdog(self):
        self.entered.wait(3)
        self.progress.wait(.5)
        self.release.set()


async def assert_responsive(app, blocker, method, url, **kwargs):
    @app.get('/probe-health')
    async def health(): return {'ok': True}
    watchdog = threading.Thread(target=blocker.watchdog)
    watchdog.start()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            task = asyncio.create_task(client.request(method, url, **kwargs))
            while not blocker.entered.is_set():
                if task.done(): raise AssertionError(f'BLOCKER_NOT_REACHED: {(await task).status_code}')
                await asyncio.sleep(.001)
            health = await client.get('/probe-health')
            progressed_before_release = not blocker.release.is_set()
            blocker.progress.set()
            blocker.release.set()
            response = await task
            assert health.status_code == 200 and progressed_before_release, 'EVENT_LOOP_BLOCKED_BY_DATABASE'
            assert blocker.worker_thread != threading.get_ident(), 'DATABASE_RAN_ON_EVENT_LOOP'
            return response
    finally:
        blocker.release.set()
        watchdog.join(4)


def probe_app(override_access=True):
    app = FastAPI()
    app.include_router(booking.router)
    if override_access: app.dependency_overrides[deps.legacy_order_access] = lambda: None
    return app


@pytest.mark.parametrize('url,target,value', [
    ('/v1/orders/o1', 'get_order', SimpleNamespace(order_id='o1', hotel_id='h1', status='CONFIRMED',
          total_amount_minor=100, currency='CNY', supplier_confirmation_no='s1')),
    ('/internal/v1/orders/o1/events', 'event_dicts', []),
    ('/internal/v1/orders/o1/payment-orchestration', 'orchestration_for_order', {'phase': 'COMPLETED'}),
])
async def test_sync_booking_reads_release_event_loop(monkeypatch, url, target, value):
    blocker = BlockedCall(value)
    monkeypatch.setattr(booking.repo, target, blocker)
    response = await assert_responsive(probe_app(), blocker, 'GET', url)
    assert response.status_code == 200


@pytest.mark.parametrize('target', ['authentication', 'ownership', 'credit'])
async def test_real_legacy_dependency_releases_event_loop(monkeypatch, target):
    principal = SimpleNamespace(user_id='owner', actor_type='CONSUMER')
    monkeypatch.setattr(deps.identity_service, 'authenticate', lambda *a, **k: principal)
    monkeypatch.setattr(deps, 'assert_consumer_order', lambda *a: None)
    blocker = BlockedCall(principal if target == 'authentication' else None)
    if target == 'authentication': monkeypatch.setattr(deps.identity_service, 'authenticate', blocker)
    elif target == 'ownership': monkeypatch.setattr(deps, 'assert_consumer_order', blocker)
    class Session:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get(self, *a):
            return blocker() if target == 'credit' else SimpleNamespace(account_id='owner')
    if target == 'credit': blocker.value = SimpleNamespace(account_id='owner')
    monkeypatch.setattr(deps, 'SessionLocal', Session)
    app = FastAPI()
    @app.get('/guard/{order_id}/{credit_id}')
    async def guarded(p=Depends(deps.legacy_order_access)): return {'owner': p.user_id}
    response = await assert_responsive(app, blocker, 'GET', '/guard/o1/c1', headers={'Authorization':'Bearer test'})
    assert response.status_code == 200


@pytest.mark.parametrize('method,args,target', [
    ('create_order', ('pb1', 'owner'), 'get_prebook'),
    ('pay', ('o1', 100, 'CNY', 'pm'), 'get_order'),
    ('confirm', ('o1',), 'get_order'),
    ('prebook', ('offer1',), 'get_offer'),
    ('recover_authorization', ({'result_payload': {'payment_id':'p','amount_minor':100,'currency':'CNY'},
                               'aggregate_id':'o1','operation_id':'op'},), 'commit_authorization_saga'),
])
async def test_service_database_segments_release_event_loop(monkeypatch, method, args, target):
    blocker = BlockedCall(error=HTTPException(404, 'controlled-missing'))
    monkeypatch.setattr(booking.repo, target, blocker)
    app = FastAPI()
    @app.get('/service')
    async def service(): return await getattr(booking_service, method)(*args)
    response = await assert_responsive(app, blocker, 'GET', '/service')
    assert response.status_code == 404


@pytest.mark.parametrize('actor,account,env,status,detail', [
    ('CONSUMER','owner','production',409,'USE_VAULT_BACKED_CONSUMER_ORDER_ENTRY'),
    ('CONSUMER','other','production',403,'ORDER_ACCOUNT_MISMATCH'),
    ('GO_ADMIN','owner','production',403,'CONSUMER_IDENTITY_REQUIRED'),
])
async def test_access_error_order_and_production_creation_deny(monkeypatch, actor, account, env, status, detail):
    monkeypatch.setattr(deps.settings, 'app_env', env)
    monkeypatch.setattr(deps.identity_service, 'authenticate', lambda *a, **k: SimpleNamespace(user_id='owner',actor_type=actor))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=probe_app(False)), base_url='http://test') as client:
        response = await client.post('/v1/orders', headers={'Authorization':'Bearer test'}, json={'prebook_id':'p','account_id':account})
    assert response.status_code == status and response.json()['detail'] == detail


@pytest.mark.parametrize('operation,blocked_method', [
    ('create', 'get_idempotency'), ('create', 'save_idempotency'),
    ('payment', 'get_idempotency'), ('payment', 'save_idempotency'),
])
async def test_route_idempotency_io_releases_event_loop(monkeypatch, operation, blocked_method):
    order = SimpleNamespace(order_id='o1', status='PAYMENT_PENDING', total_amount_minor=100, currency='CNY')
    payment = SimpleNamespace(payment_id='p1', status='AUTHORIZED', amount_minor=100, currency='CNY')
    async def create(*a, **k): return order
    async def pay(*a, **k): return payment
    monkeypatch.setattr(booking_service, 'create_order', create)
    monkeypatch.setattr(booking_service, 'pay', pay)
    monkeypatch.setattr(booking.repo, 'get_idempotency', lambda *a: None)
    monkeypatch.setattr(booking.repo, 'save_idempotency', lambda *a: None)
    blocker = BlockedCall()
    monkeypatch.setattr(booking.repo, blocked_method, blocker)
    url, body = ('/v1/orders', {'prebook_id':'pb1', 'account_id':'owner'}) if operation == 'create' else (
        '/v1/orders/o1/payments', {'payment_method_token':'pm', 'amount_minor':100, 'currency':'CNY'})
    response = await assert_responsive(probe_app(), blocker, 'POST', url, json=body, headers={'Idempotency-Key':'same-key'})
    assert response.status_code == 200


async def test_post_provider_commit_releases_loop_and_provider_stays_on_loop(monkeypatch):
    from go_hotel.domain.models import Payment, PaymentStatus
    from go_hotel.services.booking import payment_provider
    caller = threading.get_ident()
    payment = Payment('p1', 'o1', 100, 'CNY', PaymentStatus.AUTHORIZED)
    monkeypatch.setattr(booking_service, '_prepare_payment', lambda *a: (None, {'operation_id':'op1'}))
    async def authorize(*a, **k):
        assert threading.get_ident() == caller
        await asyncio.sleep(0)
        return payment
    monkeypatch.setattr(payment_provider, 'authorize', authorize)
    blocker = BlockedCall()
    monkeypatch.setattr(booking.repo, 'mark_external_success', blocker)
    commits = []
    monkeypatch.setattr(booking.repo, 'commit_authorization_saga', lambda *a: commits.append(threading.get_ident()))
    app = FastAPI()
    @app.get('/pay')
    async def pay():
        result = await booking_service.pay('o1', 100, 'CNY', 'pm')
        return {'status': result.status}
    response = await assert_responsive(app, blocker, 'GET', '/pay')
    assert response.status_code == 200 and commits == [blocker.worker_thread]
