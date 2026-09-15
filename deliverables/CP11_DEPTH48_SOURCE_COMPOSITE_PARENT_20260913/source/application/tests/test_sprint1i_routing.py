from datetime import datetime, timezone
import pytest
from go_hotel.connectors.base import ConnectorMetadata, ConnectorCapabilities
from go_hotel.connectors.registry import registry
from go_hotel.domain.models import Offer, Prebook, new_id
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import SupplierConnectorOnboardingRow
from go_hotel.routing.router import traffic_router, rollout_bucket
from go_hotel.routing.sla import sla_service
from go_hotel.routing.failover import execute_safe_failover, FailoverBlocked

class AltConnector:
    metadata=ConnectorMetadata(connector_id="conn_alt",display_name="Alt",version="1",capabilities=ConnectorCapabilities())
    async def search(self,city_code,check_in,check_out,currency):
        if city_code!="TYO": return []
        return [Offer(new_id("off"),"htl_conrad_tokyo","room_bay_king","rate_alt",1_200_000,currency,check_in,check_out,official_direct=False,connector_id="conn_alt")]
    async def prebook(self,offer): return Prebook(new_id("pb"),offer.offer_id,offer.total_amount_minor,offer.currency)
    async def book(self,order_id,prebook,idempotency_key=None): return "ALT-1"
    async def status(self,confirmation_no): return "CONFIRMED"
    async def cancel(self,confirmation_no): return "CANCELLED"
    async def health(self): return {"status":"UP"}

try: registry.register(AltConnector())
except Exception: pass

def activate(connector_id,pct=100,supplier="sup_test"):
    now=datetime.now(timezone.utc)
    with SessionLocal.begin() as s:
        s.add(SupplierConnectorOnboardingRow(onboarding_id=new_id("onb"),supplier_id=supplier+connector_id,connector_id=connector_id,environment="SANDBOX",status="ACTIVE",rollout_percent=pct,created_at=now,updated_at=now,activated_at=now))

def test_official_authorization_outranks_cheaper_nonofficial():
    activate("conn_mock_hotel"); activate("conn_alt")
    sla_service.upsert_snapshot("conn_mock_hotel",success_rate_bps=9500,confirmation_latency_ms_p95=800,cancel_success_rate_bps=9500,inventory_accuracy_bps=9500,price_consistency_bps=9500,sample_size=100)
    sla_service.upsert_snapshot("conn_alt",success_rate_bps=10000,confirmation_latency_ms_p95=100,cancel_success_rate_bps=10000,inventory_accuracy_bps=10000,price_consistency_bps=10000,sample_size=100)
    import asyncio
    candidates,decision=asyncio.run(traffic_router.search(request_key="r1",city_code="TYO",check_in="2026-09-01",check_out="2026-09-05",currency="CNY"))
    assert candidates[0].connector_id=="conn_mock_hotel"
    assert candidates[0].offer.total_amount_minor > candidates[1].offer.total_amount_minor
    assert decision.reason_codes[0]=="OFFICIAL_AUTHORIZATION_PRIORITY"

def test_unhealthy_connector_removed_from_route():
    activate("conn_mock_hotel"); activate("conn_alt")
    sla_service.upsert_snapshot("conn_alt",success_rate_bps=1000,confirmation_latency_ms_p95=10000,cancel_success_rate_bps=1000,inventory_accuracy_bps=1000,price_consistency_bps=1000,sample_size=100)
    import asyncio
    candidates,_=asyncio.run(traffic_router.search(request_key="r2",city_code="TYO",check_in="2026-09-01",check_out="2026-09-05",currency="CNY"))
    assert all(c.connector_id!="conn_alt" for c in candidates)

def test_canary_bucket_is_deterministic():
    assert rollout_bucket("acct:search:1","conn_alt") == rollout_bucket("acct:search:1","conn_alt")
    assert 1 <= rollout_bucket("acct:search:1","conn_alt") <= 100

@pytest.mark.asyncio
async def test_search_failover_allowed_and_book_failover_blocked():
    calls=[]
    async def search_call(cid):
        calls.append(cid)
        if cid=="a": raise RuntimeError("down")
        return "ok"
    result,cid=await execute_safe_failover("SEARCH",["a","b"],search_call)
    assert (result,cid)==("ok","b")
    async def book_call(cid):
        raise TimeoutError("ambiguous")
    with pytest.raises(FailoverBlocked):
        await execute_safe_failover("BOOK",["a","b"],book_call)

def test_sla_api(client):
    r=client.put("/internal/v1/routing/sla/conn_mock_hotel",json={"success_rate_bps":9900,"confirmation_latency_ms_p95":700,"cancel_success_rate_bps":9800,"inventory_accuracy_bps":9700,"price_consistency_bps":9900,"sample_size":55})
    assert r.status_code==200
    d=r.json()["data"]
    assert d["composite_score_bps"]>9000
    assert d["health_status"]=="HEALTHY"
