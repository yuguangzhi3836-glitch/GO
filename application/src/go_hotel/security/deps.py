from starlette.concurrency import run_in_threadpool
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from .service import identity_service, Principal
from go_hotel.core.config import settings
from .cookie_scope import cookie_access_token

bearer=HTTPBearer(auto_error=False)

def current_principal(request:Request, cred:HTTPAuthorizationCredentials|None=Depends(bearer))->Principal:
    token = cred.credentials if cred else cookie_access_token(request)
    if not token: raise HTTPException(401,detail='AUTHENTICATION_REQUIRED')
    try:
        p=identity_service.authenticate(
            token, touch_session=request.method not in {'GET', 'HEAD', 'OPTIONS'}
        )
    except ValueError as e: raise HTTPException(401,detail=str(e))
    expected_actor = request.headers.get('X-GO-Actor')
    if expected_actor is not None and expected_actor not in {'CONSUMER', 'SUPPLIER_USER', 'GO_ADMIN'}:
        raise HTTPException(400, detail='INVALID_ACTOR_CONTEXT')
    if expected_actor and expected_actor != p.actor_type:
        raise HTTPException(403, detail='ACTOR_CONTEXT_CHANGED')
    expected_user = request.headers.get('X-GO-User')
    if expected_user and expected_user != p.user_id:
        raise HTTPException(403, detail='ACTOR_CONTEXT_CHANGED')
    request.state.principal=p
    return p

def require_permission(permission:str):
    def dep(p:Principal=Depends(current_principal)):
        if permission not in p.permissions: raise HTTPException(403,detail='PERMISSION_DENIED')
        return p
    return dep

def supplier_account_principal(p:Principal=Depends(current_principal)):
    if p.actor_type!='SUPPLIER_USER' or not p.supplier_id:
        raise HTTPException(403,detail='SUPPLIER_IDENTITY_REQUIRED')
    return p

def supplier_principal(p:Principal=Depends(supplier_account_principal)):
    with SessionLocal() as s:
        onboarding=s.scalar(select(CommercialCaseRow).where(
            CommercialCaseRow.case_type=='SUPPLIER_ONBOARDING',
            CommercialCaseRow.supplier_id==p.supplier_id))
    # No onboarding case means this supplier predates staged onboarding. New account
    # creation writes the case atomically with the identity, so legacy compatibility
    # does not create a bypass for newly registered suppliers.
    if onboarding is None:
        return p
    if onboarding.state not in {'CONTRACT_ACTIVE','BUSINESS_ENABLED'}:
        raise HTTPException(403,detail='SUPPLIER_ONBOARDING_INCOMPLETE')
    return p

def admin_principal(p:Principal=Depends(current_principal)):
    if p.actor_type!='GO_ADMIN': raise HTTPException(403,detail='GO_ADMIN_REQUIRED')
    return p

def order_admin_principal(p:Principal=Depends(admin_principal)):
    if 'admin:orders' not in p.permissions:
        raise HTTPException(403,detail='TICKET_ORDER_OPERATOR_REQUIRED')
    return p

def connector_admin_principal(p:Principal=Depends(admin_principal)):
    if 'admin:connector' not in p.permissions: raise HTTPException(403,detail='CONNECTOR_ADMIN_REQUIRED')
    return p

from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OrderRow, RiskEventRuntimeRow, CommercialCaseRow

def assert_supplier_order(p:Principal, order_id:str):
    with SessionLocal() as s:
        row=s.get(OrderRow,order_id)
        if not row: raise HTTPException(404,detail='ORDER_NOT_FOUND')
        if row.supplier_id != p.supplier_id: raise HTTPException(404,detail='ORDER_NOT_FOUND')
        return row

def assert_supplier_risk(p:Principal, risk_event_id:str):
    with SessionLocal() as s:
        risk=s.get(RiskEventRuntimeRow,risk_event_id)
        if not risk: raise HTTPException(404,detail='RISK_EVENT_NOT_FOUND')
        order=s.get(OrderRow,risk.order_id)
        if not order or order.supplier_id != p.supplier_id: raise HTTPException(404,detail='RISK_EVENT_NOT_FOUND')
        return risk


def consumer_principal(p:Principal=Depends(current_principal)):
    if p.actor_type != "CONSUMER": raise HTTPException(403,detail="CONSUMER_IDENTITY_REQUIRED")
    return p

def optional_consumer_principal(request:Request, cred:HTTPAuthorizationCredentials|None=Depends(bearer)):
    """Public browsing can quote anonymously; supplied credentials must be valid."""
    token=cred.credentials if cred else cookie_access_token(request)
    if not token:return None
    return consumer_principal(current_principal(request,cred))

def assert_consumer_order(p:Principal, order_id:str):
    with SessionLocal() as s:
        row=s.get(OrderRow,order_id)
        if not row or row.account_id != p.user_id: raise HTTPException(404,detail="ORDER_NOT_FOUND")
        return row

def _legacy_order_principal(request: Request, cred: HTTPAuthorizationCredentials | None):
    """Legacy contract fixtures are local-only; signed callers always obey ownership.

    Production never falls back to a caller-supplied account or an anonymous demo ID.
    """
    token = cred.credentials if cred else cookie_access_token(request)
    if not token and settings.app_env.lower() in {'local','test','demo'}:
        return None
    p = current_principal(request, cred)
    if request.url.path.startswith('/internal/'):
        if p.actor_type != 'GO_ADMIN':
            raise HTTPException(403, detail='GO_ADMIN_REQUIRED')
        return p
    if p.actor_type != 'CONSUMER':
        raise HTTPException(403, detail='CONSUMER_IDENTITY_REQUIRED')
    oid = request.path_params.get('order_id')
    if oid:
        assert_consumer_order(p, oid)
    credit_id = request.path_params.get('credit_id')
    if credit_id:
        from go_hotel.db.models import StayCreditRow
        with SessionLocal() as s:
            credit = s.get(StayCreditRow, credit_id)
            if not credit or credit.account_id != p.user_id:
                raise HTTPException(404, detail='STAY_CREDIT_NOT_FOUND')
    return p


async def legacy_order_access(request: Request, cred: HTTPAuthorizationCredentials | None = Depends(bearer)):
    # Authentication and ownership each open/close their Session in this worker.
    # Read the ASGI body on its event loop only after the original access checks.
    p = await run_in_threadpool(_legacy_order_principal, request, cred)
    if p is None:
        return None
    if request.url.path == '/v1/orders' and request.method == 'POST':
        body = await request.json()
        if body.get('account_id') != p.user_id:
            raise HTTPException(403, detail='ORDER_ACCOUNT_MISMATCH')
        if settings.app_env.lower() not in {'local','test','demo'}:
            raise HTTPException(409, detail='USE_VAULT_BACKED_CONSUMER_ORDER_ENTRY')
    return p
