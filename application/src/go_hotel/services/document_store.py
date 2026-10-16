"""Private, content-addressed storage for applicant documents.

Mechanism reused from the existing media cache (``services/media_harvester.py``):
content addressing, sha256 read-back verification, atomic write, a local
persistent volume. Mechanism only — the *semantics* here are private evidence,
never public hotel media, and the transport is ``multipart/form-data`` rather
than base64 (frozen decision CHANGE 10).

Design constraints that matter for the applicant flow:

* Bytes never live in PostgreSQL. The DB stores metadata + sha256; the file
  lives on the mounted volume. The read path re-hashes and refuses on mismatch.
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
    """Local persistent document volume. Swap the backend without touching the table."""

    def __init__(self, root: str | Path | None = None) -> None:
        default = os.getenv("GO_SUPPLIER_DOCUMENT_DIR", "var/supplier_documents")
        self.root = Path(root or default).resolve()

    # ---- path handling -------------------------------------------------
    def _path(self, storage_key: str) -> Path:
        key = str(storage_key or "")
        # A storage key is always one we generated. Refuse anything with a
        # separator, traversal or unexpected prefix so a corrupted row can never
        # escape the volume.
        if (
            not key
            or key != key.strip()
            or "/" in key
            or "\\" in key
            or ".." in key
            or not key.startswith(STORAGE_KEY_PREFIX + "_")
        ):
            raise ValueError("DOCUMENT_STORAGE_KEY_INVALID")
        return self.root / key

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
        try:
            return self._path(storage_key).exists()
        except ValueError:
            return False


document_store = DocumentStore()
