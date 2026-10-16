from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import select

from go_hotel.db.models import CommercialCaseRow, HotelRegistrationDirectRow, HotelCanonicalProfileRow
from go_hotel.db.session import SessionLocal

CASE_TYPE = "SUPPLIER_ONBOARDING"
PROFILE_EDITABLE = {"REGISTERED", "PROFILE_DRAFT", "NEEDS_CHANGES"}
PROFILE_SUBMITTABLE = {"PROFILE_DRAFT", "NEEDS_CHANGES"}
# The states from which the *new* contract step can run (Batch 6: upload the signed
# scan and confirm — there is no second human review, D-003). CONTRACT_NEEDS_CHANGES
# and CONTRACT_UNDER_REVIEW are legacy tolerance, and they are listed because the
# pre-Batch-6 code really did write them: a live database may hold a case that an
# administrator sent back, or one left waiting for a contract review that no longer
# exists. Such a case must be able to finish, and it has to redo the step properly
# anyway — the old flow accepted a typed reference string, while the new one requires
# the signed scan as a stored document. Nothing can move a case *back* into either
# state any more.
CONTRACT_SUBMITTABLE = {"VERIFIED", "CONTRACT_NEEDS_CHANGES", "CONTRACT_UNDER_REVIEW"}
# BUSINESS_ENABLED is likewise no longer written by anything; it is still read
# because a row already in it means "this supplier has business access".
BUSINESS_READY = {"CONTRACT_ACTIVE", "BUSINESS_ENABLED"}

# What "complete" means after D-02 / D-03 / D-05. This used to be seven free-text
# references typed into the case payload (`business_license_ref` etc), which made
# "complete" a claim rather than a fact. Completion is now derived from the
# artefacts that actually exist: a legal entity row, a stored licence revision, a
# hotel claim, and the relationship proof that claim's type requires.
#
# 法人身份证 / 经办人身份证 / 门头照 / 组织架构图 are deliberately NOT required
# (D-03): the reviewer can ask for them with NEEDS_CHANGES when a specific case
# actually needs them.
MISSING_LEGAL_ENTITY = "LEGAL_ENTITY"
MISSING_BUSINESS_LICENSE = "BUSINESS_LICENSE"
MISSING_HOTEL_RELATIONSHIP = "HOTEL_RELATIONSHIP"
MISSING_HOTEL_RELATIONSHIP_PROOF = "HOTEL_RELATIONSHIP_PROOF"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _next_step(state: str) -> str:
    # CONTRACT_PENDING is deliberately absent: nothing has ever assigned it — it was
    # only ever a key in this very mapping. A case carrying it therefore cannot
    # exist, and falls through to CONTACT_SUPPORT.
    #
    # CONTRACT_UNDER_REVIEW and CONTRACT_NEEDS_CHANGES stay: the pre-Batch-6 code
    # *did* write them (a contract reference string, then an administrator's
    # verdict), so a live database may hold such a case. Such a case can finish the
    # new contract step — see CONTRACT_SUBMITTABLE below.
    return {
        "REGISTERED": "COMPLETE_PROFILE",
        "PROFILE_DRAFT": "COMPLETE_PROFILE",
        "NEEDS_CHANGES": "CORRECT_PROFILE",
        "UNDER_REVIEW": "WAIT_PROFILE_REVIEW",
        "VERIFIED": "SUBMIT_CONTRACT",
        "CLAIM_CONFLICT": "WAIT_CLAIM_RESOLUTION",
        "CONTRACT_NEEDS_CHANGES": "CORRECT_CONTRACT",
        "CONTRACT_UNDER_REVIEW": "SUBMIT_CONTRACT",
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
            "hotel_claim": payload.get("hotel_claim"),
            "profile": dict(payload.get("profile") or {}),
            "contract": dict(payload.get("contract") or {}),
            "review_note": payload.get("review_note"),
            "review_findings": list(payload.get("review_findings") or []),
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

    def missing_requirements(self, session, supplier_id: str) -> list[str]:
        """What the applicant still has to do, as stable machine codes.

        Every item is checked against stored artefacts, never against a text field
        the applicant typed. That is the difference between "the form looked full"
        and "the platform actually holds the licence".
        """
        from go_hotel.services.legal_entity import legal_entity_service
        from go_hotel.services.legal_entity_document import legal_entity_document_service
        from go_hotel.services.onboarding_hotel import (
            OWNER, RELATIONSHIP_PROOF_TYPES, onboarding_hotel_service,
        )

        missing = []
        if legal_entity_service.get_for_supplier(supplier_id) is None:
            missing.append(MISSING_LEGAL_ENTITY)
        if legal_entity_document_service.current_for_supplier(
                session, supplier_id, "BUSINESS_LICENSE") is None:
            missing.append(MISSING_BUSINESS_LICENSE)
        claim = onboarding_hotel_service.get_claim(supplier_id) or {}
        claim = claim.get("claim") or {}
        if not claim.get("relationship_type") or not (
                claim.get("hotel_id") or claim.get("proposed_hotel")):
            missing.append(MISSING_HOTEL_RELATIONSHIP)
        elif claim["relationship_type"] != OWNER:
            has_proof = any(
                legal_entity_document_service.current_for_supplier(session, supplier_id, document_type)
                is not None for document_type in RELATIONSHIP_PROOF_TYPES
            )
            if not has_proof:
                missing.append(MISSING_HOTEL_RELATIONSHIP_PROOF)
        return missing

    def submit_profile(self, supplier_id: str) -> dict:
        with SessionLocal() as s:
            row = self._row(s, supplier_id)
            if not row:
                raise ValueError("SUPPLIER_ONBOARDING_NOT_FOUND")
            if row.state not in PROFILE_SUBMITTABLE:
                raise ValueError("SUPPLIER_PROFILE_NOT_SUBMITTABLE")
            missing = self.missing_requirements(s, supplier_id)
            if missing:
                raise ValueError("SUPPLIER_PROFILE_INCOMPLETE:" + ",".join(missing))
            payload = dict(row.payload_json or {})
            now = _now()
            row.state = "UNDER_REVIEW"
            payload["submitted_at"] = _iso(now)
            payload["review_note"] = None
            payload["review_findings"] = []
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

    # ---- the contract step moved ---------------------------------------
    # `submit_contract` and `decide_contract` used to live here. Both are gone
    # (Batch 6). `submit_contract` accepted a typed `contract_ref` string as proof
    # that a contract had been signed, which is the same "completion is a claim, not
    # a fact" defect D-03 removed from the profile step; `decide_contract` was the
    # second human review that D-003 abolished. The contract is now: the platform
    # serves a template, the applicant uploads the signed scan as a real document,
    # and one confirmation writes the immutable audit event and CONTRACT_ACTIVE
    # together — see `services/onboarding_contract.py`.
    #
    # `contract_review_note` is still *read* in `serialize` (below) but is no longer
    # written anywhere: it is legacy tolerance for a case an administrator sent back
    # before Batch 6, so such an applicant still sees why.


supplier_onboarding_state_service = SupplierOnboardingStateService()
