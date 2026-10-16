from __future__ import annotations

from datetime import date, datetime, timezone
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from go_hotel.db.models import CommercialCaseRow, LegalEntityRow
from go_hotel.db.session import SessionLocal
from go_hotel.services.uscc import (
    REASON_CHARSET,
    REASON_CHECKSUM,
    REASON_LENGTH,
    normalize_uscc,
    validate_uscc,
)

# Human-mappable error codes. The frontend owns the copy; the backend never
# renders text. Codes stay stable because the UI maps them to Chinese sentences.
LEGAL_NAME_REQUIRED = "LEGAL_NAME_REQUIRED"
LEGAL_NAME_TOO_LONG = "LEGAL_NAME_TOO_LONG"
USCC_REQUIRED = "UNIFIED_SOCIAL_CREDIT_CODE_REQUIRED"
USCC_ALREADY_REGISTERED = "UNIFIED_SOCIAL_CREDIT_CODE_ALREADY_REGISTERED"
LEGAL_REP_REQUIRED = "LEGAL_REPRESENTATIVE_NAME_REQUIRED"
REGISTERED_ADDRESS_REQUIRED = "REGISTERED_ADDRESS_REQUIRED"
LICENSE_VALIDITY_INVALID = "LICENSE_VALIDITY_INVALID"
LEGAL_ENTITY_NOT_FOUND = "LEGAL_ENTITY_NOT_FOUND"

MAX_LEGAL_NAME = 200
MAX_LEGAL_REP = 80
MAX_REGISTERED_ADDRESS = 300

VERIFICATION_PENDING = "PENDING"
VERIFICATION_STATES = {"UNVERIFIED", "PENDING", "VERIFIED", "REJECTED"}


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValueError(LICENSE_VALIDITY_INVALID) from None


