"""Batch 6 — the contract step: template, signed scan, one atomic confirmation.

What these tests insist on, beyond "the route answers":

  * the confirmation records every CHANGE 11 field, and it is written in the same
    transaction as CONTRACT_ACTIVE — so there is never a supplier with business
    access and no recorded agreement, nor a recorded agreement and no access;
  * a template hash that is not the one being served is refused, because "I agreed
    to the text I read" is the only thing the hash is for;
  * a double-click is not a second governance act;
  * the *old* contract path — a typed reference string plus an administrator's
    verdict — cannot be called any more;
  * the dead state CONTRACT_PENDING is gone from the workflow while the storage
    predicate that must tolerate legacy rows is untouched.

The fixture has to alternate between two sessions on one HTTP client: the applicant
registers and files evidence, a GO_GOVERNANCE reviewer approves the claim, and then
the applicant comes back to sign. The applicant's password is therefore kept, and the
session is re-established rather than assumed.
"""
from __future__ import annotations

import hashlib
import io
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from go_hotel.db.models import (
    AuditEventRow,
    CommercialCaseRow,
    HotelCanonicalProfileRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.security.mfa import totp
from go_hotel.security.service import identity_service
from go_hotel.services import onboarding_contract as contract_module
from go_hotel.services.document_store import document_store
from go_hotel.services.onboarding_hotel import LIVE_CASE_STATES
from go_hotel.services.supplier_onboarding_state import _next_step
from test_registration_verification import send, delivery  # noqa: F401  (fixtures)
from supplier_document_upload import upload_document

HOTEL_ID = "hotel_contract_seed"
CONTRACT = "/bff/supplier/onboarding/contract"
REAL_TEMPLATE_DIR = contract_module.CONTRACT_DIR
TEMPLATE_VERSION = contract_module.TEMPLATE_VERSION


@pytest.fixture(autouse=True)
def _private_volume(tmp_path, monkeypatch):
    """Uploaded evidence and a swapped template must never land in the repo tree."""
    monkeypatch.setattr(document_store, "root", tmp_path / "supplier_documents")


def _licence_png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (240, 160), (30, 90, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


def _signed_pdf() -> bytes:
    """A real PDF: the document store sniffs the leading bytes and would refuse
    anything else, so a fake upload would prove nothing."""
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


def _uscc(seed: str) -> str:
    """A checksum-valid USCC derived from a seed, so two applicants differ.

    One credit code identifies one legal entity, so every applicant here needs their
    own; reusing a constant would hide a broken validator behind a 409.
    """
    from go_hotel.services.uscc import CODE_CHARS, WEIGHTS

    clean = "".join(c for c in seed.upper() if c in CODE_CHARS) or "A"
    body = ("91350100" + clean)[:17].ljust(17, "0")
    total = sum(CODE_CHARS.index(c) * w for c, w in zip(body, WEIGHTS))
    return body + CODE_CHARS[(31 - total % 31) % 31]


def csrf(client):
    return {"X-CSRF-Token": client.cookies.get("go_csrf")}


def reviewer(client) -> dict:
    """A real GO_GOVERNANCE session, enrolled through the real MFA flow."""
    client.cookies.clear()
    name = f"contract-reviewer-{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(24)
    identity_service.create_user(name, password, "GO_ADMIN", None, ["GO_GOVERNANCE"])
    enrollment = client.post(
        "/bff/auth/mfa/enroll/start", json={"username": name, "password": password}
    ).json()["data"]
    confirmed = client.post("/bff/auth/mfa/enroll/confirm", json={
        "enrollment_token": enrollment["enrollment_token"], "code": totp(enrollment["secret"])})
    assert confirmed.status_code == 200, confirmed.text
    return {"X-GO-Actor": "GO_ADMIN", **csrf(client)}


def seed_hotel(hotel_id: str = HOTEL_ID, name: str = "合同测试酒店"):
    """A canonical hotel to claim. Idempotent, because several tests share the id."""
    now = datetime.now(timezone.utc)
    with SessionLocal.begin() as s:
        if s.get(HotelCanonicalProfileRow, hotel_id) is not None:
            return
        s.add(HotelCanonicalProfileRow(
            hotel_id=hotel_id, slug=f"seed-{hotel_id}",
            canonical_json={"name": name,
                            "address": {"city": "哈尔滨市", "formatted": "哈尔滨市测试街道 1 号"}},
            field_provenance_json={}, source_snapshot_ids_json=[], completeness_bps=0,
            go_direct_state="NOT_REGISTERED", page_state="DRAFT", version=1,
            created_at=now, updated_at=now,
        ))


def register_and_fill(client, body) -> str:
    """The applicant's own steps, through the applicant's own routes."""
    registered = client.post("/bff/auth/supplier/register", json=body)
    assert registered.status_code == 201, registered.text
    saved = client.put("/bff/supplier/legal-entity", headers=csrf(client), json={
        "legal_name": "合同测试酒店管理有限公司", "unified_social_credit_code": _uscc(body["email"]),
        "legal_representative_name": "合同法人", "registered_address": "黑龙江省哈尔滨市测试街道 1 号",
    })
    assert saved.status_code == 200, saved.text
    uploaded = upload_document(client, _licence_png(), filename="licence.png", mime="image/png",
                               headers=csrf(client), document_type="BUSINESS_LICENSE", scope="ENTITY")
    assert uploaded.status_code == 201, uploaded.text
    claim = client.put("/bff/supplier/hotel/claim", headers=csrf(client), json={
        "mode": "EXISTING", "relationship_type": "OWNER", "hotel_id": HOTEL_ID})
    assert claim.status_code == 200, claim.text
    submitted = client.post("/bff/supplier/onboarding/profile/submit",
                            headers=csrf(client), json={})
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["data"]["state"] == "UNDER_REVIEW"
    return client.get("/bff/auth/me").json()["data"]["supplier_id"]


def login_supplier(client, body) -> None:
    client.cookies.clear()
    logged = client.post("/bff/auth/login", json={
        "username": body["email"], "password": body["password"],
        "expected_actor_type": "SUPPLIER_USER"})
    assert logged.status_code == 200, logged.text


def verified_case(client, delivery, email: str) -> str:
    """A case in VERIFIED, with the applicant's session live when this returns."""
    seed_hotel()
    body = send(client, delivery, "supplier", email)
    supplier_id = register_and_fill(client, body)

    headers = reviewer(client)
    approved = client.post(f"/internal/v1/onboarding-review/cases/{supplier_id}/decision",
                           headers=headers, json={"decision": "APPROVE"})
    assert approved.status_code == 200, approved.text
    assert case_state(supplier_id) == "VERIFIED"

    login_supplier(client, body)
    return supplier_id


def case_state(supplier_id: str) -> str:
    with SessionLocal() as s:
        row = s.scalar(select(CommercialCaseRow).where(
            CommercialCaseRow.case_type == "SUPPLIER_ONBOARDING",
            CommercialCaseRow.supplier_id == supplier_id))
        assert row is not None
        return row.state


def confirmations(supplier_id: str) -> list[AuditEventRow]:
    with SessionLocal() as s:
        return list(s.scalars(select(AuditEventRow).where(
            AuditEventRow.action == "SUPPLIER_CONTRACT_CONFIRMED",
            AuditEventRow.supplier_id == supplier_id)))


def upload_signed(client, payload: bytes | None = None):
    return upload_document(client, payload or _signed_pdf(), filename="signed.pdf",
                           mime="application/pdf", headers=csrf(client),
                           document_type="SIGNED_CONTRACT", scope="ONBOARDING")


def current_template_sha(client) -> str:
    return client.get(CONTRACT).json()["data"]["template"]["sha256"]


def confirm(client, **overrides):
    body = {"agreed": True}
    # Only ask the server for the current hash when the caller is not supplying one:
    # in the tampered-template test the whole point is that this call fails.
    if "template_sha256" not in overrides:
        body["template_sha256"] = current_template_sha(client)
    body.update(overrides)
    return client.post(f"{CONTRACT}/confirm", headers=csrf(client), json=body)


# --------------------------------------------------------------------------- #
# the template asset
# --------------------------------------------------------------------------- #
def test_the_shipped_template_is_self_consistent_and_declared_as_a_fixture(client, delivery):
    """The bytes, the manifest hash and the "this is not a contract" marking agree.

    Without a real approved agreement there is nothing to ship; what must not happen
    is shipping something that *looks* like one. So the fixture proves itself: the
    file's own text carries the TEST marking, and the manifest says out loud which
    external asset is missing.
    """
    supplier_id = verified_case(client, delivery, "template-check@example.test")
    state = client.get(CONTRACT).json()["data"]
    template = state["template"]
    assert template["version"] == TEMPLATE_VERSION
    assert template["source"] == "TEST"
    assert template["marking"] == "LOCAL_TEST_CONTRACT_FIXTURE"
    assert template["is_test_fixture"] is True
    assert template["blocked_external_asset"] == "PRODUCTION_CONTRACT_TEMPLATE_REQUIRED"

    served = client.get(f"{CONTRACT}/template")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("application/pdf")
    assert hashlib.sha256(served.content).hexdigest() == template["sha256"]
    # The marking is inside the served bytes, not only in a JSON field.
    assert b"LOCAL TEST FIXTURE" in served.content
    assert supplier_id


def test_the_template_cannot_be_read_without_a_session(client):
    client.cookies.clear()
    assert client.get(f"{CONTRACT}/template").status_code in (401, 403)
    assert client.get(CONTRACT).status_code in (401, 403)


def test_a_swapped_template_is_refused_rather_than_served(client, delivery, tmp_path, monkeypatch):
    """Byte tampering under an unchanged manifest is a hard error.

    A template whose hash no longer matches what the platform recorded is worse than
    a missing one: the applicant would be asked to confirm a text nobody can identify
    afterwards. The state call reports it as a blocker instead of raising, so the page
    still renders and the human is told it is not their fault.
    """
    supplier_id = verified_case(client, delivery, "tamper@example.test")

    target = tmp_path / "legal" / "contract" / TEMPLATE_VERSION
    target.mkdir(parents=True)
    real = REAL_TEMPLATE_DIR / TEMPLATE_VERSION
    manifest = json.loads((real / "template.json").read_text(encoding="utf-8"))
    (target / "template.json").write_text(json.dumps(manifest), encoding="utf-8")
    (target / manifest["filename"]).write_bytes(b"%PDF-1.4 tampered\n%%EOF\n")
    monkeypatch.setattr(contract_module, "CONTRACT_DIR", tmp_path / "legal" / "contract")

    assert client.get(f"{CONTRACT}/template").status_code == 503
    state = client.get(CONTRACT).json()["data"]
    assert state["template"] is None
    assert "CONTRACT_TEMPLATE_UNAVAILABLE" in state["blockers"]
    assert state["can_confirm"] is False
    assert confirm(client, template_sha256=manifest["sha256"]).status_code == 503
    assert case_state(supplier_id) == "VERIFIED"


def test_a_missing_manifest_is_refused_rather_than_served(client, delivery, tmp_path, monkeypatch):
    verified_case(client, delivery, "no-manifest@example.test")
    (tmp_path / "legal" / "contract" / TEMPLATE_VERSION).mkdir(parents=True)
    monkeypatch.setattr(contract_module, "CONTRACT_DIR", tmp_path / "legal" / "contract")
    assert client.get(f"{CONTRACT}/template").status_code == 503
    assert "CONTRACT_TEMPLATE_UNAVAILABLE" in client.get(CONTRACT).json()["data"]["blockers"]


# --------------------------------------------------------------------------- #
# the contract screen
# --------------------------------------------------------------------------- #
def test_the_contract_step_is_closed_until_the_case_is_verified(client, delivery):
    body = send(client, delivery, "supplier", "too-early@example.test")
    assert client.post("/bff/auth/supplier/register", json=body).status_code == 201
    state = client.get(CONTRACT).json()["data"]
    assert state["state"] == "REGISTERED"
    assert state["can_confirm"] is False
    assert "CONTRACT_NOT_CONFIRMABLE" in state["blockers"]
    refused = client.post(f"{CONTRACT}/confirm", headers=csrf(client),
                          json={"agreed": True, "template_sha256": "x"})
    assert refused.status_code in (409, 422)


def test_the_screen_lists_what_is_missing_before_the_signed_scan_exists(client, delivery):
    verified_case(client, delivery, "no-scan@example.test")
    state = client.get(CONTRACT).json()["data"]
    assert state["state"] == "VERIFIED"
    assert state["signed_document"] is None
    assert state["legal_entity"]["legal_name"] == "合同测试酒店管理有限公司"
    assert state["hotel"]["hotel_id"] == HOTEL_ID
    assert state["hotel"]["name"] == "合同测试酒店"
    assert state["can_confirm"] is False
    assert state["blockers"] == ["CONTRACT_SIGNED_DOCUMENT_REQUIRED"]


# --------------------------------------------------------------------------- #
# the four refusals
# --------------------------------------------------------------------------- #
def test_confirming_without_agreeing_is_unprocessable_and_changes_nothing(client, delivery):
    supplier_id = verified_case(client, delivery, "no-agree@example.test")
    upload_signed(client)
    response = confirm(client, agreed=False)
    assert response.status_code == 422
    assert response.json()["detail"] == "CONTRACT_AGREEMENT_REQUIRED"
    assert case_state(supplier_id) == "VERIFIED"
    assert confirmations(supplier_id) == []


def test_confirming_a_template_version_that_is_not_the_current_one_is_refused(client, delivery):
    """The hash is the whole point: it is what makes "I read this text" checkable."""
    supplier_id = verified_case(client, delivery, "stale-hash@example.test")
    upload_signed(client)
    response = confirm(client, template_sha256="0" * 64)
    assert response.status_code == 409
    assert response.json()["detail"] == "CONTRACT_TEMPLATE_CHANGED"
    assert case_state(supplier_id) == "VERIFIED"
    assert confirmations(supplier_id) == []


def test_confirming_without_the_signed_scan_is_refused(client, delivery):
    supplier_id = verified_case(client, delivery, "scan-required@example.test")
    response = confirm(client)
    assert response.status_code == 409
    assert response.json()["detail"] == "CONTRACT_SIGNED_DOCUMENT_REQUIRED"
    assert confirmations(supplier_id) == []


def test_confirming_a_document_that_has_since_been_replaced_is_refused(client, delivery):
    """A verdict must not land on a file the applicant has already swapped out."""
    supplier_id = verified_case(client, delivery, "swapped@example.test")
    first = upload_signed(client).json()["data"]["document_id"]
    second = upload_signed(client, _signed_pdf() + b"\n% second revision\n").json()["data"]
    assert second["revision"] == 2

    stale = confirm(client, signed_document_id=first)
    assert stale.status_code == 409
    assert stale.json()["detail"] == "CONTRACT_SIGNED_DOCUMENT_INVALID"
    assert confirmations(supplier_id) == []

    good = confirm(client, signed_document_id=second["document_id"])
    assert good.status_code == 200, good.text


# --------------------------------------------------------------------------- #
# the one write
# --------------------------------------------------------------------------- #
def test_confirmation_records_every_change_11_field_and_activates_in_one_step(client, delivery):
    supplier_id = verified_case(client, delivery, "activate@example.test")
    assert client.get("/v1/supplier/dashboard").status_code == 403

    signed = upload_signed(client).json()["data"]
    response = confirm(client, signed_document_id=signed["document_id"])
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["state"] == "CONTRACT_ACTIVE"
    assert data["activated"] is True
    assert data["business_ready"] is True

    events = confirmations(supplier_id)
    assert len(events) == 1, "exactly one governance record for one confirmation"
    after = events[0].after_state
    assert set(after) == {
        "template_version", "template_sha256", "signed_document_id",
        "signed_document_sha256", "legal_entity_id", "hotel_id",
        "registration_direct_id", "confirmed_by", "confirmed_at",
    }, "CHANGE 11 names the fields; a single opaque body_sha256 is not allowed"
    assert after["hotel_id"] == HOTEL_ID
    assert after["signed_document_id"] == signed["document_id"]
    assert after["signed_document_sha256"] == signed["sha256"]
    assert after["template_version"] == TEMPLATE_VERSION
    assert after["template_sha256"] == data["template"]["sha256"]
    assert after["registration_direct_id"]
    assert after["confirmed_by"] == events[0].actor_id
    # The audit event is attributed to the applicant, not to the platform.
    assert events[0].actor_type == "SUPPLIER_USER"

    with SessionLocal() as s:
        row = s.scalar(select(CommercialCaseRow).where(
            CommercialCaseRow.supplier_id == supplier_id))
        assert row.payload_json["contract_confirmation"]["signed_document_id"] == signed["document_id"]

    # Activation is what unlocks the business console, and it is the same act.
    assert client.get("/v1/supplier/dashboard").status_code == 200


def test_a_double_click_does_not_write_a_second_governance_record(client, delivery):
    supplier_id = verified_case(client, delivery, "double@example.test")
    signed = upload_signed(client).json()["data"]
    assert confirm(client, signed_document_id=signed["document_id"]).status_code == 200
    again = confirm(client, signed_document_id=signed["document_id"])
    assert again.status_code == 200, again.text
    assert again.json()["data"]["already_confirmed"] is True
    assert len(confirmations(supplier_id)) == 1


def test_covering_an_activated_contract_with_a_different_document_is_refused(client, delivery):
    supplier_id = verified_case(client, delivery, "resubmit@example.test")
    signed = upload_signed(client).json()["data"]
    assert confirm(client, signed_document_id=signed["document_id"]).status_code == 200
    other = upload_signed(client, _signed_pdf() + b"\n% different revision\n").json()["data"]
    refused = confirm(client, signed_document_id=other["document_id"])
    assert refused.status_code == 409
    assert refused.json()["detail"] == "CONTRACT_NOT_CONFIRMABLE"
    assert len(confirmations(supplier_id)) == 1


def test_the_business_console_stays_shut_until_the_contract_is_confirmed(client, delivery):
    """The 403 is the product boundary; its code is what the UI turns into a sentence."""
    verified_case(client, delivery, "gate@example.test")
    blocked = client.get("/v1/supplier/dashboard")
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "SUPPLIER_ONBOARDING_INCOMPLETE"


def test_a_legacy_business_enabled_case_still_reads_as_activated(client, delivery):
    """BUSINESS_ENABLED is no longer written, but a stored row must keep working."""
    supplier_id = verified_case(client, delivery, "legacy@example.test")
    with SessionLocal.begin() as s:
        row = s.scalar(select(CommercialCaseRow).where(
            CommercialCaseRow.supplier_id == supplier_id))
        row.state = "BUSINESS_ENABLED"
    assert client.get(CONTRACT).json()["data"]["activated"] is True
    assert client.get("/v1/supplier/dashboard").status_code == 200


def test_a_legacy_contract_under_review_case_can_still_finish_the_new_step(client, delivery):
    """A case an older version left waiting for a contract review is not stranded.

    CONTRACT_UNDER_REVIEW was written by the pre-Batch-6 flow, so it can exist in a
    live database. Its applicant has to be able to finish — and redoing the step is
    right anyway, because the old flow took a typed reference string rather than the
    signed scan itself.
    """
    supplier_id = verified_case(client, delivery, "legacy-review@example.test")
    with SessionLocal.begin() as s:
        row = s.scalar(select(CommercialCaseRow).where(
            CommercialCaseRow.supplier_id == supplier_id))
        row.state = "CONTRACT_UNDER_REVIEW"
    upload_signed(client)
    assert client.get(CONTRACT).json()["data"]["can_confirm"] is True
    assert confirm(client).status_code == 200
    assert case_state(supplier_id) == "CONTRACT_ACTIVE"


# --------------------------------------------------------------------------- #
# 我的酒店
# --------------------------------------------------------------------------- #
def test_my_hotel_reports_stored_facts_and_the_first_thing_to_do(client, delivery):
    verified_case(client, delivery, "my-hotel@example.test")
    signed = upload_signed(client).json()["data"]
    assert confirm(client, signed_document_id=signed["document_id"]).status_code == 200

    data = client.get("/bff/supplier/my-hotel").json()["data"]
    assert data["business_ready"] is True
    assert data["hotel"]["hotel_id"] == HOTEL_ID
    assert data["hotel"]["claimed"] is True
    assert data["hotel"]["name"] == "合同测试酒店"
    assert data["hotel"]["city"] == "哈尔滨市"
    assert data["hotel"]["completeness_bps"] == 0
    # The page is still a draft and GO Direct is not live, so there is work to do and
    # the screen has to be able to name it.
    assert "PUBLISH_HOTEL_PAGE" in data["hotel"]["todo"]
    assert data["contract"]["template_version"] == TEMPLATE_VERSION


# --------------------------------------------------------------------------- #
# the removed dead ends
# --------------------------------------------------------------------------- #
def test_the_typed_reference_contract_path_is_gone(client, delivery):
    """The old flow accepted a string as proof of signature, then waited for an admin.

    Both halves were removed on purpose, so neither route may answer any more — a
    typed reference is not evidence and there is no contract reviewer (D-003).
    """
    supplier_id = verified_case(client, delivery, "old-path@example.test")
    # The path still exists as a GET (the step's state); a POST is no longer a route.
    assert client.post(CONTRACT, headers=csrf(client),
                       json={"contract_ref": "upload://signed/1"}).status_code == 405
    decision = client.post(
        f"/internal/v1/supplier-onboarding/{supplier_id}/contract-decision",
        headers=csrf(client), json={"decision": "APPROVE", "note": "合同通过"})
    assert decision.status_code == 404


def test_the_dead_state_is_out_of_the_workflow_and_the_storage_predicate_kept(client, delivery):
    """CONTRACT_PENDING is cleaned from the workflow, not from the index predicate.

    Nothing has ever assigned that token, so it must not appear in any transition or
    next-step answer any more. It stays inside `LIVE_CASE_STATES` on purpose: that
    tuple is the WHERE clause of a partial unique index, whose job is also to cover
    rows written by older versions — rebuilding it would buy nothing.
    """
    assert _next_step("CONTRACT_PENDING") == "CONTACT_SUPPORT"
    assert "CONTRACT_PENDING" in LIVE_CASE_STATES

    # No module under go_hotel may assign the token to a state any more.
    root = Path(__file__).resolve().parents[1] / "src" / "go_hotel"
    offenders = [
        f"{path.relative_to(root)}:{number}"
        for path in root.rglob("*.py")
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "= \"CONTRACT_PENDING\"" in line or "= 'CONTRACT_PENDING'" in line
    ]
    assert offenders == [], offenders

    # The states an earlier version really did write are still understood, because
    # their rows can still be in a live database.
    assert _next_step("CONTRACT_UNDER_REVIEW") == "SUBMIT_CONTRACT"
    assert _next_step("CONTRACT_NEEDS_CHANGES") == "CORRECT_CONTRACT"


def test_both_unique_index_predicates_still_cover_every_live_state(client, delivery):
    """The index a fresh database is born with must list the same states.

    `commercial_case` is created from the live declarative metadata by an old
    revision, so the model's predicate and migration 0148's predicate are two copies
    of one rule that must not drift.
    """
    index = next(i for i in CommercialCaseRow.__table__.indexes
                 if i.name == "uq_commercial_case_live_onboarding_hotel")
    predicate = str(index.dialect_options["postgresql"]["where"])
    migration = (Path(__file__).resolve().parents[1] / "alembic" / "versions"
                 / "0148_onboarding_constraints.py").read_text(encoding="utf-8")
    for token in LIVE_CASE_STATES:
        assert token in predicate, token
        assert token in migration, token
    assert "CONTRACT_PENDING" in predicate
