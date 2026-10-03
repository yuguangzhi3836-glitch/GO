from __future__ import annotations

from datetime import datetime, timezone
import uuid
from sqlalchemy import select

from go_hotel.db.models import SupplierOnboardingRow, HotelRegistrationDirectRow, HotelCanonicalProfileRow
from go_hotel.db.session import SessionLocal


PROFILE_EDITABLE = {"REGISTERED", "PROFILE_DRAFT", "NEEDS_CHANGES"}
PROFILE_SUBMITTABLE = {"PROFILE_DRAFT", "NEEDS_CHANGES"}
CONTRACT_SUBMITTABLE = {"VERIFIED", "CONTRACT_NEEDS_CHANGES"}
BUSINESS_READY = {"CONTRACT_ACTIVE", "BUSINESS_ENABLED"}
REQUIRED_PROFILE_FIELDS = {
    "organization_name",
    "hotel_name",
    "contact_name",
    "business_license_ref",
    "legal_representative_name",
    "identity_document_ref",
    "storefront_photo_ref",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> str:
    return "onb_" + uuid.uuid4().hex


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


class SupplierOnboardingService:
    def serialize(self, row: SupplierOnboardingRow) -> dict:
        return {
            "supplier_id": row.supplier_id,
            "state": row.state,
            "next_step": _next_step(row.state),
            "business_ready": row.state in BUSINESS_READY,
            "hotel_id": row.hotel_id,
            "hotel_registration_direct_id": row.hotel_registration_direct_id,
            "profile": dict(row.profile_json or {}),
            "contract": dict(row.contract_json or {}),
            "review_note": row.review_note,
            "contract_review_note": row.contract_review_note,
            "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            "contract_submitted_at": row.contract_submitted_at.isoformat() if row.contract_submitted_at else None,
            "contract_reviewed_at": row.contract_reviewed_at.isoformat() if row.contract_reviewed_at else None,
            "updated_at": row.updated_at.isoformat(),
        }

    def get(self, supplier_id: str) -> dict | None:
        with SessionLocal() as s:
            row = s.scalar(select(SupplierOnboardingRow).where(SupplierOnboardingRow.supplier_id == supplier_id))
            return self.serialize(row) if row else None

    def create_registered(self, supplier_id: str, owner_user_id: str, initial_profile: dict | None = None) -> dict:
        t = _now()
        with SessionLocal() as s:
            row = s.scalar(select(SupplierOnboardingRow).where(SupplierOnboardingRow.supplier_id == supplier_id))
            if row:
                return self.serialize(row)
            profile = {k: v for k, v in (initial_profile or {}).items() if v not in (None, "")}
            row = SupplierOnboardingRow(
                onboarding_id=_id(), supplier_id=supplier_id, owner_user_id=owner_user_id,
                state="REGISTERED", profile_json=profile, contract_json={}, hotel_id=None, hotel_registration_direct_id=None,
                review_note=None, reviewed_by=None, contract_review_note=None, contract_reviewed_by=None,
                submitted_at=None, reviewed_at=None, contract_submitted_at=None, contract_reviewed_at=None,
                created_at=t, updated_at=t,
            )
            s.add(row); s.commit(); s.refresh(row)
            return self.serialize(row)

    def save_profile(self, supplier_id: str, profile: dict) -> dict:
        with SessionLocal() as s:
            row = s.scalar(select(SupplierOnboardingRow).where(SupplierOnboardingRow.supplier_id == supplier_id))
            if not row:
                raise ValueError("SUPPLIER_ONBOARDING_NOT_FOUND")
            if row.state not in PROFILE_EDITABLE:
                raise ValueError("SUPPLIER_PROFILE_NOT_EDITABLE")
            clean = {str(k): v for k, v in profile.items() if v not in (None, "")}
            row.profile_json = {**(row.profile_json or {}), **clean}
            row.state = "PROFILE_DRAFT"
            row.updated_at = _now()
            s.commit(); s.refresh(row)
            return self.serialize(row)

    def submit_profile(self, supplier_id: str) -> dict:
        with SessionLocal() as s:
            row = s.scalar(select(SupplierOnboardingRow).where(SupplierOnboardingRow.supplier_id == supplier_id))
            if not row:
                raise ValueError("SUPPLIER_ONBOARDING_NOT_FOUND")
            if row.state not in PROFILE_SUBMITTABLE:
                raise ValueError("SUPPLIER_PROFILE_NOT_SUBMITTABLE")
            profile = row.profile_json or {}
            missing = sorted(k for k in REQUIRED_PROFILE_FIELDS if not str(profile.get(k) or "").strip())
            if missing:
                raise ValueError("SUPPLIER_PROFILE_INCOMPLETE:" + ",".join(missing))
            row.state = "UNDER_REVIEW"
            row.submitted_at = _now()
            row.review_note = None
            row.updated_at = row.submitted_at
            s.commit(); s.refresh(row)
            return self.serialize(row)

    def decide_profile(self, supplier_id: str, actor: str, decision: str, note: str | None = None, registration_direct_id: str | None = None) -> dict:
        with SessionLocal() as s:
            row = s.scalar(select(SupplierOnboardingRow).where(SupplierOnboardingRow.supplier_id == supplier_id))
            if not row or row.state != "UNDER_REVIEW":
                raise ValueError("SUPPLIER_PROFILE_NOT_REVIEWABLE")
            decision = str(decision or "").upper()
            if decision not in {"APPROVE", "NEEDS_CHANGES"}:
                raise ValueError("INVALID_SUPPLIER_PROFILE_DECISION")
            if decision == "APPROVE":
                registration = s.get(HotelRegistrationDirectRow, registration_direct_id) if registration_direct_id else None
                profile = s.get(HotelCanonicalProfileRow, registration.hotel_id) if registration else None
                if (
                    not registration
                    or registration.supplier_id != supplier_id
                    or registration.state != "APPROVED"
                    or not registration.reviewed_by
                    or not registration.reviewed_at
                    or not profile
                    or profile.go_direct_state not in {"GO_DIRECT_VERIFIED", "GO_DIRECT_LIVE"}
                ):
                    raise ValueError("APPROVED_HOTEL_REGISTRATION_REQUIRED")
                row.state = "VERIFIED"
                row.hotel_id = registration.hotel_id
                row.hotel_registration_direct_id = registration.hotel_registration_direct_id
            else:
                row.state = "NEEDS_CHANGES"
            row.review_note = note
            row.reviewed_by = actor
            row.reviewed_at = _now()
            row.updated_at = row.reviewed_at
            s.commit(); s.refresh(row)
            return self.serialize(row)

    def submit_contract(self, supplier_id: str, contract: dict) -> dict:
        with SessionLocal() as s:
            row = s.scalar(select(SupplierOnboardingRow).where(SupplierOnboardingRow.supplier_id == supplier_id))
            if not row:
                raise ValueError("SUPPLIER_ONBOARDING_NOT_FOUND")
            if row.state not in CONTRACT_SUBMITTABLE:
                raise ValueError("SUPPLIER_CONTRACT_NOT_SUBMITTABLE")
            if not str(contract.get("contract_ref") or "").strip():
                raise ValueError("SUPPLIER_CONTRACT_REFERENCE_REQUIRED")
            row.contract_json = {str(k): v for k, v in contract.items() if v not in (None, "")}
            row.state = "CONTRACT_UNDER_REVIEW"
            row.contract_submitted_at = _now()
            row.contract_review_note = None
            row.updated_at = row.contract_submitted_at
            s.commit(); s.refresh(row)
            return self.serialize(row)

    def decide_contract(self, supplier_id: str, actor: str, decision: str, note: str | None = None) -> dict:
        with SessionLocal() as s:
            row = s.scalar(select(SupplierOnboardingRow).where(SupplierOnboardingRow.supplier_id == supplier_id))
            if not row or row.state != "CONTRACT_UNDER_REVIEW":
                raise ValueError("SUPPLIER_CONTRACT_NOT_REVIEWABLE")
            decision = str(decision or "").upper()
            if decision not in {"APPROVE", "NEEDS_CHANGES"}:
                raise ValueError("INVALID_SUPPLIER_CONTRACT_DECISION")
            row.state = "CONTRACT_ACTIVE" if decision == "APPROVE" else "CONTRACT_NEEDS_CHANGES"
            row.contract_review_note = note
            row.contract_reviewed_by = actor
            row.contract_reviewed_at = _now()
            row.updated_at = row.contract_reviewed_at
            s.commit(); s.refresh(row)
            return self.serialize(row)


supplier_onboarding_state_service = SupplierOnboardingService()
