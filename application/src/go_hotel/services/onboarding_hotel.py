"""Hotel claim: the relationship between an applicant and the hotel they run.

Flow (frozen decisions D-05, D-06, CHANGE 6):

    search the canonical catalogue
      -> found:    claim an existing canonical hotel
      -> not found: record a *proposed* hotel on the case and create NOTHING
    choose the relationship type (OWNER / OPERATOR / MANAGEMENT_COMPANY /
    AUTHORIZED_AGENT) and attach the operation proof that type requires
    -> save on the case (repeatable while the applicant is still drafting)
    -> a reviewer approves: exactly then the canonical hotel appears (proposed
       branch only) and exactly one APPROVED relation is written

Why approval is the only place that creates anything: a canonical hotel is a
public platform identity. Letting an applicant's typed-in name create one would
let anyone mint platform entities, and would make "not found" indistinguishable
from "someone else just made it up".

Conflict handling is deliberately not "last write wins". Two suppliers may both
submit a claim for the same hotel — that is a legitimate race, and the loser is
recorded as CLAIM_CONFLICT for a human, never silently overwritten (the task's
explicit requirement). Two independent database constraints back this up, because
two concurrent approvals can both pass any application-level check.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from go_hotel.autonomy.durable import transaction
from go_hotel.db.models import (
    AuditEventRow,
    CommercialCaseRow,
    HotelCanonicalProfileRow,
    HotelRegistrationDirectRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services import catalog_scope, hotel_search
from go_hotel.services.hotel_autopage_factory import hotel_autopage_factory_service
from go_hotel.services.legal_entity_document import legal_entity_document_service

CASE_TYPE = "SUPPLIER_ONBOARDING"

RELATIONSHIP_TYPES = ("OWNER", "OPERATOR", "MANAGEMENT_COMPANY", "AUTHORIZED_AGENT")
OWNER = "OWNER"
# D-03: only a declared owner is exempt from an operation proof. Everybody else
# must show either that they operate the hotel or that they are contracted to.
RELATIONSHIP_PROOF_TYPES = ("HOTEL_OPERATION_PROOF", "FRANCHISE_OR_MANAGEMENT_CONTRACT")

MODE_EXISTING = "EXISTING"
MODE_PROPOSED = "PROPOSED"
MODES = (MODE_EXISTING, MODE_PROPOSED)

CLAIM_EDITABLE_STATES = {"REGISTERED", "PROFILE_DRAFT", "NEEDS_CHANGES"}
CLAIM_APPROVABLE_STATES = {"PROFILE_DRAFT", "NEEDS_CHANGES", "UNDER_REVIEW"}
# A state in which the case already holds the hotel. Kept identical to the partial
# unique index in migration 0148 — a granted hotel has exactly one holder.
#
# Two entries in this tuple can no longer be produced by the workflow, and they are
# retained on purpose rather than by oversight:
#
#   * CONTRACT_PENDING — nothing has ever assigned it (it only ever appeared as a
#     `_next_step` mapping key, which Batch 6 removed as well). No row can be in it.
#   * CONTRACT_UNDER_REVIEW — the pre-Batch-6 code did write it; Batch 6 removed the
#     contract-review step that did so (D-003: there is no second human review). A
#     live database may still hold a case in it.
#
# This tuple is a *storage* predicate, not a workflow description: it is the
# `WHERE` clause of a partial unique index, so it must also cover rows written by
# earlier versions of the product. Shortening it would mean rebuilding the index on
# live data in order to gain nothing, so it stays. What must NOT happen is a new
# write path producing these tokens; `services/onboarding_contract.py` is the only
# place that moves a case past VERIFIED, and it writes CONTRACT_ACTIVE.
LIVE_CASE_STATES = (
    "VERIFIED", "CONTRACT_PENDING", "CONTRACT_NEEDS_CHANGES",
    "CONTRACT_UNDER_REVIEW", "CONTRACT_ACTIVE", "BUSINESS_ENABLED",
)

ONBOARDING_NOT_FOUND = "SUPPLIER_ONBOARDING_NOT_FOUND"
CLAIM_NOT_EDITABLE = "HOTEL_CLAIM_NOT_EDITABLE"
CLAIM_NOT_REVIEWABLE = "HOTEL_CLAIM_NOT_REVIEWABLE"
CLAIM_REQUIRED = "HOTEL_CLAIM_REQUIRED"
CLAIM_MODE_INVALID = "HOTEL_CLAIM_MODE_INVALID"
CLAIM_HOTEL_REQUIRED = "HOTEL_CLAIM_HOTEL_REQUIRED"
RELATIONSHIP_TYPE_REQUIRED = "HOTEL_RELATIONSHIP_TYPE_REQUIRED"
RELATIONSHIP_TYPE_INVALID = "HOTEL_RELATIONSHIP_TYPE_INVALID"
RELATIONSHIP_PROOF_REQUIRED = "HOTEL_RELATIONSHIP_PROOF_REQUIRED"
PROPOSED_HOTEL_NAME_REQUIRED = "PROPOSED_HOTEL_NAME_REQUIRED"
PROPOSED_HOTEL_CITY_REQUIRED = "PROPOSED_HOTEL_CITY_REQUIRED"
PROPOSED_HOTEL_ALREADY_EXISTS = "PROPOSED_HOTEL_ALREADY_EXISTS"
CLAIM_CONFLICT = "CLAIM_CONFLICT"
ALREADY_VERIFIED = "SUPPLIER_ONBOARDING_ALREADY_VERIFIED"
HOTEL_NOT_FOUND = hotel_search.HOTEL_NOT_FOUND

# Why a claim lost. Recorded for the human who has to resolve it; the applicant
# sees a single translated sentence, never this code.
CONFLICT_HOTEL_HELD_BY_ANOTHER = "HOTEL_HELD_BY_ANOTHER_SUPPLIER"
CONFLICT_CANONICAL_ALREADY_EXISTS = "CANONICAL_HOTEL_ALREADY_EXISTS"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _text(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def proposed_hotel_id(case_id: str) -> str:
    """Deterministic canonical id for a hotel that only exists as a proposal.

    Derived from the case, not random: an approval that is retried (or replayed
    after a crash) addresses the same row instead of minting a second hotel.
    """
    return "hotel_" + hashlib.sha256(("go.onboarding.claim:" + case_id).encode()).hexdigest()[:32]


class ClaimConflict(Exception):
    """Internal signal; never leaves this module as anything but CLAIM_CONFLICT."""

    def __init__(self, detail: dict):
        super().__init__(CLAIM_CONFLICT)
        self.detail = detail


class OnboardingHotelService:
    # ---- read ----------------------------------------------------------
    def _case(self, session, supplier_id: str) -> CommercialCaseRow | None:
        return session.scalar(
            select(CommercialCaseRow).where(
                CommercialCaseRow.case_type == CASE_TYPE,
                CommercialCaseRow.supplier_id == supplier_id,
            )
        )

    def search(self, *, query: str | None = None, city: str | None = None,
               limit: int = hotel_search.DEFAULT_LIMIT) -> list[dict]:
        with SessionLocal() as session:
            return hotel_search.search(session, query=query, city=city, limit=limit)

    def get_claim(self, supplier_id: str) -> dict | None:
        with SessionLocal() as session:
            row = self._case(session, supplier_id)
            if row is None:
                return None
            payload = dict(row.payload_json or {})
            return {
                "state": row.state,
                "claim": payload.get("hotel_claim"),
                "hotel_id": payload.get("hotel_id"),
                "relationship_types": list(RELATIONSHIP_TYPES),
            }

    # ---- applicant write ------------------------------------------------
    def _proof(self, session, supplier_id: str, relationship_type: str):
        if relationship_type == OWNER:
            return None
        for document_type in RELATIONSHIP_PROOF_TYPES:
            row = legal_entity_document_service.current_for_supplier(session, supplier_id, document_type)
            if row is not None:
                return row
        raise ValueError(RELATIONSHIP_PROOF_REQUIRED)

    def save_claim(self, supplier_id: str, actor: str, body: dict) -> dict:
        mode = str(body.get("mode") or "").strip().upper()
        if mode not in MODES:
            raise ValueError(CLAIM_MODE_INVALID)
        relationship_type = str(body.get("relationship_type") or "").strip().upper()
        if not relationship_type:
            raise ValueError(RELATIONSHIP_TYPE_REQUIRED)
        if relationship_type not in RELATIONSHIP_TYPES:
            raise ValueError(RELATIONSHIP_TYPE_INVALID)

        with transaction(SessionLocal) as session:
            row = self._case(session, supplier_id)
            if row is None:
                raise ValueError(ONBOARDING_NOT_FOUND)
            if row.state not in CLAIM_EDITABLE_STATES:
                raise ValueError(CLAIM_NOT_EDITABLE)

            if mode == MODE_EXISTING:
                hotel_id = _text(body.get("hotel_id"), 64)
                if not hotel_id:
                    raise ValueError(CLAIM_HOTEL_REQUIRED)
                profile = hotel_search.resolve_visible(session, hotel_id)
                display = hotel_search.serialize_candidate(profile)
                proposed = None
            else:
                raw = body.get("proposed_hotel") or {}
                name = _text(raw.get("name"), 160)
                city = _text(raw.get("city"), 80)
                if not name:
                    raise ValueError(PROPOSED_HOTEL_NAME_REQUIRED)
                if not city:
                    raise ValueError(PROPOSED_HOTEL_CITY_REQUIRED)
                address = _text(raw.get("address"), 300)
                if hotel_search.find_exact(session, name, city=city, limit=1):
                    # The hotel is already in the catalogue under this exact name:
                    # claiming it as "new" would mint a duplicate canonical hotel.
                    raise ValueError(PROPOSED_HOTEL_ALREADY_EXISTS)
                hotel_id = None
                display = {"hotel_id": None, "name": name, "city": city,
                           "address": address or city, "brand": None,
                           "page_state": None, "claim_state": hotel_search.CLAIM_STATE_AVAILABLE}
                proposed = {"name": name, "city": city, "address": address}

            proof = self._proof(session, supplier_id, relationship_type)
            now = _now()
            payload = dict(row.payload_json or {})
            payload["hotel_claim"] = {
                "mode": mode,
                "hotel_id": hotel_id,
                "hotel_display": display,
                "proposed_hotel": proposed,
                "relationship_type": relationship_type,
                "proof_document_id": proof.document_id if proof else None,
                "proof_document_type": proof.document_type if proof else None,
                "proof_revision": proof.revision if proof else None,
                "saved_at": _iso(now),
                "approved_at": None,
                "hotel_registration_direct_id": None,
                "conflict": None,
            }
            row.payload_json = payload
            if row.state == "REGISTERED":
                row.state = "PROFILE_DRAFT"
            row.updated_at = now
            session.add(AuditEventRow(
                audit_id=f"aud_{uuid.uuid4().hex}", actor_id=actor, actor_type="SUPPLIER_USER",
                supplier_id=supplier_id, roles=[], action="SUPPLIER_HOTEL_CLAIM_SAVED",
                resource_type="supplier_onboarding", resource_id=row.commercial_case_id,
                after_state={"mode": mode, "relationship_type": relationship_type},
                metadata_json={
                    "hotel_id": hotel_id,
                    "proposed_hotel": proposed,
                    "proof_document_type": proof.document_type if proof else None,
                },
                created_at=now,
            ))
            return {"state": row.state, "claim": dict(payload["hotel_claim"])}

    # ---- reviewer approval ---------------------------------------------
    def approve_claim(self, supplier_id: str, actor: str, note: str | None = None) -> dict:
        try:
            with transaction(SessionLocal) as session:
                return self._approve_locked(session, supplier_id, actor, note)
        except ClaimConflict as conflict:
            # Record the conflict on the case in its own transaction: the approval
            # attempt itself must leave no half-built hotel or relation behind.
            self._record_conflict(supplier_id, actor, conflict.detail)
            raise ValueError(CLAIM_CONFLICT) from None

    def record_conflict(self, supplier_id: str, actor: str, detail: dict) -> None:
        """Park a case as CLAIM_CONFLICT, in its own transaction.

        Public because the review service (Batch 5) owns the approval transaction:
        when it rolls that transaction back it is the one that has to record the
        conflict afterwards, and it must not reach into a private method to do it.
        """
        self._record_conflict(supplier_id, actor, detail)

    def approve_locked(self, session, supplier_id: str, actor: str, note: str | None = None) -> dict:
        """Approve inside a transaction the caller already owns.

        Batch 5 needs this. Resolving a CLAIM_CONFLICT by revoking the incumbent
        holder and granting the hotel to the winning claimant has to be ONE
        transaction: if the second half failed on its own, the hotel would be
        left with no holder at all, which is a worse state than the conflict.
        """
        return self._approve_locked(session, supplier_id, actor, note)

    def _approve_locked(self, session, supplier_id: str, actor: str, note: str | None) -> dict:
        row = session.scalar(
            select(CommercialCaseRow)
            .where(CommercialCaseRow.case_type == CASE_TYPE,
                   CommercialCaseRow.supplier_id == supplier_id)
            .with_for_update()
        )
        if row is None:
            raise ValueError(ONBOARDING_NOT_FOUND)
        payload = dict(row.payload_json or {})
        claim = payload.get("hotel_claim") or None
        if not claim:
            raise ValueError(CLAIM_REQUIRED)
        if claim.get("approved_at") and row.state in LIVE_CASE_STATES:
            # Replayed approval: report the state it already reached instead of
            # building a second hotel or a second relation.
            return {"idempotent": True, "state": row.state,
                    "hotel_id": payload.get("hotel_id"),
                    "hotel_registration_direct_id": payload.get("hotel_registration_direct_id")}
        if row.state not in CLAIM_APPROVABLE_STATES:
            raise ValueError(CLAIM_NOT_REVIEWABLE)

        relationship_type = claim["relationship_type"]
        self._proof(session, supplier_id, relationship_type)

        if claim["mode"] == MODE_EXISTING:
            hotel_id = claim["hotel_id"]
            profile = hotel_search.resolve_visible(session, hotel_id)
            self._assert_undisputed(session, hotel_id, supplier_id)
        else:
            proposed = claim["proposed_hotel"]
            # Lock the "does this hotel exist yet" decision before looking, so
            # two simultaneous approvals cannot both decide it does not.
            hotel_autopage_factory_service.claim_name_lock(session, proposed["name"])
            duplicate = hotel_search.find_exact(
                session, proposed["name"], city=proposed.get("city"), limit=1)
            if duplicate:
                raise ClaimConflict({"reason": CONFLICT_CANONICAL_ALREADY_EXISTS,
                                     "hotel_id": duplicate[0].get("hotel_id"),
                                     "hotel_display": duplicate[0]})
            hotel_id = proposed_hotel_id(row.commercial_case_id)
            # A plain string address, not a nested object: the canonical page
            # publishes ``canonical_json['address']`` straight into
            # ``location.address``, so an object here would leak a raw JSON
            # blob onto a public page.
            where = " ".join(part for part in (proposed["city"], proposed.get("address")) if part)
            payload_for_hotel = {"name": proposed["name"], "address": where}
            profile = hotel_autopage_factory_service.materialize_claim_hotel(
                session, hotel_id=hotel_id, supplier_id=supplier_id,
                payload=payload_for_hotel, actor=actor)

        registration = self._approve_relation(session, row, claim, hotel_id, relationship_type, actor)
        catalog_scope.require_hotel(session, hotel_id)
        profile.go_direct_state = "GO_DIRECT_VERIFIED"
        profile.updated_at = _now()
        # GO Direct state is part of the public page and its trust block; publish
        # it in the same transaction so the page never contradicts the row.
        hotel_autopage_factory_service.publish_hotel_state(session, profile, actor)

        now = _now()
        claim = dict(claim)
        claim["hotel_id"] = hotel_id
        claim["approved_at"] = _iso(now)
        claim["hotel_registration_direct_id"] = registration.hotel_registration_direct_id
        claim["conflict"] = None
        payload["hotel_claim"] = claim
        payload["hotel_id"] = hotel_id
        payload["hotel_registration_direct_id"] = registration.hotel_registration_direct_id
        payload["review_note"] = note
        payload["reviewed_by"] = actor
        payload["reviewed_at"] = _iso(now)
        row.payload_json = payload
        row.state = "VERIFIED"
        row.property_id = hotel_id
        row.updated_at = now
        session.add(AuditEventRow(
            audit_id=f"aud_{uuid.uuid4().hex}", actor_id=actor, actor_type="GO_ADMIN",
            supplier_id=supplier_id, roles=[], action="SUPPLIER_ONBOARDING_HOTEL_APPROVED",
            resource_type="supplier_onboarding", resource_id=row.commercial_case_id,
            after_state={"state": "VERIFIED", "hotel_id": hotel_id},
            metadata_json={
                "hotel_registration_direct_id": registration.hotel_registration_direct_id,
                "relationship_type": relationship_type,
                "claim_mode": claim["mode"],
                "review_note": note,
            },
            created_at=now,
        ))
        try:
            session.flush()
        except IntegrityError:
            # A concurrent approval won one of the two uniqueness rules. Both
            # mean the same thing to a human: this hotel already has a holder.
            # Rolling back is the transaction owner's job, not ours: a caller that
            # is resolving a conflict owns a bigger transaction, and it has to undo
            # in full rather than leave half of it standing.
            raise ClaimConflict({"reason": CONFLICT_HOTEL_HELD_BY_ANOTHER,
                                 "hotel_id": hotel_id}) from None
        return {"idempotent": False, "state": "VERIFIED", "hotel_id": hotel_id,
                "hotel_registration_direct_id": registration.hotel_registration_direct_id,
                "relationship_type": relationship_type, "claim": claim}

    def _assert_undisputed(self, session, hotel_id: str, supplier_id: str) -> None:
        """Refuse to grant a hotel that already has a holder, and say why."""
        holder = session.scalar(
            select(CommercialCaseRow).where(
                CommercialCaseRow.case_type == CASE_TYPE,
                CommercialCaseRow.property_id == hotel_id,
                CommercialCaseRow.supplier_id != supplier_id,
                CommercialCaseRow.state.in_(LIVE_CASE_STATES),
            )
        )
        if holder is not None:
            raise ClaimConflict({"reason": CONFLICT_HOTEL_HELD_BY_ANOTHER,
                                 "hotel_id": hotel_id,
                                 "held_since": _iso(holder.updated_at)})
        relation = session.scalar(
            select(HotelRegistrationDirectRow).where(
                HotelRegistrationDirectRow.hotel_id == hotel_id,
                HotelRegistrationDirectRow.state == "APPROVED",
                HotelRegistrationDirectRow.supplier_id != supplier_id,
            )
        )
        if relation is not None:
            raise ClaimConflict({"reason": CONFLICT_HOTEL_HELD_BY_ANOTHER,
                                 "hotel_id": hotel_id})

    def _approve_relation(self, session, row, claim, hotel_id, relationship_type, actor):
        existing = session.scalar(
            select(HotelRegistrationDirectRow).where(
                HotelRegistrationDirectRow.hotel_id == hotel_id,
                HotelRegistrationDirectRow.supplier_id == row.supplier_id,
                HotelRegistrationDirectRow.state.in_(("SUBMITTED", "APPROVED")),
            )
        )
        now = _now()
        evidence = [{
            "kind": "ONBOARDING_HOTEL_CLAIM",
            "relationship_type": relationship_type,
            "claim_mode": claim["mode"],
            "proof_document_id": claim.get("proof_document_id"),
        }]
        if existing is not None:
            existing.state = "APPROVED"
            existing.relationship_type = relationship_type
            existing.evidence_json = evidence
            existing.reviewed_by = actor
            existing.reviewed_at = now
            return existing
        registration = HotelRegistrationDirectRow(
            hotel_registration_direct_id=f"hregdir_{uuid.uuid4().hex}",
            hotel_id=hotel_id, supplier_id=row.supplier_id, state="APPROVED",
            relationship_type=relationship_type, evidence_json=evidence,
            official_supplement_json=dict(claim.get("proposed_hotel") or {}),
            requested_by=str((row.payload_json or {}).get("owner_user_id") or "SUPPLIER"),
            reviewed_by=actor, created_at=now, reviewed_at=now,
        )
        session.add(registration)
        return registration

    def _record_conflict(self, supplier_id: str, actor: str, detail: dict) -> None:
        """Park the case for a human. Nothing is overwritten, nothing is granted."""
        with transaction(SessionLocal) as session:
            row = self._case(session, supplier_id)
            if row is None or row.state in LIVE_CASE_STATES:
                return
            payload = dict(row.payload_json or {})
            claim = dict(payload.get("hotel_claim") or {})
            claim["conflict"] = {**detail, "recorded_at": _iso(_now())}
            claim["approved_at"] = None
            claim["hotel_registration_direct_id"] = None
            payload["hotel_claim"] = claim
            now = _now()
            row.payload_json = payload
            row.state = "CLAIM_CONFLICT"
            row.updated_at = now
            session.add(AuditEventRow(
                audit_id=f"aud_{uuid.uuid4().hex}", actor_id=actor, actor_type="GO_ADMIN",
                supplier_id=supplier_id, roles=[], action="SUPPLIER_ONBOARDING_CLAIM_CONFLICT",
                resource_type="supplier_onboarding", resource_id=row.commercial_case_id,
                after_state={"state": "CLAIM_CONFLICT"},
                metadata_json={"conflict": claim["conflict"]},
                created_at=now,
            ))


onboarding_hotel_service = OnboardingHotelService()
