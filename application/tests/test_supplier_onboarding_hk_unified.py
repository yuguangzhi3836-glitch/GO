import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from go_hotel.db.models import (
    HotelCanonicalProfileRow, HotelRegistrationDirectRow,
    HotelPartnerPropertyRow, RegistrationDecisionRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services.supplier_onboarding_state import supplier_onboarding_state_service
from test_registration_verification import send, delivery


def csrf(client):
    return {"X-CSRF-Token": client.cookies.get("go_csrf")}


def register_supplier(client, delivery, email="new-hotel@example.test"):
    body=send(client,delivery,"supplier",email)
    response=client.post("/bff/auth/supplier/register",json=body)
    assert response.status_code==201,response.text
    return response.json()["data"],body


def complete_profile():
    return {
        "hotel_name":"测试酒店",
        "organization_name":"测试酒店管理有限公司",
        "contact_name":"测试联系人",
        "phone":"13800000000",
        "province":"黑龙江省",
        "city":"哈尔滨市",
        "street_address":"测试街道 1 号",
        "business_license_ref":"upload://business-license/1",
        "legal_representative_name":"测试法人",
        "identity_document_ref":"upload://identity/1",
        "storefront_photo_ref":"upload://storefront/1",
    }


def test_supplier_account_is_created_before_hotel_and_deferred_authorizations(client,delivery):
    registration,body=register_supplier(client,delivery)
    supplier_id=registration["supplier_id"]
    assert registration["registration_state"]=="REGISTERED"
    assert registration["next_step"]=="COMPLETE_PROFILE"

    me=client.get("/bff/auth/me").json()["data"]
    assert me["onboarding"]["state"]=="REGISTERED"
    assert me["onboarding"]["business_ready"] is False

    with SessionLocal() as s:
        assert s.scalar(select(HotelPartnerPropertyRow).where(
            HotelPartnerPropertyRow.supplier_id==supplier_id)) is None
        receipt=s.scalar(select(RegistrationDecisionRow).where(
            RegistrationDecisionRow.user_id==me["user_id"]))
        assert receipt.decisions["privacy_policy"]=="NOTICE_ACKNOWLEDGED"
        assert receipt.decisions["data_processing_terms"]=="DEFERRED"
        assert receipt.decisions["electronic_signature_authorization"]=="DEFERRED"
        assert receipt.decisions["supplier_service_terms"]=="CONTRACT_ACCEPTED"
        assert receipt.decisions["platform_operating_rules"]=="CONTRACT_ACCEPTED"
        assert receipt.hashes==body["term_hashes"]

    blocked=client.get("/v1/supplier/dashboard")
    assert blocked.status_code==403
    assert blocked.json()["detail"]=="SUPPLIER_ONBOARDING_INCOMPLETE"


def test_supplier_onboarding_requires_existing_hotel_truth_and_contract(client,delivery):
    registration,_=register_supplier(client,delivery,"resume-hotel@example.test")
    supplier_id=registration["supplier_id"]

    saved=client.put("/bff/supplier/onboarding/profile",headers=csrf(client),json=complete_profile())
    assert saved.status_code==200,saved.text
    assert saved.json()["data"]["state"]=="PROFILE_DRAFT"

    submitted=client.post("/bff/supplier/onboarding/profile/submit",headers=csrf(client),json={})
    assert submitted.status_code==200,submitted.text
    assert submitted.json()["data"]["state"]=="UNDER_REVIEW"
    assert client.get("/v1/supplier/dashboard").status_code==403

    with pytest.raises(ValueError,match="APPROVED_HOTEL_REGISTRATION_REQUIRED"):
        supplier_onboarding_state_service.decide_profile(
            supplier_id,"admin-test","APPROVE","不能自证认证通过")
    assert client.get("/bff/auth/me").json()["data"]["onboarding"]["state"]=="UNDER_REVIEW"

    with SessionLocal.begin() as s:
        now=datetime.now(timezone.utc)
        s.add(HotelCanonicalProfileRow(
            hotel_id="hotel_test",slug="hotel-test",
            canonical_json={"name":"测试酒店","address":"测试街道 1 号"},
            field_provenance_json={},source_snapshot_ids_json=[],completeness_bps=0,
            go_direct_state="GO_DIRECT_VERIFIED",page_state="DRAFT",version=1,
            created_at=now,updated_at=now,
        ))
        s.add(HotelRegistrationDirectRow(
            hotel_registration_direct_id="hregdir_test",hotel_id="hotel_test",
            supplier_id=supplier_id,state="APPROVED",
            evidence_json=[{"reference":"upload://business-license/1"}],
            official_supplement_json={"name":"测试酒店"},
            requested_by=client.get("/bff/auth/me").json()["data"]["user_id"],
            reviewed_by="admin-test",created_at=now,reviewed_at=now,
        ))

    verified=supplier_onboarding_state_service.decide_profile(
        supplier_id,"admin-test","APPROVE","主体资料通过","hregdir_test")
    assert verified["state"]=="VERIFIED"
    assert verified["hotel_id"]=="hotel_test"
    assert client.get("/v1/supplier/dashboard").status_code==403

    contract=client.post("/bff/supplier/onboarding/contract",headers=csrf(client),
        json={"contract_ref":"upload://signed-contract/1","contract_version":"standard-v1"})
    assert contract.status_code==200,contract.text
    assert contract.json()["data"]["state"]=="CONTRACT_UNDER_REVIEW"
    assert client.get("/v1/supplier/dashboard").status_code==403

    active=supplier_onboarding_state_service.decide_contract(
        supplier_id,"admin-test","APPROVE","合同通过")
    assert active["state"]=="CONTRACT_ACTIVE"
    assert active["business_ready"] is True
    assert client.get("/v1/supplier/dashboard").status_code==200
