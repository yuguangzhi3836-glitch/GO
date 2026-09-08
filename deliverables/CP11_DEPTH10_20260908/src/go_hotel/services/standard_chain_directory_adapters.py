"""Fail-closed official directory adapters for the next chain wave.

These adapters intentionally accept only official-host links with a stable property
identifier encoded in a recognized URL shape. They never infer a hotel identity
from prose or a search-engine result. If a group's official site changes shape, the
adapter fails closed and must be updated from captured official evidence.
"""
from __future__ import annotations

import base64
import hashlib
from html.parser import HTMLParser
import json
import os
import re
from urllib.parse import urljoin, urlsplit

from .chain_hotel_registry import ChainCode, ChainDirectoryAdapter, OfficialPropertySeed, POLICIES


_GENERIC = {
    "hotel", "view hotel", "view details", "book now", "learn more", "reserve",
    "查看酒店", "查看详情", "立即预订", "预订", "了解更多",
}


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.href = None
        self.text = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a" or self.href is not None:
            return
        values = {str(k).lower(): (v or "") for k, v in attrs}
        href = str(values.get("href") or "").strip()
        if href:
            self.href = href
            self.text = []

    def handle_data(self, data):
        if self.href is not None:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.href is not None:
            self.links.append((self.href, _norm(" ".join(self.text))))
            self.href = None
            self.text = []


def _host_ok(host: str | None, roots: tuple[str, ...]) -> bool:
    host = str(host or "").lower().rstrip(".")
    return bool(host) and any(host == root or host.endswith("." + root) for root in roots)


def _fetch(fetch_page, url: str) -> tuple[str, str]:
    value = fetch_page(url)
    if isinstance(value, str):
        return url, value
    if isinstance(value, tuple) and len(value) >= 2 and isinstance(value[0], str) and isinstance(value[1], str):
        return value[0], value[1]
    raise ValueError("CHAIN_DIRECTORY_FETCH_RESULT_INVALID")


def _decode(cursor: str | None) -> dict:
    if not cursor:
        return {"offset": 0, "snapshot_sha256": None}
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii") + b"=" * (-len(cursor) % 4))
        value = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("CHAIN_DIRECTORY_CURSOR_INVALID") from exc
    if not isinstance(value, dict) or not isinstance(value.get("offset"), int) or value["offset"] < 0:
        raise ValueError("CHAIN_DIRECTORY_CURSOR_INVALID")
    return value


