"""Find the canonical GO hotel an applicant is trying to claim.

The applicant types a name (and optionally a city); the platform matches it
against the canonical catalogue. This is deliberately a *search*, not an
identifier lookup: the human never sees or types a ``hotel_id``, they pick a
result row, and the id stays an opaque option value inside the request payload.

Matching is a case-insensitive substring match on the canonical name (zh / en /
neutral) plus a slug match, with an optional city filter. A name and a city are
handled differently on purpose: the name narrows the query, the city is applied
in Python against the *structured* address, because the SQL view of a nested
address object is escaped JSON text in which a Chinese city name never matches.
Names are also pre-filtered on three spellings (raw, separator-free, longest
token) so a human who types spaces the catalogue does not have still finds the
hotel; the final answer always comes from the squashed-string comparison, so a
wider pre-filter can only add rows to reject, never change a match.

``pg_trgm`` GIN indexes (migration 0149) are what make that substring filter cheap
on PostgreSQL; the index expression is exactly the expression compiled here, which
the migration evidence verifies with EXPLAIN.

Ranking is computed in Python and is therefore identical on PostgreSQL and on the
SQLite correctness fixture: an index changes speed, never answer order.
"""
from __future__ import annotations

import re
import unicodedata

from sqlalchemy import or_, select

from go_hotel.db.models import HotelCanonicalProfileRow
from go_hotel.services import catalog_scope

MAX_RESULTS = 20
DEFAULT_LIMIT = 10
# Below this a "search" is a guess: a single CJK character matches almost anything.
MIN_QUERY_LENGTH = 2
CANDIDATE_FACTOR = 10
MAX_CANDIDATES = 200

SEARCH_QUERY_REQUIRED = "HOTEL_SEARCH_QUERY_REQUIRED"
HOTEL_NOT_FOUND = "HOTEL_NOT_FOUND"

# The applicant should know, before investing effort in a claim, that the hotel is
# already taken. Nothing about *who* holds it is exposed.
CLAIM_STATE_AVAILABLE = "AVAILABLE"
CLAIM_STATE_IN_PROGRESS = "IN_PROGRESS"
CLAIM_STATE_CLAIMED = "CLAIMED"


def _norm(value) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip().lower()


def _squash(value) -> str:
    """Drop everything that is not a letter or a digit (CJK included).

    "Hilton 北京  王府井店" and "hilton北京王府井店" must compare equal: the
    difference is punctuation a human would never notice.
    """
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", _norm(value))


