from go_hotel.services.supplier_onboarding_state import supplier_onboarding_state_service


def csrf(client):
    return {"X-CSRF-Token": client.cookies.get("go_csrf")}


def register_supplier(client, email="new-hotel@example.test"):
    terms = client.get("/bff/auth/supplier/registration-terms").json()["data"]
    response = client.post("/bff/auth/supplier/register", json={
        "email": email,
        "password": "staged-onboarding-pass",
        "accepted_terms": True,
        "term_versions": terms["versions"],
    })
    assert response.status_code == 201, response.text
    return response.json()["data"], terms


def complete_profile():
    return {
        "hotel_name": "测试酒店",
        "organization_name": "测试酒店管理有限公司",
        "contact_name": "测试联系人",
        "phone": "13800000000",
        "province": "黑龙江省",
        "city": "哈尔滨市",
        "street_address": "测试街道 1 号",
        "business_license_ref": "upload://business-license/1",
        "legal_representative_name": "测试法人",
        "identity_document_ref": "upload://identity/1",
        "storefront_photo_ref": "upload://storefront/1",
    }


def test_registration_creates_account_first_and_defers_high_risk_terms(client):
    registration, terms = register_supplier(client)
    assert registration["registration_state"] == "REGISTERED"
    assert registration["next_step"] == "COMPLETE_PROFILE"
    assert "data_processing_terms" not in terms["versions"]
    assert "electronic_signature_authorization" not in terms["versions"]
    assert set(terms["deferred"]["versions"]) == {
        "data_processing_terms", "electronic_signature_authorization",
    }

    me = client.get("/bff/auth/me").json()["data"]
    assert me["onboarding"]["state"] == "REGISTERED"
    assert me["onboarding"]["business_ready"] is False

    blocked = client.get("/v1/supplier/dashboard")
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "SUPPLIER_ONBOARDING_INCOMPLETE"


def test_onboarding_resumes_and_only_unlocks_after_profile_and_contract_review(client):
    registration, _ = register_supplier(client, "resume-hotel@example.test")
    supplier_id = registration["supplier_id"]

    draft = client.put(
        "/bff/supplier/onboarding/profile",
        headers=csrf(client),
        json={"hotel_name": "测试酒店"},
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["data"]["state"] == "PROFILE_DRAFT"

    incomplete = client.post(
        "/bff/supplier/onboarding/profile/submit",
        headers=csrf(client),
        json={},
    )
    assert incomplete.status_code == 409
    assert "SUPPLIER_PROFILE_INCOMPLETE" in incomplete.json()["detail"]

    saved = client.put(
        "/bff/supplier/onboarding/profile",
        headers=csrf(client),
        json=complete_profile(),
    )
    assert saved.status_code == 200, saved.text

    submitted = client.post(
        "/bff/supplier/onboarding/profile/submit",
        headers=csrf(client),
        json={},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["data"]["state"] == "UNDER_REVIEW"

    supplier_onboarding_state_service.decide_profile(
        supplier_id, "admin-test", "APPROVE", "主体资料通过"
    )
    me = client.get("/bff/auth/me").json()["data"]
    assert me["onboarding"]["state"] == "VERIFIED"
    assert client.get("/v1/supplier/dashboard").status_code == 403

    contract = client.post(
        "/bff/supplier/onboarding/contract",
        headers=csrf(client),
        json={"contract_ref": "upload://signed-contract/1", "contract_version": "standard-v1"},
    )
    assert contract.status_code == 200, contract.text
    assert contract.json()["data"]["state"] == "CONTRACT_UNDER_REVIEW"

    supplier_onboarding_state_service.decide_contract(
        supplier_id, "admin-test", "APPROVE", "合同通过"
    )
    me = client.get("/bff/auth/me").json()["data"]
    assert me["onboarding"]["state"] == "CONTRACT_ACTIVE"
    assert me["onboarding"]["business_ready"] is True

    # The lifecycle gate is now open. The supplier may have no business data yet,
    # but it is allowed to reach the existing console API.
    assert client.get("/v1/supplier/dashboard").status_code == 200
