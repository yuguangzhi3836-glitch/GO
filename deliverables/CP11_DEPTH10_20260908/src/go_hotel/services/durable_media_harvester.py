"""Durable media harvester: immutable content bytes + PostgreSQL metadata authority."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, ipaddress, mimetypes, os, socket, uuid
from pathlib import Path
from urllib.parse import urlparse
import httpx
from PIL import Image
from .durable_media_index import durable_media_index_service

ALLOWED_ROLES={"HERO","GALLERY","ROOM","DINING","FACILITY","MEETING","POI","EXTERIOR","LOBBY","WELLNESS","SIGNATURE_SPACE"}
MAX_IMAGE_BYTES=int(os.getenv("GO_MEDIA_MAX_IMAGE_BYTES",str(15*1024*1024))); MIN_IMAGE_EDGE=int(os.getenv("GO_MEDIA_MIN_IMAGE_EDGE","64"))
def now_iso(): return datetime.now(timezone.utc).isoformat()
def _asset_id(): return "media_"+uuid.uuid4().hex
def _safe_ext(mime):
    ext=mimetypes.guess_extension(mime.split(";",1)[0].strip()) or ".img"; return ".jpg" if ext==".jpe" else ext
def _public_host(host):
    try: infos=socket.getaddrinfo(host,None,type=socket.SOCK_STREAM)
    except socket.gaierror: return False
    if not infos:return False
    for info in infos:
        ip=ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:return False
    return True
def _dhash(path):
    with Image.open(path) as im: px=list(im.convert("L").resize((9,8)).getdata())
    bits=[]
    for y in range(8):
        row=px[y*9:(y+1)*9]; bits.extend(1 if row[x]>row[x+1] else 0 for x in range(8))
    value=0
    for bit in bits:value=(value<<1)|bit
    return f"{value:016x}"
def _sha_file(path):
    d=hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b""):d.update(chunk)
    return d.hexdigest()

class DurableMediaHarvesterService:
    def __init__(self,cache_dir=None,transport=None):
        self.cache_dir=Path(cache_dir or os.getenv("GO_MEDIA_CACHE_DIR","var/media_cache")).resolve(); self.files_dir=self.cache_dir/"files"; self.files_dir.mkdir(parents=True,exist_ok=True); self._transport=transport
    def _validate_source(self,url,*,allow_private=False):
        p=urlparse(url)
        if p.scheme not in {"http","https"} or not p.hostname or p.username or p.password:raise ValueError("MEDIA_SOURCE_URL_INVALID")
        if not allow_private and not _public_host(p.hostname):raise ValueError("MEDIA_SOURCE_PRIVATE_OR_UNRESOLVABLE_BLOCKED")
    def _validate_image(self,path):
        try:
            with Image.open(path) as im:im.verify()
            with Image.open(path) as im:width,height=im.size; fmt=(im.format or "").upper()
        except Exception as exc:raise ValueError("MEDIA_CONTENT_NOT_VALID_IMAGE") from exc
        if min(width,height)<MIN_IMAGE_EDGE:raise ValueError("MEDIA_IMAGE_TOO_SMALL")
        mime={"JPEG":"image/jpeg","PNG":"image/png","WEBP":"image/webp","GIF":"image/gif","AVIF":"image/avif"}.get(fmt)
        if not mime:raise ValueError("MEDIA_IMAGE_FORMAT_NOT_ALLOWED")
        return mime,width,height
    def harvest(self,*,source_url,hotel_id,role,room_type_id=None,source_type="PUBLIC_SOURCE",observed_at=None,allow_private=False,request_headers=None,timeout_seconds=12.0,actor="SYSTEM"):
        role=str(role or "").upper()
        if role not in ALLOWED_ROLES:raise ValueError("MEDIA_ROLE_INVALID")
        if role=="ROOM" and not room_type_id:raise ValueError("MEDIA_ROOM_TYPE_ID_REQUIRED")
        if not hotel_id:raise ValueError("MEDIA_HOTEL_ID_REQUIRED")
        self._validate_source(source_url,allow_private=allow_private)
        headers={"User-Agent":"GO-Media-Harvester/DEPTH10 (+durable-index)","Accept":"image/avif,image/webp,image/apng,image/*,*/*;q=0.8"}
        if request_headers:headers.update({str(k):str(v) for k,v in request_headers.items()})
        tmp=self.cache_dir/("download-"+uuid.uuid4().hex+".part"); digest=hashlib.sha256(); size=0; final_url=source_url
        try:
            with httpx.Client(follow_redirects=True,timeout=timeout_seconds,headers=headers,trust_env=False,transport=self._transport) as client:
                with client.stream("GET",source_url) as response:
                    if response.status_code!=200:raise ValueError(f"MEDIA_DOWNLOAD_HTTP_{response.status_code}")
                    final_url=str(response.url); self._validate_source(final_url,allow_private=allow_private)
                    with tmp.open("wb") as fh:
                        for chunk in response.iter_bytes():
                            if not chunk:continue
                            size+=len(chunk)
                            if size>MAX_IMAGE_BYTES:raise ValueError("MEDIA_IMAGE_TOO_LARGE")
                            digest.update(chunk); fh.write(chunk)
            if size==0:raise ValueError("MEDIA_DOWNLOAD_EMPTY")
            mime,width,height=self._validate_image(tmp); sha=digest.hexdigest(); final_path=self.files_dir/(sha+_safe_ext(mime)); created=False
            if not final_path.exists():os.replace(tmp,final_path); created=True
            else:
                tmp.unlink(missing_ok=True)
                if _sha_file(final_path)!=sha:raise ValueError("MEDIA_EXISTING_BLOB_INTEGRITY_FAILED")
            record={"asset_id":_asset_id(),"hotel_id":hotel_id,"room_type_id":room_type_id,"role":role,"sha256":sha,"cache_file":final_path.name,"cache_state":"VALIDATED","source_url":source_url,"resolved_url":final_url,"source_type":source_type,"observed_at":observed_at or now_iso(),"downloaded_at":now_iso(),"byte_size":size,"mime_type":mime,"width":width,"height":height,"perceptual_hash":_dhash(final_path),"rights_state":"RIGHTS_UNKNOWN","publication_state":"HOLD"}
            try:return durable_media_index_service.register(record,actor=actor)
            except Exception:
                # Never delete here: another durable asset may share the same SHA.
                # A crash/failure leaves an immutable orphan which reconciliation
                # quarantines after grace if PostgreSQL has no reference.
                if created:
                    marker=self.cache_dir/("orphan-"+sha+".pending")
                    marker.write_text(now_iso(),encoding="utf-8")
                raise
        finally:tmp.unlink(missing_ok=True)
    def decide_rights(self,asset_id,*,rights_state,actor,rights_owner=None,evidence_reference=None,rights_basis=None):return durable_media_index_service.decide_rights(asset_id,rights_state=rights_state,actor=actor,rights_owner=rights_owner,evidence_reference=evidence_reference,rights_basis=rights_basis)
    def publish(self,asset_id,*,actor="SYSTEM"):
        path=self.content_path(asset_id,require_publishable=False)
        if _sha_file(path)!=self.get(asset_id).get("sha256"):raise ValueError("MEDIA_CACHE_INTEGRITY_FAILED")
        return durable_media_index_service.set_publication(asset_id,publish=True,actor=actor)
    def hold(self,asset_id,*,actor="SYSTEM"):return durable_media_index_service.set_publication(asset_id,publish=False,actor=actor)
    def revoke(self,asset_id,*,reason,actor="SYSTEM"):return durable_media_index_service.revoke(asset_id,reason=reason,actor=actor)
    def get(self,asset_id):return durable_media_index_service.get(asset_id)
    def list_assets(self,*,hotel_id=None,room_type_id=None,publishable_only=False):return durable_media_index_service.list_assets(hotel_id=hotel_id,room_type_id=room_type_id,publishable_only=publishable_only)
    def content_path(self,asset_id,*,require_publishable=True):
        record=self.get(asset_id)
        if require_publishable and not(record.get("publishable") and record.get("publication_state")=="PUBLISHED"):raise ValueError("MEDIA_ASSET_NOT_PUBLISHED")
        path=(self.files_dir/str(record["cache_file"])).resolve()
        if self.files_dir not in path.parents or not path.exists():raise ValueError("MEDIA_CACHE_FILE_MISSING")
        if _sha_file(path)!=record.get("sha256"):raise ValueError("MEDIA_CACHE_INTEGRITY_FAILED")
        return path

durable_media_harvester_service=DurableMediaHarvesterService()
