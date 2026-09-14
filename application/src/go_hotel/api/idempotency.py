from fastapi import HTTPException
from go_hotel.core.config import settings
from go_hotel.repositories.sql import repo
import logging
from uuid import uuid4
from go_hotel.services.mutation_boundary import MutationBoundary

_PROD = {"prod", "production"}
_RECOVERABLE = {'FLIGHT_CHECKOUT', 'FLIGHT_EXECUTE_CHANGE'}
log = logging.getLogger(__name__)


def run_recoverable_idempotent(operation, key, payload, resource_id, fn, recover):
    """Opt-in flight contract; existing generic callback semantics are intact."""
    if operation not in _RECOVERABLE:
        raise ValueError('IDEMPOTENCY_RECOVERY_OPERATION_UNSUPPORTED')
    _require_key(key)
    if not key:
        return fn(None)
    token = uuid4().hex
    try:
        state, rec = repo.claim_idempotency(operation, key, payload)
        if state == 'REPLAY':
            if rec['response_code'] != 200:
                raise ValueError('IDEMPOTENCY_RECONCILIATION_REQUIRED')
            if rec['resource_id'] != resource_id:
                # Pre-upgrade flight routes completed without resource_id.
                # claim_idempotency already checked the complete payload hash
                # (including actor/order/quote); additionally prove the stored
                # response belongs to the same order before replaying it.
                expected = payload.get('order_id') if operation == 'FLIGHT_CHECKOUT' else payload.get('quote_id')
                data = rec.get('response', {}).get('data', {})
                if not (rec['resource_id'] is None and resource_id == expected
                        and isinstance(data, dict) and data.get('order_id') == payload.get('order_id')):
                    raise ValueError('IDEMPOTENCY_RESOURCE_CONFLICT')
            return rec['response']
        mode, response = repo.bind_idempotency_resource(
            operation, key, payload, resource_id, token, new_claim=state == 'CLAIMED')
    except ValueError as exc:
        if str(exc).startswith('IDEMPOTENCY_'):
            raise HTTPException(409, detail={'code': str(exc), 'message': 'Request identity or execution conflicts'}) from exc
        raise
    if mode == 'REPLAY':
        return response
    if mode == 'IN_PROGRESS':
        raise HTTPException(409, detail={'code': 'IDEMPOTENCY_IN_PROGRESS', 'message': 'Execution is active or requires recovery review'})
    boundary = MutationBoundary(recovering=mode == 'RECOVER')
    try:
        response = (recover if boundary.recovering else fn)(boundary)
    except BaseException:
        try:
            repo.finish_recoverable_idempotency(operation, key, payload, resource_id, token,
                'RELEASE' if boundary.proven_no_effect else 'RECOVERY_REQUIRED')
        except Exception:
            # Database/classifier failure never becomes permission to repeat.
            # Do not log request payloads, payment identifiers or raw secrets.
            log.warning('IDEMPOTENCY_FAILURE_RECORDING_UNAVAILABLE operation=%s', operation)
        raise
    try:
        repo.finish_recoverable_idempotency(operation, key, payload, resource_id, token, 'COMPLETE', response)
    except BaseException:
        try:
            repo.finish_recoverable_idempotency(operation, key, payload, resource_id, token, 'RECOVERY_REQUIRED')
        except Exception:
            log.warning('IDEMPOTENCY_COMPLETION_RECOVERY_UNAVAILABLE operation=%s', operation)
        raise
    return response

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
