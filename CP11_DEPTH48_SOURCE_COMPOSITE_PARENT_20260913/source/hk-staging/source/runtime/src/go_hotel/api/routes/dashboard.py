from fastapi import APIRouter, Depends, Query
from go_hotel.services.operational import operational_dashboard_service as svc
from go_hotel.security.deps import supplier_principal, require_permission
from go_hotel.security.service import Principal

router=APIRouter()

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
