"""Select an authentication namespace, never an identity or permission.

Fixed routes cannot change scope. Shared API routes with both sessions require
an explicit namespace so a stale console cookie cannot shadow the traveler.
Bearer clients remain handled by the existing token/RBAC path.
"""
from fastapi import HTTPException, Request
from go_hotel.core.config import settings


def session_cookie_names(request: Request) -> tuple[str, str, str]:
    path = request.url.path
    fixed = None
    if path == '/v1/consumer' or path.startswith('/v1/consumer/'):
        fixed = 'consumer'
    elif path.startswith(('/bff/', '/internal/', '/v1/supplier/')):
        fixed = 'console'
    requested = request.headers.get('X-GO-Session')
    if requested is not None and requested not in {'consumer', 'console'}:
        raise HTTPException(400, detail='INVALID_SESSION_SCOPE')
    if fixed and requested and fixed != requested:
        raise HTTPException(400, detail='SESSION_SCOPE_ROUTE_MISMATCH')
    scope = fixed or requested
    consumer = (settings.consumer_access_cookie_name, settings.consumer_refresh_cookie_name,
                settings.consumer_csrf_cookie_name)
    console = (settings.access_cookie_name, settings.refresh_cookie_name, settings.csrf_cookie_name)
    if scope is None:
        has_consumer = any(request.cookies.get(n) for n in consumer[:2])
        has_console = any(request.cookies.get(n) for n in console[:2])
        if has_consumer and has_console:
            raise HTTPException(409, detail='SESSION_SCOPE_REQUIRED')
        scope = 'consumer' if has_consumer else 'console'
    return consumer if scope == 'consumer' else console


def cookie_access_token(request: Request) -> str | None:
    return request.cookies.get(session_cookie_names(request)[0])
