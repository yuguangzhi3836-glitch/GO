from fastapi import HTTPException
from go_hotel.core.config import settings
from go_hotel.repositories.sql import repo

_PROD = {"prod", "production"}

def _require_key(key: str | None) -> None:
    if settings.app_env.strip().lower() in _PROD and not key:
        raise HTTPException(status_code=428, detail={"code":"IDEMPOTENCY_KEY_REQUIRED","message":"Idempotency-Key is required for production mutations"})

def run_idempotent(operation: str, key: str | None, payload: dict, fn, resource_id_fn=None):
    _require_key(key)
    if not key:
        return fn()
    try:
        state, rec = repo.claim_idempotency(operation, key, payload)
    except ValueError as exc:
        if str(exc) == "IDEMPOTENCY_CONFLICT":
            raise HTTPException(status_code=409, detail={"code":"IDEMPOTENCY_CONFLICT","message":"Idempotency key reused with different payload"})
        raise
    if state == "REPLAY":
        return rec["response"]
    if state == "IN_PROGRESS":
        raise HTTPException(status_code=409, detail={"code":"IDEMPOTENCY_IN_PROGRESS","message":"Request with this idempotency key is still in progress"})
    try:
        response = fn()
    except Exception:
        repo.release_idempotency_claim(operation, key, payload)
        raise
    # The mutation already returned successfully. If recording its result fails,
    # retain the durable claim: retry must reconcile, not repeat the side effect.
    rid = resource_id_fn(response) if resource_id_fn else None
    repo.complete_idempotency(operation, key, payload, response, rid)
    return response

async def run_idempotent_async(operation: str, key: str | None, payload: dict, fn, resource_id_fn=None):
    _require_key(key)
    if not key:
        return await fn()
    try:
        state, rec = repo.claim_idempotency(operation, key, payload)
    except ValueError as exc:
        if str(exc) == "IDEMPOTENCY_CONFLICT":
            raise HTTPException(status_code=409, detail={"code":"IDEMPOTENCY_CONFLICT","message":"Idempotency key reused with different payload"})
        raise
    if state == "REPLAY":
        return rec["response"]
    if state == "IN_PROGRESS":
        raise HTTPException(status_code=409, detail={"code":"IDEMPOTENCY_IN_PROGRESS","message":"Request with this idempotency key is still in progress"})
    try:
        response = await fn()
    except Exception:
        repo.release_idempotency_claim(operation, key, payload)
        raise
    # Keep the same fail-closed boundary as the synchronous mutation path.
    rid = resource_id_fn(response) if resource_id_fn else None
    repo.complete_idempotency(operation, key, payload, response, rid)
    return response
