from fastapi import APIRouter, Depends, Query
from go_hotel.services.operational import operational_dashboard_service as svc
from go_hotel.security.deps import supplier_principal, require_permission
from go_hotel.security.service import Principal

router=APIRouter()

# Read-only cross-vertical views. Tenant identifiers are never client inputs.
from fastapi import HTTPException
from go_hotel.security.deps import consumer_principal
from go_hotel.services import transaction_order_view

def transaction_snapshot(vertical, order_id, **scope):
    try:
        return {'data': transaction_order_view.snapshot(vertical, order_id, **scope)}
    except ValueError:
        raise HTTPException(404, detail='ORDER_NOT_FOUND')

@router.get('/v1/supplier/transaction-orders')
def supplier_transaction_orders(limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),p:Principal=Depends(supplier_principal)):
    return {'data': transaction_order_view.supplier_orders(p.supplier_id, limit, offset)}

@router.get('/v1/supplier/transaction-orders/{vertical}/{order_id}')
def supplier_transaction_order(vertical:str,order_id:str,p:Principal=Depends(supplier_principal)):
    return transaction_snapshot(vertical, order_id, supplier_id=p.supplier_id)

@router.get('/v1/consumer/transaction-orders/{vertical}/{order_id}')
def consumer_transaction_order(vertical:str,order_id:str,p:Principal=Depends(consumer_principal)):
    return transaction_snapshot(vertical, order_id, account_id=p.user_id)

@router.get('/internal/v1/admin/transaction-orders/{vertical}/{order_id}')
def admin_transaction_order(vertical:str,order_id:str,p:Principal=Depends(require_permission('admin:finance'))):
    return transaction_snapshot(vertical, order_id, admin=True)

# Supplier Console: tenant always comes from authenticated identity; frontend supplier_id is not accepted.
@router.get('/v1/supplier/dashboard')
def supplier_dashboard(p:Principal=Depends(supplier_principal)): return {'data':svc.supplier_dashboard(p.supplier_id)}
@router.get('/v1/supplier/orders')
def supplier_orders(status:str|None=None,limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),p:Principal=Depends(supplier_principal)): return {'data':svc.supplier_orders(p.supplier_id,status,limit,offset)}
@router.get('/v1/supplier/refunds')
def supplier_refunds(status:str|None=None,limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),p:Principal=Depends(supplier_principal)): return {'data':svc.supplier_refunds(p.supplier_id,status,limit,offset)}
@router.get('/v1/supplier/stay-credits')
def supplier_credits(status:str|None=None,limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),p:Principal=Depends(supplier_principal)): return {'data':svc.supplier_stay_credits(p.supplier_id,status,limit,offset)}
@router.get('/v1/supplier/liabilities')
def supplier_liabilities(status:str|None=None,limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),p:Principal=Depends(supplier_principal)): return {'data':svc.supplier_liabilities(p.supplier_id,status,limit,offset)}
@router.get('/v1/supplier/risk-cases')
def supplier_risks(status:str|None=None,limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),p:Principal=Depends(supplier_principal)): return {'data':svc.supplier_risk_cases(p.supplier_id,status,limit,offset)}
@router.get('/v1/supplier/judgments')
def supplier_judgments(limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),p:Principal=Depends(supplier_principal)): return {'data':svc.supplier_judgments(p.supplier_id,limit,offset)}
@router.get('/v1/supplier/connectors')
def supplier_connectors(p:Principal=Depends(supplier_principal)): return {'data':svc.supplier_connectors(p.supplier_id)}

