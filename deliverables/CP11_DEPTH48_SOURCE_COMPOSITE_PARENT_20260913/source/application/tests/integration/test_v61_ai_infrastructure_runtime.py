import pytest
from httpx import ASGITransport, AsyncClient
from go_hotel.main import app
from go_hotel.db.models import Base
from go_hotel.db.session import engine

Base.metadata.create_all(engine)

pytestmark = [pytest.mark.integration, pytest.mark.no_db, pytest.mark.asyncio]


async def _request(method: str, path: str, **kwargs):
    # These V6.1 contract endpoints are deliberately stateless. ASGITransport avoids
    # spawning/tearing down a TestClient portal thread for every contract assertion.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.request(method, path, **kwargs)


async def test_manifest_exposes_ai_agent_as_client_and_free_distribution():
    r = await _request('GET', '/v1/ai-infrastructure/manifest')
    assert r.status_code == 200
    j = r.json()
    assert 'AI_AGENT' in j['clients']
    assert j['production_truth'].startswith('CAPABILITY_CONTRACT')
    assert j['base_call_price_cny'] == 0
    assert j['paid_recommendation_ranking'] is False
    assert 'DOES_NOT_BUY_DISTRIBUTION' in j['distribution_principle']


async def test_identity_release_never_exports_full_vault():
    r = await _request('POST', '/v1/ai-infrastructure/identity-release-plan', json={
        'external_agent':'example-agent','consent_ref':'consent_1','purpose':'BOOKING',
        'requested_scopes':['traveler.name','traveler.contact']})
    assert r.status_code == 200
    j = r.json()
    assert j['full_vault_export'] is False
    assert j['release_mode'] == 'PURPOSE_BOUND_MINIMUM_NECESSARY'


async def test_booking_plan_requires_supplier_evidence():
    r = await _request('POST', '/v1/ai-infrastructure/booking-orchestration-plan', json={
        'external_agent':'example-agent','consent_ref':'consent_1','offer_ref':'offer_1'})
    assert r.status_code == 200
    assert r.json()['booking_success_may_only_follow_supplier_evidence'] is True
