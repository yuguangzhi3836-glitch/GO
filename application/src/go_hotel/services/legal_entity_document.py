"""Private applicant evidence with revisions, revisions we can prove, and no leaks.

What this service owns (frozen decisions CHANGE 2, CHANGE 10, D-03, D-04):

* The DB row + the file on a private volume. Bytes never live in PostgreSQL and
  the ``storage_key`` never leaves the backend.
* Two scopes in one table: entity level (``onboarding_case_id IS NULL``) and
  onboarding level. A licence is entity level; a hotel operation proof or a
  signed contract is onboarding level. Which one a document type belongs to is
  derived from the type (``natural_scope``), so the browser asks for a *named
  scope* (``ENTITY`` / ``ONBOARDING``) and never carries an internal case id.
* ``revision`` history with exactly one *current* row per (scope, document type),
  enforced by partial unique indexes rather than application bookkeeping.
* De-duplication by content hash: re-uploading the identical bytes does not burn
  a revision and does not create a second row.
* ``expected_revision`` optimistic concurrency, so a reviewer's verdict can never
  be silently attached to a document the applicant has already replaced.

Errors are codes, never prose. The frontend owns the copy.
"""
from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from go_hotel.db.models import (
    AuditEventRow,
    CommercialCaseRow,
    LegalEntityDocumentRow,
    LegalEntityRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.services.document_store import document_store

# Kept in step with ``ck_legal_entity_document_type``.
DOCUMENT_TYPES = frozenset(
    {
        "BUSINESS_LICENSE",
        "LEGAL_REP_ID",
        "AGENT_ID",
        "STOREFRONT_PHOTO",
        "HOTEL_OPERATION_PROOF",
        "FRANCHISE_OR_MANAGEMENT_CONTRACT",
        "SIGNED_CONTRACT",
    }
)

DOCUMENT_TYPE_UNSUPPORTED = "DOCUMENT_TYPE_UNSUPPORTED"
LEGAL_ENTITY_REQUIRED = "LEGAL_ENTITY_REQUIRED"
ONBOARDING_CASE_NOT_FOUND = "ONBOARDING_CASE_NOT_FOUND"
DOCUMENT_REVISION_STALE = "DOCUMENT_REVISION_STALE"
DOCUMENT_REVISION_CONFLICT = "DOCUMENT_REVISION_CONFLICT"
DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
DOCUMENT_STATUS_INVALID = "DOCUMENT_STATUS_INVALID"
DOCUMENT_SCOPE_INVALID = "DOCUMENT_SCOPE_INVALID"

STATUS_UPLOADED = "UPLOADED"
STATUS_SUPERSEDED = "SUPERSEDED"
STATUSES = {"UPLOADED", "ACCEPTED", "REJECTED", "SUPERSEDED"}

PREVIEW_INLINE = "inline"
PREVIEW_ATTACHMENT = "attachment"

# Two scopes, named so the client never has to know a case id. "Entity" documents
# belong to the legal person for all time; "onboarding" documents exist only in
# the context of the current supplier onboarding (an operation proof, a signed
# contract). Which scope a document type belongs to is a backend fact, derived
# from the type, not something an applicant picks or can get wrong.
SCOPE_ENTITY = "ENTITY"
SCOPE_ONBOARDING = "ONBOARDING"
SCOPES = (SCOPE_ENTITY, SCOPE_ONBOARDING)
ONBOARDING_SCOPED_TYPES = frozenset(
    {"HOTEL_OPERATION_PROOF", "FRANCHISE_OR_MANAGEMENT_CONTRACT", "SIGNED_CONTRACT"}
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LegalEntityDocumentService:
    # ---- serialisation -------------------------------------------------
    @staticmethod
    def serialize(row: LegalEntityDocumentRow, *, deduplicated: bool = False) -> dict:
        # ``storage_key`` is deliberately absent: it is an internal path token and
        # the applicant has no business knowing it.
        return {
            "document_id": row.document_id,
            "document_type": row.document_type,
            "scope": "ENTITY" if row.onboarding_case_id is None else "ONBOARDING",
            "onboarding_case_id": row.onboarding_case_id,
            "original_filename": row.original_filename,
            "mime_type": row.mime_type,
            "size_bytes": row.size_bytes,
            "sha256": row.sha256,
            "revision": row.revision,
            "status": row.status,
            "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
            "replaced_at": row.replaced_at.isoformat() if row.replaced_at else None,
            "deduplicated": deduplicated,
        }

    # ---- lookups -------------------------------------------------------
    @staticmethod
    def _entity(session, supplier_id: str) -> LegalEntityRow | None:
        return session.scalar(
            select(LegalEntityRow).where(LegalEntityRow.supplier_id == supplier_id)
        )

    @staticmethod
    def _current_query(legal_entity_id: str, document_type: str, onboarding_case_id: str | None):
        query = select(LegalEntityDocumentRow).where(
            LegalEntityDocumentRow.legal_entity_id == legal_entity_id,
            LegalEntityDocumentRow.document_type == document_type,
            LegalEntityDocumentRow.status != STATUS_SUPERSEDED,
        )
        if onboarding_case_id is None:
            return query.where(LegalEntityDocumentRow.onboarding_case_id.is_(None))
        return query.where(LegalEntityDocumentRow.onboarding_case_id == onboarding_case_id)

    def _current(self, session, legal_entity_id, document_type, onboarding_case_id):
        return session.scalar(
            self._current_query(legal_entity_id, document_type, onboarding_case_id)
        )

    def _assert_case(self, session, supplier_id: str, onboarding_case_id: str) -> None:
        """A client must never be able to attach a document to someone else's case."""
        case = session.get(CommercialCaseRow, onboarding_case_id)
        if (
            case is None
            or case.case_type != "SUPPLIER_ONBOARDING"
            or case.supplier_id != supplier_id
        ):
            raise ValueError(ONBOARDING_CASE_NOT_FOUND)

    @staticmethod
    def natural_scope(document_type: str) -> str:
        return SCOPE_ONBOARDING if document_type in ONBOARDING_SCOPED_TYPES else SCOPE_ENTITY

    @staticmethod
    def _case_for_supplier(session, supplier_id: str) -> CommercialCaseRow | None:
        return session.scalar(
            select(CommercialCaseRow).where(
                CommercialCaseRow.case_type == "SUPPLIER_ONBOARDING",
                CommercialCaseRow.supplier_id == supplier_id,
            )
        )

    def resolve_case_id(self, session, supplier_id: str, scope: str | None = None,
                        onboarding_case_id: str | None = None) -> str | None:
        """Turn a *named scope* into the case it means, server side.

        The applicant's browser never carries a case id: it asks for scope
        ``ONBOARDING`` and the backend resolves it to the case the caller owns.
        A foreign id is therefore not "rejected", it is unrepresentable.
        """
        if onboarding_case_id is not None:
            self._assert_case(session, supplier_id, onboarding_case_id)
            return onboarding_case_id
        if scope is None:
            return None
        scope = str(scope).strip().upper()
        if scope == SCOPE_ENTITY:
            return None
        if scope != SCOPE_ONBOARDING:
            raise ValueError(DOCUMENT_SCOPE_INVALID)
        case = self._case_for_supplier(session, supplier_id)
        if case is None:
            raise ValueError(ONBOARDING_CASE_NOT_FOUND)
        return case.commercial_case_id

    def _resolve_for_read(self, session, supplier_id: str, scope: str | None,
                          onboarding_case_id: str | None) -> str | None:
        """Same resolution as a write, except that "no case yet" is not an error.

        Reading is how the screens learn the applicant has not reached that step;
        refusing to list would turn a normal early state into a failure.
        """
        try:
            return self.resolve_case_id(session, supplier_id, scope, onboarding_case_id)
        except ValueError as exc:
            if str(exc) == ONBOARDING_CASE_NOT_FOUND:
                return None
            raise

    def _effective_scope(self, document_type: str, scope: str | None,
                         onboarding_case_id: str | None) -> str | None:
        if onboarding_case_id is not None:
            return None
        if scope is not None:
            return scope
        return self.natural_scope(document_type)

    # ---- write ---------------------------------------------------------
    def upload(
        self,
        *,
        supplier_id: str,
        uploaded_by: str,
        document_type: str,
        data: bytes,
        filename: str | None,
        declared_mime: str | None = None,
        scope: str | None = None,
        onboarding_case_id: str | None = None,
        expected_revision: int | None = None,
    ) -> dict:
        document_type = str(document_type or "").strip().upper()
        if document_type not in DOCUMENT_TYPES:
            raise ValueError(DOCUMENT_TYPE_UNSUPPORTED)
        if expected_revision is not None and int(expected_revision) < 0:
            raise ValueError(DOCUMENT_REVISION_STALE)
        effective_scope = self._effective_scope(document_type, scope, onboarding_case_id)

        # Validate + write the bytes first. The store is content addressed and
        # writes atomically, so a failure here leaves the current revision intact.
        stored = document_store.persist(data, filename, declared_mime)

        now = _now()
        with SessionLocal() as session:
            entity = self._entity(session, supplier_id)
            if entity is None:
                # A licence without a legal entity has nothing to attach to.
                raise ValueError(LEGAL_ENTITY_REQUIRED)
            case_id = self.resolve_case_id(session, supplier_id, effective_scope, onboarding_case_id)

            current = self._current(session, entity.legal_entity_id, document_type, case_id)
            current_revision = current.revision if current else 0
            if expected_revision is not None and int(expected_revision) != current_revision:
                # The applicant is replacing a revision that is no longer current.
                # Refusing is the whole point: a verdict must not land on a document
                # that changed underneath it.
                raise ValueError(DOCUMENT_REVISION_STALE)

            if current is not None and current.sha256 == stored.sha256:
                # Byte-identical re-upload: no new revision, no second row. This is
                # what makes a double-clicked submit harmless.
                return self.serialize(current, deduplicated=True)

            if current is not None:
                # Retire the old revision *before* inserting, so the partial unique
                # index on the current row is never transiently violated.
                current.status = STATUS_SUPERSEDED
                current.replaced_at = now
                session.flush()

            row = LegalEntityDocumentRow(
                document_id=f"led_{uuid.uuid4().hex}",
                legal_entity_id=entity.legal_entity_id,
                onboarding_case_id=case_id,
                document_type=document_type,
                storage_key=stored.storage_key,
                original_filename=stored.original_filename,
                mime_type=stored.mime_type,
                size_bytes=stored.size_bytes,
                sha256=stored.sha256,
                revision=current_revision + 1,
                status=STATUS_UPLOADED,
                uploaded_by=uploaded_by,
                uploaded_at=now,
            )
            session.add(row)
            session.add(
                AuditEventRow(
                    audit_id=f"aud_{uuid.uuid4().hex}",
                    actor_id=uploaded_by,
                    actor_type="SUPPLIER_USER",
                    supplier_id=supplier_id,
                    roles=[],
                    action="SUPPLIER_DOCUMENT_UPLOADED",
                    resource_type="legal_entity_document",
                    resource_id=row.document_id,
                    before_state={"revision": current_revision} if current_revision else None,
                    after_state={"revision": row.revision, "document_type": document_type},
                    metadata_json={
                        "sha256": stored.sha256,
                        "size_bytes": stored.size_bytes,
                        "mime_type": stored.mime_type,
                        "scope": "ENTITY" if case_id is None else "ONBOARDING",
                        "superseded_document_id": current.document_id if current else None,
                    },
                    created_at=now,
                )
            )
            try:
                session.commit()
            except IntegrityError:
                # Another write won the race for this (scope, type) current slot.
                session.rollback()
                raise ValueError(DOCUMENT_REVISION_CONFLICT) from None
            session.refresh(row)
            return self.serialize(row)

    def set_status(self, document_id: str, status: str, *, actor_id: str) -> dict:
        """Reviewer-side accept/reject of one revision. Never touches the file."""
        status = str(status or "").strip().upper()
        if status not in STATUSES or status == STATUS_SUPERSEDED:
            raise ValueError(DOCUMENT_STATUS_INVALID)
        with SessionLocal() as session:
            row = session.get(LegalEntityDocumentRow, document_id)
            if row is None:
                raise ValueError(DOCUMENT_NOT_FOUND)
            before = row.status
            row.status = status
            session.add(
                AuditEventRow(
                    audit_id=f"aud_{uuid.uuid4().hex}",
                    actor_id=actor_id,
                    actor_type="GO_ADMIN",
                    supplier_id=None,
                    roles=[],
                    action="SUPPLIER_DOCUMENT_REVIEWED",
                    resource_type="legal_entity_document",
                    resource_id=document_id,
                    before_state={"status": before},
                    after_state={"status": status},
                    metadata_json={"revision": row.revision, "document_type": row.document_type},
                    created_at=_now(),
                )
            )
            session.commit()
            session.refresh(row)
            return self.serialize(row)

    # ---- read ----------------------------------------------------------
    def _locate_for_owner(self, session, supplier_id: str, document_id: str) -> LegalEntityDocumentRow:
        row = session.get(LegalEntityDocumentRow, document_id)
        if row is None:
            raise ValueError(DOCUMENT_NOT_FOUND)
        entity = session.get(LegalEntityRow, row.legal_entity_id)
        if entity is None or entity.supplier_id != supplier_id:
            # 404 rather than 403: a foreign applicant must not even learn that
            # this document id exists.
            raise ValueError(DOCUMENT_NOT_FOUND)
        return row

    def meta_for_owner(self, supplier_id: str, document_id: str) -> dict:
        with SessionLocal() as session:
            return self.serialize(self._locate_for_owner(session, supplier_id, document_id))

    def meta_for_reviewer(self, document_id: str) -> dict:
        """Only reachable from a route that already required ``admin:onboarding_review``."""
        with SessionLocal() as session:
            row = session.get(LegalEntityDocumentRow, document_id)
            if row is None:
                raise ValueError(DOCUMENT_NOT_FOUND)
            return self.serialize(row)

    def list_for_supplier(self, supplier_id: str, scope: str | None = None,
                          onboarding_case_id: str | None = None) -> list[dict]:
        """With no scope, return every document the applicant owns, both scopes.

        The step screens need one honest answer to "what have I uploaded", not two
        calls with an id the browser should never hold.
        """
        with SessionLocal() as session:
            entity = self._entity(session, supplier_id)
            if entity is None:
                return []
            case_id = None
            if scope is not None or onboarding_case_id is not None:
                case_id = self._resolve_for_read(session, supplier_id, scope, onboarding_case_id)
                scoped = True
            else:
                scoped = False
            query = select(LegalEntityDocumentRow).where(
                LegalEntityDocumentRow.legal_entity_id == entity.legal_entity_id
            )
            if scoped:
                if case_id is None:
                    query = query.where(LegalEntityDocumentRow.onboarding_case_id.is_(None))
                else:
                    query = query.where(LegalEntityDocumentRow.onboarding_case_id == case_id)
            rows = session.scalars(
                query.order_by(LegalEntityDocumentRow.document_type, LegalEntityDocumentRow.revision)
            ).all()
            return [self.serialize(r) for r in rows]

    def current_for_supplier(self, session, supplier_id: str, document_type: str):
        """The live revision of one document type, in its natural scope.

        Used by the onboarding flow to answer "is the proof for this relationship
        type actually on file". Returns ``None`` rather than raising when the
        applicant simply has not uploaded it yet — that is a normal state.
        """
        document_type = str(document_type or "").strip().upper()
        entity = self._entity(session, supplier_id)
        if entity is None:
            return None
        try:
            case_id = self.resolve_case_id(session, supplier_id, self.natural_scope(document_type))
        except ValueError:
            return None
        return self._current(session, entity.legal_entity_id, document_type, case_id)

    def history(self, supplier_id: str, document_type: str, scope: str | None = None,
                onboarding_case_id: str | None = None) -> list[dict]:
        """Every revision of one document type, newest first (revision history UI)."""
        document_type = str(document_type or "").strip().upper()
        if document_type not in DOCUMENT_TYPES:
            raise ValueError(DOCUMENT_TYPE_UNSUPPORTED)
        with SessionLocal() as session:
            entity = self._entity(session, supplier_id)
            if entity is None:
                return []
            case_id = self.resolve_case_id(
                session, supplier_id,
                scope if (scope is not None or onboarding_case_id is not None)
                else self.natural_scope(document_type),
                onboarding_case_id,
            )
            query = select(LegalEntityDocumentRow).where(
                LegalEntityDocumentRow.legal_entity_id == entity.legal_entity_id,
                LegalEntityDocumentRow.document_type == document_type,
            )
            if case_id is None:
                query = query.where(LegalEntityDocumentRow.onboarding_case_id.is_(None))
            else:
                query = query.where(LegalEntityDocumentRow.onboarding_case_id == case_id)
            rows = session.scalars(
                query.order_by(LegalEntityDocumentRow.revision.desc())
            ).all()
            return [self.serialize(r) for r in rows]

    @staticmethod
    def _payload(row: LegalEntityDocumentRow, *, disposition: str) -> tuple[bytes, str, str]:
        """Read, re-verify the hash, and re-sniff the type before serving.

        The stored MIME type is trusted only as far as the bytes confirm it: a
        file that no longer matches its recorded hash is refused rather than
        served, and the served ``Content-Type`` comes from the bytes.
        """
        from go_hotel.services.document_store import sniff_mime

        data = document_store.read_verified(row.storage_key, row.sha256)
        sniffed = sniff_mime(data)
        if sniffed is None or sniffed != row.mime_type:
            raise ValueError("DOCUMENT_INTEGRITY_FAILED")
        filename = row.original_filename or "document"
        return data, sniffed, filename

    def read_for_owner(self, supplier_id: str, document_id: str, *, inline: bool = False) -> tuple[bytes, str, str, str]:
        with SessionLocal() as session:
            row = self._locate_for_owner(session, supplier_id, document_id)
            data, mime, filename = self._payload(row, disposition=PREVIEW_INLINE if inline else PREVIEW_ATTACHMENT)
        return data, mime, filename, (PREVIEW_INLINE if inline else PREVIEW_ATTACHMENT)

    def read_for_reviewer(self, document_id: str, *, inline: bool = False) -> tuple[bytes, str, str, str]:
        with SessionLocal() as session:
            row = session.get(LegalEntityDocumentRow, document_id)
            if row is None:
                raise ValueError(DOCUMENT_NOT_FOUND)
            data, mime, filename = self._payload(row, disposition=PREVIEW_INLINE if inline else PREVIEW_ATTACHMENT)
        return data, mime, filename, (PREVIEW_INLINE if inline else PREVIEW_ATTACHMENT)


legal_entity_document_service = LegalEntityDocumentService()