# GO Admin operational API: permission-separated read planes.
@router.get('/internal/v1/admin/dashboard')
def admin_dashboard(p:Principal=Depends(require_permission('admin:read'))): return {'data':svc.admin_dashboard()}
@router.get('/internal/v1/admin/queues')
def admin_queues(limit:int=Query(50,ge=1,le=200),p:Principal=Depends(require_permission('admin:read'))): return {'data':svc.admin_queues(limit)}
@router.get('/internal/v1/admin/orders')
def admin_orders(status:str|None=None,supplier_id:str|None=None,limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),p:Principal=Depends(require_permission('admin:orders'))): return {'data':svc.admin_orders(status,supplier_id,limit,offset)}
@router.get('/internal/v1/admin/refunds')
def admin_refunds(status:str|None=None,limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),p:Principal=Depends(require_permission('admin:finance'))): return {'data':svc.admin_refunds(status,limit,offset)}
@router.get('/internal/v1/admin/liabilities')
def admin_liabilities(status:str|None=None,limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),p:Principal=Depends(require_permission('admin:finance'))): return {'data':svc.admin_liabilities(status,limit,offset)}
@router.get('/internal/v1/admin/risk-cases')
def admin_risks(status:str|None=None,limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),p:Principal=Depends(require_permission('admin:trust'))): return {'data':svc.admin_risks(status,limit,offset)}
@router.get('/internal/v1/admin/judgments')
def admin_judgments(status:str|None=None,limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0),p:Principal=Depends(require_permission('admin:trust'))): return {'data':svc.admin_judgments(status,limit,offset)}
@router.get('/internal/v1/admin/connectors')
def admin_connectors(p:Principal=Depends(require_permission('admin:connector'))): return {'data':svc.admin_connectors()}
@router.get('/internal/v1/admin/settlement')
def admin_settlement(p:Principal=Depends(require_permission('admin:finance'))): return {'data':svc.admin_settlement()}

# Shared workflow; supplier scope is resolved by the same verified transaction binding.
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from go_hotel.security.deps import admin_principal
from go_hotel.services import ticket_operations

class TicketReceipt(BaseModel):
    model_config=ConfigDict(extra='forbid')
    state:Literal['TICKETED','FAILED','UNKNOWN_EXTERNAL_STATE']
    evidence_reference:str=Field(min_length=1,max_length=256)
    supplier_reference:str|None=Field(default=None,max_length=64)
    ticket_numbers:list[str]|None=Field(default=None,max_length=54)
    quote_id:str|None=Field(default=None,max_length=64)

class TicketCommand(BaseModel):
    model_config=ConfigDict(extra='forbid')
    command_id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    expected_revision:int=Field(strict=True,ge=0)
    action:Literal['REGISTER','CLAIM','RECEIPT','APPLY','VERIFY','FOLLOW_UP']
    note:str=Field(min_length=1,max_length=1000)
    receipt:TicketReceipt|None=None


def ticket_call(fn,*args):
    try:return {'data':fn(*args)}
    except ValueError as e:
        code=str(e)
        raise HTTPException(404 if code=='TICKET_ORDER_NOT_FOUND' else 403 if 'DENIED' in code else 409,detail=code)

@router.get('/v1/supplier/ticket-operations/{vertical}/{order_id}')
def supplier_ticket_operations(vertical:str,order_id:str,p:Principal=Depends(supplier_principal)):
    return ticket_call(ticket_operations.view,vertical,order_id,p)

@router.post('/v1/supplier/ticket-operations/{vertical}/{order_id}')
def supplier_ticket_command(vertical:str,order_id:str,b:TicketCommand,p:Principal=Depends(supplier_principal)):
    return ticket_call(ticket_operations.command,vertical,order_id,p,b.model_dump(exclude_none=True))

@router.get('/internal/v1/admin/ticket-operations/{vertical}/{order_id}')
def admin_ticket_operations(vertical:str,order_id:str,p:Principal=Depends(admin_principal)):
    return ticket_call(ticket_operations.view,vertical,order_id,p)

@router.post('/internal/v1/admin/ticket-operations/{vertical}/{order_id}')
def admin_ticket_command(vertical:str,order_id:str,b:TicketCommand,p:Principal=Depends(admin_principal)):
    return ticket_call(ticket_operations.apply if b.action=='APPLY' else ticket_operations.command,vertical,order_id,p,b.model_dump(exclude_none=True))
