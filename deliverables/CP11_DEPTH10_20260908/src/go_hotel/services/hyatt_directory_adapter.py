"""Hyatt official directory adapter for autonomous chain-first hotel discovery.

The adapter enumerates hotels only from an official Hyatt destination directory.
It does not infer identities from arbitrary prose. A resumable cursor includes a
snapshot hash so a directory change cannot silently create a mixed inventory.
"""
from __future__ import annotations

import base64
import hashlib
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit

from .chain_hotel_registry import ChainCode, ChainDirectoryAdapter, OfficialPropertySeed


HYATT_CHINA_DIRECTORY = "https://www.hyatt.com/zh-CN/destinations/chinese-mainland"
_PROPERTY_PATH = re.compile(
    r"^/[^/?#]+/(?:[a-z]{2}(?:-[A-Z]{2})?)/([a-z0-9]{5,10})(?:[-/?#]|$)",
    re.IGNORECASE,
)
_GENERIC_LABELS = {
    "view hotel", "hotel", "book now", "立即预订", "查看酒店", "查看设施", "view amenities"
}


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


class _DirectoryLinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a" or self._href is not None:
            return
        values = {str(k).lower(): (v or "") for k, v in attrs}
        href = values.get("href", "").strip()
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, _norm_text(" ".join(self._text))))
            self._href = None
            self._text = []


def _decode_cursor(cursor: str | None) -> dict:
    if not cursor:
        return {"offset": 0, "snapshot_sha256": None}
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii") + b"=" * (-len(cursor) % 4))
        value = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("HYATT_DIRECTORY_CURSOR_INVALID") from exc
    if not isinstance(value, dict) or not isinstance(value.get("offset"), int) or value["offset"] < 0:
        raise ValueError("HYATT_DIRECTORY_CURSOR_INVALID")
    return value


def _encode_cursor(offset: int, snapshot_sha256: str) -> str:
    raw = json.dumps(
        {"offset": int(offset), "snapshot_sha256": snapshot_sha256},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _fetch_result(fetch_page, url: str) -> tuple[str, str]:
    result = fetch_page(url)
    if isinstance(result, str):
        return url, result
    if isinstance(result, tuple) and len(result) >= 2:
        final, html = result[0], result[1]
        if isinstance(final, str) and isinstance(html, str):
            return final, html
    raise ValueError("HYATT_DIRECTORY_FETCH_RESULT_INVALID")


class HyattDirectoryAdapter(ChainDirectoryAdapter):
    chain = ChainCode.HYATT

    def __init__(self, directory_url: str = HYATT_CHINA_DIRECTORY, *, page_size: int = 40):
        if not 1 <= int(page_size) <= 100:
            raise ValueError("HYATT_DIRECTORY_PAGE_SIZE_INVALID")
        self.directory_url = directory_url
        self.page_size = int(page_size)

    def _inventory(self, fetch_page) -> tuple[list[OfficialPropertySeed], str]:
        final, html = _fetch_result(fetch_page, self.directory_url)
        parsed = urlsplit(final)
        if parsed.scheme != "https" or not parsed.hostname or not (
            parsed.hostname == "hyatt.com" or parsed.hostname.endswith(".hyatt.com")
        ):
            raise ValueError("HYATT_DIRECTORY_FINAL_URL_NOT_OFFICIAL")

        snapshot = hashlib.sha256(html.encode("utf-8")).hexdigest()
        parser = _DirectoryLinkParser()
        parser.feed(html)

        by_id: dict[str, dict] = {}
        for href, label in parser.links:
            absolute = urljoin(final, href)
            u = urlsplit(absolute)
            if u.scheme != "https" or not u.hostname or not (
                u.hostname == "hyatt.com" or u.hostname.endswith(".hyatt.com")
            ):
                continue
            match = _PROPERTY_PATH.match(u.path)
            if not match:
                continue
            property_id = match.group(1).upper()
            candidate = _norm_text(label)
            if not candidate or candidate.lower() in _GENERIC_LABELS or len(candidate) < 3:
                continue
            item = by_id.get(property_id)
            if item is None:
                by_id[property_id] = {"name": candidate, "url": absolute.split("#", 1)[0]}
                continue
            # Different human-readable names for the same official Hyatt code are
            # an identity conflict. Do not silently choose one.
            if _norm_text(item["name"]).casefold() != candidate.casefold():
                raise ValueError(f"HYATT_DIRECTORY_PROPERTY_NAME_CONFLICT:{property_id}")

        if not by_id:
            raise ValueError("HYATT_DIRECTORY_NO_PROPERTIES_FOUND")

        seeds = [
            OfficialPropertySeed(
                chain=ChainCode.HYATT,
                official_property_id=property_id,
                name=item["name"],
                property_url=item["url"],
                directory_url=final,
                country_code="CN",
            )
            for property_id, item in sorted(by_id.items())
        ]
        return self.validate(seeds), snapshot

    def enumerate_page(self, fetch_page, cursor: str | None = None):
        state = _decode_cursor(cursor)
        seeds, snapshot = self._inventory(fetch_page)
        expected = state.get("snapshot_sha256")
        if expected and expected != snapshot:
            raise ValueError("HYATT_DIRECTORY_SNAPSHOT_CHANGED")
        offset = state["offset"]
        if offset > len(seeds):
            raise ValueError("HYATT_DIRECTORY_CURSOR_OUT_OF_RANGE")
        page = seeds[offset: offset + self.page_size]
        next_offset = offset + len(page)
        next_cursor = _encode_cursor(next_offset, snapshot) if next_offset < len(seeds) else None
        return page, next_cursor

    def enumerate_all(self, fetch_page, cursor: str | None = None, *, max_properties: int = 1000):
        if not 1 <= int(max_properties) <= 5000:
            raise ValueError("HYATT_DIRECTORY_MAX_PROPERTIES_INVALID")
        out: list[OfficialPropertySeed] = []
        current = cursor
        while True:
            page, current = self.enumerate_page(fetch_page, current)
            out.extend(page)
            if len(out) > max_properties:
                raise ValueError("HYATT_DIRECTORY_PROPERTY_BUDGET_EXCEEDED")
            if current is None:
                return out
