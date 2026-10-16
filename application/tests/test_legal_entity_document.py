"""Batch 3 — private applicant evidence (营业执照 / 经营证明 / 合同).

Covers the frozen decisions that make documents safe to accept from a stranger:

  * CHANGE 10 — octet-stream transport, private storage, content
    addressing, de-duplication, revision, ``expected_revision`` staleness guard,
    preview vs download, ``no-store``;
  * CHANGE 2  — two scopes in one table (entity level and onboarding level) with
    FK integrity, so a document cannot be attached to someone else's case;
  * D-03/D-04 — JPG/PNG/PDF, <=10 MB, magic-byte validation, filename
    sanitisation, decompression-bomb guard;
  * the authorisation boundary — the owner and an authorised onboarding reviewer
    may read private evidence; another supplier and an ordinary admin may not.

The tests assert *behaviour that a real failure would break*, not that a route
exists: a fake PDF must be refused, a stale revision must be refused, a foreign
reader must get 404 rather than 403, and the internal storage key must never
appear in any response body.
"""
from __future__ import annotations

import importlib.abc
import io
import secrets
import sys

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from go_hotel.core.config import settings
from go_hotel.db.models import (
    AuditEventRow,
    LegalEntityDocumentBlobRow,
    LegalEntityDocumentRow,
)
from go_hotel.db.session import SessionLocal
from go_hotel.security.mfa import totp
from go_hotel.security.service import identity_service
from go_hotel.services.document_store import document_store
from registration_terms_test_support import approved_terms_fixture, with_verification
from supplier_document_upload import upload_document

USCC = "91350100M000100Y43"
LICENCE = "BUSINESS_LICENSE"


# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _private_volume(tmp_path, monkeypatch):
    """Never write test documents into the repository's working directory."""
    root = tmp_path / "supplier_documents"
    monkeypatch.setattr(document_store, "root", root)
    return root


def _csrf(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get(settings.csrf_cookie_name)}


