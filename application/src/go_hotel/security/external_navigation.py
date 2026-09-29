from __future__ import annotations

import ipaddress
from urllib.parse import parse_qsl, urlsplit


_SENSITIVE_QUERY_PARTS = (
    'access_token', 'refresh_token', 'password', 'passwd', 'secret', 'session',
    'cookie', 'authorization', 'id_token', 'api_key', 'apikey', 'signature',
)


def validate_external_navigation_url(
    value: object,
    *,
    allowed_custom_schemes: set[str] | None = None,
    reject_sensitive_query: bool = True,
) -> str:
    """Validate a URL returned to a browser/app. GO must never fetch this URL."""
    raw = str(value or '').strip()
    if not raw or len(raw) > 2048 or '\\' in raw or any(ord(ch) < 32 for ch in raw):
        raise ValueError('EXTERNAL_NAVIGATION_URL_INVALID')
    parsed = urlsplit(raw)
    scheme = parsed.scheme.lower()
    allowed = {x.lower() for x in (allowed_custom_schemes or set())}
    if scheme == 'https':
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError('EXTERNAL_NAVIGATION_URL_INVALID')
        host = parsed.hostname.rstrip('.').lower()
        if host == 'localhost' or host.endswith('.localhost'):
            raise ValueError('EXTERNAL_NAVIGATION_URL_INVALID')
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address and not address.is_global:
            raise ValueError('EXTERNAL_NAVIGATION_URL_INVALID')
    elif scheme in allowed:
        if parsed.username is not None or parsed.password is not None:
            raise ValueError('EXTERNAL_NAVIGATION_URL_INVALID')
    else:
        raise ValueError('EXTERNAL_NAVIGATION_URL_INVALID')
    if reject_sensitive_query:
        for key, _ in parse_qsl(parsed.query, keep_blank_values=True) + parse_qsl(parsed.fragment, keep_blank_values=True):
            normalized = key.lower().replace('-', '_')
            if any(part in normalized for part in _SENSITIVE_QUERY_PARTS):
                raise ValueError('EXTERNAL_NAVIGATION_SECRET_FORBIDDEN')
    return raw
