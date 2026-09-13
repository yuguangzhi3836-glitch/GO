from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import ipaddress
import mimetypes
import os
from pathlib import Path
import socket
import uuid
from urllib.parse import urlparse, urljoin

import httpx
from PIL import Image

from go_hotel.services.media_index import MediaIndex


PUBLISHABLE_RIGHTS = {"AUTHORIZED", "HOTEL_SUBMITTED", "LICENSED", "DISTRIBUTION_LICENSE", "PUBLIC_DOMAIN"}
RIGHTS_STATES = PUBLISHABLE_RIGHTS | {"RIGHTS_UNKNOWN", "REJECTED", "EXPIRED"}
ALLOWED_ROLES = {"HERO", "GALLERY", "ROOM", "DINING", "FACILITY", "MEETING", "POI", "EXTERIOR", "LOBBY", "WELLNESS", "SIGNATURE_SPACE"}
MAX_IMAGE_BYTES = int(os.getenv("GO_MEDIA_MAX_IMAGE_BYTES", str(15 * 1024 * 1024)))
MIN_IMAGE_EDGE = int(os.getenv("GO_MEDIA_MIN_IMAGE_EDGE", "64"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _rights_publishable(record: dict) -> bool:
    if record.get("rights_state") not in PUBLISHABLE_RIGHTS:
        return False
    if record.get("cache_state") != "VALIDATED":
        return False
    if not all(isinstance(record.get(k), str) and record[k].strip()
               for k in ("rights_owner", "rights_evidence_reference")):
        return False
    if record.get("rights_state") == "DISTRIBUTION_LICENSE" and (
        not record.get("provider") or not record.get("contract_id") or record.get("cache_allowed") is not True
    ):
        return False
    try:
        expires = _parse_iso(record.get("rights_expires_at"))
    except (ValueError, TypeError, OverflowError):
        return False
    if expires is not None and expires <= datetime.now(timezone.utc):
        return False
    return True


def _asset_id() -> str:
    return f"media_{uuid.uuid4().hex}"


def _safe_ext(mime: str) -> str:
    ext = mimetypes.guess_extension(mime.split(";", 1)[0].strip()) or ".img"
    if ext == ".jpe":
        ext = ".jpg"
    return ext


def _dhash(path: Path) -> str:
    """64-bit difference hash for near-duplicate media QA; deterministic and dependency-free."""
    with Image.open(path) as im:
        g=im.convert("L").resize((9,8))
        px=list(g.getdata())
    bits=[]
    for y in range(8):
        row=px[y*9:(y+1)*9]
        bits.extend(1 if row[x] > row[x+1] else 0 for x in range(8))
    v=0
    for bit in bits: v=(v<<1)|bit
    return f"{v:016x}"


def _is_public_ip(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        raw = info[4][0]
        ip = ipaddress.ip_address(raw)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
    return True


@dataclass(frozen=True)
class HarvestResult:
    asset_id: str
    sha256: str
    cache_path: str
    rights_state: str
    publishable: bool


class MediaHarvesterService:
    """Downloads hotel media into a local immutable cache and enforces a fail-closed rights gate.

    Discovery/downloading and publication are deliberately separate. A downloaded image is never
    public until an explicit rights decision with evidence places it in a publishable rights state.
    """

    def __init__(self, cache_dir: str | Path | None = None, transport: httpx.BaseTransport | None = None):
        default = os.getenv("GO_MEDIA_CACHE_DIR", "var/media_cache")
        self.cache_dir = Path(cache_dir or default).resolve()
        self._transport = transport
        self.files_dir = self.cache_dir / "files"
        self.index_path = self.cache_dir / "index.json"
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self._index = MediaIndex(self.cache_dir)

    def _read_index(self) -> dict:
        return self._index.snapshot()

    def _write_index(self, data: dict) -> None:
        self._index.replace_snapshot(data)

    def _sync_files_directory(self) -> None:
        fd = os.open(self.files_dir, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _admit_file(self, temporary: Path, destination: Path, digest: str) -> None:
        if destination.is_symlink():
            raise ValueError("MEDIA_CACHE_PATH_INVALID")
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise ValueError("MEDIA_CACHE_INTEGRITY_FAILED")
        else:
            os.replace(temporary, destination)
            self._sync_files_directory()

    def _delete_file(self, name: str) -> None:
        p = self.files_dir / name
        if Path(name).name != name or p.is_symlink() or p.resolve().parent != self.files_dir:
            raise ValueError("MEDIA_CACHE_PATH_INVALID")
        p.unlink(missing_ok=True)
        self._sync_files_directory()

    def _validate_source_url(self, source_url: str, allow_private: bool = False) -> None:
        u = urlparse(source_url)
        if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password:
            raise ValueError("MEDIA_SOURCE_URL_INVALID")
        if not allow_private and not _is_public_ip(u.hostname):
            raise ValueError("MEDIA_SOURCE_PRIVATE_OR_UNRESOLVABLE_BLOCKED")

    def _validate_image(self, path: Path, declared_mime: str | None) -> tuple[str, int, int]:
        try:
            with Image.open(path) as im:
                im.verify()
            with Image.open(path) as im:
                width, height = im.size
                fmt = (im.format or "").upper()
        except Exception as e:
            raise ValueError("MEDIA_CONTENT_NOT_VALID_IMAGE") from e
        if min(width, height) < MIN_IMAGE_EDGE:
            raise ValueError("MEDIA_IMAGE_TOO_SMALL")
        format_to_mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif", "AVIF": "image/avif"}
        detected = format_to_mime.get(fmt)
        if not detected:
            raise ValueError("MEDIA_IMAGE_FORMAT_NOT_ALLOWED")
        if declared_mime and declared_mime.split(";", 1)[0].strip().lower().startswith("image/"):
            # Trust actual decoded format over a generic/mistyped response header.
            return detected, width, height
        return detected, width, height

    def harvest(
        self,
        *,
        source_url: str,
        hotel_id: str,
        role: str,
        room_type_id: str | None = None,
        source_type: str = "PUBLIC_SOURCE",
        observed_at: str | None = None,
        allow_private: bool = False,
        request_headers: dict | None = None,
        timeout_seconds: float = 12.0,
    ) -> dict:
        if allow_private and (os.getenv("APP_ENV") or os.getenv("GO_ENV") or "").lower() in {"production", "prod", "staging"}:
            raise ValueError("MEDIA_PRIVATE_TEST_DISABLED")
        role = role.upper()
        if role not in ALLOWED_ROLES:
            raise ValueError("MEDIA_ROLE_INVALID")
        if role == "ROOM" and not room_type_id:
            raise ValueError("MEDIA_ROOM_TYPE_ID_REQUIRED")
        self._validate_source_url(source_url, allow_private=allow_private)

        headers = {
            "User-Agent": "GO-Media-Harvester/6.1 (+rights-gated-cache)",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        if request_headers:
            headers.update({str(k): str(v) for k, v in request_headers.items()})

        tmp = self.cache_dir / f"download-{uuid.uuid4().hex}.part"
        sha = hashlib.sha256()
        size = 0
        declared_mime = None
        final_url = source_url
        try:
            with httpx.Client(follow_redirects=False, timeout=timeout_seconds, headers=headers, trust_env=False, transport=self._transport) as client:
                next_url = source_url
                for hop in range(6):
                    # Validate each target before contacting it, including intermediate redirects.
                    self._validate_source_url(next_url, allow_private=allow_private)
                    with client.stream("GET", next_url) as resp:
                        if resp.status_code in {301, 302, 303, 307, 308}:
                            if hop == 5 or not resp.headers.get("location"):
                                raise ValueError("MEDIA_REDIRECT_LIMIT_OR_LOCATION_INVALID")
                            redirected = urljoin(str(resp.url), resp.headers["location"])
                            self._validate_source_url(redirected, allow_private=allow_private)
                            if urlparse(redirected).netloc != urlparse(next_url).netloc:
                                # Explicit origin credentials cannot follow a cross-origin redirect.
                                for key in list(client.headers):
                                    if key.lower() not in {"user-agent", "accept", "accept-encoding", "connection"}:
                                        del client.headers[key]
                            next_url = redirected
                            continue
                        if resp.status_code != 200:
                            raise ValueError(f"MEDIA_DOWNLOAD_HTTP_{resp.status_code}")
                        declared_mime = resp.headers.get("content-type")
                        final_url = str(resp.url)
                        with tmp.open("wb") as f:
                            for chunk in resp.iter_bytes():
                                if not chunk:
                                    continue
                                size += len(chunk)
                                if size > MAX_IMAGE_BYTES:
                                    raise ValueError("MEDIA_IMAGE_TOO_LARGE")
                                sha.update(chunk)
                                f.write(chunk)
                            f.flush()
                            os.fsync(f.fileno())
                        break
            if size == 0:
                raise ValueError("MEDIA_DOWNLOAD_EMPTY")
            mime, width, height = self._validate_image(tmp, declared_mime)
            digest = sha.hexdigest()
            final_path = self.files_dir / f"{digest}{_safe_ext(mime)}"
            asset_id = _asset_id()
            record = {
                "asset_id": asset_id,
                "hotel_id": hotel_id,
                "role": role,
                "room_type_id": room_type_id,
                "source_type": source_type,
                "source_url": source_url,
                "resolved_url": final_url,
                "observed_at": observed_at or now_iso(),
                "downloaded_at": now_iso(),
                "sha256": digest,
                "perceptual_hash": _dhash(tmp),
                "byte_size": size,
                "mime_type": mime,
                "width": width,
                "height": height,
                "cache_file": final_path.name,
                "cache_state": "VALIDATED",
                "rights_state": "RIGHTS_UNKNOWN",
                "rights_owner": None,
                "rights_evidence_reference": None,
                "rights_decided_by": None,
                "rights_decided_at": None,
                "rights_expires_at": None,
                "rights_scope": None,
                "rights_regions": [],
                "rights_basis": None,
                "provider": None,
                "contract_id": None,
                "cache_allowed": None,
                "modification_allowed": None,
                "publishable": False,
                "rights_history": [],
            }
            return self._index.insert(record, lambda: self._admit_file(tmp, final_path, digest))
        finally:
            tmp.unlink(missing_ok=True)


    def purge_hotel(self, hotel_id: str) -> dict:
        """Staging clean-slate helper: removes only cache/index records belonging to one hotel.
        Files are deleted only when no remaining asset references the same immutable cache file.
        """
        return self._index.purge_hotel(hotel_id, self._delete_file)

    def harvest_batch(self, candidates: list[dict], allow_private: bool = False) -> dict:
        results, failures = [], []
        for c in candidates:
            try:
                results.append(self.harvest(allow_private=allow_private, **c))
            except Exception as e:
                failures.append({"source_url": c.get("source_url"), "hotel_id": c.get("hotel_id"), "role": c.get("role"), "error": str(e)})
        return {"downloaded": results, "failures": failures, "downloaded_count": len(results), "failure_count": len(failures)}

    def decide_rights(
        self,
        asset_id: str,
        *,
        rights_state: str,
        actor: str,
        rights_owner: str | None = None,
        evidence_reference: str | None = None,
        expires_at: str | None = None,
        rights_scope: str | None = None,
        rights_regions: list[str] | None = None,
        rights_basis: str | None = None,
        provider: str | None = None,
        contract_id: str | None = None,
        cache_allowed: bool | None = None,
        modification_allowed: bool | None = None,
        expected_revision: int | None = None,
    ) -> dict:
        if not isinstance(rights_state, str) or not isinstance(actor, str) or not actor.strip():
            raise ValueError("MEDIA_RIGHTS_DECISION_INVALID")
        state = rights_state.upper()
        if state not in RIGHTS_STATES:
            raise ValueError("MEDIA_RIGHTS_STATE_INVALID")
        if state in PUBLISHABLE_RIGHTS and not all(isinstance(v, str) and v.strip() for v in (rights_owner, evidence_reference)):
            raise ValueError("MEDIA_PUBLISHABLE_RIGHTS_EVIDENCE_REQUIRED")
        if state == "DISTRIBUTION_LICENSE" and (not provider or not contract_id or cache_allowed is not True):
            raise ValueError("MEDIA_DISTRIBUTION_LICENSE_CONTRACT_REQUIRED")
        if expires_at:
            try:
                _parse_iso(expires_at)
            except Exception as e:
                raise ValueError("MEDIA_RIGHTS_EXPIRY_INVALID") from e
        def change(rec):
            decided_at = now_iso()
            prior = {
                "rights_state": rec.get("rights_state"),
                "rights_owner": rec.get("rights_owner"),
                "rights_evidence_reference": rec.get("rights_evidence_reference"),
                "rights_decided_by": rec.get("rights_decided_by"),
                "rights_decided_at": rec.get("rights_decided_at"),
                "rights_expires_at": rec.get("rights_expires_at"),
                "rights_scope": rec.get("rights_scope"),
                "rights_regions": rec.get("rights_regions", []),
                "rights_basis": rec.get("rights_basis"),
                "provider": rec.get("provider"),
                "contract_id": rec.get("contract_id"),
                "cache_allowed": rec.get("cache_allowed"),
                "modification_allowed": rec.get("modification_allowed"),
            }
            rec.setdefault("rights_history", []).append({
                "changed_at": decided_at,
                "actor": actor,
                "from": prior,
                "to": {
                    "rights_state": state,
                    "rights_owner": rights_owner,
                    "rights_evidence_reference": evidence_reference,
                    "rights_expires_at": expires_at,
                    "rights_scope": rights_scope,
                    "rights_regions": list(rights_regions or []),
                    "rights_basis": rights_basis,
                    "provider": provider,
                    "contract_id": contract_id,
                    "cache_allowed": cache_allowed,
                    "modification_allowed": modification_allowed,
                },
            })
            rec["rights_state"] = state
            rec["rights_owner"] = rights_owner
            rec["rights_evidence_reference"] = evidence_reference
            rec["rights_decided_by"] = actor
            rec["rights_decided_at"] = decided_at
            rec["rights_expires_at"] = expires_at
            rec["rights_scope"] = rights_scope
            rec["rights_regions"] = list(rights_regions or [])
            rec["rights_basis"] = rights_basis
            rec["provider"] = provider
            rec["contract_id"] = contract_id
            rec["cache_allowed"] = cache_allowed
            rec["modification_allowed"] = modification_allowed
            rec["publishable"] = _rights_publishable(rec)
        return self._index.update(asset_id, change, expected_revision)

    def get(self, asset_id: str) -> dict:
        rec = self._index.get(asset_id)
        rec["publishable"] = _rights_publishable(rec)
        return rec

    def list_assets(self, *, hotel_id: str | None = None, room_type_id: str | None = None, publishable_only: bool = False) -> list[dict]:
        assets = list(self._read_index()["assets"].values())
        if hotel_id:
            assets = [x for x in assets if x.get("hotel_id") == hotel_id]
        if room_type_id:
            assets = [x for x in assets if x.get("room_type_id") == room_type_id]
        for x in assets:
            x["publishable"] = _rights_publishable(x)
        if publishable_only:
            assets = [x for x in assets if x.get("publishable")]
        return sorted(assets, key=lambda x: (x.get("hotel_id") or "", x.get("role") or "", x.get("room_type_id") or "", x.get("downloaded_at") or ""))

    def content_path(self, asset_id: str, *, require_publishable: bool = True) -> Path:
        rec = self.get(asset_id)
        rec["publishable"] = _rights_publishable(rec)
        if require_publishable and not rec.get("publishable"):
            raise ValueError("MEDIA_ASSET_NOT_PUBLISHABLE")
        p = (self.files_dir / rec["cache_file"]).resolve()
        if self.files_dir not in p.parents or not p.exists():
            raise ValueError("MEDIA_CACHE_FILE_MISSING")
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if digest != rec.get("sha256"):
            raise ValueError("MEDIA_CACHE_INTEGRITY_FAILED")
        return p

    def page_media(self, hotel_id: str, *, asset_ids: set[str] | None = None) -> dict:
        assets = self.list_assets(hotel_id=hotel_id, publishable_only=True)
        if asset_ids is not None:
            assets = [x for x in assets if x['asset_id'] in asset_ids]
        grouped: dict[str, list[dict]] = {"hero": [], "gallery": [], "rooms": {}, "dining": [], "facility": [], "meeting": [], "poi": []}
        for x in assets:
            public = {
                "asset_id": x["asset_id"],
                "url": f"/v1/hotel-media/{x['asset_id']}",
                "width": x["width"],
                "height": x["height"],
                "mime_type": x["mime_type"],
                "source_type": x["source_type"],
                "rights_state": x["rights_state"],
                "evidence_reference": x["rights_evidence_reference"],
                "rights_expires_at": x.get("rights_expires_at"),
                "rights_scope": x.get("rights_scope"),
                "rights_regions": x.get("rights_regions", []),
            }
            role = x["role"]
            if role == "HERO": grouped["hero"].append(public)
            elif role == "GALLERY": grouped["gallery"].append(public)
            elif role == "ROOM": grouped["rooms"].setdefault(x["room_type_id"], []).append(public)
            elif role == "DINING": grouped["dining"].append(public)
            elif role == "FACILITY": grouped["facility"].append(public)
            elif role == "MEETING": grouped["meeting"].append(public)
            elif role == "POI": grouped["poi"].append(public)
        return grouped


media_harvester_service = MediaHarvesterService()
