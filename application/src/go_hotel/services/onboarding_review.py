"""The GO side of supplier onboarding: a queue, a case view, and a decision.

Three ideas hold this module together.

**A queue that is honest about waiting.** Two states need a human: UNDER_REVIEW
(the applicant has submitted and is waiting) and CLAIM_CONFLICT (two applicants
want the same hotel). Ordering is ``updated_at ASC`` — the case that has been
waiting longest is served first — with the case id as a stable tie-breaker so
paging cannot silently skip a row that shares a timestamp.

**A decision that says what is missing.** NEEDS_CHANGES without a structured
finding is just a rejection with softer wording: the applicant cannot tell what
to fix, and the platform cannot tell whether they fixed it. So a NEEDS_CHANGES
decision must carry at least one finding, and every finding code comes from a
closed vocabulary the interface can translate into a sentence.

**A rejection that rejects the application, not the company.** REJECT ends this
onboarding attempt. It deliberately leaves the legal entity row and its own
verification state untouched: who the tenant legally is does not stop being true
because a hotel claim failed, and silently marking the entity REJECTED would
break unrelated features that trust that row. Reopening is an explicit,
reason-bearing governance act, not an implied side effect.

APPROVE does not create the hotel itself — it delegates to the hotel service,
which is the only thing in the system allowed to (frozen decision D-05). What
this module adds is the atomic envelope around it: the case lock, the decision
record, and the audit line, in one transaction with the approval.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from go_hotel.autonomy.durable import transaction
from go_hotel.db.models import AuditEventRow, CommercialCaseRow, HotelRegistrationDirectRow
from go_hotel.db.session import SessionLocal
from go_hotel.services.legal_entity import legal_entity_service
from go_hotel.services.legal_entity_document import legal_entity_document_service
from go_hotel.services.onboarding_hotel import (
    CASE_TYPE,
    OWNER,
    RELATIONSHIP_PROOF_TYPES,
    ClaimConflict,
    LIVE_CASE_STATES,
    MODE_EXISTING,
    onboarding_hotel_service,
)

RESOURCE_TYPE = "supplier_onboarding"

# What a reviewer is asked to deal with. PROFILE_DRAFT is the applicant's own
# work in progress and needs no reviewer; everything past review is a different
# surface (contract, business).
QUEUE_STATES = ("UNDER_REVIEW", "CLAIM_CONFLICT")
DECIDABLE_STATES = ("UNDER_REVIEW", "CLAIM_CONFLICT")
REOPENABLE_STATES = ("REJECTED", "NEEDS_CHANGES")

DECISION_APPROVE = "APPROVE"
DECISION_NEEDS_CHANGES = "NEEDS_CHANGES"
DECISION_REJECT = "REJECT"
DECISIONS = (DECISION_APPROVE, DECISION_NEEDS_CHANGES, DECISION_REJECT)

# A closed vocabulary, so the applicant's screen can translate a finding into a
# sentence instead of showing an internal code, and so "what was asked for" can
# be counted later. Free text still travels alongside as ``message``.
FINDING_LEGAL_ENTITY_MISMATCH = "LEGAL_ENTITY_MISMATCH"
FINDING_LICENSE_ILLEGIBLE = "LICENSE_ILLEGIBLE"
FINDING_LICENSE_EXPIRED = "LICENSE_EXPIRED"
FINDING_RELATIONSHIP_UNPROVEN = "RELATIONSHIP_UNPROVEN"
FINDING_PROOF_ILLEGIBLE = "PROOF_ILLEGIBLE"
FINDING_HOTEL_INFO_MISMATCH = "HOTEL_INFO_MISMATCH"
FINDING_DOCUMENT_REQUIRED = "DOCUMENT_REQUIRED"
FINDING_OTHER = "OTHER"
FINDING_CODES = (
    FINDING_LEGAL_ENTITY_MISMATCH,
    FINDING_LICENSE_ILLEGIBLE,
    FINDING_LICENSE_EXPIRED,
    FINDING_RELATIONSHIP_UNPROVEN,
    FINDING_PROOF_ILLEGIBLE,
    FINDING_HOTEL_INFO_MISMATCH,
    FINDING_DOCUMENT_REQUIRED,
    FINDING_OTHER,
)

RESOLUTION_REJECT_LATE = "REJECT_LATE_CLAIMANT"
RESOLUTION_REVOKE_INCUMBENT = "REVOKE_INCUMBENT"
RESOLUTIONS = (RESOLUTION_REJECT_LATE, RESOLUTION_REVOKE_INCUMBENT)

CASE_NOT_FOUND = "REVIEW_CASE_NOT_FOUND"
CASE_NOT_REVIEWABLE = "REVIEW_CASE_NOT_REVIEWABLE"
DECISION_INVALID = "INVALID_REVIEW_DECISION"
FINDINGS_REQUIRED = "REVIEW_FINDINGS_REQUIRED"
FINDING_SHAPE_INVALID = "REVIEW_FINDING_SHAPE_INVALID"
FINDING_CODE_INVALID = "REVIEW_FINDING_CODE_INVALID"
REOPEN_NOT_ALLOWED = "REVIEW_REOPEN_NOT_ALLOWED"
REOPEN_REASON_REQUIRED = "REVIEW_REOPEN_REASON_REQUIRED"
CLAIM_CONFLICT_REQUIRED = "CLAIM_CONFLICT_REQUIRED"
CLAIM_CONFLICT_MUST_BE_RESOLVED = "CLAIM_CONFLICT_MUST_BE_RESOLVED_FIRST"
CLAIM_CONFLICT_RESOLUTION_INVALID = "CLAIM_CONFLICT_RESOLUTION_INVALID"
CLAIM_CONFLICT_REASON_REQUIRED = "CLAIM_CONFLICT_REASON_REQUIRED"
CLAIM_CONFLICT_CONFIRMATION_REQUIRED = "CLAIM_CONFLICT_CONFIRMATION_REQUIRED"
CLAIM_CONFLICT_HOTEL_UNKNOWN = "CLAIM_CONFLICT_HOTEL_UNKNOWN"
CLAIM_CONFLICT_INCUMBENT_NOT_FOUND = "CLAIM_CONFLICT_INCUMBENT_NOT_FOUND"

HISTORY_LIMIT = 100
MAX_LIMIT = 100


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _text(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def clean_findings(findings) -> list[dict]:
    """Normalise reviewer findings, refusing anything the interface cannot show.

    A bare string is accepted as a code with no message because the console offers
    codes as buttons; a free-text-only request is refused, because a finding with
    no code is the one thing the applicant's screen cannot translate.
    """
    if findings in (None, "", []):
        return []
    if isinstance(findings, (str, bytes, dict)):
        raise ValueError(FINDING_SHAPE_INVALID)
    out: list[dict] = []
    for item in findings:
        if isinstance(item, str):
            code, message = item.strip().upper(), ""
        elif isinstance(item, dict):
            code = str(item.get("code") or "").strip().upper()
            message = _text(item.get("message"), 500)
        else:
            raise ValueError(FINDING_SHAPE_INVALID)
        if code not in FINDING_CODES:
            raise ValueError(f"{FINDING_CODE_INVALID}:{code}")
        out.append({"code": code, "message": message})
    # Duplicate codes collapse: the same thing asked twice is the same request.
    seen: dict[str, dict] = {}
    for item in out:
        seen.setdefault(item["code"], item)
    return list(seen.values())


class OnboardingReviewService:
    # ---- internals ------------------------------------------------------
    def _case(self, session, supplier_id: str) -> CommercialCaseRow | None:
        return session.scalar(
            select(CommercialCaseRow).where(
                CommercialCaseRow.case_type == CASE_TYPE,
                CommercialCaseRow.supplier_id == supplier_id,
            )
        )

    def _locked_case(self, session, supplier_id: str) -> CommercialCaseRow | None:
        return session.scalar(
            select(CommercialCaseRow)
            .where(CommercialCaseRow.case_type == CASE_TYPE,
                   CommercialCaseRow.supplier_id == supplier_id)
            .with_for_update()
        )

    def _audit(self, session, *, actor: str, action: str, supplier_id: str, resource_id: str,
               before: str | None, after: str | None, metadata: dict) -> None:
        session.add(AuditEventRow(
            audit_id=f"aud_{uuid.uuid4().hex}", actor_id=actor, actor_type="GO_ADMIN",
            supplier_id=supplier_id, roles=[], action=action,
            resource_type=RESOURCE_TYPE, resource_id=resource_id,
            before_state={"state": before} if before else None,
            after_state={"state": after} if after else None,
            metadata_json=metadata, created_at=_now(),
        ))

    # ---- read -----------------------------------------------------------
    def queue(self, *, states=None, limit: int = 25, offset: int = 0) -> dict:
        wanted = tuple(s for s in (states or QUEUE_STATES) if s in QUEUE_STATES) or QUEUE_STATES
        limit = max(1, min(int(limit), MAX_LIMIT))
        offset = max(0, int(offset))
        with SessionLocal() as session:
            condition = (CommercialCaseRow.case_type == CASE_TYPE,
                         CommercialCaseRow.state.in_(wanted))
            total = session.scalar(
                select(func.count()).select_from(CommercialCaseRow).where(*condition)) or 0
            rows = session.scalars(
                select(CommercialCaseRow).where(*condition)
                # Oldest waiting first. A row that shares a timestamp must still
                # sort deterministically, or a page boundary could hide it.
                .order_by(CommercialCaseRow.updated_at.asc(),
                          CommercialCaseRow.commercial_case_id.asc())
                .limit(limit).offset(offset)
            ).all()
            return {"items": [self._queue_item(row) for row in rows],
                    "total": total, "limit": limit, "offset": offset,
                    "states": list(wanted)}

    def _queue_item(self, row: CommercialCaseRow) -> dict:
        payload = dict(row.payload_json or {})
        claim = dict(payload.get("hotel_claim") or {})
        display = dict(claim.get("hotel_display") or {})
        proposed = dict(claim.get("proposed_hotel") or {})
        profile = dict(payload.get("profile") or {})
        conflict = dict(claim.get("conflict") or {})
        return {
            "supplier_id": row.supplier_id,
            "case_id": row.commercial_case_id,
            "state": row.state,
            "waiting_since": _iso(row.updated_at),
            "submitted_at": payload.get("submitted_at"),
            "organization_name": profile.get("organization_name") or payload.get("organization_name"),
            "legal_name": payload.get("legal_name"),
            "hotel_name": display.get("name") or proposed.get("name"),
            "hotel_city": display.get("city") or proposed.get("city"),
            "claim_mode": claim.get("mode"),
            "relationship_type": claim.get("relationship_type"),
            "conflict_reason": conflict.get("reason"),
        }

    def detail(self, supplier_id: str) -> dict:
        with SessionLocal() as session:
            row = self._case(session, supplier_id)
            if row is None:
                raise ValueError(CASE_NOT_FOUND)
            payload = dict(row.payload_json or {})
            claim = dict(payload.get("hotel_claim") or {})
            history = session.scalars(
                select(AuditEventRow).where(
                    AuditEventRow.resource_type == RESOURCE_TYPE,
                    AuditEventRow.resource_id == row.commercial_case_id,
                ).order_by(AuditEventRow.created_at.asc(),
                           AuditEventRow.audit_id.asc()).limit(HISTORY_LIMIT)
            ).all()
            state = row.state
            return {
                "supplier_id": row.supplier_id,
                "case_id": row.commercial_case_id,
                "state": state,
                "submitted_at": payload.get("submitted_at"),
                "reviewed_at": payload.get("reviewed_at"),
                "reviewed_by": payload.get("reviewed_by"),
                "updated_at": _iso(row.updated_at),
                "legal_entity": legal_entity_service.get_for_supplier(supplier_id),
                "documents": legal_entity_document_service.list_for_supplier(supplier_id),
                "hotel_claim": claim or None,
                "hotel_id": payload.get("hotel_id"),
                "hotel_registration_direct_id": payload.get("hotel_registration_direct_id"),
                "conflict": claim.get("conflict"),
                "review": payload.get("review"),
                "review_findings": list(payload.get("review_findings") or []),
                "review_note": payload.get("review_note"),
                "reopen": payload.get("reopen"),
                "finding_codes": list(FINDING_CODES),
                "relationship_proof_types": list(RELATIONSHIP_PROOF_TYPES),
                "actions": {
                    "can_decide": state in DECIDABLE_STATES,
                    "can_approve": state == "UNDER_REVIEW",
                    "can_reject": state in DECIDABLE_STATES,
                    "can_resolve_conflict": state == "CLAIM_CONFLICT",
                    "can_reopen": state in REOPENABLE_STATES,
                },
                "history": [{
                    "action": event.action,
                    "actor_id": event.actor_id,
                    "actor_type": event.actor_type,
                    "created_at": _iso(event.created_at),
                    "before_state": event.before_state,
                    "after_state": event.after_state,
                    "metadata": dict(event.metadata_json or {}),
                } for event in history],
            }

    # ---- the decision ---------------------------------------------------
    def decide(self, supplier_id: str, actor: str, decision: str,
               note: str | None = None, findings=None) -> dict:
        decision = str(decision or "").strip().upper()
        if decision not in DECISIONS:
            raise ValueError(DECISION_INVALID)
        cleaned = clean_findings(findings)
        if decision == DECISION_NEEDS_CHANGES and not cleaned:
            # Without a finding this is a rejection wearing a friendlier word.
            raise ValueError(FINDINGS_REQUIRED)
        try:
            with transaction(SessionLocal) as session:
                return self._decide_locked(session, supplier_id, actor, decision, note, cleaned)
        except ClaimConflict as conflict:
            # The approval lost a race inside its own transaction, which has now
            # been rolled back in full. Recording the conflict is a separate,
            # deliberate write; it is not part of a half-finished approval.
            onboarding_hotel_service.record_conflict(supplier_id, actor, conflict.detail)
            raise ValueError("CLAIM_CONFLICT") from None

    def _decide_locked(self, session, supplier_id: str, actor: str, decision: str,
                       note: str | None, findings: list[dict]) -> dict:
        row = self._locked_case(session, supplier_id)
        if row is None:
            raise ValueError(CASE_NOT_FOUND)
        if row.state not in DECIDABLE_STATES:
            raise ValueError(CASE_NOT_REVIEWABLE)
        before = row.state
        now = _now()

        if decision == DECISION_APPROVE:
            if before == "CLAIM_CONFLICT":
                # Approving both claimants would be a coin flip. Somebody has to
                # say who gets the hotel first.
                raise ValueError(CLAIM_CONFLICT_MUST_BE_RESOLVED)
            result = onboarding_hotel_service.approve_locked(session, supplier_id, actor, note)
            # Same session, same identity map: this is the row the hotel service
            # just moved to VERIFIED, so the decision record lands with it.
            case_row = self._case(session, supplier_id)
            payload = dict(case_row.payload_json or {})
            payload["review"] = {
                "decision": decision, "note": note, "findings": [],
                "decided_by": actor, "decided_at": _iso(now),
            }
            payload["review_findings"] = []
            case_row.payload_json = payload
            self._audit(session, actor=actor, action="SUPPLIER_ONBOARDING_REVIEW_DECIDED",
                        supplier_id=supplier_id, resource_id=row.commercial_case_id,
                        before=before, after=case_row.state,
                        metadata={"decision": decision, "note": note, "findings": [],
                                  "hotel_id": result.get("hotel_id"),
                                  "idempotent_replay": bool(result.get("idempotent"))})
            return {"state": case_row.state, "decision": decision,
                    "hotel_id": result.get("hotel_id"),
                    "hotel_registration_direct_id": result.get("hotel_registration_direct_id")}

        payload = dict(row.payload_json or {})
        payload["review"] = {
            "decision": decision, "note": note, "findings": findings,
            "decided_by": actor, "decided_at": _iso(now),
        }
        payload["review_findings"] = findings
        payload["review_note"] = note
        payload["reviewed_by"] = actor
        payload["reviewed_at"] = _iso(now)
        if decision == DECISION_NEEDS_CHANGES:
            claim = dict(payload.get("hotel_claim") or {})
            if claim.get("conflict"):
                # A human has now judged the conflict, so the applicant is free to
                # pick again; keeping the marker would disable the claim screen.
                claim["conflict"] = None
                payload["hotel_claim"] = claim
            row.state = "NEEDS_CHANGES"
        else:
            row.state = "REJECTED"
        row.payload_json = payload
        row.updated_at = now
        self._audit(session, actor=actor, action="SUPPLIER_ONBOARDING_REVIEW_DECIDED",
                    supplier_id=supplier_id, resource_id=row.commercial_case_id,
                    before=before, after=row.state,
                    metadata={"decision": decision, "note": note, "findings": findings,
                              # Recorded explicitly, because "we did not touch the
                              # legal entity" is the whole point of this decision.
                              "legal_entity_untouched": True})
        return {"state": row.state, "decision": decision, "findings": findings}

    # ---- governance acts ------------------------------------------------
    def reopen(self, supplier_id: str, actor: str, reason: str) -> dict:
        reason = _text(reason, 500)
        if not reason:
            raise ValueError(REOPEN_REASON_REQUIRED)
        with transaction(SessionLocal) as session:
            row = self._locked_case(session, supplier_id)
            if row is None:
                raise ValueError(CASE_NOT_FOUND)
            if row.state not in REOPENABLE_STATES:
                raise ValueError(REOPEN_NOT_ALLOWED)
            before = row.state
            now = _now()
            payload = dict(row.payload_json or {})
            payload["reopen"] = {"from_state": before, "reason": reason,
                                 "by": actor, "at": _iso(now)}
            # The previous decision stays in the audit trail and in ``reopen``;
            # the live decision block is cleared so the applicant is not looking
            # at stale findings while they edit.
            payload["review"] = None
            payload["review_findings"] = []
            row.payload_json = payload
            row.state = "PROFILE_DRAFT"
            row.updated_at = now
            self._audit(session, actor=actor, action="SUPPLIER_ONBOARDING_REOPENED",
                        supplier_id=supplier_id, resource_id=row.commercial_case_id,
                        before=before, after=row.state,
                        metadata={"reason": reason})
            return {"state": row.state, "reopened_from": before}

    def resolve_conflict(self, supplier_id: str, actor: str, resolution: str,
                         reason: str, confirmed: bool) -> dict:
        resolution = str(resolution or "").strip().upper()
        if resolution not in RESOLUTIONS:
            raise ValueError(CLAIM_CONFLICT_RESOLUTION_INVALID)
        reason = _text(reason, 500)
        if not reason:
            raise ValueError(CLAIM_CONFLICT_REASON_REQUIRED)
        if confirmed is not True:
            # Both resolutions take a hotel away from somebody. An unconfirmed
            # click must not be able to do that.
            raise ValueError(CLAIM_CONFLICT_CONFIRMATION_REQUIRED)
        try:
            with transaction(SessionLocal) as session:
                return self._resolve_locked(session, supplier_id, actor, resolution, reason)
        except ClaimConflict as conflict:
            onboarding_hotel_service.record_conflict(supplier_id, actor, conflict.detail)
            raise ValueError("CLAIM_CONFLICT") from None

    def _resolve_locked(self, session, supplier_id: str, actor: str, resolution: str,
                        reason: str) -> dict:
        row = self._locked_case(session, supplier_id)
        if row is None:
            raise ValueError(CASE_NOT_FOUND)
        if row.state != "CLAIM_CONFLICT":
            raise ValueError(CLAIM_CONFLICT_REQUIRED)
        payload = dict(row.payload_json or {})
        claim = dict(payload.get("hotel_claim") or {})
        conflict = dict(claim.get("conflict") or {})
        hotel_id = conflict.get("hotel_id")
        now = _now()

        if resolution == RESOLUTION_REJECT_LATE:
            claim["hotel_id"] = None
            claim["proposed_hotel"] = None
            claim["approved_at"] = None
            claim["hotel_registration_direct_id"] = None
            claim["conflict"] = None
            claim["resolution"] = {"resolution": resolution, "reason": reason,
                                   "by": actor, "at": _iso(now), "hotel_id": hotel_id}
            payload["hotel_claim"] = claim
            payload["review_findings"] = [{
                "code": "HOTEL_CLAIM_LOST",
                "message": "该酒店已由其他主体持有，请重新选择或提交你的酒店资料。",
            }]
            row.payload_json = payload
            row.state = "NEEDS_CHANGES"
            row.updated_at = now
            self._audit(session, actor=actor, action="SUPPLIER_ONBOARDING_CLAIM_CONFLICT_RESOLVED",
                        supplier_id=supplier_id, resource_id=row.commercial_case_id,
                        before="CLAIM_CONFLICT", after=row.state,
                        metadata={"resolution": resolution, "reason": reason,
                                  "hotel_id": hotel_id, "incumbent_changed": False})
            return {"state": row.state, "resolution": resolution, "hotel_id": hotel_id,
                    "incumbent_changed": False}

        # REVOKE_INCUMBENT. The incumbent's grant and the late claimant's new grant
        # are one transaction on purpose: if the second half failed alone, the hotel
        # would end up with no holder at all, which is worse than the conflict.
        if not hotel_id:
            raise ValueError(CLAIM_CONFLICT_HOTEL_UNKNOWN)
        incumbent = session.scalar(
            select(CommercialCaseRow).where(
                CommercialCaseRow.case_type == CASE_TYPE,
                CommercialCaseRow.property_id == hotel_id,
                CommercialCaseRow.supplier_id != supplier_id,
                CommercialCaseRow.state.in_(LIVE_CASE_STATES),
            ).with_for_update()
        )
        if incumbent is None:
            raise ValueError(CLAIM_CONFLICT_INCUMBENT_NOT_FOUND)
        incumbent_supplier_id = incumbent.supplier_id
        self._revoke_holder(session, incumbent, hotel_id, actor, reason, now)

        claim["mode"] = MODE_EXISTING
        claim["hotel_id"] = hotel_id
        claim["proposed_hotel"] = None
        claim["conflict"] = None
        claim["resolution"] = {"resolution": resolution, "reason": reason,
                               "by": actor, "at": _iso(now), "hotel_id": hotel_id,
                               "revoked_supplier_id": incumbent_supplier_id}
        payload["hotel_claim"] = claim
        row.payload_json = payload
        # approve_locked refuses anything outside CLAIM_APPROVABLE_STATES, and the
        # case is currently parked in CLAIM_CONFLICT. Human judgement has resolved
        # it, so the case resumes as "needs changes, now corrected".
        row.state = "NEEDS_CHANGES"
        row.updated_at = now
        result = onboarding_hotel_service.approve_locked(session, supplier_id, actor, reason)
        self._audit(session, actor=actor, action="SUPPLIER_ONBOARDING_CLAIM_CONFLICT_RESOLVED",
                    supplier_id=supplier_id, resource_id=row.commercial_case_id,
                    before="CLAIM_CONFLICT", after=result.get("state"),
                    metadata={"resolution": resolution, "reason": reason,
                              "hotel_id": hotel_id, "incumbent_supplier_id": incumbent_supplier_id,
                              "incumbent_changed": True})
        return {"state": result.get("state"), "resolution": resolution, "hotel_id": hotel_id,
                "revoked_supplier_id": incumbent_supplier_id, "incumbent_changed": True}

    def _revoke_holder(self, session, incumbent: CommercialCaseRow, hotel_id: str,
                       actor: str, reason: str, now: datetime) -> None:
        """Take a granted hotel away from its holder, in the caller's transaction."""
        before = incumbent.state
        payload = dict(incumbent.payload_json or {})
        claim = dict(payload.get("hotel_claim") or {})
        claim["hotel_id"] = None
        claim["proposed_hotel"] = None
        claim["approved_at"] = None
        claim["hotel_registration_direct_id"] = None
        claim["conflict"] = None
        claim["revoked"] = {"reason": reason, "by": actor, "at": _iso(now), "hotel_id": hotel_id}
        payload["hotel_claim"] = claim
        payload["hotel_id"] = None
        payload["hotel_registration_direct_id"] = None
        payload["review_findings"] = [{
            "code": "HOTEL_CLAIM_REVOKED",
            "message": "该酒店的归属经人工复核后改判，请重新选择或提交你的酒店资料。",
        }]
        payload["review"] = {"decision": RESOLUTION_REVOKE_INCUMBENT, "note": reason,
                             "findings": payload["review_findings"],
                             "decided_by": actor, "decided_at": _iso(now)}
        incumbent.payload_json = payload
        # property_id must be released before the late claimant can hold the same
        # hotel: the partial unique index in migration 0148 allows exactly one live
        # holder per hotel, and that is the point of it.
        incumbent.property_id = None
        incumbent.state = "NEEDS_CHANGES"
        incumbent.updated_at = now
        for relation in session.scalars(
                select(HotelRegistrationDirectRow).where(
                    HotelRegistrationDirectRow.hotel_id == hotel_id,
                    HotelRegistrationDirectRow.supplier_id == incumbent.supplier_id,
                    HotelRegistrationDirectRow.state == "APPROVED")):
            relation.state = "REVOKED"
            relation.reviewed_by = actor
            relation.reviewed_at = now
        # Flush the release BEFORE the grant is staged. Both uniqueness rules are
        # checked row by row, not at commit, so an interleaved order would trip them
        # on an intermediate state where both cases hold the hotel. Still inside the
        # caller's transaction: if the grant then fails, the release rolls back too.
        session.flush()
        self._audit(session, actor=actor, action="SUPPLIER_ONBOARDING_HOTEL_REVOKED",
                    supplier_id=incumbent.supplier_id,
                    resource_id=incumbent.commercial_case_id,
                    before=before, after=incumbent.state,
                    metadata={"hotel_id": hotel_id, "reason": reason,
                              "revoked_for_supplier_id": incumbent.supplier_id})


onboarding_review_service = OnboardingReviewService()


def relationship_is_proven(supplier_id: str, claim: dict) -> bool:
    """Whether the stored artefacts actually back a non-owner relationship.

    Exposed for the console so the reviewer sees the same answer the submit gate
    would give, instead of re-deriving it and disagreeing.
    """
    relationship_type = str((claim or {}).get("relationship_type") or "").upper()
    if not relationship_type or relationship_type == OWNER:
        return True
    with SessionLocal() as session:
        return any(
            legal_entity_document_service.current_for_supplier(session, supplier_id, document_type)
            is not None for document_type in RELATIONSHIP_PROOF_TYPES
        )
