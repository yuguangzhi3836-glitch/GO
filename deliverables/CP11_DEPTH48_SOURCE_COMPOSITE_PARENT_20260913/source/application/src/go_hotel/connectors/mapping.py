from __future__ import annotations
from dataclasses import dataclass
from typing import Any

class MappingError(ValueError):
    pass

def get_path(data: Any, path: str, default: Any = None) -> Any:
    """Minimal dot-path mapper with [] list expansion marker.

    This intentionally avoids assuming any supplier schema. Mapping paths are supplied by
    provider configuration derived from the provider's contracted API specification.
    """
    if not path:
        return data
    cur = data
    for token in path.split('.'):
        if token.endswith('[]'):
            key = token[:-2]
            cur = cur.get(key, []) if isinstance(cur, dict) else []
            if not isinstance(cur, list):
                return default
        else:
            if isinstance(cur, dict):
                if token not in cur:
                    return default
                cur = cur[token]
            else:
                return default
    return cur

@dataclass(frozen=True)
class CanonicalOfferMapping:
    offers_path: str
    external_property_id: str
    external_room_id: str
    external_rate_id: str
    amount_minor: str
    currency: str
    check_in: str
    check_out: str
    fare_rule_id: str | None = None
    expires_at: str | None = None

@dataclass(frozen=True)
class BookingMapping:
    confirmation_no: str
    status: str | None = None

@dataclass(frozen=True)
class PrebookMapping:
    external_prebook_id: str | None = None
    amount_minor: str | None = None
    currency: str | None = None
