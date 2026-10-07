from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import select

from go_hotel.db.models import CommercialCaseRow, HotelRegistrationDirectRow, HotelCanonicalProfileRow
from go_hotel.db.session import SessionLocal

CASE_TYPE = "SUPPLIER_ONBOARDING"
PROFILE_EDITABLE = {"REGISTERED", "PROFILE_DRAFT", "NEEDS_CHANGES"}
PROFILE_SUBMITTABLE = {"PROFILE_DRAFT", "NEEDS_CHANGES"}
CONTRACT_SUBMITTABLE = {"VERIFIED", "CONTRACT_NEEDS_CHANGES"}
BUSINESS_READY = {"CONTRACT_ACTIVE", "BUSINESS_ENABLED"}
REQUIRED_PROFILE_FIELDS = {
    "organization_name", "hotel_name", "contact_name", "business_license_ref",
    "legal_representative_name", "identity_document_ref", "storefront_photo_ref",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _next_step(state: str) -> str:
    return {
        "REGISTERED": "COMPLETE_PROFILE",
        "PROFILE_DRAFT": "COMPLETE_PROFILE",
        "NEEDS_CHANGES": "CORRECT_PROFILE",
        "UNDER_REVIEW": "WAIT_PROFILE_REVIEW",
        "VERIFIED": "SUBMIT_CONTRACT",
        "CONTRACT_PENDING": "SUBMIT_CONTRACT",
        "CONTRACT_NEEDS_CHANGES": "CORRECT_CONTRACT",
        "CONTRACT_UNDER_REVIEW": "WAIT_CONTRACT_REVIEW",
        "CONTRACT_ACTIVE": "BUSINESS_CONSOLE",
        "BUSINESS_ENABLED": "BUSINESS_CONSOLE",
    }.get(state, "CONTACT_SUPPORT")


class SupplierOnboardingStateService:
    def _row(self, session, supplier_id: str) -> CommercialCaseRow | None:
        return session.scalar(
            select(CommercialCaseRow).where(
                CommercialCaseRow.case_type == CASE_TYPE,
                CommercialCaseRow.supplier_id == supplier_id,
            )
        )

    def serialize(self, row: CommercialCaseRow) -> dict:
        payload = dict(row.payload_json or {})
        return {
            "supplier_id": row.supplier_id,
            "state": row.state,
            "next_step": _next_step(row.state),
            "business_ready": row.state in BUSINESS_READY,
            "hotel_id": payload.get("hotel_id"),
            "hotel_registration_direct_id": payload.get("hotel_registration_direct_id"),
            "profile": dict(payload.get("profile") or {}),
            "contract": dict(payload.get("contract") or {}),
            "review_note": payload.get("review_note"),
            "contract_review_note": payload.get("contract_review_note"),
            "submitted_at": payload.get("submitted_at"),
            "reviewed_at": payload.get("reviewed_at"),
            "contract_submitted_at": payload.get("contract_submitted_at"),
            "contract_reviewed_at": payload.get("contract_reviewed_at"),
            "updated_at": row.updated_at.isoformat(),
        }

    def get(self, supplier_id: str) -> dict | None:
        with SessionLocal() as s:
            row = self._row(s, supplier_id)
            return self.serialize(row) if row else None

    def save_profile(self, supplier_id: str, profile: dict) -> dict:
        with SessionLocal() as s:
            row = self._row(s, supplier_id)
            if not row:
                raise ValueError("SUPPLIER_ONBOARDING_NOT_FOUND")
            if row.state not in PROFILE_EDITABLE:
                raise ValueError("SUPPLIER_PROFILE_NOT_EDITABLE")
            payload = dict(row.payload_json or {})
            clean = {str(k): v for k, v in profile.items() if v not in (None, "")}
            payload["profile"] = {**(payload.get("profile") or {}), **clean}
            row.payload_json = payload
            row.state = "PROFILE_DRAFT"
            row.updated_at = _now()
            s.commit(); s.refresh(row)
            return self.serialize(row)

    def submit_profile(self, supplier_id: str) -> dict:
        with SessionLocal() as s:
            row = self._row(s, supplier_id)
            if not row:
                raise ValueError("SUPPLIER_ONBOARDING_NOT_FOUND")
            if row.state not in PROFILE_SUBMITTABLE:
                raise ValueError("SUPPLIER_PROFILE_NOT_SUBMITTABLE")
            payload = dict(row.payload_json or {})
            profile = payload.get("profile") or {}
            missing = sorted(k for k in REQUIRED_PROFILE_FIELDS if not str(profile.get(k) or "").strip())
            if missing:
                raise ValueError("SUPPLIER_PROFILE_INCOMPLETE:" + ",".join(missing))
            now = _now()
            row.state = "UNDER_REVIEW"
            payload["submitted_at"] = _iso(now)
            payload["review_note"] = None
            row.payload_json = payload
            row.updated_at = now
            s.commit(); s.refresh(row)
            return self.serialize(row)

    def decide_profile(self, supplier_id: str, actor: str, decision: str, note: str | None = None, registration_direct_id: str | None = None) -> dict:
        with SessionLocal() as s:
            row = self._row(s, supplier_id)
            if not row or row.state != "UNDER_REVIEW":
                raise ValueError("SUPPLIER_PROFILE_NOT_REVIEWABLE")
            decision = str(decision or "").upper()
            if decision not in {"APPROVE", "NEEDS_CHANGES"}:
                raise ValueError("INVALID_SUPPLIER_PROFILE_DECISION")
            payload = dict(row.payload_json or {})
            if decision == "APPROVE":
                registration = s.get(HotelRegistrationDirectRow, registration_direct_id) if registration_direct_id else None
                profile = s.get(HotelCanonicalProfileRow, registration.hotel_id) if registration else None
                if (
                    not registration or registration.supplier_id != supplier_id
                    or registration.state != "APPROVED" or not registration.reviewed_by
                    or not registration.reviewed_at or not profile
                    or profile.go_direct_state not in {"GO_DIRECT_VERIFIED", "GO_DIRECT_LIVE"}
                ):
                    raise ValueError("APPROVED_HOTEL_REGISTRATION_REQUIRED")
                row.state = "VERIFIED"
                row.property_id = registration.hotel_id
                payload["hotel_id"] = registration.hotel_id
                payload["hotel_registration_direct_id"] = registration.hotel_registration_direct_id
            else:
                row.state = "NEEDS_CHANGES"
            now = _now()
            payload["review_note"] = note
            payload["reviewed_by"] = actor
            payload["reviewed_at"] = _iso(now)
            row.payload_json = payload
            row.updated_at = now
            s.commit(); s.refresh(row)
            return self.serialize(row)

    def submit_contract(self, supplier_id: str, contract: dict) -> dict:
        with SessionLocal() as s:
            row = self._row(s, supplier_id)
            if not row:
                raise ValueError("SUPPLIER_ONBOARDING_NOT_FOUND")
            if row.state not in CONTRACT_SUBMITTABLE:
                raise ValueError("SUPPLIER_CONTRACT_NOT_SUBMITTABLE")
            if not str(contract.get("contract_ref") or "").strip():
                raise ValueError("SUPPLIER_CONTRACT_REFERENCE_REQUIRED")
            payload = dict(row.payload_json or {})
            payload["contract"] = {str(k): v for k, v in contract.items() if v not in (None, "")}
            now = _now()
            row.state = "CONTRACT_UNDER_REVIEW"
            payload["contract_submitted_at"] = _iso(now)
            payload["contract_review_note"] = None
            row.payload_json = payload
            row.updated_at = now
            s.commit(); s.refresh(row)
            return self.serialize(row)

    def decide_contract(self, supplier_id: str, actor: str, decision: str, note: str | None = None) -> dict:
        with SessionLocal() as s:
            row = self._row(s, supplier_id)
            if not row or row.state != "CONTRACT_UNDER_REVIEW":
                raise ValueError("SUPPLIER_CONTRACT_NOT_REVIEWABLE")
            decision = str(decision or "").upper()
            if decision not in {"APPROVE", "NEEDS_CHANGES"}:
                raise ValueError("INVALID_SUPPLIER_CONTRACT_DECISION")
            payload = dict(row.payload_json or {})
            now = _now()
            row.state = "CONTRACT_ACTIVE" if decision == "APPROVE" else "CONTRACT_NEEDS_CHANGES"
            payload["contract_review_note"] = note
            payload["contract_reviewed_by"] = actor
            payload["contract_reviewed_at"] = _iso(now)
            row.payload_json = payload
            row.updated_at = now
            s.commit(); s.refresh(row)
            return self.serialize(row)


supplier_onboarding_state_service = SupplierOnboardingStateService()