class LegalEntityService:
    """The legal person behind a supplier tenant (frozen decision D-02).

    One supplier tenant owns exactly one legal entity row. The identity user is
    the operator holding credentials today; it is deliberately NOT the legal
    entity. Conflating the two is what made the shipped path unusable.
    """

    def serialize(self, row: LegalEntityRow) -> dict:
        return {
            "legal_entity_id": row.legal_entity_id,
            "supplier_id": row.supplier_id,
            "legal_name": row.legal_name,
            "unified_social_credit_code": row.unified_social_credit_code,
            "legal_representative_name": row.legal_representative_name,
            "registered_address": row.registered_address,
            "license_valid_from": row.license_valid_from.isoformat() if row.license_valid_from else None,
            "license_valid_until": row.license_valid_until.isoformat() if row.license_valid_until else None,
            "license_long_term": bool(row.license_long_term),
            "verification_state": row.verification_state,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _row(self, session, supplier_id: str) -> LegalEntityRow | None:
        return session.scalar(
            select(LegalEntityRow).where(LegalEntityRow.supplier_id == supplier_id)
        )

    def get_for_supplier(self, supplier_id: str) -> dict | None:
        with SessionLocal() as session:
            row = self._row(session, supplier_id)
            return self.serialize(row) if row else None

    def normalize_payload(self, payload: dict) -> dict:
        """trim -> upper -> validate, in that order (frozen decision CHANGE 4).

        Lowercase input is accepted and normalised, never rejected. Only length,
        charset and checksum are hard blockers; structural positions are advisory
        because there is no complete provable value set for them.
        """
        legal_name = _text(payload.get("legal_name"), MAX_LEGAL_NAME)
        if not legal_name:
            raise ValueError(LEGAL_NAME_REQUIRED)
        if len(str(payload.get("legal_name") or "").strip()) > MAX_LEGAL_NAME:
            raise ValueError(LEGAL_NAME_TOO_LONG)

        raw_uscc = normalize_uscc(payload.get("unified_social_credit_code"))
        if not raw_uscc:
            raise ValueError(USCC_REQUIRED)
        result = validate_uscc(raw_uscc)
        if not result.ok:
            # Length / charset / checksum each get their own code so the human
            # sees "位数不对" vs "含非法字符" vs "校验位不对".
            raise ValueError(result.reason or REASON_CHARSET)

        legal_rep = _text(payload.get("legal_representative_name"), MAX_LEGAL_REP)
        if not legal_rep:
            raise ValueError(LEGAL_REP_REQUIRED)

        address = _text(payload.get("registered_address"), MAX_REGISTERED_ADDRESS)
        if not address:
            raise ValueError(REGISTERED_ADDRESS_REQUIRED)

        long_term = bool(payload.get("license_long_term"))
        valid_from = _parse_date(payload.get("license_valid_from"))
        valid_until = _parse_date(payload.get("license_valid_until"))
        if long_term:
            valid_from, valid_until = None, None
        elif valid_from is not None and valid_until is not None and valid_until < valid_from:
            # The window is optional on this step: the applicant often fills the
            # entity before they have the licence to hand (it is uploaded in the
            # next step). Only a self-contradictory range is refused — blocking a
            # save merely because a date is still unknown would stop a real user
            # from ever finishing step one.
            raise ValueError(LICENSE_VALIDITY_INVALID)

        return {
            "legal_name": legal_name,
            "unified_social_credit_code": result.value,
            "legal_representative_name": legal_rep,
            "registered_address": address,
            "license_valid_from": valid_from,
            "license_valid_until": valid_until,
            "license_long_term": long_term,
        }

    def save(self, supplier_id: str, payload: dict) -> dict:
        clean = self.normalize_payload(payload)
        now = _now()
        with SessionLocal() as session:
            row = self._row(session, supplier_id)
            owner = session.scalar(
                select(LegalEntityRow).where(
                    LegalEntityRow.unified_social_credit_code == clean["unified_social_credit_code"],
                    LegalEntityRow.supplier_id != supplier_id,
                )
            )
            if owner is not None:  # Layer 2: GO-internal uniqueness, D-03
                raise ValueError(USCC_ALREADY_REGISTERED)
            if row is None:
                row = LegalEntityRow(
                    legal_entity_id=_id("le"),
                    supplier_id=supplier_id,
                    verification_state=VERIFICATION_PENDING,
                    created_at=now,
                    updated_at=now,
                    **clean,
                )
                session.add(row)
            else:
                for key, value in clean.items():
                    setattr(row, key, value)
                if row.verification_state not in {VERIFICATION_PENDING, "UNVERIFIED"}:
                    # Correcting an entity that a reviewer already touched puts it
                    # back in the queue instead of silently keeping a stale verdict.
                    row.verification_state = VERIFICATION_PENDING
                row.updated_at = now

            # Keep the onboarding case in step with the entity without inventing
            # a second source of truth for the legal entity itself.
            case = session.scalar(
                select(CommercialCaseRow).where(
                    CommercialCaseRow.case_type == "SUPPLIER_ONBOARDING",
                    CommercialCaseRow.supplier_id == supplier_id,
                )
            )
            if case is not None and case.state == "REGISTERED":
                case.state = "PROFILE_DRAFT"
                case.updated_at = now

            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if session.scalar(
                    select(LegalEntityRow).where(
                        LegalEntityRow.unified_social_credit_code == clean["unified_social_credit_code"],
                        LegalEntityRow.supplier_id != supplier_id,
                    )
                ):
                    raise ValueError(USCC_ALREADY_REGISTERED) from None
                raise
            session.refresh(row)
            return self.serialize(row)

    def mark_verified(self, supplier_id: str, state: str) -> dict:
        """Reviewer-side verdict on the entity itself (never on the relationship)."""
        state = str(state or "").upper()
        if state not in VERIFICATION_STATES:
            raise ValueError("INVALID_LEGAL_ENTITY_VERIFICATION_STATE")
        with SessionLocal() as session:
            row = self._row(session, supplier_id)
            if row is None:
                raise ValueError(LEGAL_ENTITY_NOT_FOUND)
            row.verification_state = state
            row.updated_at = _now()
            session.commit()
            session.refresh(row)
            return self.serialize(row)


legal_entity_service = LegalEntityService()
