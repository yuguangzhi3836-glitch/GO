from __future__ import annotations

import json

from sqlalchemy import text

from go_hotel.db.session import SessionLocal
from go_hotel.security.service import identity_service


SUPPLIER_PASSWORD = "SupplierPass123!"
CONSUMER_PASSWORD = "StrongPass123!"


def supplier_csrf(client):
    return {"X-CSRF-Token": client.cookies.get("go_csrf")}


def consumer_csrf(client):
    return {"X-CSRF-Token": client.cookies.get("go_consumer_csrf")}


def admin_headers():
    token = identity_service.login("go_admin", "change-me-admin")
    return {"Authorization": "Bearer " + token["access_token"]}


def supplier_terms(client):
    response = client.get("/bff/auth/supplier/registration-terms")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def register_supplier(client, email: str):
    terms = supplier_terms(client)
    response = client.post(
        "/bff/auth/supplier/register",
        json={
            "email": email,
            "password": SUPPLIER_PASSWORD,
            "accepted_terms": True,
            "term_versions": terms["versions"],
            "organization_name": "V91 Supplier Org",
            "contact_name": "V91 Supplier Contact",
            "phone": "13800000000",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def login_supplier(client, email: str):
    response = client.post(
        "/bff/auth/login",
        json={
            "username": email,
            "password": SUPPLIER_PASSWORD,
            "expected_actor_type": "SUPPLIER_USER",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def register_consumer(client, email: str):
    response = client.post(
        "/v1/consumer/auth/register",
        json={
            "email": email,
            "password": CONSUMER_PASSWORD,
            "display_name": "V91 Consumer",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def login_consumer(client, email: str):
    response = client.post(
        "/v1/consumer/auth/login",
        json={"email": email, "password": CONSUMER_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def search_offer(client):
    response = client.post(
        "/v1/search/hotels",
        json={
            "destination": {"city_code": "TYO"},
            "stay": {"check_in": "2026-09-01", "check_out": "2026-09-05"},
            "occupancy": {"rooms": 1, "adults": 2, "children": 0},
            "currency": "CNY",
        },
        headers=consumer_csrf(client),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["hotels"][0]["best_offer"]


def observe_database():
    with SessionLocal() as session:
        backend = session.bind.dialect.name
        if backend == "postgresql":
            return {
                "status": "PASS",
                "backend": backend,
                "engine": str(session.bind.url),
                "version": session.execute(text("select version()")).scalar_one(),
                "server_version_num": session.execute(text("show server_version_num")).scalar_one(),
            }
        return {
            "status": "DEFERRED",
            "backend": backend,
            "engine": str(session.bind.url),
            "version": session.execute(text("select sqlite_version()")).scalar_one(),
            "reason": "POSTGRESQL18_4_NOT_CONFIGURED_IN_AGENT_SANDBOX",
        }


def test_postregistration_backend_chain_v91(client):
    matrix: dict[str, dict] = {}

    matrix["database"] = observe_database()

    supplier_email = "supplier-v91@example.test"
    consumer_email = "consumer-v91@example.test"
    stranger_email = "consumer-v91-other@example.test"

    supplier_registration = register_supplier(client, supplier_email)
    supplier_id = supplier_registration["supplier_id"]
    me_after_register = client.get("/bff/auth/me")
    assert me_after_register.status_code == 200, me_after_register.text
    supplier_me = me_after_register.json()["data"]
    assert supplier_me["supplier_id"] == supplier_id
    assert supplier_me["onboarding"]["state"] == "REGISTERED"
    logout = client.post("/bff/auth/logout", headers=supplier_csrf(client))
    assert logout.status_code == 200, logout.text
    relogin = login_supplier(client, supplier_email)
    relogin_me = client.get("/bff/auth/me")
    assert relogin_me.status_code == 200, relogin_me.text
    assert relogin_me.json()["data"]["supplier_id"] == supplier_id
    matrix["supplier_register_logout_relogin"] = {
        "status": "PASS",
        "supplier_id": supplier_id,
        "session_refresh": relogin["expires_in"],
        "state_after_relogin": relogin_me.json()["data"]["onboarding"]["state"],
    }

    dashboard = client.get("/v1/supplier/dashboard")
    assert dashboard.status_code == 403, dashboard.text
    assert dashboard.json()["detail"] == "SUPPLIER_ONBOARDING_INCOMPLETE"
    matrix["supplier_console_gate_before_approval"] = {
        "status": "PASS",
        "http_status": dashboard.status_code,
        "detail": dashboard.json()["detail"],
    }

    profile = client.put(
        "/bff/supplier/onboarding/profile",
        headers=supplier_csrf(client),
        json={
            "organization_name": "V91 Supplier Org",
            "hotel_name": "V91 Test Hotel",
            "contact_name": "V91 Supplier Contact",
            "phone": "13800000000",
            "province": "Heilongjiang",
            "city": "Harbin",
            "street_address": "V91 Test Street 1",
            "business_license_ref": "upload://v91/business-license",
            "legal_representative_name": "V91 Legal",
            "identity_document_ref": "upload://v91/legal-id",
            "storefront_photo_ref": "upload://v91/storefront",
        },
    )
    assert profile.status_code == 200, profile.text
    submit = client.post(
        "/bff/supplier/onboarding/profile/submit",
        headers=supplier_csrf(client),
        json={},
    )
    assert submit.status_code == 200, submit.text
    assert submit.json()["data"]["state"] == "UNDER_REVIEW"
    matrix["supplier_profile_submit"] = {
        "status": "PASS",
        "state": submit.json()["data"]["state"],
        "next_step": submit.json()["data"]["next_step"],
    }

    approval = client.post(
        f"/internal/v1/supplier-onboarding/{supplier_id}/profile-decision",
        headers=admin_headers(),
        json={"decision": "APPROVE"},
    )
    assert approval.status_code == 409, approval.text
    assert approval.json()["detail"] == "APPROVED_HOTEL_REGISTRATION_REQUIRED"
    matrix["supplier_profile_review_breakpoint"] = {
        "status": "BLOCKED",
        "http_status": approval.status_code,
        "detail": approval.json()["detail"],
        "path": "/internal/v1/supplier-onboarding/{supplier_id}/profile-decision",
        "module": "application/src/go_hotel/services/supplier_onboarding_state.py",
        "dependency": "Existing Supplier Onboarding V1 owner/candidate in PR #592",
    }
    matrix["supplier_contract_review"] = {
        "status": "BLOCKED",
        "blocked_by": "supplier_profile_review_breakpoint",
        "dependency": "Approved hotel registration direct record required before contract flow",
    }
    matrix["supplier_business_console"] = {
        "status": "BLOCKED",
        "blocked_by": "supplier_profile_review_breakpoint",
        "path": "/v1/supplier/dashboard",
    }
    matrix["supplier_room_inventory_price"] = {
        "status": "BLOCKED",
        "blocked_by": "supplier_profile_review_breakpoint",
        "dependency": "No business-ready supplier/hotel ownership created through current HTTP flow",
    }

    supplier_logout = client.post("/bff/auth/logout", headers=supplier_csrf(client))
    assert supplier_logout.status_code == 200, supplier_logout.text

    consumer_registration = register_consumer(client, consumer_email)
    consumer_go_id = consumer_registration["profile"]["go_id"]
    consumer_logout = client.post("/v1/consumer/auth/logout", headers=consumer_csrf(client))
    assert consumer_logout.status_code == 200, consumer_logout.text
    login_consumer(client, consumer_email)
    consumer_me = client.get("/v1/consumer/me")
    assert consumer_me.status_code == 200, consumer_me.text
    assert consumer_me.json()["data"]["go_id"] == consumer_go_id
    matrix["consumer_register_logout_relogin"] = {
        "status": "PASS",
        "go_id": consumer_go_id,
    }

    tokenize = client.post(
        "/v1/consumer/wallet/payment-methods/tokenize",
        json={
            "pan": "4111111111111111",
            "expiry_month": 12,
            "expiry_year": 2030,
            "cvc": "123",
            "make_default": True,
        },
        headers=consumer_csrf(client),
    )
    assert tokenize.status_code == 200, tokenize.text
    payment_method_id = tokenize.json()["data"]["payment_method_id"]
    offer = search_offer(client)
    prebook = client.post(
        f"/v1/offers/{offer['offer_id']}/prebook",
        json={"currency": "CNY"},
        headers=consumer_csrf(client),
    )
    assert prebook.status_code == 200, prebook.text
    prebook_data = prebook.json()["data"]
    order_body = {
        "prebook_id": prebook_data["prebook_id"],
        "expected_fare_rule_hash": prebook_data["fare_rule"]["offer_rule_hash"],
        "fare_confirmed": True,
    }
    first_order = client.post(
        "/v1/consumer/orders",
        json=order_body,
        headers=consumer_csrf(client) | {"Idempotency-Key": "v91-consumer-order"},
    )
    second_order = client.post(
        "/v1/consumer/orders",
        json=order_body,
        headers=consumer_csrf(client) | {"Idempotency-Key": "v91-consumer-order"},
    )
    assert first_order.status_code == 200, first_order.text
    assert second_order.status_code == 200, second_order.text
    first_order_data = first_order.json()["data"]
    second_order_data = second_order.json()["data"]
    assert first_order_data["order_id"] == second_order_data["order_id"]
    checkout = client.post(
        f"/v1/consumer/orders/{first_order_data['order_id']}/secure-checkout",
        json={"payment_method_id": payment_method_id},
        headers=consumer_csrf(client),
    )
    assert checkout.status_code == 200, checkout.text
    assert checkout.json()["data"]["status"] == "CONFIRMED"
    matrix["consumer_order_idempotency_and_checkout"] = {
        "status": "PASS",
        "order_id": first_order_data["order_id"],
        "replayed_order_id": second_order_data["order_id"],
        "payment_status": checkout.json()["data"]["status"],
    }

    consumer_logout_2 = client.post("/v1/consumer/auth/logout", headers=consumer_csrf(client))
    assert consumer_logout_2.status_code == 200, consumer_logout_2.text
    register_consumer(client, stranger_email)
    hidden = client.get(f"/v1/consumer/orders/{first_order_data['order_id']}/detail")
    assert hidden.status_code == 404, hidden.text
    matrix["consumer_cross_account_order_access_rejected"] = {
        "status": "PASS",
        "http_status": hidden.status_code,
    }

    matrix["supplier_cross_hotel_access_check"] = {
        "status": "BLOCKED",
        "blocked_by": "supplier_profile_review_breakpoint",
        "path": "/v1/supplier/transaction-orders/{vertical}/{order_id}",
        "dependency": "Supplier principal never becomes business-ready without approved hotel registration",
    }
    matrix["payment_callback_recovery_refund_settlement"] = {
        "status": "BLOCKED",
        "dependency": "Reuse C11 payment closure from #569/#570 instead of re-implementing finance internals in C01",
    }

    print(json.dumps(matrix, indent=2, sort_keys=True))

    assert matrix["supplier_profile_review_breakpoint"]["detail"] == "APPROVED_HOTEL_REGISTRATION_REQUIRED"
    assert matrix["consumer_order_idempotency_and_checkout"]["payment_status"] == "CONFIRMED"
