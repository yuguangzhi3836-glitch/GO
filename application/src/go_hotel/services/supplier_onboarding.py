from __future__ import annotations

from datetime import datetime, timezone
import uuid
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from go_hotel.db.models import IdentityUserRow, HotelPartnerPropertyRow, HotelPartnerAuditEventRow, CommercialCaseRow
from go_hotel.db.session import SessionLocal
from go_hotel.security.crypto import hash_password


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SupplierOnboardingService:
    """Public supplier sign-up without weakening authenticated hotel ownership checks."""

    def register_account(self, body: dict, *, audit_factory=None, verification_proof=None, initial_profile=None) -> dict:
        username = str(body.get("username") or "").strip().lower()
        password = str(body.get("password") or "")
        if len(username) > 128 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", username):
            raise ValueError("VALID_EMAIL_REQUIRED")
        if len(password) < 10 or len(password) > 128:
            raise ValueError("PASSWORD_LENGTH_INVALID")
        supplier_id, user_id, created = _id("sup"), _id("usr"), _now()
        profile = {str(k): v for k, v in (initial_profile or {}).items() if v not in (None, "")}
        with SessionLocal() as session:
            if verification_proof is not None:
                from go_hotel.services.registration_verification import consume
                consume(session, verification_proof, user_id)
            if session.scalar(select(IdentityUserRow).where(IdentityUserRow.username == username)):
                raise ValueError("USERNAME_ALREADY_REGISTERED")
            user = IdentityUserRow(
                user_id=user_id, username=username, password_hash=hash_password(password),
                actor_type="SUPPLIER_USER", supplier_id=supplier_id, roles=["SUPPLIER_OWNER"],
                status="ACTIVE", token_version=1, created_at=created, updated_at=created,
            )
            onboarding = CommercialCaseRow(
                commercial_case_id=f"onb_{supplier_id}",
                case_type="SUPPLIER_ONBOARDING",
                supplier_id=supplier_id,
                property_id=None,
                priority="MEDIUM",
                owner_id=user_id,
                state="PROFILE_DRAFT" if profile else "REGISTERED",
                sla_due_at=None,
                payload_json={
                    "owner_user_id": user_id,
                    "profile": profile,
                    "contract": {},
                    "hotel_id": None,
                    "hotel_registration_direct_id": None,
                    "review_note": None,
                    "reviewed_by": None,
                    "contract_review_note": None,
                    "contract_reviewed_by": None,
                    "submitted_at": None,
                    "reviewed_at": None,
                    "contract_submitted_at": None,
                    "contract_reviewed_at": None,
                },
                evidence_json=[],
                created_at=created,
                updated_at=created,
            )
            session.add_all([user, onboarding])
            if audit_factory is not None:
                session.add(audit_factory(user_id, supplier_id))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if session.scalar(select(IdentityUserRow).where(IdentityUserRow.username == username)):
                    raise ValueError("USERNAME_ALREADY_REGISTERED") from None
                raise
        return {
            "status": "REGISTERED", "user_id": user_id, "supplier_id": supplier_id,
            "onboarding_state": onboarding.state, "next_step": "COMPLETE_PROFILE",
        }

    def register(self, body: dict, *, audit_factory=None, verification_proof=None) -> dict:
        username = str(body.get("username") or "").strip().lower()
        password = str(body.get("password") or "")
        hotel = body.get("hotel") or {}
        if len(username) > 128 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", username):
            raise ValueError("VALID_EMAIL_REQUIRED")
        if len(password) < 10 or len(password) > 128:
            raise ValueError("PASSWORD_LENGTH_INVALID")
        if not str(hotel.get("name_zh") or "").strip():
            raise ValueError("HOTEL_NAME_REQUIRED")
        if not str(hotel.get("property_type") or "").strip():
            raise ValueError("PROPERTY_TYPE_REQUIRED")

        supplier_id, user_id, property_id = _id("sup"), _id("usr"), _id("prop")
        created = _now()
        with SessionLocal() as session:
            if verification_proof is not None:
                from go_hotel.services.registration_verification import consume
                consume(session, verification_proof, user_id)
            if session.scalar(select(IdentityUserRow).where(IdentityUserRow.username == username)):
                raise ValueError("USERNAME_ALREADY_REGISTERED")
            user = IdentityUserRow(
                user_id=user_id, username=username, password_hash=hash_password(password),
                actor_type="SUPPLIER_USER", supplier_id=supplier_id, roles=["SUPPLIER_OWNER"],
                status="ACTIVE", token_version=1, created_at=created, updated_at=created,
            )
            prop = HotelPartnerPropertyRow(
                property_id=property_id, supplier_id=supplier_id,
                name_zh=str(hotel["name_zh"]).strip(), name_en=hotel.get("name_en"),
                property_type=str(hotel["property_type"]).strip(), group_name=hotel.get("group_name"),
                brand_name=hotel.get("brand_name"), address_json=hotel.get("address") or {},
                latitude=hotel.get("latitude"), longitude=hotel.get("longitude"),
                contacts_json=hotel.get("contacts") or {}, legal_json=hotel.get("legal") or {},
                operations_json={"onboarding_source": "SELF_REGISTRATION", "ownership": {
                    "status": "DECLARED", "declared_by": user_id,
                    "verification_required_before_publication": True,
                }}, poi_json=[],
                publication_state="DRAFT", version=1, created_at=created, updated_at=created,
            )
            session.add_all([user, prop, HotelPartnerAuditEventRow(
                audit_event_id=_id("hpa"), property_id=property_id,
                event_type="SUPPLIER_SELF_REGISTERED", aggregate_type="PROPERTY",
                aggregate_id=property_id, payload_json={"supplier_id": supplier_id,
                    "ownership_status": "DECLARED", "publication_blocked_until_verified": True},
                actor_id=user_id, created_at=created,
            )])
            if audit_factory is not None:
                session.add(audit_factory(user_id, supplier_id, property_id))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if session.scalar(select(IdentityUserRow).where(IdentityUserRow.username == username)):
                    raise ValueError("USERNAME_ALREADY_REGISTERED") from None
                raise
        return {
            "status": "REGISTERED", "user_id": user_id, "supplier_id": supplier_id,
            "property_id": property_id, "next_step": "LOGIN_AND_BUILD_HOTEL_LIBRARY",
        }


supplier_onboarding_service = SupplierOnboardingService()
