from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import ipaddress
import json
import os
import re
import socket
import time
import uuid
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy import select

from go_hotel.db.models import HotelAutoPageEventRow, HotelContentSourceSnapshotRow
from go_hotel.db.session import SessionLocal
from go_hotel.services.hotel_autopage_factory import hotel_autopage_factory_service


DISCOVERY_SOURCE_MAP = {
    "OFFICIAL_WEBSITE": "OFFICIAL_WEBSITE",
    "GROUP_OFFICIAL": "GROUP_OFFICIAL",
    "PUBLIC_SOURCE": "PUBLIC_SOURCE",
    "OTA_DISCOVERY": "OTA_DISCOVERY",
    "CONTENT_PROVIDER": "CONTENT_PROVIDER",
    "AUTHORIZED_DISTRIBUTOR": "AUTHORIZED_DISTRIBUTOR",
    "DATA_PROVIDER": "CONTENT_PROVIDER",
    "SEARCH_RESULT": "PUBLIC_SOURCE",
    "MAP_DIRECTORY": "PUBLIC_SOURCE",
}

DEFAULT_RIGHTS = {
    "OFFICIAL_WEBSITE": "PUBLIC_BUSINESS_FACT",
    "GROUP_OFFICIAL": "PUBLIC_BUSINESS_FACT",
    "PUBLIC_SOURCE": "PUBLIC_BUSINESS_FACT",
    "OTA_DISCOVERY": "PUBLIC_BUSINESS_FACT",
    "SEARCH_RESULT": "PUBLIC_BUSINESS_FACT",
    "MAP_DIRECTORY": "PUBLIC_BUSINESS_FACT",
    "CONTENT_PROVIDER": "AUTHORIZED",
    "AUTHORIZED_DISTRIBUTOR": "DISTRIBUTION_LICENSE",
    "DATA_PROVIDER": "AUTHORIZED",
}

TRANSIENT_HTTP = {408, 425, 429, 500, 502, 503, 504}
MAX_HTML_BYTES = 3 * 1024 * 1024


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ident(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value) -> str:
    return hashlib.sha256(_dump(value).encode("utf-8")).hexdigest()


def _norm(value) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    # Block every non-global destination, including RFC1918, loopback, link-local,
    # CGNAT, multicast, unspecified, documentation/reserved ranges and cloud metadata.
    if not ip.is_global:
        return True
    if ip.version == 4 and ip in ipaddress.ip_network("169.254.169.254/32"):
        return True
    if ip.version == 6 and ip in ipaddress.ip_network("fe80::/10"):
        return True
    return False