def _png(size=(320, 200), color=(190, 40, 40)) -> bytes:
    """A genuinely decodable PNG, so the decompression-bomb guard really runs."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _png_like(payload: bytes) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + payload


PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _register(client, monkeypatch, email: str) -> str:
    approved_terms_fixture(monkeypatch)
    policy = client.get("/bff/auth/supplier/registration-terms").json()["data"]
    # Three login identifiers and two proved channels are part of the sign-up
    # contract now; the shared helper mints both challenges so this suite keeps
    # its subject (private evidence) rather than re-spelling registration.
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


def _save_entity(client) -> dict:
    response = client.put(
        "/bff/supplier/legal-entity",
        headers=_csrf(client),
        json={
            "legal_name": "宁德时代新能源科技股份有限公司",
            "unified_social_credit_code": USCC,
            "legal_representative_name": "曾毓群",
            "registered_address": "福建省宁德市蕉城区漳湾镇新港路2号",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _applicant(client, monkeypatch, email="doc.applicant@example.test") -> str:
    supplier_id = _register(client, monkeypatch, email)
    _save_entity(client)
    return supplier_id


def _upload(client, data: bytes, filename="licence.png", mime="image/png", **fields):
    # A caller-supplied document_type wins, so the case-insensitivity and
    # unknown-type tests can override the default without a second helper.
    fields.setdefault("document_type", LICENCE)
    return upload_document(
        client, data, filename=filename, mime=mime, headers=_csrf(client), **fields
    )


def _admin(client, name: str, roles: list[str]) -> dict:
    """Real MFA enrolment over HTTP, so the reviewer session is not a shortcut."""
    client.cookies.clear()
    password = secrets.token_urlsafe(24)
    identity_service.create_user(name, password, "GO_ADMIN", None, roles)
    enrollment = client.post(
        "/bff/auth/mfa/enroll/start", json={"username": name, "password": password}
    ).json()["data"]
    confirmed = client.post(
        "/bff/auth/mfa/enroll/confirm",
        json={"enrollment_token": enrollment["enrollment_token"], "code": totp(enrollment["secret"])},
    )
    assert confirmed.status_code == 200, confirmed.text
    return {"X-GO-Actor": "GO_ADMIN", **_csrf(client)}


# --------------------------------------------------------------------------- #
# upload: happy path + shape
# --------------------------------------------------------------------------- #
def test_upload_png_creates_revision_one_and_hides_the_storage_key(client, monkeypatch):
    _applicant(client, monkeypatch)
    response = _upload(client, _png())
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["revision"] == 1
    assert data["document_type"] == LICENCE
    assert data["scope"] == "ENTITY"
    assert data["mime_type"] == "image/png"
    assert data["status"] == "UPLOADED"
    assert len(data["sha256"]) == 64
    # The internal path token is exactly the thing that must not travel.
    assert "storage_key" not in data

    with SessionLocal() as session:
        row = session.scalar(select(LegalEntityDocumentRow))
        assert row is not None and row.storage_key.startswith("led_")
        assert row.revision == 1


def test_uploaded_bytes_land_on_the_private_volume(_private_volume, client, monkeypatch):
    _applicant(client, monkeypatch)
    response = _upload(client, _png())
    assert response.status_code == 201, response.text
    with SessionLocal() as session:
        row = session.scalar(select(LegalEntityDocumentRow))
    stored = document_store.read_verified(row.storage_key, row.sha256)
    assert stored == _png()
    # Evidence, not public hotel media: the public media cache is a different root.
    assert str(_private_volume) in str(document_store.root)


def test_document_type_input_is_case_insensitive(client, monkeypatch):
    _applicant(client, monkeypatch)
    response = _upload(client, _png(), document_type="business_license")
    assert response.status_code == 201, response.text
    assert response.json()["data"]["document_type"] == LICENCE


def test_pdf_is_accepted_and_recorded_as_pdf(client, monkeypatch):
    _applicant(client, monkeypatch)
    response = _upload(client, PDF, filename="scan.pdf", mime="application/pdf")
    assert response.status_code == 201, response.text
    assert response.json()["data"]["mime_type"] == "application/pdf"


# --------------------------------------------------------------------------- #
# upload: the refusal paths that actually matter
# --------------------------------------------------------------------------- #
def test_upload_without_a_legal_entity_is_refused(client, monkeypatch):
    _register(client, monkeypatch, "no.entity@example.test")
    response = _upload(client, _png())
    assert response.status_code == 409
    assert response.json()["detail"] == "LEGAL_ENTITY_REQUIRED"


def test_unknown_document_type_is_refused(client, monkeypatch):
    _applicant(client, monkeypatch)
    response = _upload(client, _png(), document_type="PASSPORT")
    assert response.status_code == 409
    assert response.json()["detail"] == "DOCUMENT_TYPE_UNSUPPORTED"


def test_oversize_document_is_refused(client, monkeypatch):
    _applicant(client, monkeypatch)
    response = _upload(client, _png_like(b"\x00" * (10 * 1024 * 1024 + 1)))
    assert response.status_code == 409
    assert response.json()["detail"] == "DOCUMENT_TOO_LARGE"


def test_plain_text_masquerading_as_an_image_is_refused(client, monkeypatch):
    _applicant(client, monkeypatch)
    response = _upload(client, b"this is definitely not an image", filename="x.png", mime="image/png")
    assert response.status_code == 409
    assert response.json()["detail"] == "DOCUMENT_TYPE_UNSUPPORTED"


def test_png_bytes_declared_as_pdf_are_refused(client, monkeypatch):
    """A renamed extension must not let a file through as another type."""
    _applicant(client, monkeypatch)
    response = _upload(client, _png(), filename="licence.pdf", mime="application/pdf")
    assert response.status_code == 409
    assert response.json()["detail"] == "DOCUMENT_TYPE_MISMATCH"


def test_corrupt_image_is_refused_rather_than_stored(client, monkeypatch):
    _applicant(client, monkeypatch)
    response = _upload(client, _png_like(b"garbage-not-an-image"))
    assert response.status_code == 409
    assert response.json()["detail"] == "DOCUMENT_IMAGE_UNREADABLE"


def test_empty_body_is_refused(client, monkeypatch):
    _applicant(client, monkeypatch)
    response = _upload(client, b"")
    assert response.status_code == 409
    assert response.json()["detail"] == "DOCUMENT_BYTES_REQUIRED"


def test_path_traversal_filename_never_becomes_a_path(_private_volume, client, monkeypatch):
    _applicant(client, monkeypatch)
    response = _upload(client, _png(), filename="../../../../etc/passwd.png")
    assert response.status_code == 201, response.text
    stored_name = response.json()["data"]["original_filename"]
    assert "/" not in stored_name and "\\" not in stored_name and ".." not in stored_name
    # Every byte we wrote lives inside the volume root; nothing escaped.
    root = document_store.root
    assert all(p.resolve().is_relative_to(root) for p in root.rglob("*") if p.is_file())


# --------------------------------------------------------------------------- #
# de-duplication and revisions
# --------------------------------------------------------------------------- #
def test_byte_identical_reupload_does_not_burn_a_revision(client, monkeypatch):
    _applicant(client, monkeypatch)
    first = _upload(client, _png()).json()["data"]
    again = _upload(client, _png()).json()["data"]
    assert again["document_id"] == first["document_id"]
    assert again["revision"] == 1
    assert again["deduplicated"] is True
    with SessionLocal() as session:
        assert len(session.scalars(select(LegalEntityDocumentRow)).all()) == 1


def test_replacing_a_document_creates_revision_two_and_supersedes_revision_one(client, monkeypatch):
    _applicant(client, monkeypatch)
    first = _upload(client, _png(color=(10, 10, 200))).json()["data"]
    second = _upload(client, _png(color=(200, 200, 10))).json()["data"]
    assert second["revision"] == 2
    assert second["document_id"] != first["document_id"]

    with SessionLocal() as session:
        rows = {r.document_id: r for r in session.scalars(select(LegalEntityDocumentRow)).all()}
    assert rows[first["document_id"]].status == "SUPERSEDED"
    assert rows[first["document_id"]].replaced_at is not None
    assert rows[second["document_id"]].status == "UPLOADED"


def test_stale_expected_revision_is_refused_and_nothing_changes(client, monkeypatch):
    """The guard that stops a reviewer's verdict landing on a replaced file."""
    _applicant(client, monkeypatch)
    _upload(client, _png(color=(10, 10, 200)))
    stale = _upload(client, _png(color=(1, 2, 3)), expected_revision=0)
    assert stale.status_code == 409
    assert stale.json()["detail"] == "DOCUMENT_REVISION_STALE"
    with SessionLocal() as session:
        row = session.scalar(select(LegalEntityDocumentRow))
        assert row.revision == 1

    fresh = _upload(client, _png(color=(4, 5, 6)), expected_revision=1)
    assert fresh.status_code == 201, fresh.text
    assert fresh.json()["data"]["revision"] == 2


