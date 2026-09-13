from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import socket
import threading
import uuid
from urllib.parse import urlparse

import httpx
from PIL import Image


PUBLISHABLE_RIGHTS = {"AUTHORIZED", "HOTEL_SUBMITTED", "HOTEL_SUBMITTED_INFERRED", "OWNER_VERIFIED_HOTEL_ASSET", "LICENSED", "DISTRIBUTION_LICENSE", "PUBLIC_DOMAIN"}
RIGHTS_STATES = PUBLISHABLE_RIGHTS | {"RIGHTS_UNKNOWN", "REJECTED", "EXPIRED"}
ALLOWED_ROLES = {"HERO", "GALLERY", "ROOM", "DINING", "FACILITY", "MEETING", "POI", "EXTERIOR", "LOBBY", "WELLNESS", "SIGNATURE_SPACE"}
MAX_IMAGE_BYTES = int(os.getenv("GO_MEDIA_MAX_IMAGE_BYTES", str(15 * 1024 * 1024)))
MIN_IMAGE_EDGE = int(os.getenv("GO_MEDIA_MIN_IMAGE_EDGE", "64"))

SIX_SCENE_ROLES = ("EXTERIOR", "LOBBY", "ROOM", "DINING", "WELLNESS", "SIGNATURE_SPACE")
SCENE_LABELS = {
    "EXTERIOR": "外观", "LOBBY": "大堂", "ROOM": "客房", "DINING": "餐饮",
    "WELLNESS": "康体", "SIGNATURE_SPACE": "特色空间",
}
SCENE_KEYWORDS = {
    "EXTERIOR": ("exterior","facade","façade","building","entrance","外观","外立面","建筑","入口","夜景"),
    "LOBBY": ("lobby","reception","frontdesk","front-desk","大堂","前台","接待"),
    "ROOM": ("room","suite","guestroom","bedroom","客房","套房","卧云","阅江","映日","圆梦","枕月"),
    "DINING": ("restaurant","dining","breakfast","bar","cafe","café","餐厅","餐饮","早餐","酒吧","咖啡"),
    "WELLNESS": ("spa","pool","swimming","gym","fitness","wellness","康体","泳池","游泳","健身","水疗"),
    "SIGNATURE_SPACE": ("signature","culture","cultural","reindeer","forest","library","meeting","function","banquet","ballroom","vip area","特色","文化","驯鹿","森林","书吧","艺术","会议","宴会","多功能","贵宾"),
}

def classify_scene(*, role: str | None = None, source_url: str | None = None, title: str | None = None, alt: str | None = None, context: str | None = None) -> str:
    declared=str(role or "").upper().strip()
    if declared in SIX_SCENE_ROLES:
        return declared
    text=" ".join(str(x or "").lower() for x in (source_url,title,alt,context))
    # High-signal phrase routing resolves ambiguous hotel words such as
    # "private dining room" (DINING, not ROOM) and "suite spa area" (WELLNESS).
    padded=f" {text} "
    if "suite" in padded and "dining area" in padded:
        return "ROOM"
    phrase_routes=(
        ("WELLNESS", ("spa","pool","swimming","fitness","health club","gym","wellness","水疗","泳池","健身","康体")),
        ("DINING", ("restaurant","dining","breakfast","steak house","lobby bar","bar","cafe","café","餐厅","餐饮","早餐","酒吧","咖啡")),
        ("SIGNATURE_SPACE", ("meeting","function room","banquet","ballroom","vip area","会议","宴会","多功能","贵宾")),
        ("EXTERIOR", ("hotel exterior","exterior view","facade","façade","building exterior","外观","外立面")),
        ("LOBBY", ("lobby","concierge lounge","executive lounge","reception","front desk","frontdesk","大堂","前台","接待","行政酒廊")),
        ("ROOM", ("guestroom","bedroom"," room ","suite","bed","bathroom","living area","卧云","阅江","映日","圆梦","枕月","客房","套房")),
    )
    for scene,phrases in phrase_routes:
        if any(p in padded for p in phrases):
            return scene
    scores={}
    for scene,words in SCENE_KEYWORDS.items():
        score=sum(3 if w in str(title or "").lower() or w in str(alt or "").lower() else 1 for w in words if w in text)
        if score:
            scores[scene]=score
    if scores:
        return max(scores.items(), key=lambda kv:(kv[1], -SIX_SCENE_ROLES.index(kv[0])))[0]
    if declared == "HERO":
        return "EXTERIOR"
    return "GALLERY"

