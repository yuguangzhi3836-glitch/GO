"""Private, content-addressed storage for applicant documents.

Mechanism reused from the existing media cache (``services/media_harvester.py``):
content addressing, sha256 read-back verification, atomic write, a local
persistent volume. Mechanism only — the *semantics* here are private evidence,
never public hotel media, and the transport is ``multipart/form-data`` rather
than base64 (frozen decision CHANGE 10).

Design constraints that matter for the applicant flow:

* The bytes live in one durable store, never in the container filesystem alone.
  An explicit ``GO_SUPPLIER_DOCUMENT_DIR`` selects the filesystem volume; without
  it the bytes go to the ``legal_entity_document_blob`` table, because the Hong
  Kong deployment recreates the eight business containers from a digest-pinned
  Compose file and environment file and mounts no private directory. Either way the
  read path re-hashes and refuses on mismatch.
* Uploads must be atomic: a failed or interrupted upload must never damage the
  revision that is already in force.
* Never trust a client supplied filename, extension or ``Content-Type``. The
  declared type is validated *and* the leading bytes are sniffed.
* ``I O S V Z``-style: no user supplied string may ever become part of a path.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024  # frozen decision D-04: 10 MB per file
MAX_IMAGE_PIXELS = 40_000_000           # decompression-bomb guard (~40 MP)
MAX_FILENAME_LENGTH = 200
STORAGE_KEY_PREFIX = "led"
# The conventional volume path, reported when the filesystem backend is selected
# by nothing more than an operator's expectation. It is never written to unless
# ``GO_SUPPLIER_DOCUMENT_DIR`` actually says so (see ``DocumentStore``).
DEFAULT_ROOT = "var/supplier_documents"

# Declared MIME -> canonical extension we will store. Extension is derived from
# the *sniffed* type, never from the user supplied filename.
ALLOWED_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
}

_SAFE_FILENAME = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class StoredDocument:
    storage_key: str
    mime_type: str
    size_bytes: int
    sha256: str
    original_filename: str


def sniff_mime(data: bytes) -> str | None:
    """Return the MIME type implied by the file's leading bytes.

    A declared ``Content-Type`` and a filename extension are both user supplied
    and therefore untrusted; this is the authoritative check.
    """
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:5] == b"%PDF-":
        return "application/pdf"
    return None


def sanitize_filename(name: str | None) -> str:
    """Reduce a client filename to something safe to *display*.

    The result is only ever stored for a reviewer to recognise the file; it is
    never used to build a path. Path separators, traversal and control
    characters are removed here as defence in depth.
    """
    base = unicodedata.normalize("NFC", str(name or "")).replace("\\", "/")
    base = base.rsplit("/", 1)[-1]
    base = _SAFE_FILENAME.sub("", base).strip().strip(".")
    base = base.replace("\u202e", "")  # right-to-left override spoofing
    if not base:
        return "document"
    if len(base) > MAX_FILENAME_LENGTH:
        stem, dot, ext = base.rpartition(".")
        base = (stem[: MAX_FILENAME_LENGTH - len(ext) - 1] + dot + ext) if dot else base[:MAX_FILENAME_LENGTH]
    return base


def validate_image_bomb(data: bytes, mime_type: str) -> None:
    """Refuse images whose declared pixel count implies a decompression bomb."""
    if mime_type not in ("image/jpeg", "image/png"):
        return
    try:
        from PIL import Image  # local import keeps the PDF path dependency-light

        with Image.open(io.BytesIO(data)) as probe:
            width, height = probe.size
    except Exception as exc:  # unreadable image bytes
        raise ValueError("DOCUMENT_IMAGE_UNREADABLE") from exc
    if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
        raise ValueError("DOCUMENT_IMAGE_TOO_LARGE")


class DocumentStore:
    """Private document bytes in one durable store, keyed by content address.

    Two backends, selected by configuration rather than guessed at:

    * ``GO_SUPPLIER_DOCUMENT_DIR`` set -> the filesystem volume at that path. This
      is development, the local acceptance lab, and any deployment that does mount
      a private volume;
    * not set -> the ``legal_entity_document_blob`` table.

    The second case is the default because the Hong Kong deployment recreates the
    eight business containers from a digest-pinned Compose file and environment
    file: a directory inside the container is discarded on every deployment, and a
    private host directory cannot be mounted without editing the host's sealed
    deployment runtime. The database is the one store that environment already
    has, already backs up and already restores as a unit, so the bytes and the
    metadata row describing them live and die together.

    Assigning ``root`` (including from a test) selects the filesystem backend.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self._root: Path | None = None
        self.root = root

    # ---- backend selection ---------------------------------------------
    @property
    def root(self) -> Path:
        """The filesystem volume in force, or the conventional path when unused."""
        if self._root is not None:
            return self._root
        return Path(os.getenv("GO_SUPPLIER_DOCUMENT_DIR") or DEFAULT_ROOT).resolve()

    @root.setter
    def root(self, value: str | Path | None) -> None:
        self._root = None if value is None else Path(value).resolve()

    def _uses_database(self) -> bool:
        """True when no filesystem volume is configured for this process."""
        return self._root is None and not os.getenv("GO_SUPPLIER_DOCUMENT_DIR")

    # ---- path handling -------------------------------------------------
    @staticmethod
    def _validated_key(storage_key: str) -> str:
        key = str(storage_key or "")
        # A storage key is always one we generated. Refuse anything with a
        # separator, traversal or unexpected prefix so a corrupted row can never
        # escape the volume, and so a read can never name a row it does not name.
        if (
            not key
            or key != key.strip()
            or "/" in key
            or "\\" in key
            or ".." in key
            or not key.startswith(STORAGE_KEY_PREFIX + "_")
        ):
            raise ValueError("DOCUMENT_STORAGE_KEY_INVALID")
        return key

    def _path(self, storage_key: str) -> Path:
        return self.root / self._validated_key(storage_key)

    @staticmethod
    def _storage_key(sha256: str, extension: str) -> str:
        return f"{STORAGE_KEY_PREFIX}_{sha256[:48]}{extension}"

    # ---- write ---------------------------------------------------------
    def persist(self, data: bytes, original_filename: str | None, declared_mime: str | None = None) -> StoredDocument:
        """Validate and atomically write one document. Returns the stored record."""
        if not data:
            raise ValueError("DOCUMENT_BYTES_REQUIRED")
        if len(data) > MAX_DOCUMENT_BYTES:
            raise ValueError("DOCUMENT_TOO_LARGE")

        mime_type = sniff_mime(data)
        if mime_type is None or mime_type not in ALLOWED_MIME:
            raise ValueError("DOCUMENT_TYPE_UNSUPPORTED")
        if declared_mime and declared_mime.split(";")[0].strip().lower() not in ALLOWED_MIME:
            raise ValueError("DOCUMENT_TYPE_UNSUPPORTED")
        if declared_mime and declared_mime.split(";")[0].strip().lower() != mime_type:
            # Declared and actual disagree: the bytes are authoritative, but a
            # mismatch means the client is confused or hostile. Refuse.
            raise ValueError("DOCUMENT_TYPE_MISMATCH")

        validate_image_bomb(data, mime_type)

        sha256 = hashlib.sha256(data).hexdigest()
        storage_key = self._storage_key(sha256, ALLOWED_MIME[mime_type])
        if self._uses_database():
            self._persist_database(storage_key, sha256, mime_type, len(data), data)
        else:
            target = self._path(storage_key)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.parent / f".upload-{uuid.uuid4().hex}.part"
                try:
                    tmp.write_bytes(data)
                    os.replace(tmp, target)  # atomic within the volume
                finally:
                    if tmp.exists():
                        tmp.unlink(missing_ok=True)
        return StoredDocument(
            storage_key=storage_key,
            mime_type=mime_type,
            size_bytes=len(data),
            sha256=sha256,
            original_filename=sanitize_filename(original_filename),
        )

    # ---- read ----------------------------------------------------------
    def read(self, storage_key: str) -> bytes:
        if self._uses_database():
            return self._read_database(storage_key)
        path = self._path(storage_key)
        if not path.exists():
            raise ValueError("DOCUMENT_BYTES_MISSING")
        return path.read_bytes()

    def read_verified(self, storage_key: str, expected_sha256: str) -> bytes:
        """Read and re-hash. A tampered or truncated file is refused, not served."""
        data = self.read(storage_key)
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise ValueError("DOCUMENT_INTEGRITY_FAILED")
        return data

    def exists(self, storage_key: str) -> bool:
        if self._uses_database():
            return self._exists_database(storage_key)
        try:
            return self._path(storage_key).exists()
        except ValueError:
            return False

    # ---- database backend ----------------------------------------------
    # The bytes are addressed by the same content address the volume store uses, so
    # a key is validated exactly as it is there: a row can never be reached through
    # a caller-supplied path. The engine import stays local so a process that only
    # uses the filesystem backend never needs a configured database.
    @staticmethod
    def _blob_row_type():
        from go_hotel.db.models import LegalEntityDocumentBlobRow

        return LegalEntityDocumentBlobRow

    @staticmethod
    def _session_factory():
        from go_hotel.db.session import SessionLocal

        return SessionLocal

    def _persist_database(
        self, storage_key: str, sha256: str, mime_type: str, size_bytes: int, data: bytes
    ) -> None:
        from datetime import datetime, timezone

        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError

        row_type = self._blob_row_type()
        with self._session_factory()() as session:
            present = session.scalar(
                select(row_type.storage_key).where(row_type.storage_key == storage_key)
            )
            if present:
                # Content addressed: the same bytes are the same document, whether
                # they are already there because of this upload or an earlier one.
                return
            session.add(
                row_type(
                    storage_key=storage_key,
                    sha256=sha256,
                    mime_type=mime_type,
                    size_bytes=size_bytes,
                    content=data,
                    created_at=datetime.now(timezone.utc),
                )
            )
            try:
                session.commit()
            except IntegrityError:
                # A concurrent upload of the same bytes won the insert. That is the
                # same document, not a conflict, and the row is already correct.
                session.rollback()

    def _read_database(self, storage_key: str) -> bytes:
        key = self._validated_key(storage_key)
        row_type = self._blob_row_type()
        with self._session_factory()() as session:
            row = session.get(row_type, key)
            if row is None:
                raise ValueError("DOCUMENT_BYTES_MISSING")
            return bytes(row.content)

    def _exists_database(self, storage_key: str) -> bool:
        try:
            key = self._validated_key(storage_key)
        except ValueError:
            return False
        row_type = self._blob_row_type()
        with self._session_factory()() as session:
            return session.get(row_type, key) is not None


document_store = DocumentStore()