def _encode(offset: int, snapshot: str) -> str:
    raw = json.dumps({"offset": int(offset), "snapshot_sha256": snapshot}, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class StaticOfficialLinkDirectoryAdapter(ChainDirectoryAdapter):
    chain: ChainCode
    default_directory_url: str
    property_patterns: tuple[re.Pattern, ...]
    country_code: str | None = None
    env_directory_url: str | None = None

    def __init__(self, directory_url: str | None = None, *, page_size: int = 50):
        if not 1 <= int(page_size) <= 100:
            raise ValueError("CHAIN_DIRECTORY_PAGE_SIZE_INVALID")
        configured = os.getenv(self.env_directory_url or "") if self.env_directory_url else None
        self.directory_url = directory_url or configured or self.default_directory_url
        self.page_size = int(page_size)

    def _property_id(self, path: str) -> str | None:
        for pattern in self.property_patterns:
            match = pattern.search(path)
            if match:
                groups = [str(x).strip().upper() for x in match.groups() if str(x or "").strip()]
                return "__".join(groups) if groups else str(match.group(1)).upper()
        return None

    def _inventory(self, fetch_page):
        final, html = _fetch(fetch_page, self.directory_url)
        policy = POLICIES[self.chain]
        parsed = urlsplit(final)
        if parsed.scheme != "https" or not _host_ok(parsed.hostname, policy.official_hosts):
            raise ValueError("CHAIN_DIRECTORY_FINAL_URL_NOT_OFFICIAL")
        snapshot = hashlib.sha256(html.encode("utf-8")).hexdigest()
        parser = _Links(); parser.feed(html)
        by_id = {}
        for href, label in parser.links:
            absolute = urljoin(final, href)
            u = urlsplit(absolute)
            if u.scheme != "https" or not _host_ok(u.hostname, policy.official_hosts):
                continue
            property_id = self._property_id(u.path)
            if not property_id:
                continue
            name = _norm(label)
            if not name or name.casefold() in _GENERIC or len(name) < 3:
                continue
            current = by_id.get(property_id)
            if current and current["name"].casefold() != name.casefold():
                raise ValueError(f"CHAIN_DIRECTORY_PROPERTY_NAME_CONFLICT:{self.chain.value}:{property_id}")
            by_id[property_id] = {"name": name, "url": absolute.split("#", 1)[0]}
        if not by_id:
            raise ValueError(f"CHAIN_DIRECTORY_NO_PROPERTIES_FOUND:{self.chain.value}")
        seeds = [OfficialPropertySeed(
            chain=self.chain,
            official_property_id=property_id,
            name=item["name"],
            property_url=item["url"],
            directory_url=final,
            country_code=self.country_code,
        ) for property_id, item in sorted(by_id.items())]
        return self.validate(seeds), snapshot

    def enumerate_page(self, fetch_page, cursor: str | None = None):
        state = _decode(cursor)
        seeds, snapshot = self._inventory(fetch_page)
        if state.get("snapshot_sha256") and state["snapshot_sha256"] != snapshot:
            raise ValueError(f"CHAIN_DIRECTORY_SNAPSHOT_CHANGED:{self.chain.value}")
        offset = state["offset"]
        if offset > len(seeds):
            raise ValueError("CHAIN_DIRECTORY_CURSOR_OUT_OF_RANGE")
        page = seeds[offset:offset + self.page_size]
        next_offset = offset + len(page)
        return page, (_encode(next_offset, snapshot) if next_offset < len(seeds) else None)


class MarriottDirectoryAdapter(StaticOfficialLinkDirectoryAdapter):
    chain = ChainCode.MARRIOTT
    default_directory_url = "https://www.marriott.com/en-us/hotel-search.mi"
    env_directory_url = "GO_MARRIOTT_DIRECTORY_URL"
    property_patterns = (
        re.compile(r"/(?:[a-z]{2}-[a-z]{2}/)?hotels/([a-z0-9]{3,12})-[^/]+(?:/|$)", re.I),
        re.compile(r"/hotels/travel/([a-z0-9]{3,12})(?:/|$)", re.I),
    )


class ShangriLaDirectoryAdapter(StaticOfficialLinkDirectoryAdapter):
    chain = ChainCode.SHANGRI_LA
    default_directory_url = "https://www.shangri-la.com/cn/find-a-hotel/"
    env_directory_url = "GO_SHANGRILA_DIRECTORY_URL"
    # Current official property URLs resolve to /<city>/<property-slug>/ with an
    # optional locale prefix, e.g. /harbin/shangrila/ and /harbin/songbeishangrila/.
    # We derive the durable property identity from the two official path segments.
    property_patterns = (
        re.compile(r"^/(?:cn/|en/)?([a-z0-9-]{2,40})/([a-z0-9-]{3,64})/?$", re.I),
    )
    country_code = "CN"


class HiltonDirectoryAdapter(StaticOfficialLinkDirectoryAdapter):
    chain = ChainCode.HILTON
    default_directory_url = "https://www.hilton.com/en/locations/"
    env_directory_url = "GO_HILTON_DIRECTORY_URL"
    property_patterns = (
        re.compile(r"/(?:[a-z]{2}/)?hotels/([a-z0-9]{4,18})-[^/]+(?:/|$)", re.I),
    )


class IHGDirectoryAdapter(StaticOfficialLinkDirectoryAdapter):
    chain = ChainCode.IHG
    default_directory_url = "https://www.ihg.com/hotels/us/en/reservation"
    env_directory_url = "GO_IHG_DIRECTORY_URL"
    property_patterns = (
        re.compile(r"/hotels/[a-z]{2}/[a-z]{2}/[^/]+/[^/]+/([a-z0-9]{4,14})/hoteldetail(?:/|$)", re.I),
    )


class HWorldDirectoryAdapter(StaticOfficialLinkDirectoryAdapter):
    chain = ChainCode.H_WORLD
    default_directory_url = "https://www.hworld.com/"
    env_directory_url = "GO_HWORLD_DIRECTORY_URL"
    property_patterns = (
        re.compile(r"/(?:hotel|hotels)/([a-z0-9_-]{3,24})(?:/|$)", re.I),
    )
    country_code = "CN"


class AtourDirectoryAdapter(StaticOfficialLinkDirectoryAdapter):
    chain = ChainCode.ATOUR
    default_directory_url = "https://www.atour.com/"
    env_directory_url = "GO_ATOUR_DIRECTORY_URL"
    property_patterns = (
        re.compile(r"/(?:hotel|hotels)/([a-z0-9_-]{3,24})(?:/|$)", re.I),
    )
    country_code = "CN"
