import os
os.environ.setdefault("DATABASE_URL","sqlite+pysqlite:///:memory:")

def test_cost_governor_never_defaults_to_external(monkeypatch):
    from go_hotel.travel_intelligence.cost_governor import model_cost_governor
    d=model_cost_governor.route(capability="QUERY_REWRITE",complexity=0.1,privacy_class="INTERNAL",local_capability_available=True)
    assert d.tier==0 and d.external_egress is False

def test_sensitive_external_is_fail_closed(monkeypatch):
    from go_hotel.travel_intelligence.cost_governor import model_cost_governor
    import pytest
    with pytest.raises(ValueError,match="MODEL_GATEWAY_EXTERNAL_EGRESS_DENIED"):
        model_cost_governor.route(capability="TRAVEL_REASONING",complexity=1.0,privacy_class="SENSITIVE",local_capability_available=False,self_hosted_available=False,explicit_external_policy=False)

def test_event_contract_registry_matches_freeze():
    from go_hotel.travel_intelligence.contracts import EVENT_TYPES
    assert "PAYMENT_CONFIRMED" in EVENT_TYPES and "SUPPLIER_CONFIRMED" in EVENT_TYPES and "REFUND_COMPLETED" in EVENT_TYPES

def test_transaction_projection_domains_are_authoritative_sources_only():
    from go_hotel.travel_intelligence.contracts import TRANSACTION_TRUTH_DOMAINS
    assert TRANSACTION_TRUTH_DOMAINS=={"ORDER","PAYMENT_LEDGER","SUPPLIER_FULFILLMENT","REFUND","TRIP"}