def _resolve_host(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("DISCOVERY_SOURCE_DNS_UNRESOLVABLE") from exc
    ips=[]
    for info in infos:
        raw=info[4][0].split('%',1)[0]
        ip=ipaddress.ip_address(raw)
        if _is_blocked_ip(ip):
            raise ValueError("DISCOVERY_SOURCE_PRIVATE_OR_SPECIAL_BLOCKED")
        if str(ip) not in ips:
            ips.append(str(ip))
    if not ips:
        raise ValueError("DISCOVERY_SOURCE_DNS_UNRESOLVABLE")
    return sorted(ips)


def _sanitize_url(url: str) -> str:
    u=urlparse(url)
    if u.username is not None or u.password is not None:
        raise ValueError("DISCOVERY_SOURCE_URL_CREDENTIALS_FORBIDDEN")
    return u._replace(fragment='').geturl()



class DiscoveryNetworkPolicyError(ValueError):
    def __init__(self, code: str, audit: dict | None = None):
        super().__init__(code)
        self.audit = audit or {"block_reason": code}


def _safe_url_for_log(url: str | None) -> str | None:
    if not url:
        return None
    try:
        u=urlparse(str(url))
        host=u.hostname or ""
        port=f":{u.port}" if u.port else ""
        return u._replace(netloc=host+port, fragment="").geturl()
    except Exception:
        return "INVALID_URL"


def _safe_hint_for_log(hint: dict) -> dict:
    return {
        "kind": str(hint.get("kind") or "PUBLIC_SOURCE"),
        "source_key": hint.get("source_key"),
        "url": _safe_url_for_log(hint.get("url")),
        "has_provider_payload": isinstance(hint.get("payload"), dict),
    }


class _HotelHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.in_title = False
        self.meta: dict[str, str] = {}
        self.links: list[tuple[str, str]] = []
        self.images: list[str] = []
        self.jsonld_parts: list[str] = []
        self.in_jsonld = False

    def handle_starttag(self, tag, attrs):
        a = {str(k).lower(): (v or "") for k, v in attrs}
        tag = tag.lower()
        if tag == "title":
            self.in_title = True
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta[key] = a["content"].strip()
        elif tag == "a" and a.get("href"):
            self.links.append((a["href"].strip(), a.get("rel", "")))
        elif tag == "img":
            src = a.get("src") or a.get("data-src") or a.get("data-lazy-src")
            if src:
                self.images.append(src.strip())
        elif tag == "script" and "application/ld+json" in a.get("type", "").lower():
            self.in_jsonld = True

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.in_title = False
        elif tag.lower() == "script":
            self.in_jsonld = False

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
        if self.in_jsonld:
            self.jsonld_parts.append(data)


def _jsonld_nodes(raw: str) -> list[dict]:
    try:
        value = json.loads(raw)
    except Exception:
        return []
    nodes: list[dict] = []
    if isinstance(value, dict):
        graph = value.get("@graph")
        if isinstance(graph, list):
            nodes.extend(x for x in graph if isinstance(x, dict))
        nodes.append(value)
    elif isinstance(value, list):
        nodes.extend(x for x in value if isinstance(x, dict))
    return nodes


def _type_set(node: dict) -> set[str]:
    raw = node.get("@type")
    if isinstance(raw, str):
        return {raw.lower()}
    if isinstance(raw, list):
        return {str(x).lower() for x in raw}
    return set()


def _address(value):
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return None
    formatted = ", ".join(str(value.get(k)).strip() for k in ["streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry"] if value.get(k))
    if not formatted:
        return None
    return {"formatted": formatted, "street": value.get("streetAddress"), "city": value.get("addressLocality"), "region": value.get("addressRegion"), "postal_code": value.get("postalCode"), "country": value.get("addressCountry")}


def _extract_payload(html: str, base_url: str, seed: dict) -> dict:
    parser = _HotelHTMLParser()
    parser.feed(html)
    payload: dict = {}
    contacts: list[dict] = []
    media_candidates: list[dict] = []

    # Prefer structured data. We intentionally do not copy arbitrary body prose.
    for raw in parser.jsonld_parts:
        for node in _jsonld_nodes(raw):
            types = _type_set(node)
            if not (types & {"hotel", "lodgingbusiness", "resort", "motel", "bedandbreakfast", "hostel"}):
                continue
            payload.setdefault("name", node.get("name"))
            payload.setdefault("address", _address(node.get("address")))
            payload.setdefault("website", node.get("url"))
            tel = node.get("telephone")
            email = node.get("email")
            if tel:
                contacts.append({"contact_type": "GENERAL", "channel": "PHONE", "value": str(tel), "is_public_business_contact": True})
            if email:
                contacts.append({"contact_type": "GENERAL", "channel": "EMAIL", "value": str(email), "is_public_business_contact": True})
            geo = node.get("geo")
            if isinstance(geo, dict):
                payload.setdefault("latitude", geo.get("latitude"))
                payload.setdefault("longitude", geo.get("longitude"))
            amenities = node.get("amenityFeature")
            if isinstance(amenities, list):
                vals = []
                for x in amenities:
                    if isinstance(x, dict) and x.get("name") and x.get("value", True) not in {False, "false", 0}:
                        vals.append(str(x["name"]).strip())
                if vals:
                    payload.setdefault("facilities", list(dict.fromkeys(vals)))
            policies = []
            if node.get("checkinTime"):
                policies.append({"type": "CHECK_IN", "value": node.get("checkinTime")})
            if node.get("checkoutTime"):
                policies.append({"type": "CHECK_OUT", "value": node.get("checkoutTime")})
            if policies:
                payload.setdefault("policies", policies)
            imgs = node.get("image")
            if isinstance(imgs, str):
                imgs = [imgs]
            if isinstance(imgs, list):
                for img in imgs:
                    if isinstance(img, dict):
                        img = img.get("url") or img.get("contentUrl")
                    if isinstance(img, str) and img.strip():
                        media_candidates.append({"source_url": urljoin(base_url, img.strip()), "role": "GALLERY", "rights_state": "RIGHTS_UNKNOWN"})

    title = " ".join(x.strip() for x in parser.title_parts if x.strip()).strip()
    if not payload.get("name"):
        payload["name"] = seed.get("name") or parser.meta.get("og:site_name") or parser.meta.get("og:title") or title or None
    if not payload.get("website"):
        payload["website"] = base_url
    if not payload.get("address") and seed.get("address"):
        payload["address"] = seed["address"]

    for href, _ in parser.links:
        low = href.lower()
        if low.startswith("mailto:"):
            value = href[7:].split("?", 1)[0].strip()
            if value:
                contacts.append({"contact_type": "GENERAL", "channel": "EMAIL", "value": value, "is_public_business_contact": True})
        elif low.startswith("tel:"):
            value = href[4:].split("?", 1)[0].strip()
            if value:
                contacts.append({"contact_type": "GENERAL", "channel": "PHONE", "value": value, "is_public_business_contact": True})
    for image in parser.images[:100]:
        media_candidates.append({"source_url": urljoin(base_url, image), "role": "GALLERY", "rights_state": "RIGHTS_UNKNOWN"})
    og = parser.meta.get("og:image")
    if og:
        media_candidates.insert(0, {"source_url": urljoin(base_url, og), "role": "HERO", "rights_state": "RIGHTS_UNKNOWN"})

    if contacts:
        dedup = {}
        for c in contacts:
            key = (c["channel"], _norm(c["value"]))
            dedup[key] = c
        payload["contacts"] = list(dedup.values())
    if media_candidates:
        dedup_urls = {}
        for c in media_candidates:
            if c["source_url"].startswith(("http://", "https://")):
                dedup_urls[c["source_url"]] = c
        payload["media_candidates"] = list(dedup_urls.values())[:100]
    return {k: v for k, v in payload.items() if v not in (None, "", [], {})}


class HotelDiscoveryOrchestratorService:
    """Discovers hotel facts and persists immutable Source Snapshots before AutoPage composition.

    This slice intentionally stops at discovery/snapshot orchestration. Candidate media URLs are
    recorded as evidence only; Media Harvester + Rights Gate remain separate publication controls.
    """

    def __init__(self, *, transport: httpx.BaseTransport | None = None):
        self._transport = transport

    def _event(self, s, event_type: str, evidence: dict, actor: str, hotel_id: str | None = None):
        row = HotelAutoPageEventRow(
            hotel_auto_page_event_id=_ident("hape"), hotel_id=hotel_id,
            event_type=event_type, evidence_json=evidence, actor=actor, created_at=_now(),
        )
        s.add(row)
        return row

    def _seed_fingerprint(self, seed: dict) -> str:
        identity = {
            "name": _norm(seed.get("name")),
            "address": _norm(seed.get("address")),
            "city": _norm(seed.get("city")),
            "country": _norm(seed.get("country")),
            "external_ids": seed.get("external_ids") or {},
            "source_hints": sorted(str(x.get("url") or x.get("source_key") or "") for x in (seed.get("source_hints") or []) if isinstance(x, dict)),
        }
        if not identity["name"] and not identity["external_ids"]:
            raise ValueError("DISCOVERY_SEED_IDENTITY_REQUIRED")
        return _sha(identity)

    def register_seed(self, seed: dict, actor: str = "SYSTEM") -> dict:
        if not isinstance(seed, dict):
            raise ValueError("DISCOVERY_SEED_INVALID")
        fp = self._seed_fingerprint(seed)
        job_id = f"hdj_{fp[:32]}"
        with SessionLocal() as s:
            events = s.scalars(select(HotelAutoPageEventRow).where(HotelAutoPageEventRow.event_type == "DISCOVERY_JOB_CREATED")).all()
            for e in events:
                ev = e.evidence_json or {}
                if ev.get("seed_fingerprint") == fp:
                    return {"idempotent": True, "job_id": ev.get("job_id"), "seed_fingerprint": fp, "seed": ev.get("seed"), "state": self.job_status(ev.get("job_id"))}
            self._event(s, "DISCOVERY_SEED_REGISTERED", {"job_id": job_id, "seed_fingerprint": fp, "seed": seed}, actor)
            self._event(s, "DISCOVERY_JOB_CREATED", {"job_id": job_id, "seed_fingerprint": fp, "seed": seed, "state": "PENDING"}, actor)
            s.commit()
        return {"idempotent": False, "job_id": job_id, "seed_fingerprint": fp, "seed": seed, "state": "PENDING"}

    def list_seeds(self, limit: int = 100) -> list[dict]:
        with SessionLocal() as s:
            rows = s.scalars(select(HotelAutoPageEventRow).where(HotelAutoPageEventRow.event_type == "DISCOVERY_SEED_REGISTERED").order_by(HotelAutoPageEventRow.created_at.desc()).limit(max(1, min(limit, 1000)))).all()
            return [{"created_at": r.created_at.isoformat(), **(r.evidence_json or {})} for r in rows]

    def _private_test_override(self) -> bool:
        env=(os.getenv("APP_ENV") or os.getenv("GO_ENV") or "").strip().lower()
        return env not in {"production","prod","staging"} and os.getenv("GO_DISCOVERY_ALLOW_PRIVATE_TEST") == "1"

    def _validate_url(self, url: str) -> dict:
        raw=str(url or "").strip()
        audit={"original_url":_safe_url_for_log(raw),"normalized_url":None,"target_host":None,"resolved_ips":[],"block_reason":None}
        try:
            clean=_sanitize_url(raw)
            audit["normalized_url"]=_safe_url_for_log(clean)
            u=urlparse(clean)
            audit["target_host"]=u.hostname
            if u.scheme not in {"http", "https"} or not u.hostname:
                raise DiscoveryNetworkPolicyError("DISCOVERY_SOURCE_URL_INVALID", audit)
            try:
                if u.port is not None and not (1 <= int(u.port) <= 65535):
                    raise DiscoveryNetworkPolicyError("DISCOVERY_SOURCE_URL_INVALID", audit)
            except ValueError as exc:
                if isinstance(exc, DiscoveryNetworkPolicyError):
                    raise
                raise DiscoveryNetworkPolicyError("DISCOVERY_SOURCE_URL_INVALID", audit) from exc
            if self._private_test_override():
                return {"url":clean,"host":u.hostname,"resolved_ips":[],"audit":audit}
            try:
                ips=_resolve_host(u.hostname)
            except ValueError as exc:
                audit["block_reason"]=str(exc)
                raise DiscoveryNetworkPolicyError(str(exc),audit) from exc
            audit["resolved_ips"]=ips
            return {"url":clean,"host":u.hostname,"resolved_ips":ips,"audit":audit}
        except DiscoveryNetworkPolicyError:
            raise
        except ValueError as exc:
            audit["block_reason"]=str(exc)
            raise DiscoveryNetworkPolicyError(str(exc),audit) from exc
        except Exception as exc:
            audit["block_reason"]="DISCOVERY_SOURCE_URL_INVALID"
            raise DiscoveryNetworkPolicyError("DISCOVERY_SOURCE_URL_INVALID",audit) from exc


    def _connected_peer_ip(self, response: httpx.Response) -> str | None:
        stream=response.extensions.get("network_stream") if isinstance(response.extensions,dict) else None
        if stream is None:
            return None
        candidates=[]
        try:
            sock=stream.get_extra_info("socket")
            if sock is not None:
                candidates.append(sock.getpeername())
        except Exception:
            pass
        for key in ("server_addr","peername"):
            try:
                candidates.append(stream.get_extra_info(key))
            except Exception:
                pass
        for value in candidates:
            if isinstance(value,(tuple,list)) and value:
                value=value[0]
            if value:
                try:
                    return str(ipaddress.ip_address(str(value).split('%',1)[0]))
                except Exception:
                    continue
        return None

    def _verify_connected_peer(self, response: httpx.Response, checked: dict, audit: dict) -> None:
        if self._private_test_override():
            return
        peer=self._connected_peer_ip(response)
        audit["connected_peer_ip"]=peer
        if peer is None:
            # httpx MockTransport and some alternative transports do not expose the socket.
            # DNS is still validated twice; standard httpcore transports expose a peer socket.
            return
        ip=ipaddress.ip_address(peer)
        if _is_blocked_ip(ip) or peer not in set(checked.get("resolved_ips") or []):
            audit["block_reason"]="DISCOVERY_CONNECTED_PEER_MISMATCH_BLOCKED"
            raise DiscoveryNetworkPolicyError("DISCOVERY_CONNECTED_PEER_MISMATCH_BLOCKED",dict(audit))

    def _fetch_html(self, url: str, *, timeout_seconds: float = 12.0, allow_json: bool = False) -> tuple[str, str, int, dict]:
        requested=max(1.0,float(timeout_seconds))
        # Connection establishment remains tightly capped, while read timeout follows the caller.
        # RC17.9.1 passed 55s for Overpass but the old code silently capped reads at 10s,
        # producing false REGIONAL_DISCOVERY_ALL_PROVIDERS_FAILED timeouts on valid large city payloads.
        connect_timeout=min(requested,10.0)
        read_timeout=min(max(requested,12.0),90.0)
        timeout=httpx.Timeout(connect=connect_timeout,read=read_timeout,write=connect_timeout,pool=connect_timeout)
        max_redirects=max(0,min(int(os.getenv("GO_DISCOVERY_MAX_REDIRECTS","5")),10))
        max_bytes=max(64*1024,min(int(os.getenv("GO_DISCOVERY_MAX_HTML_BYTES",str(MAX_HTML_BYTES))),5*1024*1024))
        headers={"User-Agent":"GO-Hotel-Discovery/6.1 (+source-snapshot; rights-gated-media)","Accept":"text/html,application/xhtml+xml;q=0.9,*/*;q=0.2"}
        current=str(url)
        redirect_chain=[]
        audit={"original_url":_safe_url_for_log(str(url)),"normalized_url":None,"target_host":None,"resolved_ips":[],"redirect_chain":redirect_chain,"targets":[],"final_url":None,"final_ips":[],"block_reason":None}
        with httpx.Client(follow_redirects=False,timeout=timeout,headers=headers,trust_env=False,transport=self._transport) as client:
            for hop in range(max_redirects+1):
                try:
                    checked=self._validate_url(current)
                except DiscoveryNetworkPolicyError as exc:
                    exc.audit.setdefault("redirect_chain", list(redirect_chain))
                    raise
                audit["normalized_url"]=checked["url"]
                audit["target_host"]=checked["host"]
                audit["resolved_ips"]=checked["resolved_ips"]
                # Resolve twice immediately before connect. A changed answer is treated as rebinding.
                if not self._private_test_override():
                    second=_resolve_host(checked["host"])
                    if checked["resolved_ips"] != second:
                        audit["block_reason"]="DISCOVERY_DNS_REBINDING_BLOCKED"
                        raise DiscoveryNetworkPolicyError("DISCOVERY_DNS_REBINDING_BLOCKED",dict(audit))
                audit["targets"].append({"url":checked["url"],"host":checked["host"],"resolved_ips":checked["resolved_ips"]})
                with client.stream("GET",checked["url"]) as resp:
                    self._verify_connected_peer(resp,checked,audit)
                    if resp.status_code in {301,302,303,307,308}:
                        loc=resp.headers.get("location")
                        if not loc:
                            audit["block_reason"]="DISCOVERY_REDIRECT_LOCATION_MISSING"
                            raise DiscoveryNetworkPolicyError("DISCOVERY_REDIRECT_LOCATION_MISSING",dict(audit))
                        if hop >= max_redirects:
                            audit["block_reason"]="DISCOVERY_REDIRECT_LIMIT_EXCEEDED"
                            raise DiscoveryNetworkPolicyError("DISCOVERY_REDIRECT_LIMIT_EXCEEDED",dict(audit))
                        nxt=urljoin(checked["url"],loc)
                        try:
                            nxt_checked=self._validate_url(nxt)
                        except DiscoveryNetworkPolicyError as exc:
                            exc.audit.setdefault("redirect_chain", list(redirect_chain)+[{"from":checked["url"],"to":_safe_url_for_log(nxt),"status":resp.status_code}])
                            raise
                        redirect_chain.append({"from":checked["url"],"to":nxt_checked["url"],"status":resp.status_code})
                        current=nxt_checked["url"]
                        continue
                    if resp.status_code != 200:
                        code=f"DISCOVERY_HTTP_{resp.status_code}"
                        if resp.status_code in TRANSIENT_HTTP:
                            code=f"DISCOVERY_TRANSIENT_HTTP_{resp.status_code}"
                        raise ValueError(code)
                    ctype=(resp.headers.get("content-type") or "").lower()
                    if "html" not in ctype and "xhtml" not in ctype and not (allow_json and "json" in ctype):
                        raise ValueError("DISCOVERY_CONTENT_TYPE_NOT_ALLOWED" if allow_json else "DISCOVERY_CONTENT_TYPE_NOT_HTML")
                    chunks=[]; total=0
                    for chunk in resp.iter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise ValueError("DISCOVERY_HTML_TOO_LARGE")
                        chunks.append(chunk)
                    raw=b"".join(chunks)
                    encoding=resp.encoding or "utf-8"
                    try: html=raw.decode(encoding,errors="replace")
                    except LookupError: html=raw.decode("utf-8",errors="replace")
                    audit["final_url"]=checked["url"]
                    audit["block_reason"]=None
                    audit["final_host"]=checked["host"]
                    audit["final_ips"]=checked["resolved_ips"]
                    return checked["url"],html,total,audit
        audit["block_reason"]="DISCOVERY_REDIRECT_LIMIT_EXCEEDED"
        raise DiscoveryNetworkPolicyError("DISCOVERY_REDIRECT_LIMIT_EXCEEDED",dict(audit))

    def _source_payload(self, seed: dict, hint: dict) -> tuple[dict, str | None, dict]:
        kind = str(hint.get("kind") or "PUBLIC_SOURCE").upper()
        if kind not in DISCOVERY_SOURCE_MAP:
            raise ValueError("DISCOVERY_SOURCE_KIND_UNSUPPORTED")
        source_type = DISCOVERY_SOURCE_MAP[kind]
        if isinstance(hint.get("payload"), dict):
            payload = dict(hint["payload"])
            payload.setdefault("name", seed.get("name"))
            if seed.get("address"):
                payload.setdefault("address", seed.get("address"))
            return payload, hint.get("url"), {"source_type": source_type, "kind": kind, "transport": "PROVIDER_PAYLOAD"}
        url = hint.get("url")
        if not url:
            raise ValueError("DISCOVERY_SOURCE_URL_REQUIRED")
        if kind in {"OFFICIAL_WEBSITE", "GROUP_OFFICIAL"}:
            from .official_hotel_capture import capture_catalog
            payload, capture = capture_catalog(self._fetch_html, url, seed)
            return payload, url, {"source_type": source_type, "kind": kind,
                "transport": "OFFICIAL_STRUCTURED_CATALOG", "capture": capture}
        final, html, byte_size, network_audit = self._fetch_html(url, timeout_seconds=float(hint.get("timeout_seconds", 12.0)))
        payload = _extract_payload(html, final, seed)
        return payload, final, {"source_type": source_type, "kind": kind, "transport": "HTTP_HTML", "byte_size": byte_size, "network_audit": network_audit}

    def _ingest_hint(self, seed: dict, hint: dict, actor: str) -> dict:
        kind = str(hint.get("kind") or "PUBLIC_SOURCE").upper()
        payload, source_url, meta = self._source_payload(seed, hint)
        if not payload.get("name"):
            raise ValueError("DISCOVERY_EXTRACTED_NAME_REQUIRED")
        source_key = hint.get("source_key") or f"discovery:{kind.lower()}:{urlparse(source_url).netloc if source_url else 'payload'}"
        external_id = hint.get("external_hotel_id") or (seed.get("external_ids") or {}).get(source_key) or f"seed:{self._seed_fingerprint(seed)[:24]}"
        rights_status = str(hint.get("rights_status") or DEFAULT_RIGHTS[kind]).upper()
        ingest_payload = {
            "source_key": str(source_key)[:64],
            "source_type": meta["source_type"],
            "external_hotel_id": str(external_id)[:192],
            "source_url": source_url,
            "rights_status": rights_status,
            "confidence_bps": int(hint.get("confidence_bps", 8500 if kind in {"OFFICIAL_WEBSITE", "GROUP_OFFICIAL"} else 6500)),
            "payload": payload,
        }
        result = hotel_autopage_factory_service.ingest(ingest_payload, actor)
        result["discovery"] = {**meta, "source_key": ingest_payload["source_key"], "external_hotel_id": ingest_payload["external_hotel_id"], "media_candidate_count": len(payload.get("media_candidates") or [])}
        return result

    def _job_seed(self, job_id: str) -> dict:
        with SessionLocal() as s:
            rows = s.scalars(select(HotelAutoPageEventRow).where(HotelAutoPageEventRow.event_type == "DISCOVERY_JOB_CREATED").order_by(HotelAutoPageEventRow.created_at.desc())).all()
            for r in rows:
                ev = r.evidence_json or {}
                if ev.get("job_id") == job_id:
                    return ev.get("seed") or {}
        raise ValueError("DISCOVERY_JOB_NOT_FOUND")

    def run_job(self, job_id: str, actor: str = "SYSTEM", *, max_retries: int = 2) -> dict:
        if not isinstance(max_retries,int) or not 0<=max_retries<=3:
            raise ValueError("DISCOVERY_RETRY_LIMIT_3")
        seed = self._job_seed(job_id)
        hints = [x for x in (seed.get("source_hints") or []) if isinstance(x, dict)]
        if not hints:
            raise ValueError("DISCOVERY_SOURCE_HINTS_REQUIRED")
        if len(hints)>16:raise ValueError("DISCOVERY_SOURCE_LIMIT_16")
        with SessionLocal() as s:
            self._event(s, "DISCOVERY_JOB_STARTED", {"job_id": job_id, "source_count": len(hints)}, actor)
            s.commit()
        results, failures = [], []
        hotel_id = None
        for idx, hint in enumerate(hints):
            last_error = None
            for attempt in range(max(0, max_retries) + 1):
                try:
                    item = self._ingest_hint(seed, hint, actor)
                    snapshot = item.get("snapshot") or {}
                    profile = item.get("profile") or {}
                    hotel_id = hotel_id or profile.get("hotel_id") or snapshot.get("canonical_hotel_id")
                    results.append({"index": idx, "attempt": attempt + 1, **item})
                    with SessionLocal() as s:
                        self._event(s, "DISCOVERY_SOURCE_SNAPSHOTTED", {"job_id":job_id,"index":idx,"attempt":attempt+1,"snapshot_id":snapshot.get("content_source_snapshot_id"),"source_url":snapshot.get("source_url"),"source_type":snapshot.get("source_type"),"idempotent":bool(item.get("idempotent")),"network_audit":(item.get("discovery") or {}).get("network_audit")}, actor, hotel_id)
                        s.commit()
                    last_error = None
                    break
                except Exception as exc:
                    last_error = str(exc)
                    retryable = last_error.startswith("DISCOVERY_TRANSIENT_HTTP_")
                    network_audit = exc.audit if isinstance(exc, DiscoveryNetworkPolicyError) else None
                    evidence={"job_id":job_id,"index":idx,"attempt":attempt+1,"source":_safe_hint_for_log(hint),"error":last_error,"retryable":retryable}
                    if network_audit:
                        evidence["network_audit"]=network_audit
                    with SessionLocal() as s:
                        self._event(s, "DISCOVERY_SOURCE_FAILED", evidence, actor, hotel_id)
                        s.commit()
                    if not retryable or attempt >= max_retries:
                        break
                    time.sleep(min(0.25 * (2 ** attempt), 1.0))
            if last_error:
                failures.append({"index":idx,"source":_safe_hint_for_log(hint),"error":last_error})
        state = "COMPLETED" if not failures else ("PARTIAL" if results else "FAILED")
        with SessionLocal() as s:
            self._event(s, "DISCOVERY_JOB_FINISHED", {"job_id": job_id, "state": state, "success_count": len(results), "failure_count": len(failures)}, actor, hotel_id)
            s.commit()
        build_quality = None
        if hotel_id:
            with SessionLocal() as s:
                from go_hotel.db.models import HotelCanonicalProfileRow
                profile = s.get(HotelCanonicalProfileRow, hotel_id)
                if profile: build_quality = hotel_autopage_factory_service.catalog_quality(profile)
        return {"job_id": job_id, "state": state, "stage": "SOURCE_COLLECTION",
                "build_state": "READY" if build_quality and build_quality['passed'] and not failures else "NEEDS_ENRICHMENT",
                "catalog_quality": build_quality, "hotel_id": hotel_id, "success_count": len(results),
                "failure_count": len(failures), "results": results, "failures": failures}

    def retry_job(self, job_id: str, actor: str = "SYSTEM", *, max_retries: int = 2) -> dict:
        with SessionLocal() as s:
            self._event(s, "DISCOVERY_JOB_RETRY_REQUESTED", {"job_id": job_id}, actor)
            s.commit()
        return self.run_job(job_id, actor, max_retries=max_retries)

    def run_batch(self, seeds: list[dict], actor: str = "SYSTEM", *, max_retries: int = 2) -> dict:
        if not isinstance(seeds, list) or not seeds:
            raise ValueError("DISCOVERY_BATCH_SEEDS_REQUIRED")
        if len(seeds)>100:
            raise ValueError("DISCOVERY_BATCH_LIMIT_100")
        if not 0<=max_retries<=3:
            raise ValueError("DISCOVERY_RETRY_LIMIT_3")
        from concurrent.futures import ThreadPoolExecutor
        start=time.monotonic()
        def execute_seed(seed):
            try:
                reg = self.register_seed(seed, actor)
                run = self.run_job(reg["job_id"], actor, max_retries=max_retries)
                return {"registration": reg, "run": run},None
            except Exception as exc:
                return None,{"seed": seed, "error": str(exc)}
        # A fixed bound avoids multiplying the per-job network and DB budgets.
        # map preserves input order; a failure in one hotel does not cancel peers.
        workers=min(4,len(seeds))
        with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='official-capture') as pool:
            outcomes=list(pool.map(execute_seed,seeds))
        jobs=[item for item,error in outcomes if item is not None]
        failures=[error for item,error in outcomes if error is not None]
        ready=sum(1 for x in jobs if x['run'].get('build_state')=='READY')
        return {"job_count": len(jobs), "failure_count": len(failures), "jobs": jobs, "failures": failures,
                "ready_hotels":ready,"needs_enrichment":len(jobs)-ready,"live_replication_accepted":False,
                "max_parallel_hotels":workers,"seconds":round(time.monotonic()-start,4)}

    def job_status(self, job_id: str) -> dict:
        if not job_id:
            raise ValueError("DISCOVERY_JOB_NOT_FOUND")
        with SessionLocal() as s:
            rows = s.scalars(select(HotelAutoPageEventRow).where(HotelAutoPageEventRow.event_type.in_([
                "DISCOVERY_JOB_CREATED", "DISCOVERY_JOB_STARTED", "DISCOVERY_SOURCE_SNAPSHOTTED",
                "DISCOVERY_SOURCE_FAILED", "DISCOVERY_JOB_FINISHED", "DISCOVERY_JOB_RETRY_REQUESTED",
            ])).order_by(HotelAutoPageEventRow.created_at.asc())).all()
            events = [r for r in rows if (r.evidence_json or {}).get("job_id") == job_id]
            if not events:
                raise ValueError("DISCOVERY_JOB_NOT_FOUND")
            state = "PENDING"
            success = failure = 0
            hotel_id = None
            for e in events:
                ev = e.evidence_json or {}
                hotel_id = hotel_id or e.hotel_id
                if e.event_type == "DISCOVERY_JOB_STARTED":
                    state = "RUNNING"
                elif e.event_type == "DISCOVERY_SOURCE_SNAPSHOTTED":
                    success += 1
                elif e.event_type == "DISCOVERY_SOURCE_FAILED" and not ev.get("retryable"):
                    failure += 1
                elif e.event_type == "DISCOVERY_JOB_FINISHED":
                    state = ev.get("state") or state
                    success = int(ev.get("success_count", success))
                    failure = int(ev.get("failure_count", failure))
            return {"job_id": job_id, "state": state, "hotel_id": hotel_id, "success_count": success, "failure_count": failure, "event_count": len(events), "events": [{"event_type": e.event_type, "created_at": e.created_at.isoformat(), "hotel_id": e.hotel_id, "evidence": e.evidence_json} for e in events]}

    def job_snapshots(self, job_id: str) -> dict:
        status = self.job_status(job_id)
        snapshot_ids = []
        for event in status["events"]:
            if event["event_type"] == "DISCOVERY_SOURCE_SNAPSHOTTED":
                sid = (event.get("evidence") or {}).get("snapshot_id")
                if sid:
                    snapshot_ids.append(sid)
        with SessionLocal() as s:
            rows = [s.get(HotelContentSourceSnapshotRow, sid) for sid in dict.fromkeys(snapshot_ids)]
            data = []
            for row in rows:
                if not row:
                    continue
                data.append({
                    "content_source_snapshot_id": row.content_source_snapshot_id,
                    "source_key": row.source_key,
                    "source_type": row.source_type,
                    "external_hotel_id": row.external_hotel_id,
                    "source_url": row.source_url,
                    "rights_status": row.rights_status,
                    "confidence_bps": row.confidence_bps,
                    "payload_hash": row.payload_hash,
                    "canonical_hotel_id": row.canonical_hotel_id,
                    "observed_at": row.observed_at.isoformat(),
                    "created_at": row.created_at.isoformat(),
                    "payload": row.payload_json,
                })
        return {"job_id": job_id, "count": len(data), "snapshots": data}


hotel_discovery_orchestrator_service = HotelDiscoveryOrchestratorService()