def _like(value: str) -> str:
    """Escape LIKE metacharacters so a typed ``%`` cannot widen the search."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _patterns(value) -> list[str]:
    """Candidate substrings that could occur inside the stored name.

    A human types spaces the catalogue does not have ("测试 大酒店" for
    "测试大酒店") and the catalogue uses spacing a human does not type ("Hilton
    Beijing" for "hiltonbeijing"). Trying the raw form, the separator-free form and
    the longest single token covers both directions.

    This is a *recall* pre-filter only. The answer comes from :func:`_score`,
    which compares squashed strings, so a wider pre-filter can never produce a
    wrong match — only (at worst) more rows to reject.
    """
    raw = _norm(value)
    if not raw:
        return []
    tokens = sorted(re.split(r"\s+", raw), key=len, reverse=True)
    out: list[str] = []
    for candidate in (raw, _squash(raw), tokens[0] if tokens else ""):
        candidate = candidate.strip()
        if candidate and candidate not in out:
            out.append(candidate)
    return out[:3]


def address_text(value) -> str:
    """Canonical addresses are either a string or a structured object."""
    if isinstance(value, dict):
        parts = [
            value.get("formatted"), value.get("province"), value.get("city"),
            value.get("district"), value.get("street"), value.get("address"),
        ]
        return " ".join(str(p) for p in parts if p)
    return str(value or "")


def display_name(canonical: dict) -> str:
    return str(
        canonical.get("name") or canonical.get("name_zh") or canonical.get("name_en") or ""
    ).strip()


def _city_of(canonical: dict) -> str:
    address = canonical.get("address")
    if isinstance(address, dict):
        for key in ("city", "district", "province"):
            if address.get(key):
                return str(address[key]).strip()
        return ""
    return ""


def _claim_state(profile) -> str:
    if profile.go_direct_state in {"GO_DIRECT_VERIFIED", "GO_DIRECT_LIVE"}:
        return CLAIM_STATE_CLAIMED
    if profile.go_direct_state == "REGISTRATION_PENDING":
        return CLAIM_STATE_IN_PROGRESS
    return CLAIM_STATE_AVAILABLE


def _score(profile, query_squash: str, city_squash: str) -> int:
    """Higher is a better match; 0 means "not a match at all"."""
    canonical = profile.canonical_json or {}
    names = [n for n in (
        _squash(canonical.get("name")),
        _squash(canonical.get("name_zh")),
        _squash(canonical.get("name_en")),
    ) if n]
    slug = _squash(profile.slug)
    address = _squash(address_text(canonical.get("address")))
    score = 0
    if query_squash:
        if query_squash in names:
            score = 1000
        else:
            for name in names:
                if name.startswith(query_squash):
                    score = max(score, 800)
            for name in names:
                if query_squash in name:
                    score = max(score, 600)
            if query_squash in slug:
                score = max(score, 400)
    if city_squash:
        if city_squash not in address and city_squash not in slug:
            return 0
        if not query_squash:
            score = 100
    return score


def serialize_candidate(profile) -> dict:
    canonical = profile.canonical_json or {}
    return {
        # Opaque option value. The client must never render it to the human.
        "hotel_id": profile.hotel_id,
        "name": display_name(canonical) or "未命名酒店",
        "city": _city_of(canonical),
        "address": address_text(canonical.get("address")),
        "brand": canonical.get("brand"),
        "page_state": profile.page_state,
        "claim_state": _claim_state(profile),
    }


def search(session, *, query: str | None = None, city: str | None = None,
           limit: int = DEFAULT_LIMIT) -> list[dict]:
    query_squash = _squash(query)
    city_squash = _squash(city)
    if len(query_squash) < MIN_QUERY_LENGTH and len(city_squash) < MIN_QUERY_LENGTH:
        raise ValueError(SEARCH_QUERY_REQUIRED)
    return _ranked(session, query=query, city=city, limit=limit)


def find_exact(session, name: str, city: str | None = None, limit: int = 5) -> list[dict]:
    """Canonical hotels whose name squashes *equal* to ``name``.

    Used to stop a "this hotel does not exist yet" claim from silently creating a
    duplicate canonical hotel for a hotel that is already in the catalogue. Only an
    exact (punctuation- and case-insensitive) name match counts; a fuzzy hit is
    not enough to refuse a new hotel, or an unrelated hotel with a similar name
    would block a legitimate submission.
    """
    target = _squash(name)
    if not target:
        return []
    matches = [
        candidate for candidate in _ranked(session, query=name, city=city, limit=MAX_RESULTS)
        if _squash(candidate["name"]) == target
    ]
    return matches[:limit]


def _ranked(session, *, query: str | None, city: str | None, limit: int) -> list[dict]:
    query_squash = _squash(query)
    city_squash = _squash(city)
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_RESULTS))

    # ``as_string()`` is what makes the JSON path a *text* element: it compiles to
    # ``canonical_json->>'name'`` on PostgreSQL (the exact indexed expression) and
    # to ``json_extract(...)`` on SQLite, while keeping ILIKE a legal operator.
    name_neutral = HotelCanonicalProfileRow.canonical_json["name"].as_string()
    name_zh = HotelCanonicalProfileRow.canonical_json["name_zh"].as_string()
    name_en = HotelCanonicalProfileRow.canonical_json["name_en"].as_string()
    address = HotelCanonicalProfileRow.canonical_json["address"].as_string()

    filters = []
    name_columns = (name_neutral, name_zh, name_en, HotelCanonicalProfileRow.slug)
    query_patterns = _patterns(query)
    if query_patterns:
        filters.append(or_(*[
            column.ilike(f"%{_like(pattern)}%", escape="\\")
            for pattern in query_patterns
            for column in name_columns
        ]))
    city_patterns = _patterns(city)
    if city_patterns and not query_patterns:
        # With a name present the name filter is already selective, and the city is
        # applied in Python against the *structured* address. That matters: an
        # address stored as a nested object comes back from ``->>'address'`` as
        # escaped JSON text, so a SQL ``LIKE '%哈尔滨市%'`` would silently miss every
        # such hotel. Without a name there is nothing else to narrow on, so the
        # address column is used here and that limitation is documented.
        filters.append(or_(*[
            column.ilike(f"%{_like(pattern)}%", escape="\\")
            for pattern in city_patterns
            for column in (address, HotelCanonicalProfileRow.slug)
        ]))
    if not filters:
        return []

    statement = (
        select(HotelCanonicalProfileRow)
        .where(*filters)
        .order_by(HotelCanonicalProfileRow.completeness_bps.desc(), HotelCanonicalProfileRow.hotel_id)
        .limit(min(MAX_CANDIDATES, limit * CANDIDATE_FACTOR))
    )
    scored = []
    for profile in session.scalars(statement).all():
        if not catalog_scope.visible_hotel(session, profile.hotel_id):
            continue
        score = _score(profile, query_squash, city_squash)
        if score <= 0:
            continue
        scored.append((-score, -int(profile.completeness_bps or 0), profile.hotel_id, profile))
    scored.sort(key=lambda item: item[:3])
    return [serialize_candidate(profile) for *_, profile in scored[:limit]]


def resolve_visible(session, hotel_id: str):
    """A claim may only point at a canonical hotel the platform can still see."""
    profile = session.get(HotelCanonicalProfileRow, hotel_id)
    if profile is None:
        raise ValueError(HOTEL_NOT_FOUND)
    catalog_scope.require_hotel(session, profile.hotel_id)
    return profile
