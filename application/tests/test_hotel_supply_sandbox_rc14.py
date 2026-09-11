import pytest

from go_hotel.services.hotel_supply_sandbox import hotel_supply_sandbox_certification_service as svc


def register():
    return svc.register({
        "connector_key": "rc14-hotel-sandbox",
        "display_name": "RC14 Hotel Sandbox",
        "supplier_legal_name": "Named Hotel Supplier",
        "sandbox_endpoint": "https://sandbox.hotel.example.invalid/api",
        "test_hotel_reference": "supplier-hotel-001",
        "ip_allowlist_reference": "allowlist://hk-staging/rc14",
        "documentation_reference": "docs://supplier/hotel/v1",
        "documentation_version": "v1",
        "auth_method": "API_KEY_HEADER",
        "webhook_reference": "https://staging-api.goaidirect.com/internal/webhooks/hotel",
    }, "admin")


def prepare():
    r = register(); cid = r["connector"]["connector_id"]
    svc.bind_authority(cid, {"contract_reference":"contract://sandbox/1","authority_reference":"authority://sandbox/1","evidence_reference":"evidence://approved"}, "admin")
    svc.bind_credential(cid, {"secret_reference":"vault://hotel/sandbox/named-supplier","credential_kind":"API_KEY"}, "security")
    svc.set_mapping(cid, {"mapping":{
        "supplier_property_id":"supplier-hotel-001","go_hotel_id":"go-hotel-001",
        "rooms":[{"supplier_room_id":"room-a","go_room_id":"go-room-a","rate_plans":[{"supplier_rate_plan_id":"rate-a","go_rate_plan_id":"go-rate-a"}]}]
    }}, "admin")
    return cid


def test_inline_secret_is_forbidden():
    r=register(); cid=r["connector"]["connector_id"]
    with pytest.raises(ValueError, match="INLINE_SECRET_FORBIDDEN"):
        svc.bind_credential(cid, {"secret_reference":"vault://hotel/sandbox/key","password":"plain"}, "security")


def test_readiness_without_external_transport_is_explicit():
    cid=prepare(); r=svc.readiness(cid)
    assert r["state"] == "READY_NOT_EXTERNALLY_VERIFIED"
    assert r["externally_verified"] is False
    assert r["payment_connected"] is False
    assert r["production_live"] is False


def test_framework_certification_cannot_claim_external_connection():
    cid=prepare(); r=svc.framework_certify(cid, {}, "admin")
    assert r["certification"]["result"] == "PASS"
    assert r["decision"] == "READY_NOT_EXTERNALLY_VERIFIED"
    assert r["real_supplier_connected"] is False


def test_external_certification_blocks_without_provider_executor():
    cid=prepare()
    with pytest.raises(ValueError, match="HOTEL_SUPPLY_SANDBOX_EXECUTOR_NOT_CONFIGURED"):
        svc.external_certify(cid, {"idempotency_key":"rc14-external-1"}, "admin")


def test_mapping_requires_room_and_rate_plan():
    r=register(); cid=r["connector"]["connector_id"]
    with pytest.raises(ValueError, match="RATE_PLAN_MAPPING_REQUIRED"):
        svc.set_mapping(cid, {"mapping":{"supplier_property_id":"p","go_hotel_id":"g","rooms":[{"supplier_room_id":"r","go_room_id":"gr","rate_plans":[]}]}}, "admin")
