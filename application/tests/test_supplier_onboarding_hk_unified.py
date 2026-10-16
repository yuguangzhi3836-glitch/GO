import hashlib
import io

import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from go_hotel.db.models import (
    AuditEventRow,
    HotelCanonicalProfileRow, HotelRegistrationDirectRow,
    HotelPartnerPropertyRow, RegistrationDecisionRow, CommercialCaseRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services.document_store import document_store
from go_hotel.services.onboarding_hotel import onboarding_hotel_service
from go_hotel.services.supplier_onboarding_state import supplier_onboarding_state_service
from test_registration_verification import send, delivery
from supplier_document_upload import upload_document


USCC = "91350100M000100Y43"
HOTEL_ID = "hotel_test"


@pytest.fixture(autouse=True)
def _private_volume(tmp_path, monkeypatch):
    """Uploaded evidence must never land in the repository working directory."""
    monkeypatch.setattr(document_store, "root", tmp_path / "supplier_documents")


def _licence_png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (240, 160), (30, 90, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


def _signed_pdf() -> bytes:
    """A real PDF, because the document store sniffs the leading bytes."""
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


def csrf(client):
    return {"X-CSRF-Token": client.cookies.get("go_csrf")}


def register_supplier(client, delivery, email="new-hotel@example.test"):
    body=send(client,delivery,"supplier",email)
    response=client.post("/bff/auth/supplier/register",json=body)
    assert response.status_code==201,response.text
    return response.json()["data"],body


def seed_canonical_hotel(go_direct_state="NOT_REGISTERED"):
    now=datetime.now(timezone.utc)
    with SessionLocal.begin() as s:
        s.add(HotelCanonicalProfileRow(
            hotel_id=HOTEL_ID,slug="hotel-test",
            canonical_json={"name":"测试酒店","address":{"city":"哈尔滨市","formatted":"哈尔滨市测试街道 1 号"}},
            field_provenance_json={},source_snapshot_ids_json=[],completeness_bps=0,
            go_direct_state=go_direct_state,page_state="DRAFT",version=1,
            created_at=now,updated_at=now,
        ))


def complete_draft(client):
    """Legal entity + stored licence + a hotel claim, via the product's own routes.

    The completion gate reads what the platform actually holds. Typed references
    (`business_license_ref` and friends) no longer satisfy it — that change is the
    whole point of D-03, so the fixture has to do the real thing.
    """
    saved=client.put("/bff/supplier/legal-entity",headers=csrf(client),json={
        "legal_name":"测试酒店管理有限公司","unified_social_credit_code":USCC,
        "legal_representative_name":"测试法人","registered_address":"黑龙江省哈尔滨市测试街道 1 号",
    })
    assert saved.status_code==200,saved.text
    uploaded=upload_document(client,_licence_png(),filename="licence.png",mime="image/png",
        headers=csrf(client),document_type="BUSINESS_LICENSE",scope="ENTITY")
    assert uploaded.status_code==201,uploaded.text
    claim=client.put("/bff/supplier/hotel/claim",headers=csrf(client),json={
        "mode":"EXISTING","relationship_type":"OWNER","hotel_id":HOTEL_ID})
    assert claim.status_code==200,claim.text


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
        onboarding=s.scalar(select(CommercialCaseRow).where(
            CommercialCaseRow.case_type=="SUPPLIER_ONBOARDING",
            CommercialCaseRow.supplier_id==supplier_id))
        assert onboarding is not None
        assert onboarding.state=="REGISTERED"
        assert onboarding.payload_json["profile"]=={}
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

    seed_canonical_hotel()
    complete_draft(client)

    submitted=client.post("/bff/supplier/onboarding/profile/submit",headers=csrf(client),json={})
    assert submitted.status_code==200,submitted.text
    assert submitted.json()["data"]["state"]=="UNDER_REVIEW"
    assert client.get("/v1/supplier/dashboard").status_code==403

    # A reviewer cannot grant the profile by assertion: without a real, approved
    # hotel registration behind the case, approval is refused.
    with pytest.raises(ValueError,match="APPROVED_HOTEL_REGISTRATION_REQUIRED"):
        supplier_onboarding_state_service.decide_profile(
            supplier_id,"admin-test","APPROVE","不能自证认证通过")
    assert client.get("/bff/auth/me").json()["data"]["onboarding"]["state"]=="UNDER_REVIEW"

    # Approving the claim is what creates the hotel truth: the relation, the GO
    # Direct state, and the case's own VERIFIED transition, in one transaction.
    verified=onboarding_hotel_service.approve_claim(supplier_id,"admin-test","主体资料通过")
    assert verified["state"]=="VERIFIED"
    assert verified["hotel_id"]==HOTEL_ID
    assert client.get("/v1/supplier/dashboard").status_code==403

    with SessionLocal.begin() as s:
        relations=s.scalars(select(HotelRegistrationDirectRow).where(
            HotelRegistrationDirectRow.supplier_id==supplier_id)).all()
        assert len(relations)==1
        assert relations[0].state=="APPROVED"
        assert relations[0].relationship_type=="OWNER"
        profile=s.get(HotelCanonicalProfileRow,HOTEL_ID)
        assert profile.go_direct_state=="GO_DIRECT_VERIFIED"

    # The contract step (Batch 6): the platform serves a template, the applicant
    # uploads the signed scan as a real document, and one confirmation activates.
    # There is no second human review (D-003), so an administrator cannot "approve"
    # a contract by assertion any more.
    contract = client.get("/bff/supplier/onboarding/contract")
    assert contract.status_code==200,contract.text
    contract_state = contract.json()["data"]
    assert contract_state["state"]=="VERIFIED"
    assert contract_state["can_confirm"] is False
    assert "CONTRACT_SIGNED_DOCUMENT_REQUIRED" in contract_state["blockers"]
    assert contract_state["template"]["sha256"]
    assert client.get("/v1/supplier/dashboard").status_code==403

    # Confirming without the tick, or with a stale template hash, is refused.
    refused = client.post("/bff/supplier/onboarding/contract/confirm",headers=csrf(client),
        json={"agreed":False,"template_sha256":contract_state["template"]["sha256"]})
    assert refused.status_code==422,refused.text
    assert refused.json()["detail"]=="CONTRACT_AGREEMENT_REQUIRED"
    stale = client.post("/bff/supplier/onboarding/contract/confirm",headers=csrf(client),
        json={"agreed":True,"template_sha256":"0"*64})
    assert stale.status_code==409,stale.text
    assert stale.json()["detail"]=="CONTRACT_TEMPLATE_CHANGED"
    assert client.get("/bff/auth/me").json()["data"]["onboarding"]["state"]=="VERIFIED"

    signed=upload_document(client,_signed_pdf(),filename="signed.pdf",mime="application/pdf",
        headers=csrf(client),document_type="SIGNED_CONTRACT",scope="ONBOARDING")
    assert signed.status_code==201,signed.text
    assert signed.json()["data"]["scope"]=="ONBOARDING"

    template = client.get("/bff/supplier/onboarding/contract/template")
    assert template.status_code==200,template.text
    assert template.headers["content-type"].startswith("application/pdf")
    assert hashlib.sha256(template.content).hexdigest()==contract_state["template"]["sha256"]

    active = client.post("/bff/supplier/onboarding/contract/confirm",headers=csrf(client),
        json={"agreed":True,"template_sha256":contract_state["template"]["sha256"],
              "signed_document_id":signed.json()["data"]["document_id"]})
    assert active.status_code==200,active.text
    assert active.json()["data"]["state"]=="CONTRACT_ACTIVE"
    assert active.json()["data"]["business_ready"] is True
    assert client.get("/v1/supplier/dashboard").status_code==200

    # The audit record carries every CHANGE 11 field, and it is the only place the
    # confirmation is stored.
    with SessionLocal() as s:
        event=s.scalar(select(AuditEventRow).where(
            AuditEventRow.action=="SUPPLIER_CONTRACT_CONFIRMED",
            AuditEventRow.supplier_id==supplier_id))
        assert event is not None
        after=event.after_state
        assert set(after)>= {"template_version","template_sha256","signed_document_id",
            "signed_document_sha256","legal_entity_id","hotel_id","registration_direct_id",
            "confirmed_by","confirmed_at"}
        assert after["hotel_id"]==HOTEL_ID
        assert after["signed_document_sha256"]==signed.json()["data"]["sha256"]
        assert after["confirmed_by"]==event.actor_id

    # 我的酒店 reads the same facts back, from stored rows.
    my_hotel = client.get("/bff/supplier/my-hotel")
    assert my_hotel.status_code==200,my_hotel.text
    assert my_hotel.json()["data"]["hotel"]["hotel_id"]==HOTEL_ID
    assert my_hotel.json()["data"]["hotel"]["claimed"] is True
