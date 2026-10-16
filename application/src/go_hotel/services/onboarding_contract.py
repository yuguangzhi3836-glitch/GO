"""The cooperation contract: one template, one signed scan, one atomic confirmation.

Frozen decisions landed here (D-07, CHANGE 11, DATA_MODEL §3.4, JOURNEY S10/S11):

* **V1 creates no contract table.** The six things a contract has to prove are
  already carried by artefacts that exist: *who signs with whom* is
  ``legal_entity_id``, *which hotel* is the approved ``hotel_registration_go_direct``
  row, *which version of which text* is ``template_version`` + ``template_sha256``,
  *the signed file* is ``legal_entity_document(SIGNED_CONTRACT)``, its hash is
  ``signed_document_sha256``, and *when the human agreed* is ``audit_event.created_at``.
  Adding a ``supplier_contract`` table would be ``REAL_FAILURE_PREVENTED=NONE``.

* **The template is an asset, not a row.** It has a version and a sha256, and the
  service re-hashes the file on every read: a swapped or truncated template is
  refused rather than served. Same rule ``registration_terms`` already applies to
  the registration documents.

* **``template_sha256`` is a guard, not decoration.** The applicant's browser holds
  the hash of the version it displayed and sends it back with the confirmation.
  Confirming a version the human never read is refused, which is the whole reason
  the client is asked for the hash instead of the server just trusting its own.

* **One transaction.** The immutable audit event and ``case.state =
  CONTRACT_ACTIVE`` are written together. There is therefore no window in which the
  platform grants business access without a recorded confirmation, and no window in
  which a confirmation exists but access was never granted.

* **No second human review** (D-003). The old flow took a typed reference string
  (``contract_ref``) as proof of signature and then waited for an administrator.
  Both halves are gone: a typed string was never evidence, and the journey does not
  have a contract-reviewer step.

REAL TEMPLATE BOUNDARY (D-07): no approved GO partner agreement lives in this
repository, and we do not fabricate one. The step therefore runs against
``LOCAL_TEST_CONTRACT_FIXTURE``, which says on its first line that it is not a
contract, and the release evidence records
``BLOCKED_EXTERNAL_ASSET: PRODUCTION_CONTRACT_TEMPLATE_REQUIRED``. That blocks the
*commercial* claim, not the code candidate.

Errors are codes, never prose. The frontend owns the copy.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from go_hotel.db.models import (
    AuditEventRow,
    CommercialCaseRow,
    HotelCanonicalProfileRow,
    HotelRegistrationDirectRow,
    LegalEntityRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services.legal_entity_document import legal_entity_document_service
from go_hotel.services.supplier_onboarding_state import CONTRACT_SUBMITTABLE

CASE_TYPE = "SUPPLIER_ONBOARDING"
SIGNED_CONTRACT = "SIGNED_CONTRACT"
ACTIVATED_STATES = {"CONTRACT_ACTIVE", "BUSINESS_ENABLED"}

CONTRACT_DIR = Path(__file__).resolve().parents[1] / "legal" / "contract"
TEMPLATE_VERSION = "2026-10-06-test-v1"

CONTRACT_NOT_CONFIRMABLE = "CONTRACT_NOT_CONFIRMABLE"
CONTRACT_AGREEMENT_REQUIRED = "CONTRACT_AGREEMENT_REQUIRED"
CONTRACT_TEMPLATE_CHANGED = "CONTRACT_TEMPLATE_CHANGED"
CONTRACT_TEMPLATE_UNAVAILABLE = "CONTRACT_TEMPLATE_UNAVAILABLE"
CONTRACT_SIGNED_DOCUMENT_REQUIRED = "CONTRACT_SIGNED_DOCUMENT_REQUIRED"
CONTRACT_SIGNED_DOCUMENT_INVALID = "CONTRACT_SIGNED_DOCUMENT_INVALID"
CONTRACT_HOTEL_REQUIRED = "CONTRACT_HOTEL_REQUIRED"
SUPPLIER_ONBOARDING_NOT_FOUND = "SUPPLIER_ONBOARDING_NOT_FOUND"

# The order matters: it is the order the screen tells the human what to do next.
BLOCKER_ORDER = (
    CONTRACT_NOT_CONFIRMABLE,
    CONTRACT_TEMPLATE_UNAVAILABLE,
    CONTRACT_SIGNED_DOCUMENT_REQUIRED,
    CONTRACT_HOTEL_REQUIRED,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class OnboardingContractService:
    # ---- the template asset -------------------------------------------
    def _read_template(self) -> tuple[dict, bytes]:
        """Load the manifest and the bytes, and prove they still agree.

        A template whose bytes no longer match the hash the platform recorded is a
        worse failure than a missing one: the applicant would be asked to confirm a
        text nobody can identify afterwards. So the hash is re-verified on every
        read and a mismatch is a hard error.
        """
        folder = CONTRACT_DIR / TEMPLATE_VERSION
        manifest_path = folder / "template.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError(CONTRACT_TEMPLATE_UNAVAILABLE) from None
        filename = str(manifest.get("filename") or "")
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            # The filename comes from a repo file, but it also ends up in a
            # Content-Disposition header, so it is validated like any input.
            raise ValueError(CONTRACT_TEMPLATE_UNAVAILABLE)
        try:
            raw = (folder / filename).read_bytes()
        except OSError:
            raise ValueError(CONTRACT_TEMPLATE_UNAVAILABLE) from None
        if not raw or hashlib.sha256(raw).hexdigest() != manifest.get("sha256"):
            raise ValueError(CONTRACT_TEMPLATE_UNAVAILABLE)
        return manifest, raw

    def template(self) -> dict:
        """Public description of the template the applicant is about to read.

        ``blocked_external_asset`` is published deliberately: an operator opening
        the contract page in a non-production environment should be able to see
        that what they are looking at is a fixture, without reading the source.
        """
        manifest, raw = self._read_template()
        return {
            "version": manifest["version"],
            "title": manifest.get("title") or "合作协议",
            "filename": manifest["filename"],
            "mime_type": manifest["mime_type"],
            "size_bytes": len(raw),
            "sha256": manifest["sha256"],
            "marking": manifest.get("marking"),
            "source": manifest.get("source"),
            "is_test_fixture": manifest.get("source") == "TEST",
            "blocked_external_asset": manifest.get("blocked_external_asset"),
            "note": manifest.get("note"),
        }

    def template_bytes(self) -> tuple[bytes, str, str]:
        manifest, raw = self._read_template()
        return raw, manifest["mime_type"], manifest["filename"]

    # ---- lookups -------------------------------------------------------
    @staticmethod
    def _case(session, supplier_id: str) -> CommercialCaseRow | None:
        return session.scalar(
            select(CommercialCaseRow).where(
                CommercialCaseRow.case_type == CASE_TYPE,
                CommercialCaseRow.supplier_id == supplier_id,
            )
        )

    def _hotel(self, session, supplier_id: str, payload: dict) -> dict | None:
        """The hotel the case is bound to, as a human-facing fact."""
        hotel_id = payload.get("hotel_id")
        registration_id = payload.get("hotel_registration_direct_id")
        registration = (
            session.get(HotelRegistrationDirectRow, registration_id) if registration_id else None
        )
        if registration is not None and registration.supplier_id != supplier_id:
            registration = None
        if hotel_id is None and registration is not None:
            hotel_id = registration.hotel_id
        if hotel_id is None:
            proposed = payload.get("proposed_hotel") or {}
            if proposed:
                # Not yet a platform identity (frozen decision D-05): a proposal is
                # reported as a proposal, never dressed up as a canonical hotel.
                return {
                    "hotel_id": None,
                    "name": proposed.get("name"),
                    "city": proposed.get("city"),
                    "address": proposed.get("address"),
                    "state": "PROPOSED",
                    "profile_completeness_bps": None,
                }
            return None
        profile = session.get(HotelCanonicalProfileRow, hotel_id)
        canonical = dict(profile.canonical_json or {}) if profile else {}
        address = canonical.get("address")
        city = canonical.get("city")
        if isinstance(address, dict):
            # Hotels created by the earlier seed paths keep the city inside the
            # address object. A nested object also must never be rendered straight
            # into a page, so the display value is flattened here.
            city = city or address.get("city")
            address = address.get("formatted") or address.get("city")
        return {
            "hotel_id": hotel_id,
            "name": canonical.get("name") or canonical.get("name_zh"),
            "city": city,
            "address": address,
            "state": registration.state if registration else None,
            "relationship_type": registration.relationship_type if registration else None,
            "go_direct_state": profile.go_direct_state if profile else None,
            "page_state": profile.page_state if profile else None,
            "profile_completeness_bps": profile.completeness_bps if profile else None,
        }

    # ---- the applicant's contract screen (S10) --------------------------
    def state(self, supplier_id: str) -> dict:
        """Everything the contract screen needs, and an honest list of blockers.

        Reading must not fail because the applicant has not got there yet: an early
        state is a normal state, not an error. So a missing template or a missing
        signed scan is reported as a blocker instead of raised.
        """
        with SessionLocal() as session:
            row = self._case(session, supplier_id)
            if row is None:
                raise ValueError(SUPPLIER_ONBOARDING_NOT_FOUND)
            payload = dict(row.payload_json or {})
            signed = legal_entity_document_service.current_for_supplier(
                session, supplier_id, SIGNED_CONTRACT
            )
            entity = session.scalar(
                select(LegalEntityRow).where(LegalEntityRow.supplier_id == supplier_id)
            )
            hotel = self._hotel(session, supplier_id, payload)

            blockers = []
            if row.state not in CONTRACT_SUBMITTABLE and row.state not in ACTIVATED_STATES:
                blockers.append(CONTRACT_NOT_CONFIRMABLE)
            try:
                template = self.template()
            except ValueError:
                template = None
                blockers.append(CONTRACT_TEMPLATE_UNAVAILABLE)
            if signed is None:
                blockers.append(CONTRACT_SIGNED_DOCUMENT_REQUIRED)
            if hotel is None or hotel.get("hotel_id") is None:
                blockers.append(CONTRACT_HOTEL_REQUIRED)

            confirmation = payload.get("contract_confirmation") or {}
            return {
                "supplier_id": supplier_id,
                "state": row.state,
                "can_confirm": not blockers and row.state in CONTRACT_SUBMITTABLE,
                "blockers": [b for b in BLOCKER_ORDER if b in blockers],
                "activated": row.state in ACTIVATED_STATES,
                "template": template,
                "signed_document": (
                    legal_entity_document_service.serialize(signed) if signed else None
                ),
                "legal_entity": (
                    {
                        "legal_name": entity.legal_name,
                        "unified_social_credit_code": entity.unified_social_credit_code,
                        "verification_state": getattr(entity, "verification_state", None),
                    }
                    if entity
                    else None
                ),
                "hotel": hotel,
                "confirmation": confirmation or None,
                "contract_review_note": payload.get("contract_review_note"),
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }

    # ---- the one write -------------------------------------------------
    def confirm(
        self,
        supplier_id: str,
        actor: str,
        *,
        agreed: bool | None,
        template_sha256: str | None,
        signed_document_id: str | None = None,
        note: str | None = None,
    ) -> dict:
        """Confirm the contract and activate the supplier, in one transaction.

        ``agreed`` is a real field, not a convention: the platform records that the
        human ticked the box, so it refuses to infer agreement from the mere
        presence of a request.
        """
        # The template is read (and re-verified) before the transaction opens: it is
        # an asset, so it cannot be part of the atomic unit.
        template = self.template()
        if agreed is not True:
            raise ValueError(CONTRACT_AGREEMENT_REQUIRED)
        if str(template_sha256 or "") != template["sha256"]:
            # The applicant read a version that is no longer the current one.
            raise ValueError(CONTRACT_TEMPLATE_CHANGED)

        now = _now()
        with SessionLocal() as session:
            row = session.scalar(
                select(CommercialCaseRow)
                .where(
                    CommercialCaseRow.case_type == CASE_TYPE,
                    CommercialCaseRow.supplier_id == supplier_id,
                )
                .with_for_update()
            )
            if row is None:
                raise ValueError(SUPPLIER_ONBOARDING_NOT_FOUND)
            payload = dict(row.payload_json or {})
            before_state = row.state
            previous = dict(payload.get("contract_confirmation") or {})

            signed = legal_entity_document_service.current_for_supplier(
                session, supplier_id, SIGNED_CONTRACT
            )
            if row.state not in CONTRACT_SUBMITTABLE:
                # A repeat of the *same* confirmation is a double-click, not a new
                # act: answer it with the state it already produced rather than
                # writing a second governance record. Confirming anything else after
                # activation is refused.
                same_document = signed_document_id in (None, previous.get("signed_document_id"))
                if (
                    row.state in ACTIVATED_STATES
                    and previous.get("template_sha256") == template["sha256"]
                    and same_document
                    and signed is not None
                    and previous.get("signed_document_id") == signed.document_id
                ):
                    return self._serialize(row, template, already_confirmed=True)
                raise ValueError(CONTRACT_NOT_CONFIRMABLE)

            if signed is None:
                raise ValueError(CONTRACT_SIGNED_DOCUMENT_REQUIRED)
            if signed_document_id and signed_document_id != signed.document_id:
                # The client named a revision that is no longer the current one.
                raise ValueError(CONTRACT_SIGNED_DOCUMENT_INVALID)
            entity = session.scalar(
                select(LegalEntityRow).where(LegalEntityRow.supplier_id == supplier_id)
            )
            if entity is None:
                raise ValueError("LEGAL_ENTITY_REQUIRED")
            hotel_id = payload.get("hotel_id")
            registration_direct_id = payload.get("hotel_registration_direct_id")
            if not hotel_id or not registration_direct_id:
                # A contract names a hotel. Without an approved registration there is
                # nothing for it to name.
                raise ValueError(CONTRACT_HOTEL_REQUIRED)

            confirmed_at = _iso(now)
            # CHANGE 11: nine explicit fields. Deliberately not one opaque
            # `body_sha256` — an auditor must be able to tell which hash means what.
            confirmation = {
                "template_version": template["version"],
                "template_sha256": template["sha256"],
                "signed_document_id": signed.document_id,
                "signed_document_sha256": signed.sha256,
                "legal_entity_id": entity.legal_entity_id,
                "hotel_id": hotel_id,
                "registration_direct_id": registration_direct_id,
                "confirmed_by": actor,
                "confirmed_at": confirmed_at,
            }
            if note:
                confirmation["note"] = str(note)[:2000]

            row.state = "CONTRACT_ACTIVE"
            payload["contract"] = confirmation
            payload["contract_confirmation"] = confirmation
            payload["contract_confirmed_at"] = confirmed_at
            payload["contract_review_note"] = None
            row.payload_json = payload
            row.updated_at = now
            session.add(
                AuditEventRow(
                    audit_id=f"aud_{uuid.uuid4().hex}",
                    actor_id=actor,
                    actor_type="SUPPLIER_USER",
                    supplier_id=supplier_id,
                    roles=[],
                    action="SUPPLIER_CONTRACT_CONFIRMED",
                    resource_type="commercial_case",
                    resource_id=row.commercial_case_id,
                    before_state={"state": before_state},
                    after_state=confirmation,
                    metadata_json={
                        "template_marking": template.get("marking"),
                        "template_source": template.get("source"),
                        "blocked_external_asset": template.get("blocked_external_asset"),
                        "signed_document_revision": signed.revision,
                    },
                    created_at=now,
                )
            )
            session.commit()
            session.refresh(row)
            return self._serialize(row, template, already_confirmed=False)

    @staticmethod
    def _serialize(row: CommercialCaseRow, template: dict, *, already_confirmed: bool) -> dict:
        payload = dict(row.payload_json or {})
        return {
            "supplier_id": row.supplier_id,
            "state": row.state,
            "activated": row.state in ACTIVATED_STATES,
            "business_ready": row.state in ACTIVATED_STATES,
            "already_confirmed": already_confirmed,
            "template": template,
            "confirmation": dict(payload.get("contract_confirmation") or {}) or None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    # ---- what activation actually gave the supplier (S11) ---------------
    def activation(self, supplier_id: str) -> dict:
        """Post-activation facts for the supplier console's 我的酒店 card.

        Every number here is read from stored rows, never derived from the request:
        a card that says "已认领" has to be backed by the approved relation, and a
        completeness figure has to be the one the profile actually carries.
        """
        with SessionLocal() as session:
            row = self._case(session, supplier_id)
            if row is None:
                raise ValueError(SUPPLIER_ONBOARDING_NOT_FOUND)
            payload = dict(row.payload_json or {})
            hotel = self._hotel(session, supplier_id, payload)
            confirmation = dict(payload.get("contract_confirmation") or {})
            activation_state = row.state
            if hotel and hotel.get("hotel_id"):
                completeness = hotel.get("profile_completeness_bps")
                hotel["claimed"] = hotel.get("state") == "APPROVED"
                hotel["completeness_bps"] = completeness
                # First-things-first, in the order a new partner actually needs them.
                todo = []
                if not hotel.get("page_state") or hotel.get("page_state") == "DRAFT":
                    todo.append("PUBLISH_HOTEL_PAGE")
                if hotel.get("go_direct_state") != "GO_DIRECT_LIVE":
                    todo.append("GO_DIRECT_NOT_LIVE")
                if completeness is not None and completeness < 10000:
                    todo.append("COMPLETE_HOTEL_PROFILE")
                hotel["todo"] = todo
            return {
                "supplier_id": supplier_id,
                "state": activation_state,
                "business_ready": activation_state in ACTIVATED_STATES,
                "business_enabled": activation_state == "BUSINESS_ENABLED",
                "hotel": hotel,
                "contract": {
                    "confirmed_at": confirmation.get("confirmed_at"),
                    "template_version": confirmation.get("template_version"),
                    "template_sha256": confirmation.get("template_sha256"),
                }
                or None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }


onboarding_contract_service = OnboardingContractService()
