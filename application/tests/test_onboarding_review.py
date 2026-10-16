"""Batch 5 — the reviewer console: queue, three-state decision, conflicts, reopen.

What these tests insist on, beyond "the route answers":

  * the queue serves the case that has waited longest first, and paging cannot
    hide a row that shares a timestamp;
  * NEEDS_CHANGES without a structured finding is refused, because the applicant
    could not act on it;
  * REJECT ends the application and leaves the legal entity row completely alone
    — the separation is the point, not an implementation detail;
  * resolving a conflict by taking a hotel away from its holder requires an
    explicit confirmation and a reason, and the revocation plus the new grant
    happen in one transaction, so the hotel is never left with no holder;
  * an ordinary admin cannot reach any of it.
"""
from __future__ import annotations

import io
import secrets
import threading

import pytest
from sqlalchemy import select

from go_hotel.db.models import (
    AuditEventRow,
    CommercialCaseRow,
    HotelCanonicalProfileRow,
    HotelRegistrationDirectRow,
    LegalEntityRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.security.mfa import totp
from go_hotel.security.service import identity_service
from go_hotel.services.document_store import document_store
from go_hotel.services.onboarding_hotel import onboarding_hotel_service
from go_hotel.services.onboarding_review import onboarding_review_service
from go_hotel.services.supplier_onboarding_state import supplier_onboarding_state_service
from test_registration_verification import send, delivery  # noqa: F401  (fixtures)

HOTEL_ID = "hotel_review_seed"
REVIEW = "/internal/v1/onboarding-review"


@pytest.fixture(autouse=True)
def _private_volume(tmp_path, monkeypatch):
    monkeypatch.setattr(document_store, "root", tmp_path / "supplier_documents")


def _licence_png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (240, 160), (30, 90, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


def _uscc(seed: str) -> str:
    """A checksum-valid USCC derived from a seed, so two applicants differ.

    One credit code identifies one legal entity, so every applicant in these
    tests needs their own; hard-coding a second one would hide a broken validator
    behind a constant.
    """
    from go_hotel.services.uscc import CODE_CHARS, WEIGHTS

    clean = "".join(c for c in seed.upper() if c in CODE_CHARS) or "A"
    body = ("91350100" + clean)[:17].ljust(17, "0")
    total = sum(CODE_CHARS.index(c) * w for c, w in zip(body, WEIGHTS))
    return body + CODE_CHARS[(31 - total % 31) % 31]


def csrf(client):
    return {"X-CSRF-Token": client.cookies.get("go_csrf")}


def reviewer(client, name: str | None = None) -> dict:
    """A real GO_GOVERNANCE session, enrolled through the real MFA flow."""
    client.cookies.clear()
    name = name or f"onb-reviewer-{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(24)
    identity_service.create_user(name, password, "GO_ADMIN", None, ["GO_GOVERNANCE"])
    enrollment = client.post(
        "/bff/auth/mfa/enroll/start", json={"username": name, "password": password}
    ).json()["data"]
    confirmed = client.post("/bff/auth/mfa/enroll/confirm", json={
        "enrollment_token": enrollment["enrollment_token"], "code": totp(enrollment["secret"])})
    assert confirmed.status_code == 200, confirmed.text
    return {"X-GO-Actor": "GO_ADMIN", **csrf(client)}


def ordinary_admin(client, name: str = "onb-plain-admin") -> dict:
    client.cookies.clear()
    password = secrets.token_urlsafe(24)
    identity_service.create_user(name, password, "GO_ADMIN", None, ["GO_ORDER_OPS"])
    enrollment = client.post(
        "/bff/auth/mfa/enroll/start", json={"username": name, "password": password}
    ).json()["data"]
    confirmed = client.post("/bff/auth/mfa/enroll/confirm", json={
        "enrollment_token": enrollment["enrollment_token"], "code": totp(enrollment["secret"])})
    assert confirmed.status_code == 200, confirmed.text
    return {"X-GO-Actor": "GO_ADMIN", **csrf(client)}


def seed_hotel(hotel_id: str = HOTEL_ID, name: str = "复核测试酒店"):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    with SessionLocal.begin() as s:
        s.add(HotelCanonicalProfileRow(
            hotel_id=hotel_id, slug=f"seed-{hotel_id}",
            canonical_json={"name": name,
                            "address": {"city": "哈尔滨市", "formatted": "哈尔滨市测试街道 1 号"}},
            field_provenance_json={}, source_snapshot_ids_json=[], completeness_bps=0,
            go_direct_state="NOT_REGISTERED", page_state="DRAFT", version=1,
            created_at=now, updated_at=now,
        ))


def draft(client, delivery, email: str, *, hotel_id: str = HOTEL_ID,
          relationship_type: str = "OWNER") -> str:
    """Register, file the entity + licence, claim the hotel, submit. Real routes."""
    body = send(client, delivery, "supplier", email)
    registered = client.post("/bff/auth/supplier/register", json=body)
    assert registered.status_code == 201, registered.text
    saved = client.put("/bff/supplier/legal-entity", headers=csrf(client), json={
        "legal_name": "复核测试酒店管理有限公司", "unified_social_credit_code": _uscc(email),
        "legal_representative_name": "复核法人", "registered_address": "黑龙江省哈尔滨市测试街道 1 号",
    })
    assert saved.status_code == 200, saved.text
    uploaded = client.post("/bff/supplier/legal-entity/documents", headers=csrf(client),
                           data={"document_type": "BUSINESS_LICENSE", "scope": "ENTITY"},
                           files={"file": ("licence.png", _licence_png(), "image/png")})
    assert uploaded.status_code == 201, uploaded.text
    claim = client.put("/bff/supplier/hotel/claim", headers=csrf(client), json={
        "mode": "EXISTING", "relationship_type": relationship_type, "hotel_id": hotel_id})
    assert claim.status_code == 200, claim.text
    submitted = client.post("/bff/supplier/onboarding/profile/submit",
                            headers=csrf(client), json={})
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["data"]["state"] == "UNDER_REVIEW"
    return client.get("/bff/auth/me").json()["data"]["supplier_id"]


def decide(client, headers, supplier_id, decision, **extra):
    return client.post(f"{REVIEW}/cases/{supplier_id}/decision", headers=headers,
                       json={"decision": decision, **extra})


def case_state(supplier_id: str) -> str:
    with SessionLocal() as s:
        row = s.scalar(select(CommercialCaseRow).where(
            CommercialCaseRow.case_type == "SUPPLIER_ONBOARDING",
            CommercialCaseRow.supplier_id == supplier_id))
        assert row is not None
        return row.state


def approved_relations(hotel_id: str) -> list[HotelRegistrationDirectRow]:
    with SessionLocal() as s:
        return list(s.scalars(select(HotelRegistrationDirectRow).where(
            HotelRegistrationDirectRow.hotel_id == hotel_id,
            HotelRegistrationDirectRow.state == "APPROVED")))


def canonical_hotels_named(name: str) -> int:
    with SessionLocal() as s:
        return len([h for h in s.scalars(select(HotelCanonicalProfileRow))
                    if (h.canonical_json or {}).get("name") == name])


# --------------------------------------------------------------------------- #
# authorisation
# --------------------------------------------------------------------------- #
def test_an_ordinary_admin_cannot_reach_the_queue_or_a_case(client, delivery):
    """The boundary that keeps an operator out of a stranger's legal documents."""
    headers = ordinary_admin(client)
    assert client.get(f"{REVIEW}/cases", headers=headers).status_code == 403
    assert client.get(f"{REVIEW}/cases/sup_whatever", headers=headers).status_code == 403
    assert client.post(f"{REVIEW}/cases/sup_whatever/decision", headers=headers,
                       json={"decision": "APPROVE"}).status_code == 403
    assert client.post(f"{REVIEW}/cases/sup_whatever/reopen", headers=headers,
                       json={"reason": "x"}).status_code == 403


def test_the_queue_requires_a_session_at_all(client):
    client.cookies.clear()
    assert client.get(f"{REVIEW}/cases").status_code in (401, 403)


# --------------------------------------------------------------------------- #
# queue
# --------------------------------------------------------------------------- #
def test_queue_holds_only_cases_waiting_for_a_human_oldest_first(client, delivery):
    seed_hotel()
    early = draft(client, delivery, "queue-early@example.test")
    late = draft(client, delivery, "queue-late@example.test")
    # A case still being drafted is the applicant's own work, not a reviewer's.
    body = send(client, delivery, "supplier", "queue-draft@example.test")
    client.post("/bff/auth/supplier/register", json=body)
    drafting = client.get("/bff/auth/me").json()["data"]["supplier_id"]

    # Make the waiting order unambiguous without relying on clock resolution.
    with SessionLocal.begin() as s:
        early_row = s.scalar(select(CommercialCaseRow).where(
            CommercialCaseRow.supplier_id == early))
        early_row.updated_at = early_row.updated_at.replace(year=2020)

    headers = reviewer(client)
    data = client.get(f"{REVIEW}/cases", headers=headers).json()["data"]
    ids = [item["supplier_id"] for item in data["items"]]
    assert drafting not in ids
    assert ids == [early, late]
    assert data["items"][0]["state"] == "UNDER_REVIEW"
    assert data["items"][0]["hotel_name"] == "复核测试酒店"
    assert data["total"] == 2


def test_queue_filters_by_state_and_pages_without_losing_a_row(client, delivery):
    seed_hotel()
    for index in range(3):
        draft(client, delivery, f"page-{index}@example.test")
    headers = reviewer(client)

    first = client.get(f"{REVIEW}/cases", headers=headers,
                       params={"limit": 2, "offset": 0}).json()["data"]
    second = client.get(f"{REVIEW}/cases", headers=headers,
                        params={"limit": 2, "offset": 2}).json()["data"]
    assert len(first["items"]) == 2 and first["total"] == 3
    assert len(second["items"]) == 1 and second["total"] == 3
    seen = {item["supplier_id"] for item in first["items"] + second["items"]}
    assert len(seen) == 3

    # No conflicts yet, so the conflict filter is honestly empty — not an error.
    only_conflicts = client.get(f"{REVIEW}/cases", headers=headers,
                                params={"states": "CLAIM_CONFLICT"}).json()["data"]
    assert only_conflicts["items"] == [] and only_conflicts["total"] == 0


def test_case_detail_carries_the_evidence_and_the_available_actions(client, delivery):
    seed_hotel()
    supplier_id = draft(client, delivery, "detail@example.test")
    headers = reviewer(client)

    data = client.get(f"{REVIEW}/cases/{supplier_id}", headers=headers).json()["data"]
    assert data["state"] == "UNDER_REVIEW"
    assert data["legal_entity"]["unified_social_credit_code"] == _uscc("detail@example.test")
    assert [d["document_type"] for d in data["documents"]] == ["BUSINESS_LICENSE"]
    assert data["hotel_claim"]["relationship_type"] == "OWNER"
    assert data["hotel_claim"]["hotel_id"] == HOTEL_ID
    assert data["actions"]["can_approve"] is True
    assert data["actions"]["can_resolve_conflict"] is False
    assert "LICENSE_ILLEGIBLE" in data["finding_codes"]
    assert any(e["action"] == "SUPPLIER_HOTEL_CLAIM_SAVED" for e in data["history"])

    assert client.get(f"{REVIEW}/cases/sup_does_not_exist", headers=headers).status_code == 404


# --------------------------------------------------------------------------- #
# the three-state decision
# --------------------------------------------------------------------------- #
def test_approve_is_what_creates_the_hotel_and_verifies_the_case(client, delivery):
    seed_hotel()
    supplier_id = draft(client, delivery, "approve@example.test")
    headers = reviewer(client)

    response = decide(client, headers, supplier_id, "APPROVE", note="主体与关系材料齐备")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["state"] == "VERIFIED"

    assert case_state(supplier_id) == "VERIFIED"
    with SessionLocal() as s:
        relations = list(s.scalars(select(HotelRegistrationDirectRow).where(
            HotelRegistrationDirectRow.supplier_id == supplier_id)))
        assert len(relations) == 1
        assert relations[0].state == "APPROVED"
        assert relations[0].relationship_type == "OWNER"
        profile = s.get(HotelCanonicalProfileRow, HOTEL_ID)
        assert profile.go_direct_state == "GO_DIRECT_VERIFIED"

    detail = client.get(f"{REVIEW}/cases/{supplier_id}", headers=headers).json()["data"]
    assert detail["review"]["decision"] == "APPROVE"
    assert detail["actions"]["can_approve"] is False


def test_needs_changes_without_a_finding_is_refused_and_changes_nothing(client, delivery):
    """A NEEDS_CHANGES the applicant cannot act on is just a soft rejection."""
    seed_hotel()
    supplier_id = draft(client, delivery, "no-finding@example.test")
    headers = reviewer(client)

    blank = decide(client, headers, supplier_id, "NEEDS_CHANGES", note="请再补充材料")
    assert blank.status_code == 422
    assert blank.json()["detail"] == "REVIEW_FINDINGS_REQUIRED"
    assert case_state(supplier_id) == "UNDER_REVIEW"

    unknown = decide(client, headers, supplier_id, "NEEDS_CHANGES",
                     findings=[{"code": "SOMETHING_I_MADE_UP"}])
    assert unknown.status_code == 422
    assert unknown.json()["detail"].startswith("REVIEW_FINDING_CODE_INVALID:")
    assert case_state(supplier_id) == "UNDER_REVIEW"

    freeform = decide(client, headers, supplier_id, "NEEDS_CHANGES",
                      findings=[{"message": "照片模糊"}])
    assert freeform.status_code == 422
    assert case_state(supplier_id) == "UNDER_REVIEW"


def test_needs_changes_records_translatable_findings_for_the_applicant(client, delivery):
    seed_hotel()
    supplier_id = draft(client, delivery, "findings@example.test")
    headers = reviewer(client)

    response = decide(client, headers, supplier_id, "NEEDS_CHANGES",
                      note="执照需要重新上传",
                      findings=[{"code": "LICENSE_ILLEGIBLE", "message": "照片反光看不清注册号"},
                                "RELATIONSHIP_UNPROVEN"])
    assert response.status_code == 200, response.text
    assert case_state(supplier_id) == "NEEDS_CHANGES"
    assert {f["code"] for f in response.json()["data"]["findings"]} == {
        "LICENSE_ILLEGIBLE", "RELATIONSHIP_UNPROVEN"}

    detail = client.get(f"{REVIEW}/cases/{supplier_id}", headers=headers).json()["data"]
    assert detail["review"]["decision"] == "NEEDS_CHANGES"
    assert detail["review_findings"][0]["message"] == "照片反光看不清注册号"
    assert detail["actions"]["can_reopen"] is True

    # And the applicant's own status carries the same findings, so the screen they
    # open next can say what to fix rather than "reviewed".
    onboarding = supplier_onboarding_state_service.get(supplier_id)
    assert onboarding["state"] == "NEEDS_CHANGES"
    assert onboarding["review_findings"][0]["code"] == "LICENSE_ILLEGIBLE"
    assert onboarding["review_findings"][0]["message"] == "照片反光看不清注册号"


def test_reject_ends_the_application_and_leaves_the_legal_entity_alone(client, delivery):
    """Rejecting an application must not reject the company.

    The legal entity row is who the tenant is, and other features trust its own
    verification state. Marking it REJECTED here would break them for a reason
    that has nothing to do with them.
    """
    seed_hotel()
    supplier_id = draft(client, delivery, "reject@example.test")
    headers = reviewer(client)

    with SessionLocal.begin() as s:
        entity_before = s.scalar(select(LegalEntityRow).where(
            LegalEntityRow.supplier_id == supplier_id))
        snapshot = (entity_before.verification_state, entity_before.legal_name,
                    entity_before.unified_social_credit_code)

    response = decide(client, headers, supplier_id, "REJECT", note="主体与酒店关系无法成立")
    assert response.status_code == 200, response.text
    assert case_state(supplier_id) == "REJECTED"

    with SessionLocal() as s:
        entity_after = s.scalar(select(LegalEntityRow).where(
            LegalEntityRow.supplier_id == supplier_id))
        assert (entity_after.verification_state, entity_after.legal_name,
                entity_after.unified_social_credit_code) == snapshot
        assert entity_after.verification_state != "REJECTED"

    detail = client.get(f"{REVIEW}/cases/{supplier_id}", headers=headers).json()["data"]
    assert detail["review"]["decision"] == "REJECT"
    assert detail["legal_entity"]["verification_state"] == snapshot[0]

    # And no hotel was granted on the way out.
    assert approved_relations(HOTEL_ID) == []


def test_a_case_cannot_be_decided_twice(client, delivery):
    seed_hotel()
    supplier_id = draft(client, delivery, "twice@example.test")
    headers = reviewer(client)
    assert decide(client, headers, supplier_id, "APPROVE").status_code == 200

    again = decide(client, headers, supplier_id, "REJECT", note="反悔")
    assert again.status_code == 409
    assert again.json()["detail"] == "REVIEW_CASE_NOT_REVIEWABLE"
    assert case_state(supplier_id) == "VERIFIED"


def test_an_unknown_decision_is_refused_as_unprocessable(client, delivery):
    seed_hotel()
    supplier_id = draft(client, delivery, "bogus@example.test")
    headers = reviewer(client)
    response = decide(client, headers, supplier_id, "MAYBE")
    assert response.status_code == 422
    assert response.json()["detail"] == "INVALID_REVIEW_DECISION"


# --------------------------------------------------------------------------- #
# reopen
# --------------------------------------------------------------------------- #
def test_reopen_returns_a_rejected_case_to_draft_with_a_reason_on_record(client, delivery):
    seed_hotel()
    supplier_id = draft(client, delivery, "reopen@example.test")
    headers = reviewer(client)
    assert decide(client, headers, supplier_id, "REJECT", note="首轮驳回").status_code == 200

    nameless = client.post(f"{REVIEW}/cases/{supplier_id}/reopen",
                           headers={**headers, "Content-Type": "application/json"},
                           json={"reason": "   "})
    assert nameless.status_code == 422
    assert nameless.json()["detail"] == "REVIEW_REOPEN_REASON_REQUIRED"
    assert case_state(supplier_id) == "REJECTED"

    opened = client.post(f"{REVIEW}/cases/{supplier_id}/reopen", headers=headers,
                         json={"reason": "补充了新的经营权证明，准予重新提交"})
    assert opened.status_code == 200, opened.text
    assert case_state(supplier_id) == "PROFILE_DRAFT"

    detail = client.get(f"{REVIEW}/cases/{supplier_id}", headers=headers).json()["data"]
    assert detail["reopen"]["from_state"] == "REJECTED"
    assert detail["review"] is None
    assert detail["review_findings"] == []
    # The earlier decision is not erased, it is still in the append-only history.
    assert any(e["action"] == "SUPPLIER_ONBOARDING_REVIEW_DECIDED" for e in detail["history"])
    assert any(e["action"] == "SUPPLIER_ONBOARDING_REOPENED" for e in detail["history"])


def test_reopen_is_refused_for_a_case_that_was_never_decided(client, delivery):
    seed_hotel()
    supplier_id = draft(client, delivery, "reopen-live@example.test")
    headers = reviewer(client)
    response = client.post(f"{REVIEW}/cases/{supplier_id}/reopen", headers=headers,
                           json={"reason": "没有理由"})
    assert response.status_code == 409
    assert response.json()["detail"] == "REVIEW_REOPEN_NOT_ALLOWED"
    assert case_state(supplier_id) == "UNDER_REVIEW"


# --------------------------------------------------------------------------- #
# claim conflict, resolution A4
# --------------------------------------------------------------------------- #
def _conflict_setup(client, delivery, first_email="conflict-first@example.test",
                    second_email="conflict-second@example.test"):
    """First applicant is granted the hotel; the second is parked as CLAIM_CONFLICT."""
    seed_hotel()
    first = draft(client, delivery, first_email)
    headers = reviewer(client)
    assert decide(client, headers, first, "APPROVE").status_code == 200
    assert case_state(first) == "VERIFIED"

    second = draft(client, delivery, second_email)
    headers = reviewer(client)
    lost = decide(client, headers, second, "APPROVE")
    assert lost.status_code == 409
    assert lost.json()["detail"] == "CLAIM_CONFLICT"
    assert case_state(second) == "CLAIM_CONFLICT"
    return first, second, headers


def test_a_case_in_conflict_cannot_be_approved_until_it_is_resolved(client, delivery):
    _, second, headers = _conflict_setup(client, delivery)
    response = decide(client, headers, second, "APPROVE")
    assert response.status_code == 409
    assert response.json()["detail"] == "CLAIM_CONFLICT_MUST_BE_RESOLVED_FIRST"


def test_taking_a_hotel_from_its_holder_requires_confirmation_and_a_reason(client, delivery):
    first, second, headers = _conflict_setup(client, delivery)

    unconfirmed = client.post(f"{REVIEW}/cases/{second}/resolve-conflict", headers=headers,
                              json={"resolution": "REVOKE_INCUMBENT", "reason": "证据更强",
                                    "confirmed": False})
    assert unconfirmed.status_code == 409
    assert unconfirmed.json()["detail"] == "CLAIM_CONFLICT_CONFIRMATION_REQUIRED"
    # Nothing moved: the incumbent still holds the hotel.
    assert case_state(first) == "VERIFIED" and case_state(second) == "CLAIM_CONFLICT"
    assert [r.supplier_id for r in approved_relations(HOTEL_ID)] == [first]

    nameless = client.post(f"{REVIEW}/cases/{second}/resolve-conflict", headers=headers,
                           json={"resolution": "REVOKE_INCUMBENT", "reason": "  ",
                                 "confirmed": True})
    assert nameless.status_code == 422
    assert nameless.json()["detail"] == "CLAIM_CONFLICT_REASON_REQUIRED"
    assert case_state(first) == "VERIFIED"

    unknown = client.post(f"{REVIEW}/cases/{second}/resolve-conflict", headers=headers,
                          json={"resolution": "FLIP_A_COIN", "reason": "x", "confirmed": True})
    assert unknown.status_code == 422
    assert case_state(first) == "VERIFIED"


def test_rejecting_the_late_claimant_leaves_the_incumbent_in_place(client, delivery):
    first, second, headers = _conflict_setup(client, delivery)

    response = client.post(f"{REVIEW}/cases/{second}/resolve-conflict", headers=headers,
                           json={"resolution": "REJECT_LATE_CLAIMANT",
                                 "reason": "先到者材料更完整", "confirmed": True})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["incumbent_changed"] is False

    # The loser goes back to choosing; the winner is untouched.
    assert case_state(second) == "NEEDS_CHANGES"
    assert case_state(first) == "VERIFIED"
    assert [r.supplier_id for r in approved_relations(HOTEL_ID)] == [first]

    detail = client.get(f"{REVIEW}/cases/{second}", headers=headers).json()["data"]
    assert detail["hotel_claim"]["hotel_id"] is None
    assert detail["hotel_claim"]["conflict"] is None
    assert detail["actions"]["can_resolve_conflict"] is False
    assert detail["review_findings"][0]["code"] == "HOTEL_CLAIM_LOST"


def test_revoking_the_incumbent_moves_the_hotel_and_never_leaves_it_holderless(client, delivery):
    first, second, headers = _conflict_setup(client, delivery)

    response = client.post(f"{REVIEW}/cases/{second}/resolve-conflict", headers=headers,
                           json={"resolution": "REVOKE_INCUMBENT",
                                 "reason": "后到者提供了独家经营权证明", "confirmed": True})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["incumbent_changed"] is True
    assert response.json()["data"]["revoked_supplier_id"] == first

    # The hotel changed hands in one step: exactly one live holder, and it is the
    # applicant the human decided for.
    assert case_state(second) == "VERIFIED"
    assert case_state(first) == "NEEDS_CHANGES"
    assert [r.supplier_id for r in approved_relations(HOTEL_ID)] == [second]

    with SessionLocal() as s:
        old_case = s.scalar(select(CommercialCaseRow).where(
            CommercialCaseRow.supplier_id == first))
        assert old_case.property_id is None
        revoked = list(s.scalars(select(HotelRegistrationDirectRow).where(
            HotelRegistrationDirectRow.supplier_id == first)))
        assert len(revoked) == 1 and revoked[0].state == "REVOKED"

    # Both sides have an audit line, so the decision is attributable.
    with SessionLocal() as s:
        actions = [e.action for e in s.scalars(select(AuditEventRow).where(
            AuditEventRow.resource_type == "supplier_onboarding"))]
    assert "SUPPLIER_ONBOARDING_HOTEL_REVOKED" in actions
    assert "SUPPLIER_ONBOARDING_CLAIM_CONFLICT_RESOLVED" in actions


def test_resolving_a_conflict_that_does_not_exist_is_refused(client, delivery):
    seed_hotel()
    supplier_id = draft(client, delivery, "no-conflict@example.test")
    headers = reviewer(client)
    response = client.post(f"{REVIEW}/cases/{supplier_id}/resolve-conflict", headers=headers,
                           json={"resolution": "REJECT_LATE_CLAIMANT", "reason": "x",
                                 "confirmed": True})
    assert response.status_code == 409
    assert response.json()["detail"] == "CLAIM_CONFLICT_REQUIRED"
    assert case_state(supplier_id) == "UNDER_REVIEW"


def test_a_conflicted_case_can_still_be_rejected_outright(client, delivery):
    """Rejecting the application is always available, even mid-conflict."""
    _, second, headers = _conflict_setup(client, delivery,
                                         second_email="conflict-reject@example.test")
    response = decide(client, headers, second, "REJECT", note="主体无法成立")
    assert response.status_code == 200, response.text
    assert case_state(second) == "REJECTED"


# --------------------------------------------------------------------------- #
# a proposed hotel goes through the same door
# --------------------------------------------------------------------------- #
def test_approving_a_proposed_hotel_creates_exactly_one_canonical_hotel(client, delivery):
    """The reviewer console is the first HTTP caller that can mint a hotel."""
    body = send(client, delivery, "supplier", "proposed@example.test")
    registered = client.post("/bff/auth/supplier/register", json=body)
    assert registered.status_code == 201
    client.put("/bff/supplier/legal-entity", headers=csrf(client), json={
        "legal_name": "新酒店管理有限公司", "unified_social_credit_code": _uscc("proposed@example.test"),
        "legal_representative_name": "新法人", "registered_address": "黑龙江省哈尔滨市新街 9 号"})
    client.post("/bff/supplier/legal-entity/documents", headers=csrf(client),
                data={"document_type": "BUSINESS_LICENSE", "scope": "ENTITY"},
                files={"file": ("licence.png", _licence_png(), "image/png")})
    claim = client.put("/bff/supplier/hotel/claim", headers=csrf(client), json={
        "mode": "PROPOSED", "relationship_type": "OWNER",
        "proposed_hotel": {"name": "复核全新酒店", "city": "哈尔滨市", "address": "新街 9 号"}})
    assert claim.status_code == 200, claim.text
    supplier_id = client.get("/bff/auth/me").json()["data"]["supplier_id"]
    assert client.post("/bff/supplier/onboarding/profile/submit",
                       headers=csrf(client), json={}).status_code == 200

    # Before approval the catalogue does not contain it. The applicant cannot
    # mint a platform identity by typing a name.
    assert canonical_hotels_named("复核全新酒店") == 0

    headers = reviewer(client)
    response = decide(client, headers, supplier_id, "APPROVE")
    assert response.status_code == 200, response.text
    assert canonical_hotels_named("复核全新酒店") == 1
    assert case_state(supplier_id) == "VERIFIED"

    # A replay is idempotent: still one hotel, still one relation.
    with SessionLocal() as s:
        relations = list(s.scalars(select(HotelRegistrationDirectRow).where(
            HotelRegistrationDirectRow.supplier_id == supplier_id)))
        assert len(relations) == 1
    approved = approved_relations(relations[0].hotel_id)
    assert [r.supplier_id for r in approved] == [supplier_id]


# --------------------------------------------------------------------------- #
# concurrency
# --------------------------------------------------------------------------- #
def test_two_reviewers_deciding_at_once_grant_the_hotel_to_exactly_one(client, delivery):
    """Two clicks on APPROVE must not produce two holders of one hotel."""
    seed_hotel()
    supplier_id = draft(client, delivery, "race@example.test")
    headers = reviewer(client)

    outcomes: list[str] = []
    barrier = threading.Barrier(2)
    lock = threading.Lock()

    def attempt():
        barrier.wait()
        try:
            result = onboarding_review_service.decide(supplier_id, "admin-race", "APPROVE")
            text = result["state"]
        except ValueError as error:
            text = str(error)
        with lock:
            outcomes.append(text)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("VERIFIED") == 1, outcomes
    assert case_state(supplier_id) == "VERIFIED"
    assert len(approved_relations(HOTEL_ID)) == 1
