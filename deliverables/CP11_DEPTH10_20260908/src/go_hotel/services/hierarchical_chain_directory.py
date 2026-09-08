"""Resumable hierarchical crawler for official hotel-group directories.

Some official group pages are not a flat list of properties. They expose a country /
region / city tree and hydrate hotel cards deeper in that tree. This crawler keeps a
bounded official-host-only frontier in the cursor so Marriott/Hilton/IHG adapters can
follow their real directory topology without guessing that the root page is complete.
"""
from __future__ import annotations

import base64
import hashlib
from html.parser import HTMLParser
import json
from urllib.parse import urljoin, urlsplit, urlunsplit

from .chain_hotel_registry import ChainDirectoryAdapter, OfficialPropertySeed, POLICIES
from .chain_official_source_contracts import assert_directory_production_ready, validate_contract_document


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.text = []
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a" or self.current is not None:
            return
        href = str(dict(attrs).get("href") or "").strip()
        if href:
            self.current = href; self.text = []
    def handle_data(self, data):
        if self.current is not None:
            self.text.append(data)
    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.current is not None:
            label = " ".join(" ".join(self.text).split())
            self.links.append((self.current, label))
            self.current = None; self.text = []


def _host_allowed(host: str | None, roots: tuple[str, ...]) -> bool:
    host = str(host or "").lower().rstrip(".")
    return bool(host) and any(host == root or host.endswith("." + root) for root in roots)


def _canonical_url(base: str, href: str) -> str | None:
    absolute = urljoin(base, href)
    p = urlsplit(absolute)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        return None
    path = p.path or "/"
    return urlunsplit(("https", p.netloc.lower(), path, p.query, ""))


def _encode(state: dict) -> str:
    raw = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(cursor: str | None, root: str) -> dict:
    if not cursor:
        return {"frontier": [root], "visited": [], "properties": {}, "page_digests": {}, "emitted": 0}
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii") + b"=" * (-len(cursor) % 4))
        state = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("CHAIN_HIERARCHY_CURSOR_INVALID") from exc
    required = {"frontier", "visited", "properties", "page_digests", "emitted"}
    if set(state) != required or not isinstance(state["frontier"], list) or not isinstance(state["visited"], list):
        raise ValueError("CHAIN_HIERARCHY_CURSOR_INVALID")
    return state


class HierarchicalOfficialDirectoryAdapter(ChainDirectoryAdapter):
    max_pages_per_call = 8
    max_total_pages = 2000
    page_size = 50

    def __init__(self, *, page_size: int = 50, max_pages_per_call: int = 8):
        contract = assert_directory_production_ready(self.chain)
        if not 1 <= int(page_size) <= 100:
            raise ValueError("CHAIN_DIRECTORY_PAGE_SIZE_INVALID")
        if not 1 <= int(max_pages_per_call) <= 50:
            raise ValueError("CHAIN_DIRECTORY_PAGE_BUDGET_INVALID")
        self.root_url = contract.directory_url
        self.page_size = int(page_size)
        self.max_pages_per_call = int(max_pages_per_call)

    def classify_official_link(self, url: str, label: str) -> tuple[str, object] | None:
        """Return ('PROPERTY',(id,name)) or ('DIRECTORY',None) for chain-owned URLs."""
        raise NotImplementedError

    def _fetch(self, fetch_page, url: str) -> tuple[str, str]:
        value = fetch_page(url)
        if isinstance(value, str): return url, value
        if isinstance(value, tuple) and len(value) >= 2: return str(value[0]), str(value[1])
        raise ValueError("CHAIN_DIRECTORY_FETCH_RESULT_INVALID")

    def enumerate_page(self, fetch_page, cursor: str | None = None):
        policy = POLICIES[self.chain]
        state = _decode(cursor, self.root_url)
        if len(state["visited"]) > self.max_total_pages:
            raise ValueError("CHAIN_DIRECTORY_TOTAL_PAGE_BUDGET_EXHAUSTED")
        pages = 0
        while state["frontier"] and pages < self.max_pages_per_call:
            url = state["frontier"].pop(0)
            if url in state["visited"]:
                continue
            final, html = self._fetch(fetch_page, url)
            p = urlsplit(final)
            if p.scheme != "https" or not _host_allowed(p.hostname, policy.official_hosts):
                raise ValueError("CHAIN_DIRECTORY_FINAL_URL_NOT_OFFICIAL")
            if not state["visited"]:
                validate_contract_document(self.chain, final_url=final, text=html)
            digest = hashlib.sha256(html.encode()).hexdigest()
            previous = state["page_digests"].get(final)
            if previous and previous != digest:
                raise ValueError(f"CHAIN_DIRECTORY_SNAPSHOT_CHANGED:{self.chain.value}")
            state["page_digests"][final] = digest
            parser = LinkParser(); parser.feed(html)
            for href, label in parser.links:
                absolute = _canonical_url(final, href)
                if not absolute:
                    continue
                ap = urlsplit(absolute)
                if not _host_allowed(ap.hostname, policy.official_hosts):
                    continue
                classified = self.classify_official_link(absolute, label)
                if not classified:
                    continue
                kind, data = classified
                if kind == "DIRECTORY":
                    if absolute not in state["visited"] and absolute not in state["frontier"]:
                        state["frontier"].append(absolute)
                elif kind == "PROPERTY":
                    property_id, name = data
                    property_id = str(property_id).strip().upper(); name = " ".join(str(name or "").split())
                    if not property_id or len(name) < 3:
                        continue
                    existing = state["properties"].get(property_id)
                    if existing and existing["name"].casefold() != name.casefold():
                        raise ValueError(f"CHAIN_DIRECTORY_PROPERTY_NAME_CONFLICT:{self.chain.value}:{property_id}")
                    state["properties"][property_id] = {"name": name, "url": absolute}
            state["visited"].append(final); pages += 1
            if len(state["visited"]) + len(state["frontier"]) > self.max_total_pages:
                raise ValueError("CHAIN_DIRECTORY_TOTAL_PAGE_BUDGET_EXHAUSTED")

        ordered = sorted(state["properties"].items())
        start = int(state["emitted"])
        chunk = ordered[start:start + self.page_size]
        seeds = [OfficialPropertySeed(
            chain=self.chain, official_property_id=pid, name=item["name"],
            property_url=item["url"], directory_url=self.root_url,
            country_code=getattr(self, "country_code", None),
        ) for pid, item in chunk]
        seeds = self.validate(seeds)
        state["emitted"] = start + len(chunk)

        complete = not state["frontier"] and state["emitted"] >= len(ordered)
        if complete:
            return seeds, None
        if not seeds and not state["frontier"]:
            raise ValueError(f"CHAIN_DIRECTORY_NO_PROPERTIES_FOUND:{self.chain.value}")
        return seeds, _encode(state)
