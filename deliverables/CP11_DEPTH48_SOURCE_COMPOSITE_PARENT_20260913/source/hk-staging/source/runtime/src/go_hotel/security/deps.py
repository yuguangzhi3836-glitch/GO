from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from .service import identity_service, Principal
from go_hotel.core.config import settings

bearer=HTTPBearer(auto_error=False)

def current_principal(request:Request, cred:HTTPAuthorizationCredentials|None=Depends(bearer))->Principal:
    token = cred.credentials if cred else (request.cookies.get(settings.access_cookie_name) or request.cookies.get(settings.consumer_access_cookie_name))
    if not token: raise HTTPException(401,detail='AUTHENTICATION_REQUIRED')
    try: p=identity_service.authenticate(token)
    except ValueError as e: raise HTTPException(401,detail=str(e))
    request.state.principal=p
    return p

def require_permission(permission:str):
    def dep(p:Principal=Depends(current_principal)):
        if permission not in p.permissions: raise HTTPException(403,detail='PERMISSION_DENIED')
        return p
    return dep

def supplier_principal(p:Principal=Depends(current_principal)):
    if p.actor_type!='SUPPLIER_USER' or not p.supplier_id: raise HTTPException(403,detail='SUPPLIER_IDENTITY_REQUIRED')
    return p

def admin_principal(p:Principal=Depends(current_principal)):
    if p.actor_type!='GO_ADMIN': raise HTTPException(403,detail='GO_ADMIN_REQUIRED')
    return p

from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OrderRow, RiskEventRuntimeRow

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

def assert_consumer_order(p:Principal, order_id:str):
    with SessionLocal() as s:
        row=s.get(OrderRow,order_id)
        if not row or row.account_id != p.user_id: raise HTTPException(404,detail="ORDER_NOT_FOUND")
        return row