def _hamming64(a: str | None, b: str | None) -> int | None:
    a=str(a or "").strip().lower(); b=str(b or "").strip().lower()
    if len(a)!=16 or len(b)!=16:
        return None
    try:
        return (int(a,16)^int(b,16)).bit_count()
    except ValueError:
        return None


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
    expires = _parse_iso(record.get("rights_expires_at"))
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
        self._lock = threading.RLock()
        self.files_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self._write_index({"version": 1, "assets": {}})

    def _read_index(self) -> dict:
        with self._lock:
            try:
                data = json.loads(self.index_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                data = {"version": 1, "assets": {}}
            data.setdefault("version", 1)
            data.setdefault("assets", {})
            return data

    def _write_index(self, data: dict) -> None:
        with self._lock:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.index_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self.index_path)

    def _validate_source_url(self, source_url: str, allow_private: bool = False) -> None:
        u = urlparse(source_url)
        if u.scheme not in {"http", "https"} or not u.hostname:
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
        source_group: str | None = None,
        observed_at: str | None = None,
        allow_private: bool = False,
        request_headers: dict | None = None,
        timeout_seconds: float = 12.0,
        title: str | None = None,
        alt: str | None = None,
        context: str | None = None,
    ) -> dict:
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
            with httpx.Client(follow_redirects=True, timeout=timeout_seconds, headers=headers, trust_env=False, transport=self._transport) as client:
                with client.stream("GET", source_url) as resp:
                    if resp.status_code != 200:
                        raise ValueError(f"MEDIA_DOWNLOAD_HTTP_{resp.status_code}")
                    declared_mime = resp.headers.get("content-type")
                    final_url = str(resp.url)
                    self._validate_source_url(final_url, allow_private=allow_private)
                    with tmp.open("wb") as f:
                        for chunk in resp.iter_bytes():
                            if not chunk:
                                continue
                            size += len(chunk)
                            if size > MAX_IMAGE_BYTES:
                                raise ValueError("MEDIA_IMAGE_TOO_LARGE")
                            sha.update(chunk)
                            f.write(chunk)
            if size == 0:
                raise ValueError("MEDIA_DOWNLOAD_EMPTY")
            mime, width, height = self._validate_image(tmp, declared_mime)
            digest = sha.hexdigest()
            final_path = self.files_dir / f"{digest}{_safe_ext(mime)}"
            if not final_path.exists():
                os.replace(tmp, final_path)
            else:
                tmp.unlink(missing_ok=True)

            asset_id = _asset_id()
            record = {
                "asset_id": asset_id,
                "hotel_id": hotel_id,
                "role": role,
                "scene_role": classify_scene(role=role, source_url=source_url, title=title, alt=alt, context=context),
                "room_type_id": room_type_id,
                "title": title,
                "alt": alt,
                "source_type": source_type,
                "source_group": source_group or source_type,
                "source_url": source_url,
                "resolved_url": final_url,
                "observed_at": observed_at or now_iso(),
                "downloaded_at": now_iso(),
                "sha256": digest,
                "perceptual_hash": _dhash(final_path),
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
            idx = self._read_index()
            idx["assets"][asset_id] = record
            self._write_index(idx)
            return record
        finally:
            tmp.unlink(missing_ok=True)


    def purge_hotel(self, hotel_id: str) -> dict:
        """Staging clean-slate helper: removes only cache/index records belonging to one hotel.
        Files are deleted only when no remaining asset references the same immutable cache file.
        """
        idx=self._read_index(); assets=idx.get("assets",{})
        removed=[(aid,rec) for aid,rec in list(assets.items()) if rec.get("hotel_id")==hotel_id]
        for aid,_ in removed: assets.pop(aid,None)
        referenced={rec.get("cache_file") for rec in assets.values() if rec.get("cache_file")}
        self._write_index(idx)
        for _,rec in removed:
            f=rec.get("cache_file")
            if f and f not in referenced: (self.files_dir/f).unlink(missing_ok=True)
        return {"hotel_id":hotel_id,"removed_count":len(removed)}

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
    ) -> dict:
        state = rights_state.upper()
        if state not in RIGHTS_STATES:
            raise ValueError("MEDIA_RIGHTS_STATE_INVALID")
        if state in PUBLISHABLE_RIGHTS and (not rights_owner or not evidence_reference):
            raise ValueError("MEDIA_PUBLISHABLE_RIGHTS_EVIDENCE_REQUIRED")
        if state == "DISTRIBUTION_LICENSE" and (not provider or not contract_id or cache_allowed is not True):
            raise ValueError("MEDIA_DISTRIBUTION_LICENSE_CONTRACT_REQUIRED")
        if expires_at:
            try:
                _parse_iso(expires_at)
            except Exception as e:
                raise ValueError("MEDIA_RIGHTS_EXPIRY_INVALID") from e
        idx = self._read_index()
        rec = idx["assets"].get(asset_id)
        if not rec:
            raise ValueError("MEDIA_ASSET_NOT_FOUND")
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
        idx["assets"][asset_id] = rec
        self._write_index(idx)
        return rec

    def get(self, asset_id: str) -> dict:
        rec = self._read_index()["assets"].get(asset_id)
        if not rec:
            raise ValueError("MEDIA_ASSET_NOT_FOUND")
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


    def media_duplicate_clusters(self, hotel_id: str, *, max_phash_distance: int = 10) -> list[dict]:
        """Cluster validated assets by exact SHA or near-identical dHash.

        The cluster is evidence only. It does not itself adjudicate copyright. Independent
        source groups are retained so GO can apply its commercial hotel-origin policy
        without mistaking mirrors from one platform as independent evidence.
        """
        assets=[x for x in self.list_assets(hotel_id=hotel_id) if x.get("cache_state")=="VALIDATED" and x.get("rights_state")!="REJECTED"]
        ordered=sorted(assets,key=lambda x:(int(x.get("width") or 0)*int(x.get("height") or 0), int(x.get("byte_size") or 0)),reverse=True)
        clusters=[]
        for rec in ordered:
            matched=None
            for cluster in clusters:
                # Compare against every member, not only the first/highest-resolution
                # asset. OTA/CDN recompression can form a legitimate transitive visual
                # cluster even when its two endpoints are farther apart.
                for member in cluster["assets"]:
                    exact=bool(rec.get("sha256") and rec.get("sha256")==member.get("sha256"))
                    d=_hamming64(rec.get("perceptual_hash"),member.get("perceptual_hash"))
                    if exact or (d is not None and d <= max_phash_distance):
                        matched=cluster; break
                if matched is not None:
                    break
            if matched is None:
                matched={"cluster_id":f"mcluster_{len(clusters)+1:04d}","assets":[]}
                clusters.append(matched)
            matched["assets"].append(rec)
        out=[]
        for c in clusters:
            groups=sorted({str(x.get("source_group") or x.get("source_type") or "UNKNOWN") for x in c["assets"]})
            out.append({
                "cluster_id":c["cluster_id"],
                "asset_ids":[x.get("asset_id") for x in c["assets"]],
                "source_groups":groups,
                "independent_source_group_count":len(groups),
                "best_asset_id":c["assets"][0].get("asset_id"),
                "exact_sha_count":len({x.get("sha256") for x in c["assets"] if x.get("sha256")}),
            })
        return out

    def promote_multi_source_hotel_origin(
        self, hotel_id: str, *, rights_owner: str, actor: str = "GO_MEDIA_POLICY",
        min_source_groups: int = 2, max_phash_distance: int = 10,
        rights_scope: str = "GO_CONSUMER_HOTEL_PAGE", rights_regions: list[str] | None = None,
    ) -> dict:
        """Apply GO's commercial multi-source hotel-origin inference policy.

        A same/near-identical hotel image observed on >=2 independent source groups is
        treated as strong evidence that the underlying material originated with the hotel.
        This is an internal commercial risk policy, not a legal copyright adjudication.
        The inference and all supporting source groups remain backend-only evidence.
        """
        promoted=[]; held=[]
        for cluster in self.media_duplicate_clusters(hotel_id,max_phash_distance=max_phash_distance):
            if cluster["independent_source_group_count"] < min_source_groups:
                held.append(cluster); continue
            evidence=f"go://hotel-media/multi-source-origin/{hotel_id}/{cluster['cluster_id']}"
            eligible_asset_ids=[]
            blocked_asset_ids=[]
            for aid in cluster["asset_ids"]:
                rec=self.get(aid)
                # Only a mark embedded in the image bytes is a blocker. Platform UI,
                # page chrome, page backgrounds and source-page labels are provenance,
                # not marks on the cached hotel image itself.
                if rec.get("third_party_content_mark_detected") is True or rec.get("third_party_mark_detected") is True:
                    blocked_asset_ids.append(aid)
                    continue
                if rec.get("rights_state") in {"REJECTED","AUTHORIZED","HOTEL_SUBMITTED","LICENSED","DISTRIBUTION_LICENSE","PUBLIC_DOMAIN"}:
                    continue
                eligible_asset_ids.append(aid)
                self.decide_rights(
                    aid, rights_state="HOTEL_SUBMITTED_INFERRED", actor=actor,
                    rights_owner=rights_owner, evidence_reference=evidence,
                    rights_scope=rights_scope, rights_regions=list(rights_regions or ["GLOBAL"]),
                    rights_basis="MULTI_SOURCE_IDENTICAL_HOTEL_ORIGIN_INFERENCE",
                    cache_allowed=True, modification_allowed=True,
                )
            decision={**cluster,"eligible_asset_ids":eligible_asset_ids,"blocked_asset_ids":blocked_asset_ids}
            if eligible_asset_ids:
                promoted.append(decision)
            else:
                held.append({**decision,"hold_reason":"THIRD_PARTY_CONTENT_MARK_DETECTED"})
        return {
            "hotel_id":hotel_id,
            "policy":"MULTI_SOURCE_IDENTICAL_HOTEL_ORIGIN_INFERENCE",
            "legal_adjudication":False,
            "min_independent_source_groups":min_source_groups,
            "promoted_cluster_count":len(promoted),
            "held_cluster_count":len(held),
            "promoted_asset_count":sum(len(x["eligible_asset_ids"]) for x in promoted),
            "promoted_clusters":promoted,
            "held_clusters":held,
        }


    def promote_owned_hotel_assets(
        self, hotel_id: str, *, rights_owner: str, owner_verified: bool,
        actor: str = "GO_OWNER_MEDIA_POLICY", rights_scope: str = "GO_CONSUMER_HOTEL_PAGE",
        rights_regions: list[str] | None = None, allowed_source_groups: set[str] | None = None,
        evidence_reference: str | None = None,
    ) -> dict:
        """Promote validated media for a hotel whose owner has explicitly verified asset ownership/use.

        This is intentionally opt-in and hotel-scoped. It is not inferred from crawling alone.
        The caller must provide owner_verified=True. Records explicitly marked rejected or carrying
        third_party_mark_detected=True remain blocked. Provenance and the owner attestation stay
        backend-only.
        """
        if owner_verified is not True:
            raise ValueError("MEDIA_OWNER_VERIFICATION_REQUIRED")
        groups={str(x).upper() for x in (allowed_source_groups or set())}
        promoted=[]; held=[]
        for rec in self.list_assets(hotel_id=hotel_id):
            aid=rec.get("asset_id")
            if rec.get("cache_state") != "VALIDATED":
                held.append({"asset_id":aid,"reason":"CACHE_NOT_VALIDATED"}); continue
            if rec.get("rights_state") == "REJECTED":
                held.append({"asset_id":aid,"reason":"RIGHTS_REJECTED"}); continue
            if rec.get("third_party_mark_detected") is True:
                held.append({"asset_id":aid,"reason":"THIRD_PARTY_MARK_DETECTED"}); continue
            group=str(rec.get("source_group") or rec.get("source_type") or "UNKNOWN").upper()
            if groups and group not in groups:
                held.append({"asset_id":aid,"reason":"SOURCE_GROUP_NOT_ALLOWED","source_group":group}); continue
            if rec.get("rights_state") in PUBLISHABLE_RIGHTS:
                promoted.append({"asset_id":aid,"already_publishable":True,"source_group":group}); continue
            self.decide_rights(
                aid, rights_state="OWNER_VERIFIED_HOTEL_ASSET", actor=actor,
                rights_owner=rights_owner,
                evidence_reference=evidence_reference or f"go://hotel-media/owner-attestation/{hotel_id}",
                rights_scope=rights_scope, rights_regions=list(rights_regions or ["GLOBAL"]),
                rights_basis="OWNER_VERIFIED_HOTEL_ASSET", cache_allowed=True, modification_allowed=True,
            )
            promoted.append({"asset_id":aid,"already_publishable":False,"source_group":group})
        return {
            "hotel_id":hotel_id,
            "policy":"OWNER_VERIFIED_HOTEL_ASSET",
            "owner_verified":True,
            "promoted_asset_count":len(promoted),
            "held_asset_count":len(held),
            "promoted":promoted,
            "held":held,
        }

    def unique_publishable_assets(self, hotel_id: str, *, max_phash_distance: int = 10) -> list[dict]:
        assets=self.list_assets(hotel_id=hotel_id,publishable_only=True)
        # Prefer higher resolution when two assets are exact/near duplicates.
        ordered=sorted(assets,key=lambda x:(int(x.get("width") or 0)*int(x.get("height") or 0), int(x.get("byte_size") or 0)),reverse=True)
        unique=[]
        for rec in ordered:
            duplicate=False
            for prev in unique:
                if rec.get("sha256") and rec.get("sha256")==prev.get("sha256"):
                    duplicate=True; break
                d=_hamming64(rec.get("perceptual_hash"),prev.get("perceptual_hash"))
                if d is not None and d <= max_phash_distance:
                    duplicate=True; break
            if not duplicate:
                unique.append(rec)
        return unique

    def six_scene_coverage(self, hotel_id: str) -> dict:
        unique=self.unique_publishable_assets(hotel_id)
        counts={role:0 for role in SIX_SCENE_ROLES}
        for rec in unique:
            scene=str(rec.get("scene_role") or classify_scene(role=rec.get("role"),source_url=rec.get("source_url"),title=rec.get("title"),alt=rec.get("alt"))).upper()
            if scene in counts:
                counts[scene]+=1
        return {
            "hotel_id":hotel_id,
            "unique_publishable_media":len(unique),
            "scene_counts":{SCENE_LABELS[k]:v for k,v in counts.items()},
            "scene_coverage":{SCENE_LABELS[k]:v>0 for k,v in counts.items()},
            "six_scene_complete":all(v>0 for v in counts.values()),
            "golden_media_ge_30":len(unique)>=30,
            "golden_media_gate_pass":len(unique)>=30 and all(v>0 for v in counts.values()),
        }

    def page_media(self, hotel_id: str) -> dict:
        assets = self.unique_publishable_assets(hotel_id)
        grouped: dict[str, list[dict] | dict] = {
            "hero": [], "gallery": [], "rooms": {}, "exterior": [], "lobby": [],
            "dining": [], "wellness": [], "signature_space": [], "meeting": [], "poi": [],
        }
        for x in assets:
            # Consumer projection deliberately excludes provenance, confidence and rights evidence.
            public = {
                "asset_id": x["asset_id"],
                "url": f"/v1/hotel-media/{x['asset_id']}",
                "width": x["width"],
                "height": x["height"],
                "mime_type": x["mime_type"],
            }
            role=str(x.get("role") or "GALLERY").upper()
            scene=str(x.get("scene_role") or classify_scene(role=role,source_url=x.get("source_url"),title=x.get("title"),alt=x.get("alt"))).upper()
            if role == "HERO": grouped["hero"].append(public)
            if role == "ROOM": grouped["rooms"].setdefault(x["room_type_id"], []).append(public)
            elif role == "MEETING": grouped["meeting"].append(public)
            elif role == "POI": grouped["poi"].append(public)
            if scene == "EXTERIOR": grouped["exterior"].append(public)
            elif scene == "LOBBY": grouped["lobby"].append(public)
            elif scene == "DINING": grouped["dining"].append(public)
            elif scene == "WELLNESS": grouped["wellness"].append(public)
            elif scene == "SIGNATURE_SPACE": grouped["signature_space"].append(public)
            if role == "GALLERY" or scene not in SIX_SCENE_ROLES:
                grouped["gallery"].append(public)
        return grouped



media_harvester_service = MediaHarvesterService()