def test_first_upload_accepts_expected_revision_zero(client, monkeypatch):
    _applicant(client, monkeypatch)
    response = _upload(client, _png(), expected_revision=0)
    assert response.status_code == 201, response.text
    assert response.json()["data"]["revision"] == 1


def test_partial_unique_index_blocks_a_second_current_revision(client, monkeypatch):
    """The DB, not the application, is the final guard against two live revisions."""
    _applicant(client, monkeypatch)
    _upload(client, _png())
    with SessionLocal() as session:
        row = session.scalar(select(LegalEntityDocumentRow))
        duplicate = LegalEntityDocumentRow(
            document_id="led_forced_second_current",
            legal_entity_id=row.legal_entity_id,
            onboarding_case_id=None,
            document_type=LICENCE,
            storage_key="led_" + "f" * 48 + ".png",
            original_filename="forced.png",
            mime_type="image/png",
            size_bytes=10,
            sha256="f" * 64,
            revision=99,
            status="UPLOADED",
            uploaded_by="forced",
            uploaded_at=row.uploaded_at,
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_history_returns_every_revision_newest_first(client, monkeypatch):
    _applicant(client, monkeypatch)
    _upload(client, _png(color=(10, 10, 200)))
    _upload(client, _png(color=(200, 200, 10)))
    history = client.get(
        "/bff/supplier/legal-entity/document-history", params={"document_type": LICENCE}
    ).json()["data"]
    assert [row["revision"] for row in history] == [2, 1]
    assert history[0]["status"] == "UPLOADED"
    assert history[1]["status"] == "SUPERSEDED"
    assert all("storage_key" not in row for row in history)


# --------------------------------------------------------------------------- #
# scope: entity level vs onboarding level
# --------------------------------------------------------------------------- #
def test_case_scoped_document_is_separate_from_the_entity_scope(client, monkeypatch):
    supplier_id = _applicant(client, monkeypatch)
    case_id = f"onb_{supplier_id}"
    entity_doc = _upload(client, _png()).json()["data"]
    case_doc = _upload(
        client, PDF, filename="proof.pdf", mime="application/pdf",
        document_type="HOTEL_OPERATION_PROOF", scope="ONBOARDING",
    ).json()["data"]
    assert case_doc["scope"] == "ONBOARDING"
    assert case_doc["onboarding_case_id"] == case_id

    entity_scope = client.get(
        "/bff/supplier/legal-entity/documents", params={"scope": "ENTITY"}
    ).json()["data"]
    assert [d["document_id"] for d in entity_scope] == [entity_doc["document_id"]]
    case_scope = client.get(
        "/bff/supplier/legal-entity/documents", params={"scope": "ONBOARDING"}
    ).json()["data"]
    assert [d["document_id"] for d in case_scope] == [case_doc["document_id"]]

    # No scope = everything the applicant owns, labelled with its own scope: the
    # step screens need one honest answer without holding a case id.
    every = client.get("/bff/supplier/legal-entity/documents").json()["data"]
    assert sorted(d["scope"] for d in every) == ["ENTITY", "ONBOARDING"]


def test_document_scope_is_a_name_and_a_case_id_cannot_be_smuggled_in(client, monkeypatch):
    """The scope is resolved from the session, so a foreign case is unrepresentable."""
    _applicant(client, monkeypatch)
    smuggled = _upload(client, _png(), scope="onb_sup_foreign_supplier")
    assert smuggled.status_code == 409
    assert smuggled.json()["detail"] == "DOCUMENT_SCOPE_INVALID"


# --------------------------------------------------------------------------- #
# read: preview / download / headers
# --------------------------------------------------------------------------- #
def test_owner_can_preview_and_download_with_distinct_dispositions(client, monkeypatch):
    _applicant(client, monkeypatch)
    document = _upload(client, _png()).json()["data"]
    path = f"/bff/supplier/legal-entity/documents/{document['document_id']}/content"

    preview = client.get(path, params={"disposition": "inline"})
    assert preview.status_code == 200
    assert preview.content == _png()
    assert preview.headers["Content-Type"].startswith("image/png")
    assert preview.headers["Content-Disposition"].startswith("inline")
    assert preview.headers["Cache-Control"] == "private, no-store"
    assert preview.headers["X-Content-Type-Options"] == "nosniff"

    download = client.get(path, params={"disposition": "attachment"})
    assert download.status_code == 200
    assert download.headers["Content-Disposition"].startswith("attachment")


def test_default_disposition_is_attachment_not_render(client, monkeypatch):
    _applicant(client, monkeypatch)
    document = _upload(client, PDF, filename="scan.pdf", mime="application/pdf").json()["data"]
    response = client.get(f"/bff/supplier/legal-entity/documents/{document['document_id']}/content")
    assert response.headers["Content-Disposition"].startswith("attachment")
    assert response.headers["Content-Type"].startswith("application/pdf")


def test_meta_endpoint_exposes_revision_but_never_the_storage_key(client, monkeypatch):
    _applicant(client, monkeypatch)
    document = _upload(client, _png()).json()["data"]
    meta = client.get(f"/bff/supplier/legal-entity/documents/{document['document_id']}").json()["data"]
    assert meta["revision"] == 1
    assert "storage_key" not in meta


# --------------------------------------------------------------------------- #
# authorisation boundary
# --------------------------------------------------------------------------- #
def test_another_supplier_gets_404_not_403(client, monkeypatch):
    """Existence of a foreign document id must not be confirmable."""
    from fastapi.testclient import TestClient

    _applicant(client, monkeypatch, "owner.one@example.test")
    document = _upload(client, _png()).json()["data"]
    path = f"/bff/supplier/legal-entity/documents/{document['document_id']}/content"

    # A second, independent applicant session.
    approved_terms_fixture(monkeypatch)
    from go_hotel.main import app

    with TestClient(app) as other:
        policy = other.get("/bff/auth/supplier/registration-terms").json()["data"]
        # Same contract as the first applicant: identifiers plus two proofs.
        second = with_verification({
            "email": "owner.two@example.test",
            "password": "Isolated-test-pass-123",
            "accepted_terms": True,
            "term_versions": policy["versions"],
            "term_hashes": policy["term_hashes"],
            "registration_decisions": policy["required_decisions"],
            "organization_name": "另一个企业",
            "contact_name": "另一个联系人",
        }, "supplier")
        created = other.post("/bff/auth/supplier/register", json=second)
        assert created.status_code in (200, 201), created.text
        assert other.get(path).status_code == 404
        assert other.get(f"/bff/supplier/legal-entity/documents/{document['document_id']}").status_code == 404


def test_anonymous_caller_is_rejected(client, monkeypatch):
    from fastapi.testclient import TestClient

    _applicant(client, monkeypatch)
    document = _upload(client, _png()).json()["data"]
    from go_hotel.main import app

    with TestClient(app) as anonymous:
        response = anonymous.get(
            f"/bff/supplier/legal-entity/documents/{document['document_id']}/content"
        )
    assert response.status_code == 401


def test_onboarding_reviewer_can_read_private_evidence(client, monkeypatch):
    _applicant(client, monkeypatch)
    document = _upload(client, _png()).json()["data"]
    reviewer = _admin(client, "onboarding-reviewer", ["GO_GOVERNANCE"])
    response = client.get(
        f"/internal/v1/onboarding-review/documents/{document['document_id']}/content",
        headers=reviewer,
    )
    assert response.status_code == 200, response.text
    assert response.content == _png()
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Content-Disposition"].startswith("inline")


def test_ordinary_admin_cannot_read_private_evidence(client, monkeypatch):
    """``admin:read`` is not enough; only ``admin:onboarding_review`` opens evidence."""
    _applicant(client, monkeypatch)
    document = _upload(client, _png()).json()["data"]
    ordinary = _admin(client, "ordinary-admin", ["GO_READ_ONLY"])
    response = client.get(
        f"/internal/v1/onboarding-review/documents/{document['document_id']}/content",
        headers=ordinary,
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "ONBOARDING_REVIEWER_REQUIRED"


def test_supplier_session_cannot_use_the_reviewer_endpoint(client, monkeypatch):
    _applicant(client, monkeypatch)
    document = _upload(client, _png()).json()["data"]
    response = client.get(
        f"/internal/v1/onboarding-review/documents/{document['document_id']}/content"
    )
    assert response.status_code == 403


def test_reviewer_can_reject_a_revision_and_the_applicant_sees_it(client, monkeypatch):
    from go_hotel.services.legal_entity_document import legal_entity_document_service

    _applicant(client, monkeypatch)
    document = _upload(client, _png()).json()["data"]
    legal_entity_document_service.set_status(
        document["document_id"], "REJECTED", actor_id="go-reviewer"
    )
    listed = client.get("/bff/supplier/legal-entity/documents").json()["data"]
    assert listed[0]["status"] == "REJECTED"
    # The reviewer's verdict is audited; the file itself is untouched.
    with SessionLocal() as session:
        actions = {
            row.action for row in session.scalars(select(AuditEventRow)).all()
        }
    assert "SUPPLIER_DOCUMENT_REVIEWED" in actions


# --------------------------------------------------------------------------- #
# audit trail
# --------------------------------------------------------------------------- #
def test_every_revision_is_audited_with_its_hash(client, monkeypatch):
    _applicant(client, monkeypatch)
    first = _upload(client, _png(color=(10, 10, 200))).json()["data"]
    second = _upload(client, _png(color=(200, 10, 10))).json()["data"]
    with SessionLocal() as session:
        events = session.scalars(
            select(AuditEventRow).where(AuditEventRow.action == "SUPPLIER_DOCUMENT_UPLOADED")
        ).all()
    assert len(events) == 2
    hashes = {event.metadata_json["sha256"] for event in events}
    assert hashes == {first["sha256"], second["sha256"]}
    superseding = [e for e in events if e.metadata_json.get("superseded_document_id")]
    assert superseding and superseding[0].metadata_json["superseded_document_id"] == first["document_id"]


# --------------------------------------------------------------------------- #
# durability: the bytes must survive the container being recreated
# --------------------------------------------------------------------------- #
def test_document_bytes_live_in_the_database_when_no_volume_is_configured(
    tmp_path, client, monkeypatch
):
    """The Hong Kong deployment recreates the eight business containers from a
    digest-pinned Compose file and environment file, and mounts no private
    directory. A file written inside a container is discarded on every deployment,
    so with nothing configured the bytes have to live in the one store that
    environment already backs up and restores as a unit: the database.

    This test selects that backend the way the deployment does -- by configuring
    nothing -- and then asserts the *bytes themselves* are a row, not a path.
    """
    # Undo the module's autouse volume so the store is reached with no root and no
    # override, which is the deployment's configuration exactly.
    monkeypatch.setattr(document_store, "root", None)
    monkeypatch.delenv("GO_SUPPLIER_DOCUMENT_DIR", raising=False)
    assert document_store._uses_database() is True

    _applicant(client, monkeypatch)
    licence = _png(color=(7, 77, 7))
    uploaded = _upload(client, licence)
    assert uploaded.status_code == 201, uploaded.text
    document = uploaded.json()["data"]

    with SessionLocal() as session:
        row = session.scalar(select(LegalEntityDocumentRow))
        assert row is not None and row.storage_key.startswith("led_")
        blob = session.get(LegalEntityDocumentBlobRow, row.storage_key)

    assert blob is not None, "the bytes must be a row, not a file in the container"
    assert blob.sha256 == row.sha256
    assert blob.mime_type == "image/png"
    assert blob.size_bytes == len(licence)
    assert bytes(blob.content) == licence
    # The volume is not a fallback that happened to be empty: nothing was written.
    assert not (tmp_path / "supplier_documents").exists()


def test_document_bytes_are_readable_after_the_container_is_rebuilt(
    tmp_path, client, monkeypatch
):
    """The proof the deployment actually needs: write, throw the runtime away, read.

    Every pooled connection is dropped and the store is rebuilt as a brand new
    instance, which is what a container recreation does to this process. A file
    on the container filesystem would be gone at this point; a database row cannot
    help but be there. Both the store API and the applicant's HTTP read path are
    then checked, so a failure would show as a real user seeing a broken preview.
    """
    from go_hotel.db.session import engine

    monkeypatch.setattr(document_store, "root", None)
    monkeypatch.delenv("GO_SUPPLIER_DOCUMENT_DIR", raising=False)

    _applicant(client, monkeypatch)
    licence = _png(color=(9, 40, 90))
    document = _upload(client, licence).json()["data"]

    with SessionLocal() as session:
        row = session.scalar(select(LegalEntityDocumentRow))
        storage_key, sha256 = row.storage_key, row.sha256

    # Rebuild: no live connections, no store instance state, no cached handle.
    engine.dispose(close=True)
    rebuilt = type(document_store)()
    assert rebuilt._uses_database() is True
    assert rebuilt.exists(storage_key) is True
    assert rebuilt.read_verified(storage_key, sha256) == licence

    # The applicant's own route agrees, which is what the acceptance run checks.
    resumed = client.get(
        f"/bff/supplier/legal-entity/documents/{document['document_id']}/content",
        params={"disposition": "inline"},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.content == licence

    # And a corrupted read is still refused: durability must not have traded away
    # the hash check that makes the stored bytes evidence rather than a blob.
    with pytest.raises(ValueError) as corrupted:
        rebuilt.read_verified(storage_key, "0" * 64)
    assert str(corrupted.value) == "DOCUMENT_INTEGRITY_FAILED"

    # The falsification that makes the reads above mean something: the bytes come
    # from that row and from nowhere else. Remove the row and the document is gone.
    # If the read were quietly falling back to a file still lying in the container,
    # this is the assertion that would catch it -- and it is exactly the file the
    # next deployment would have deleted.
    with SessionLocal() as session:
        session.delete(session.get(LegalEntityDocumentBlobRow, storage_key))
        session.commit()
    engine.dispose(close=True)
    assert rebuilt.exists(storage_key) is False
    with pytest.raises(ValueError) as vanished:
        rebuilt.read_verified(storage_key, sha256)
    assert str(vanished.value) == "DOCUMENT_BYTES_MISSING"
    gone = client.get(f"/bff/supplier/legal-entity/documents/{document['document_id']}/content")
    assert gone.status_code == 404
    assert gone.json()["detail"] == "DOCUMENT_BYTES_MISSING"


def test_an_explicit_volume_still_selects_the_filesystem_backend(tmp_path, monkeypatch):
    """The database must be the default, never the only option.

    The local acceptance lab and any deployment that really does mount a private
    volume keep the filesystem backend; forcing private bytes into the database
    everywhere would be a change nobody asked for.
    """
    volume = tmp_path / "mounted_volume"
    monkeypatch.setattr(document_store, "root", None)
    monkeypatch.setenv("GO_SUPPLIER_DOCUMENT_DIR", str(volume))
    assert document_store._uses_database() is False

    licence = _png(color=(3, 3, 200))
    stored = document_store.persist(licence, "licence.png", "image/png")
    assert any(p.is_file() for p in volume.rglob("*"))
    assert document_store.read_verified(stored.storage_key, stored.sha256) == licence


# --------------------------------------------------------------------------- #
# the transport must not need a wheel the deployable image does not ship
# --------------------------------------------------------------------------- #
class _NoMultipart(importlib.abc.MetaPathFinder):
    """Simulate the frozen Hong Kong image, which has no multipart parser."""

    def find_spec(self, name, path=None, target=None):
        if name == "multipart" or name.startswith("multipart."):
            raise ModuleNotFoundError("No module named %r" % name, name=name)
        return None


@pytest.fixture
def without_multipart(monkeypatch):
    """Make ``import multipart`` fail, and undo every trace of it afterwards.

    The cache has to be cleared as well as the import blocked: FastAPI imports the
    parser *lazily*, inside the request handler, so a ``sys.modules`` entry left
    behind by an earlier test would hide exactly the defect this fixture exists for.
    """
    for name in [n for n in list(sys.modules) if n == "multipart" or n.startswith("multipart.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "meta_path", [_NoMultipart(), *sys.meta_path])


def test_the_upload_needs_no_multipart_parser(client, monkeypatch, without_multipart):
    """The image we can actually deploy to is built with the network off and ships
    no multipart parser, so a ``Form``/``File`` parameter turns a missing wheel into
    a body the server cannot read.

    Every other test in this file passes on a machine that happens to have the
    wheel installed, which is precisely how this reached a candidate build -- so the
    block above is the whole point of the test, not a detail of it.
    """
    _applicant(client, monkeypatch)
    licence = _png(color=(9, 9, 9))

    # Proof the block is real before trusting anything below it.
    with pytest.raises(ModuleNotFoundError):
        __import__("multipart")

    uploaded = _upload(client, licence)
    assert uploaded.status_code == 201, uploaded.text
    document = uploaded.json()["data"]

    served = client.get(f"/bff/supplier/legal-entity/documents/{document['document_id']}/content")
    assert served.status_code == 200, served.text
    assert served.content == licence
