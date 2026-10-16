"""Batch 4 — hotel claim: search, relationship, proof, approval, conflict.

The behaviours asserted here are the ones where a wrong answer costs something
real, so the tests aim at those rather than at route existence:

  * a search returns the canonical hotel a human means, and refuses to guess from
    a one-character query;
  * a relationship type that needs an operation proof cannot be saved without it;
  * submitting a *proposed* hotel creates nothing at all — no canonical hotel, no
    relation — until a human approves it (frozen decision D-05);
  * approval creates the canonical hotel exactly once and the relation exactly
    once, and a replayed approval does not create a second of either;
  * two suppliers claiming the same hotel produce exactly one holder and one
    CLAIM_CONFLICT, including when both approvals run concurrently;
  * the applicant never supplies an internal id, and document scope is resolved
    server side from a *named* scope.
"""
from __future__ import annotations

import io
import secrets
import threading
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from go_hotel.core.config import settings
from go_hotel.db.models import (
    CommercialCaseRow,
    HotelCanonicalProfileRow,
    HotelRegistrationDirectRow,
    LegalEntityDocumentRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services.document_store import document_store
from go_hotel.services.onboarding_hotel import onboarding_hotel_service
from go_hotel.services.supplier_onboarding_state import supplier_onboarding_state_service
from registration_terms_test_support import approved_terms_fixture, with_verification
from supplier_document_upload import upload_document

HOTEL = "HOTEL_OPERATION_PROOF"
FRANCHISE = "FRANCHISE_OR_MANAGEMENT_CONTRACT"


@pytest.fixture(autouse=True)
def _private_volume(tmp_path, monkeypatch):
    root = tmp_path / "supplier_documents"
    monkeypatch.setattr(document_store, "root", root)
    return root


def _csrf(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get(settings.csrf_cookie_name)}


def _png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (240, 160), (60, 120, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def _uscc(seed: str) -> str:
    """A *checksum-valid* USCC, computed with the published algorithm.

    Hard-coding a second valid code would hide a broken validator behind a
    constant; deriving it also re-verifies the algorithm from the other side.
    Characters outside the code charset (I, O, S, V, Z) are dropped first, so a
    seed never silently produces a value the charset rule would reject.
    """
    from go_hotel.services.uscc import CODE_CHARS, WEIGHTS

    clean = "".join(c for c in seed.upper() if c in CODE_CHARS) or "A"
    body = ("91350100" + clean)[:17].ljust(17, "0")
    total = sum(CODE_CHARS.index(c) * w for c, w in zip(body, WEIGHTS))
    return body + CODE_CHARS[(31 - total % 31) % 31]


def _register(client, monkeypatch, email: str) -> str:
    approved_terms_fixture(monkeypatch)
    policy = client.get("/bff/auth/supplier/registration-terms").json()["data"]
    # Three login identifiers, two proved channels: the shared helper mints the
    # challenges so this suite keeps its subject (hotel claim) rather than
    # re-spelling the sign-up contract.
    body = with_verification({
        "email": email,
        "password": "Isolated-test-pass-123",
        "accepted_terms": True,
        "term_versions": policy["versions"],
        "term_hashes": policy["term_hashes"],
        "registration_decisions": policy["required_decisions"],
        "contact_name": "测试联系人",
    }, "supplier")
    response = client.post("/bff/auth/supplier/register", json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()["data"]["supplier_id"]


def _entity(client, legal_name="测试酒店管理有限公司", seed="M1") -> None:
    response = client.put(
        "/bff/supplier/legal-entity",
        headers=_csrf(client),
        json={
            "legal_name": legal_name,
            "unified_social_credit_code": _uscc(seed),
            "legal_representative_name": "测试法人",
            "registered_address": "黑龙江省哈尔滨市测试街道 1 号",
        },
    )
    assert response.status_code == 200, response.text


def _applicant(client, monkeypatch, email="claim.applicant@example.test", seed="M1") -> str:
    supplier_id = _register(client, monkeypatch, email)
    _entity(client, seed=seed)
    return supplier_id


def _upload(client, document_type, scope="ONBOARDING"):
    return upload_document(
        client, _png(), filename="proof.png", mime="image/png", headers=_csrf(client),
        document_type=document_type, scope=scope,
    )


def _seed_hotel(name="测试大酒店", city="哈尔滨市", hotel_id="hotel_seeded", go_direct_state="NOT_REGISTERED"):
    now = datetime.now(timezone.utc)
    with SessionLocal.begin() as session:
        session.add(HotelCanonicalProfileRow(
            hotel_id=hotel_id, slug=f"seeded-{hotel_id}",
            canonical_json={"name": name, "address": {"city": city, "formatted": f"{city}{name}"}},
            field_provenance_json={}, source_snapshot_ids_json=[], completeness_bps=100,
            go_direct_state=go_direct_state, page_state="DRAFT", version=1,
            created_at=now, updated_at=now,
        ))


def _claim(client, relationship_type="OWNER", hotel_id="hotel_seeded", mode="EXISTING", proposed=None):
    body = {"mode": mode, "relationship_type": relationship_type}
    if hotel_id is not None:
        body["hotel_id"] = hotel_id
    if proposed is not None:
        body["proposed_hotel"] = proposed
    return client.put("/bff/supplier/hotel/claim", headers=_csrf(client), json=body)


def _case(supplier_id):
    with SessionLocal() as session:
        return session.scalar(select(CommercialCaseRow).where(
            CommercialCaseRow.case_type == "SUPPLIER_ONBOARDING",
            CommercialCaseRow.supplier_id == supplier_id))


# --------------------------------------------------------------------------- #
# search
# --------------------------------------------------------------------------- #
def test_search_finds_the_canonical_hotel_by_name_and_narrows_by_city(client, monkeypatch):
    _applicant(client, monkeypatch)
    _seed_hotel()
    rows = client.get("/bff/supplier/hotel/search", params={"q": "测试大"}).json()["data"]
    assert [row["name"] for row in rows] == ["测试大酒店"]
    assert rows[0]["city"] == "哈尔滨市"
    assert rows[0]["claim_state"] == "AVAILABLE"

    elsewhere = client.get(
        "/bff/supplier/hotel/search", params={"q": "测试大", "city": "上海市"}
    ).json()["data"]
    assert elsewhere == []


def test_search_refuses_a_query_too_short_to_mean_anything(client, monkeypatch):
    _applicant(client, monkeypatch)
    _seed_hotel()
    response = client.get("/bff/supplier/hotel/search", params={"q": "测"})
    assert response.status_code == 422
    assert response.json()["detail"] == "HOTEL_SEARCH_QUERY_REQUIRED"


def test_search_needs_the_applicant_session(client, monkeypatch):
    response = client.get("/bff/supplier/hotel/search", params={"q": "测试"})
    assert response.status_code in (401, 403)


def test_search_marks_a_hotel_that_someone_else_already_holds(client, monkeypatch):
    _applicant(client, monkeypatch)
    _seed_hotel(go_direct_state="GO_DIRECT_VERIFIED")
    rows = client.get("/bff/supplier/hotel/search", params={"q": "测试大"}).json()["data"]
    assert rows[0]["claim_state"] == "CLAIMED"


# --------------------------------------------------------------------------- #
# relationship + proof (D-03)
# --------------------------------------------------------------------------- #
def test_claim_requires_a_relationship_type(client, monkeypatch):
    _applicant(client, monkeypatch)
    _seed_hotel()
    response = _claim(client, relationship_type="")
    assert response.status_code == 409
    assert response.json()["detail"] == "HOTEL_RELATIONSHIP_TYPE_REQUIRED"


def test_unknown_relationship_type_is_refused(client, monkeypatch):
    _applicant(client, monkeypatch)
    _seed_hotel()
    response = _claim(client, relationship_type="LANDLORD")
    assert response.status_code == 409
    assert response.json()["detail"] == "HOTEL_RELATIONSHIP_TYPE_INVALID"


def test_non_owner_relationship_needs_an_operation_proof(client, monkeypatch):
    _applicant(client, monkeypatch)
    _seed_hotel()
    blocked = _claim(client, relationship_type="OPERATOR")
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "HOTEL_RELATIONSHIP_PROOF_REQUIRED"
    assert _case(client.get("/bff/auth/me").json()["data"]["supplier_id"]).payload_json.get("hotel_claim") is None

    uploaded = _upload(client, HOTEL)
    assert uploaded.status_code == 201, uploaded.text
    saved = _claim(client, relationship_type="OPERATOR")
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["claim"]["proof_document_type"] == HOTEL


def test_owner_relationship_needs_no_extra_proof(client, monkeypatch):
    _applicant(client, monkeypatch)
    _seed_hotel()
    response = _claim(client, relationship_type="OWNER")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["claim"]["proof_document_id"] is None


def test_franchise_contract_satisfies_a_management_company_claim(client, monkeypatch):
    _applicant(client, monkeypatch)
    _seed_hotel()
    assert _upload(client, FRANCHISE).status_code == 201
    response = _claim(client, relationship_type="MANAGEMENT_COMPANY")
    assert response.status_code == 200, response.text


def test_proof_of_the_other_kind_also_satisfies_the_requirement(client, monkeypatch):
    """D-03 says "operation proof OR franchise/management contract", not one each."""
    _applicant(client, monkeypatch)
    _seed_hotel()
    assert _upload(client, HOTEL).status_code == 201
    response = _claim(client, relationship_type="MANAGEMENT_COMPANY")
    assert response.status_code == 200, response.text


# --------------------------------------------------------------------------- #
# proposed hotel creates nothing (D-05)
# --------------------------------------------------------------------------- #
def test_claiming_an_unknown_hotel_creates_no_canonical_row(client, monkeypatch):
    _applicant(client, monkeypatch)
    response = _claim(client, relationship_type="OWNER", hotel_id=None, mode="PROPOSED",
                      proposed={"name": "未曾登记的酒店", "city": "哈尔滨市"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["claim"]["mode"] == "PROPOSED"
    with SessionLocal() as session:
        assert session.scalars(select(HotelCanonicalProfileRow)).all() == []
        assert session.scalars(select(HotelRegistrationDirectRow)).all() == []


def test_proposed_hotel_needs_name_and_city(client, monkeypatch):
    _applicant(client, monkeypatch)
    no_name = _claim(client, hotel_id=None, mode="PROPOSED", proposed={"name": "", "city": "哈尔滨市"})
    assert no_name.status_code == 409
    assert no_name.json()["detail"] == "PROPOSED_HOTEL_NAME_REQUIRED"
    no_city = _claim(client, hotel_id=None, mode="PROPOSED", proposed={"name": "未曾登记的酒店", "city": ""})
    assert no_city.status_code == 409
    assert no_city.json()["detail"] == "PROPOSED_HOTEL_CITY_REQUIRED"


def test_a_hotel_already_in_the_catalogue_cannot_be_proposed_as_new(client, monkeypatch):
    _applicant(client, monkeypatch)
    _seed_hotel()
    response = _claim(client, hotel_id=None, mode="PROPOSED",
                      proposed={"name": "测试 大酒店", "city": "哈尔滨市"})
    assert response.status_code == 409
    assert response.json()["detail"] == "PROPOSED_HOTEL_ALREADY_EXISTS"


def test_unknown_hotel_id_is_refused_rather_than_created(client, monkeypatch):
    _applicant(client, monkeypatch)
    response = _claim(client, hotel_id="hotel_does_not_exist")
    assert response.status_code == 409
    assert response.json()["detail"] == "HOTEL_NOT_FOUND"


# --------------------------------------------------------------------------- #
# claim lifecycle
# --------------------------------------------------------------------------- #
def test_saving_the_claim_twice_keeps_one_claim(client, monkeypatch):
    _applicant(client, monkeypatch)
    _seed_hotel()
    assert _claim(client, relationship_type="OWNER").status_code == 200
    _seed_hotel(name="第二家大酒店", hotel_id="hotel_seeded_2")
    assert _claim(client, relationship_type="OWNER", hotel_id="hotel_seeded_2").status_code == 200
    supplier_id = client.get("/bff/auth/me").json()["data"]["supplier_id"]
    claim = _case(supplier_id).payload_json["hotel_claim"]
    assert claim["hotel_id"] == "hotel_seeded_2"
    assert claim["approved_at"] is None


def test_claim_cannot_be_changed_once_submitted(client, monkeypatch):
    _applicant(client, monkeypatch)
    _seed_hotel()
    assert _claim(client, relationship_type="OWNER").status_code == 200
    supplier_id = client.get("/bff/auth/me").json()["data"]["supplier_id"]
    with SessionLocal.begin() as session:
        row = session.scalar(select(CommercialCaseRow).where(CommercialCaseRow.supplier_id == supplier_id))
        row.state = "UNDER_REVIEW"
    blocked = _claim(client, relationship_type="OPERATOR")
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "HOTEL_CLAIM_NOT_EDITABLE"


def test_submission_reports_exactly_what_is_missing(client, monkeypatch):
    _register(client, monkeypatch, "empty.applicant@example.test")
    response = client.post("/bff/supplier/onboarding/profile/submit", headers=_csrf(client), json={})
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "SUPPLIER_PROFILE_INCOMPLETE:LEGAL_ENTITY,BUSINESS_LICENSE,HOTEL_RELATIONSHIP"
    )


def test_submission_reports_a_missing_relationship_proof(client, monkeypatch):
    """A claim that needs an operation proof cannot complete without one.

    The persisted shape is written directly because the product never *stores* an
    OPERATOR claim without its proof. What is asserted is that completion reads
    stored artefacts, so a case that somehow reached this shape is reported
    honestly instead of submitting.
    """
    supplier_id = _applicant(client, monkeypatch)
    _seed_hotel()
    assert _upload(client, "BUSINESS_LICENSE", scope="ENTITY").status_code == 201
    with SessionLocal.begin() as session:
        row = session.scalar(select(CommercialCaseRow).where(
            CommercialCaseRow.supplier_id == supplier_id))
        payload = dict(row.payload_json or {})
        payload["hotel_claim"] = {
            "mode": "EXISTING", "hotel_id": "hotel_seeded",
            "hotel_display": {"name": "测试大酒店"}, "relationship_type": "OPERATOR",
            "proof_document_id": None, "approved_at": None,
        }
        row.payload_json = payload
        row.state = "PROFILE_DRAFT"
    response = client.post("/bff/supplier/onboarding/profile/submit", headers=_csrf(client), json={})
    assert response.status_code == 409
    assert response.json()["detail"] == "SUPPLIER_PROFILE_INCOMPLETE:HOTEL_RELATIONSHIP_PROOF"


def test_a_complete_draft_submits(client, monkeypatch):
    _applicant(client, monkeypatch)
    _seed_hotel()
    assert _upload(client, "BUSINESS_LICENSE", scope="ENTITY").status_code == 201
    assert _claim(client, relationship_type="OWNER").status_code == 200
    submitted = client.post("/bff/supplier/onboarding/profile/submit", headers=_csrf(client), json={})
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["data"]["state"] == "UNDER_REVIEW"


# --------------------------------------------------------------------------- #
# approval
# --------------------------------------------------------------------------- #
def test_approving_an_existing_hotel_writes_exactly_one_relation(client, monkeypatch):
    supplier_id = _applicant(client, monkeypatch)
    _seed_hotel()
    assert _claim(client, relationship_type="OPERATOR").status_code == 409
    assert _upload(client, HOTEL).status_code == 201
    assert _claim(client, relationship_type="OPERATOR").status_code == 200

    result = onboarding_hotel_service.approve_claim(supplier_id, "reviewer-1", "资料齐全")
    assert result["idempotent"] is False
    assert result["hotel_id"] == "hotel_seeded"

    replay = onboarding_hotel_service.approve_claim(supplier_id, "reviewer-1", "资料齐全")
    assert replay["idempotent"] is True

    with SessionLocal() as session:
        relations = session.scalars(select(HotelRegistrationDirectRow)).all()
        assert len(relations) == 1
        assert relations[0].state == "APPROVED"
        assert relations[0].relationship_type == "OPERATOR"
    body = client.get("/bff/supplier/onboarding").json()["data"]
    assert body["state"] == "VERIFIED"
    assert body["hotel_id"] == "hotel_seeded"
    with SessionLocal() as session:
        profile = session.get(HotelCanonicalProfileRow, "hotel_seeded")
        assert profile.go_direct_state == "GO_DIRECT_VERIFIED"


def test_approving_a_proposed_hotel_creates_the_canonical_row_exactly_once(client, monkeypatch):
    supplier_id = _applicant(client, monkeypatch)
    assert _claim(client, hotel_id=None, mode="PROPOSED",
                  proposed={"name": "新登记的酒店", "city": "哈尔滨市", "address": "测试路 9 号"}
                  ).status_code == 200

    first = onboarding_hotel_service.approve_claim(supplier_id, "reviewer-1")
    replay = onboarding_hotel_service.approve_claim(supplier_id, "reviewer-1")
    assert replay["idempotent"] is True
    assert replay["hotel_id"] == first["hotel_id"]

    with SessionLocal() as session:
        hotels = session.scalars(select(HotelCanonicalProfileRow)).all()
        assert len(hotels) == 1
        assert hotels[0].canonical_json["name"] == "新登记的酒店"
        assert hotels[0].go_direct_state == "GO_DIRECT_VERIFIED"
        relations = session.scalars(select(HotelRegistrationDirectRow)).all()
        assert len(relations) == 1
        assert relations[0].hotel_id == first["hotel_id"]


def test_approval_without_a_claim_is_refused(client, monkeypatch):
    supplier_id = _applicant(client, monkeypatch)
    with pytest.raises(ValueError, match="HOTEL_CLAIM_REQUIRED"):
        onboarding_hotel_service.approve_claim(supplier_id, "reviewer-1")


# --------------------------------------------------------------------------- #
# conflict
# --------------------------------------------------------------------------- #
def test_second_supplier_claiming_the_same_hotel_gets_a_conflict_not_the_hotel(client, monkeypatch):
    winner = _applicant(client, monkeypatch, "winner@example.test", seed="WN1")
    _seed_hotel()
    assert _claim(client, relationship_type="OWNER").status_code == 200
    onboarding_hotel_service.approve_claim(winner, "reviewer-1")

    client.cookies.clear()
    loser = _applicant(client, monkeypatch, "loser@example.test", seed="LN1")
    assert client.get("/bff/supplier/onboarding").json()["data"]["state"] == "PROFILE_DRAFT"
    assert _claim(client, relationship_type="OWNER").status_code == 200
    with pytest.raises(ValueError, match="CLAIM_CONFLICT"):
        onboarding_hotel_service.approve_claim(loser, "reviewer-1")

    with SessionLocal() as session:
        loser_case = session.scalar(select(CommercialCaseRow).where(CommercialCaseRow.supplier_id == loser))
        assert loser_case.state == "CLAIM_CONFLICT"
        # A conflicting case must NOT carry property_id: the hotel belongs to the
        # winner, and claiming it here would collide with the winner's own row.
        assert loser_case.property_id is None
        assert loser_case.payload_json["hotel_claim"]["conflict"]["reason"] == "HOTEL_HELD_BY_ANOTHER_SUPPLIER"
        assert loser_case.payload_json["hotel_claim"]["approved_at"] is None
        relations = session.scalars(select(HotelRegistrationDirectRow)).all()
        assert len(relations) == 1
        assert relations[0].supplier_id == winner


def test_two_suppliers_proposing_the_same_new_hotel_yield_one_canonical_hotel(client, monkeypatch):
    first = _applicant(client, monkeypatch, "proposer-a@example.test", seed="PRA")
    assert _claim(client, hotel_id=None, mode="PROPOSED",
                  proposed={"name": "同一家新酒店", "city": "大连市"}).status_code == 200

    client.cookies.clear()
    second = _applicant(client, monkeypatch, "proposer-b@example.test", seed="PRB")
    assert _claim(client, hotel_id=None, mode="PROPOSED",
                  proposed={"name": "同一家新酒店", "city": "大连市"}).status_code == 200

    approved = onboarding_hotel_service.approve_claim(first, "reviewer-1")
    with pytest.raises(ValueError, match="CLAIM_CONFLICT"):
        onboarding_hotel_service.approve_claim(second, "reviewer-1")

    with SessionLocal() as session:
        hotels = session.scalars(select(HotelCanonicalProfileRow)).all()
        assert len(hotels) == 1
        assert hotels[0].hotel_id == approved["hotel_id"]
        loser_case = session.scalar(select(CommercialCaseRow).where(CommercialCaseRow.supplier_id == second))
        assert loser_case.state == "CLAIM_CONFLICT"
        assert loser_case.payload_json["hotel_claim"]["conflict"]["reason"] == "CANONICAL_HOTEL_ALREADY_EXISTS"


def test_concurrent_approval_grants_the_hotel_exactly_once(client, monkeypatch):
    """Two reviewers approving two suppliers' claims for one hotel, simultaneously.

    The application-level check cannot make this safe on its own: both threads can
    read "no holder yet". What makes it safe is the partial unique index on the
    approved relation plus the uniqueness of a live onboarding case per hotel.
    """
    winner = _applicant(client, monkeypatch, "race-a@example.test", seed="RCA")
    _seed_hotel()
    assert _claim(client, relationship_type="OWNER").status_code == 200
    client.cookies.clear()
    rival = _applicant(client, monkeypatch, "race-b@example.test", seed="RCB")
    assert _claim(client, relationship_type="OWNER").status_code == 200

    outcomes: dict[str, str] = {}
    barrier = threading.Barrier(2)

    def attempt(supplier_id: str, key: str) -> None:
        try:
            barrier.wait(timeout=10)
            onboarding_hotel_service.approve_claim(supplier_id, f"reviewer-{key}")
            outcomes[key] = "APPROVED"
        except ValueError as exc:
            outcomes[key] = str(exc)

    threads = [threading.Thread(target=attempt, args=(winner, "a")),
               threading.Thread(target=attempt, args=(rival, "b"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes.values()) == ["APPROVED", "CLAIM_CONFLICT"], outcomes
    with SessionLocal() as session:
        relations = session.scalars(select(HotelRegistrationDirectRow).where(
            HotelRegistrationDirectRow.state == "APPROVED")).all()
        assert len(relations) == 1
        holders = session.scalars(select(CommercialCaseRow).where(
            CommercialCaseRow.case_type == "SUPPLIER_ONBOARDING",
            CommercialCaseRow.property_id == "hotel_seeded")).all()
        assert len(holders) == 1
        assert holders[0].supplier_id == relations[0].supplier_id


# --------------------------------------------------------------------------- #
# document scope is a name, not an id
# --------------------------------------------------------------------------- #
def test_document_scope_is_resolved_from_a_name(client, monkeypatch):
    supplier_id = _applicant(client, monkeypatch)
    case_id = f"onb_{supplier_id}"
    assert _upload(client, HOTEL, scope="ONBOARDING").status_code == 201
    assert _upload(client, "BUSINESS_LICENSE", scope="ENTITY").status_code == 201

    with SessionLocal() as session:
        rows = session.scalars(select(LegalEntityDocumentRow).order_by(
            LegalEntityDocumentRow.document_type)).all()
        by_type = {row.document_type: row.onboarding_case_id for row in rows}
    assert by_type[HOTEL] == case_id
    assert by_type["BUSINESS_LICENSE"] is None

    everything = client.get("/bff/supplier/legal-entity/documents").json()["data"]
    assert sorted(row["scope"] for row in everything) == ["ENTITY", "ONBOARDING"]


def test_an_unknown_scope_is_refused(client, monkeypatch):
    _applicant(client, monkeypatch)
    response = _upload(client, "BUSINESS_LICENSE", scope="SOMEBODY_ELSES_CASE")
    assert response.status_code == 409
    assert response.json()["detail"] == "DOCUMENT_SCOPE_INVALID"


def test_hotel_claim_before_the_legal_entity_is_empty_not_an_error(client, monkeypatch):
    _register(client, monkeypatch, "no.entity@example.test")
    assert client.get("/bff/supplier/legal-entity").json()["data"] is None
    claim = client.get("/bff/supplier/hotel/claim").json()["data"]
    assert claim["claim"] is None
    assert sorted(claim["relationship_types"]) == [
        "AUTHORIZED_AGENT", "MANAGEMENT_COMPANY", "OPERATOR", "OWNER"
    ]


def test_search_and_claim_never_return_another_suppliers_claim(client, monkeypatch):
    first = _applicant(client, monkeypatch, "iso-a@example.test", seed="JA1")
    _seed_hotel()
    assert _claim(client, relationship_type="OWNER", hotel_id="hotel_seeded").status_code == 200
    client.cookies.clear()
    second = _applicant(client, monkeypatch, "iso-b@example.test", seed="JB1")
    assert onboarding_hotel_service.get_claim(second)["claim"] is None
    assert onboarding_hotel_service.get_claim(first)["claim"]["hotel_id"] == "hotel_seeded"
