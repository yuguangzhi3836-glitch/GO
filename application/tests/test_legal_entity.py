"""Batch 2 — legal entity (企业主体) and the frozen USCC rules.

Covers:
  * GB 32100-2015 validation: official worked example PASSes, negatives rejected
    with a distinct reason each;
  * canonicalisation trim -> upper -> validate (lower-case is accepted, not
    rejected) — frozen decision CHANGE 4;
  * GO-internal uniqueness of the credit code across supplier tenants;
  * one supplier tenant == one legal entity (frozen decision D-02);
  * the ``go_go_direct_state`` typo: a rejected hotel registration must actually
    reset the canonical profile's direct state instead of silently setting a
    stray Python attribute.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from go_hotel.db.models import (
    HotelCanonicalProfileRow,
    HotelRegistrationDirectRow,
    LegalEntityRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services import uscc
from go_hotel.services.legal_entity import legal_entity_service
from registration_terms_test_support import approved_terms_fixture, with_verification

OFFICIAL_USCC = "91350100M000100Y43"


def _payload(**overrides) -> dict:
    base = {
        "legal_name": "宁德时代新能源科技股份有限公司",
        "unified_social_credit_code": OFFICIAL_USCC,
        "legal_representative_name": "曾毓群",
        "registered_address": "福建省宁德市蕉城区漳湾镇新港路2号",
        "license_valid_from": "2024-01-01",
        "license_valid_until": "2034-01-01",
        "license_long_term": False,
    }
    base.update(overrides)
    return base


def _csrf(client) -> dict:
    """Cookie-authenticated unsafe verbs must echo the CSRF cookie in a header."""
    from go_hotel.core.config import settings

    return {"X-CSRF-Token": client.cookies.get(settings.csrf_cookie_name)}


def _register_supplier(client, monkeypatch, email: str) -> str:
    approved_terms_fixture(monkeypatch)
    policy = client.get("/bff/auth/supplier/registration-terms").json()["data"]
    # Sign-up collects three login identifiers and proves two channels; the
    # shared helper mints the challenges and returns the two codes, so the body
    # here only carries the account facts this suite is about.
    body = with_verification({
        "email": email,
        "password": "Isolated-test-pass-123",
        "accepted_terms": True,
        "term_versions": policy["versions"],
        "term_hashes": policy["term_hashes"],
        "registration_decisions": policy["required_decisions"],
        "organization_name": "隔离测试企业",
        "contact_name": "测试联系人",
    }, "supplier")
    response = client.post("/bff/auth/supplier/register", json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()["data"]["supplier_id"]


# --------------------------------------------------------------------------- #
# GB 32100-2015 validation
# --------------------------------------------------------------------------- #
def test_official_worked_example_passes():
    result = uscc.validate_uscc(OFFICIAL_USCC)
    assert result.ok is True
    assert result.reason is None
    assert result.value == OFFICIAL_USCC
    # The published check symbol must be reproducible from the first 17 chars.
    assert uscc.check_symbol(OFFICIAL_USCC[:17]) == OFFICIAL_USCC[17]


@pytest.mark.parametrize(
    "value,reason",
    [
        ("91350100M000100Y4", uscc.REASON_LENGTH),          # 17 chars
        (OFFICIAL_USCC + "3", uscc.REASON_LENGTH),          # 19 chars
        ("91350100M000100Y4O", uscc.REASON_CHARSET),        # 'O' is not in the 31-symbol set
        ("91350100M000100Y4S", uscc.REASON_CHARSET),        # 'S' is not in the 31-symbol set
        ("91350100M000100Y4J", uscc.REASON_CHECKSUM),       # valid charset, wrong check symbol
    ],
)
def test_invalid_codes_are_rejected_with_a_distinct_reason(value, reason):
    result = uscc.validate_uscc(value)
    assert result.ok is False
    assert result.reason == reason


def test_lowercase_input_is_accepted_and_canonicalised():
    # Frozen decision CHANGE 4: lowercase must never be a rejection reason.
    result = uscc.validate_uscc(OFFICIAL_USCC.lower())
    assert result.ok is True
    assert result.value == OFFICIAL_USCC


def test_structural_positions_are_advisory_only():
    # A non-digit registrar position must not block: there is no complete,
    # provable value set for the structural positions.
    hint = uscc.structural_hint("A1350100M000100Y43")
    assert hint == "USCC_STRUCTURE_REGISTRAR_NON_DIGIT"


# --------------------------------------------------------------------------- #
# service-level normalisation and uniqueness
# --------------------------------------------------------------------------- #
def test_normalise_trims_and_uppercases():
    clean = legal_entity_service.normalize_payload(
        _payload(
            legal_name="  测试企业  ",
            unified_social_credit_code="  " + OFFICIAL_USCC.lower() + " ",
        )
    )
    assert clean["legal_name"] == "测试企业"
    assert clean["unified_social_credit_code"] == OFFICIAL_USCC


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"legal_name": "   "}, "LEGAL_NAME_REQUIRED"),
        ({"unified_social_credit_code": ""}, "UNIFIED_SOCIAL_CREDIT_CODE_REQUIRED"),
        ({"unified_social_credit_code": "91350100M000100Y4"}, uscc.REASON_LENGTH),
        ({"unified_social_credit_code": "91350100M000100Y4J"}, uscc.REASON_CHECKSUM),
        ({"legal_representative_name": " "}, "LEGAL_REPRESENTATIVE_NAME_REQUIRED"),
        ({"registered_address": ""}, "REGISTERED_ADDRESS_REQUIRED"),
        ({"license_valid_from": "not-a-date"}, "LICENSE_VALIDITY_INVALID"),
        (
            {"license_valid_from": "2034-01-01", "license_valid_until": "2024-01-01"},
            "LICENSE_VALIDITY_INVALID",
        ),
    ],
)
def test_normalise_rejects_with_human_mappable_codes(overrides, reason):
    with pytest.raises(ValueError) as excinfo:
        legal_entity_service.normalize_payload(_payload(**overrides))
    assert str(excinfo.value) == reason


def test_licence_window_is_optional_on_this_step():
    # The applicant may not have the licence to hand yet; step one must still save.
    clean = legal_entity_service.normalize_payload(
        _payload(license_valid_from=None, license_valid_until=None)
    )
    assert clean["license_valid_from"] is None
    assert clean["license_valid_until"] is None
    assert clean["license_long_term"] is False


def test_long_term_clears_the_validity_window():
    clean = legal_entity_service.normalize_payload(
        _payload(license_long_term=True, license_valid_from="2024-01-01", license_valid_until="2034-01-01")
    )
    assert clean["license_long_term"] is True
    assert clean["license_valid_from"] is None
    assert clean["license_valid_until"] is None


def test_entity_is_persisted_in_canonical_form():
    saved = legal_entity_service.save(
        "sup-canonical",
        _payload(
            legal_name="  宁德时代新能源科技股份有限公司 ",
            unified_social_credit_code=" " + OFFICIAL_USCC.lower() + " ",
        ),
    )
    assert saved["unified_social_credit_code"] == OFFICIAL_USCC
    assert saved["verification_state"] == "PENDING"
    with SessionLocal() as session:
        row = session.scalar(select(LegalEntityRow).where(LegalEntityRow.supplier_id == "sup-canonical"))
        assert row is not None
        assert row.unified_social_credit_code == OFFICIAL_USCC
        assert row.verification_state == "PENDING"


def test_one_supplier_tenant_owns_exactly_one_legal_entity():
    first = legal_entity_service.save("sup-single", _payload())
    second = legal_entity_service.save("sup-single", _payload(legal_name="改名后企业"))
    assert first["legal_entity_id"] == second["legal_entity_id"]
    with SessionLocal() as session:
        count = session.scalar(
            select(func.count()).select_from(LegalEntityRow).where(LegalEntityRow.supplier_id == "sup-single")
        )
    assert count == 1


def test_same_credit_code_cannot_belong_to_two_suppliers():
    legal_entity_service.save("sup-first", _payload())
    with pytest.raises(ValueError) as excinfo:
        legal_entity_service.save("sup-second", _payload())
    assert str(excinfo.value) == "UNIFIED_SOCIAL_CREDIT_CODE_ALREADY_REGISTERED"


def test_editing_a_reviewed_entity_returns_it_to_the_queue():
    legal_entity_service.save("sup-requeue", _payload())
    legal_entity_service.mark_verified("sup-requeue", "REJECTED")
    refreshed = legal_entity_service.save("sup-requeue", _payload(legal_name="整改后企业"))
    assert refreshed["verification_state"] == "PENDING"


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #
def test_http_round_trip_normalises_and_hides_internal_ids(client, monkeypatch):
    _register_supplier(client, monkeypatch, "entity.roundtrip@example.test")
    assert client.get("/bff/supplier/legal-entity").json()["data"] is None

    response = client.put(
        "/bff/supplier/legal-entity",
        json=_payload(unified_social_credit_code=OFFICIAL_USCC.lower()),
        headers=_csrf(client),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["unified_social_credit_code"] == OFFICIAL_USCC
    # The applicant never supplies or sees a legal_entity_id in the request.
    assert "legal_entity_id" in data

    fetched = client.get("/bff/supplier/legal-entity").json()["data"]
    assert fetched["legal_entity_id"] == data["legal_entity_id"]
    assert fetched["legal_name"] == "宁德时代新能源科技股份有限公司"


def test_http_invalid_credit_code_returns_a_stable_code(client, monkeypatch):
    _register_supplier(client, monkeypatch, "entity.invalid@example.test")
    response = client.put(
        "/bff/supplier/legal-entity",
        json=_payload(unified_social_credit_code="91350100M000100Y4J"),
        headers=_csrf(client),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "INVALID_UNIFIED_SOCIAL_CREDIT_CODE_CHECKSUM"


def test_http_duplicate_credit_code_returns_a_stable_code(client, monkeypatch):
    legal_entity_service.save("sup-occupied", _payload())
    _register_supplier(client, monkeypatch, "entity.duplicate@example.test")
    response = client.put("/bff/supplier/legal-entity", json=_payload(), headers=_csrf(client))
    assert response.status_code == 409
    assert response.json()["detail"] == "UNIFIED_SOCIAL_CREDIT_CODE_ALREADY_REGISTERED"


def test_http_rejects_client_supplied_internal_ids(client, monkeypatch):
    _register_supplier(client, monkeypatch, "entity.forbidden@example.test")
    response = client.put(
        "/bff/supplier/legal-entity",
        json={**_payload(), "legal_entity_id": "le_forged", "supplier_id": "sup_forged"},
        headers=_csrf(client),
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# the go_go_direct_state typo
# --------------------------------------------------------------------------- #
def test_rejected_registration_actually_resets_canonical_go_direct_state():
    from go_hotel.services.hotel_autopage_factory import hotel_autopage_factory_service

    stamp = datetime.now(timezone.utc)
    with SessionLocal() as session:
        session.add(
            HotelCanonicalProfileRow(
                hotel_id="hotel-typo",
                slug="typo",
                canonical_json={},
                go_direct_state="GO_DIRECT_VERIFIED",
                created_at=stamp,
                updated_at=stamp,
            )
        )
        session.add(
            HotelRegistrationDirectRow(
                hotel_registration_direct_id="reg-typo",
                hotel_id="hotel-typo",
                supplier_id="sup-typo",
                state="SUBMITTED",
                evidence_json=[],
                official_supplement_json={},
                requested_by="owner",
                reviewed_by=None,
                created_at=stamp,
                reviewed_at=None,
            )
        )
        session.commit()

    hotel_autopage_factory_service.decide_registration_direct(
        "reg-typo", "reviewer", {"decision": "REJECT", "reason": "资料不符"}
    )

    with SessionLocal() as session:
        profile = session.get(HotelCanonicalProfileRow, "hotel-typo")
        registration = session.get(HotelRegistrationDirectRow, "reg-typo")
        # Before the fix this stayed at GO_DIRECT_VERIFIED, so a rejected hotel
        # could still pass the "hotel must already be GO_DIRECT" gate.
        assert profile.go_direct_state == "NOT_REGISTERED"
        assert registration.state == "REJECTED"
