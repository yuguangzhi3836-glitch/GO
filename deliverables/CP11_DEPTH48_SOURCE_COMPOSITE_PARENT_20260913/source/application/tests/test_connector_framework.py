import asyncio
import pytest
from go_hotel.connectors.mock_hotel import connector
from go_hotel.connectors.resilience import ResilientConnector, CircuitBreaker, CircuitConfig, ConnectorTimeout, CircuitOpen
from go_hotel.connectors.certification import harness

@pytest.mark.asyncio
async def test_connector_certification_passes_for_mock():
    report=await harness.certify(ResilientConnector(connector, timeout_seconds=1, retries=0))
    assert report.passed
    assert {x.name for x in report.checks} >= {"health","search","canonical_offer","prebook","book_idempotency","status"}

@pytest.mark.asyncio
async def test_timeout_and_circuit_breaker_open():
    connector.delay_seconds=.05
    wrapped=ResilientConnector(connector, timeout_seconds=.01, retries=0, circuit=CircuitBreaker(CircuitConfig(failure_threshold=2,recovery_seconds=10)))
    offers=await wrapped.search("TYO","2026-09-01","2026-09-02","CNY")
    pb=await wrapped.prebook(offers[0])
    with pytest.raises(ConnectorTimeout): await wrapped.book("o1",pb,idempotency_key="k1")
    with pytest.raises(ConnectorTimeout): await wrapped.book("o2",pb,idempotency_key="k2")
    with pytest.raises(CircuitOpen): await wrapped.status("x")
