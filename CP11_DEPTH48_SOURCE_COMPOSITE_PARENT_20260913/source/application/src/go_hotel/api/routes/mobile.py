from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel, Field
from go_hotel.security.service import identity_service
from go_hotel.security.deps import consumer_principal, assert_consumer_order, admin_principal
from go_hotel.consumer.service import consumer_service
from go_hotel.mobile.service import mobile_service
from go_hotel.mobile.orchestration import mobile_engagement
from go_hotel.mobile.push import push_receipt_worker
from go_hotel.fare.service import fare_service
from go_hotel.repositories.sql import repo
from go_hotel.db.session import SessionLocal

router=APIRouter(tags=["sprint2a-mobile"])

class LoginBody(BaseModel): email:str; password:str
class RefreshBody(BaseModel): refresh_token:str
class DeviceBody(BaseModel):
    device_id:str; platform:str; app_version:str|None=None; device_model:str|None=None; os_version:str|None=None; push_provider:str|None=None; push_token:str|None=None; notifications_enabled:bool=False
class DeepLinkBody(BaseModel): url:str
class ChangeQuoteBody(BaseModel): new_check_in:str; new_check_out:str
class ChangeBody(BaseModel):
    change_quote_id:str
    payment_method_id:str|None=None
    quote_hash:str|None=None
    confirmed:bool=Field(default=False,strict=True)
class CancelBody(BaseModel):
    cancellation_quote_id:str
    quote_hash:str|None=None
    confirmed:bool=Field(default=False,strict=True)

from go_hotel.api.schemas import StayCreditConvertRequest, CashFarePaymentRetryRequest
from go_hotel.api.idempotency import run_idempotent_async
from go_hotel.api.routes.fare import _fare_convert, credit_sync

@router.post("/v1/mobile/auth/login")
def mobile_login(body:LoginBody,request:Request):
    try:
        t=consumer_service.login(body.email,body.password,request.client.host if request.client else None,request.headers.get("user-agent"))
        return {"data":{k:v for k,v in t.items() if k!="csrf_token"}}
    except ValueError as e: raise HTTPException(401,detail=str(e))

@router.post("/v1/mobile/auth/refresh")
def mobile_refresh(body:RefreshBody):
    try:
        t=identity_service.refresh(body.refresh_token,allowed_actor_types={'CONSUMER'})
        return {"data":{k:v for k,v in t.items() if k!="csrf_token"}}
    except ValueError as e: raise HTTPException(401,detail=str(e))

@router.post("/v1/mobile/devices")
def register_device(body:DeviceBody,p=Depends(consumer_principal)):
    try: return {"data":mobile_service.register_device(p,**body.model_dump())}
    except ValueError as e: raise HTTPException(422,detail=str(e))

@router.get("/v1/mobile/devices")
def devices(p=Depends(consumer_principal)): return {"data":{"items":mobile_service.devices(p)}}

@router.delete("/v1/mobile/devices/{device_id}")
def unregister(device_id:str,p=Depends(consumer_principal)):
    try: mobile_service.unregister_device(p,device_id); return {"data":{"status":"REVOKED"}}
    except ValueError as e: raise HTTPException(404,detail=str(e))

@router.get("/v1/mobile/notifications")
def notifications(p=Depends(consumer_principal)): return {"data":{"items":mobile_service.notifications(p)}}

@router.post("/v1/mobile/notifications/{notification_id}/read")
def mark_read(notification_id:str,p=Depends(consumer_principal)):
    try: return {"data":mobile_service.mark_read(p,notification_id)}
    except ValueError as e: raise HTTPException(404,detail=str(e))

@router.post("/v1/mobile/deep-links/resolve")
def deep_link(body:DeepLinkBody,p=Depends(consumer_principal)):
    try: return {"data":mobile_service.resolve_deep_link(p,body.url)}
    except ValueError as e: raise HTTPException(422,detail=str(e))

@router.post("/v1/mobile/app-open")
def app_open(p=Depends(consumer_principal)):
    """Called once after authenticated foreground entry. Returns at most one blocking Quick Review intent."""
    return {"data":mobile_engagement.on_app_open(p.user_id)}

# Consumer-owned fare wrappers for native clients. They never trust account_id from the device.
@router.post("/v1/mobile/orders/{order_id}/fare-options")
def mobile_fare_options(order_id:str,p=Depends(consumer_principal)):
    assert_consumer_order(p,order_id)
    return {"data":fare_service.fare_options(order_id)}

@router.post("/v1/mobile/orders/{order_id}/cancellation-quote")
def mobile_cancel_quote(order_id:str,p=Depends(consumer_principal)):
    assert_consumer_order(p,order_id)
    return {"data":fare_service.cancellation_quote(order_id)}

@router.get('/v1/mobile/orders/{order_id}/cancellation-quotes/{quote_id}')
def mobile_existing_cancel_quote(order_id:str,quote_id:str,p=Depends(consumer_principal)):
    """Read the exact displayed quote; never replace customer consent with a new quote."""
    assert_consumer_order(p,order_id)
    from go_hotel.services.catalog_cash_fare import checked_quote, quote_public
    with SessionLocal() as s:
        try:q=checked_quote(s,quote_id)
        except ValueError as exc:raise HTTPException(409,detail=str(exc)) from exc
        if q.order_id!=order_id or q.action!='CANCEL' or q.payload_json.get('account_id')!=p.user_id:
            raise HTTPException(404,detail='OWN_CASH_FARE_QUOTE_REQUIRED')
        return {'data':quote_public(q)}

@router.post("/v1/mobile/orders/{order_id}/cancel")
async def mobile_cancel(order_id:str,body:CancelBody,p=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias="Idempotency-Key")):
    assert_consumer_order(p,order_id)
    from go_hotel.api.schemas import CancellationRequest
    from go_hotel.api.routes.fare import _fare_cancel
    request=CancellationRequest(**body.model_dump())
    payload={**request.model_dump(),'order_id':order_id,'actor':p.user_id}
    return await run_idempotent_async('cancel',idempotency_key,payload,lambda:_fare_cancel(order_id,request,p.user_id),lambda r:order_id)

@router.post("/v1/mobile/orders/{order_id}/change-quote")
async def mobile_change_quote(order_id:str,body:ChangeQuoteBody,p=Depends(consumer_principal)):
    assert_consumer_order(p,order_id)
    return {"data":await fare_service.change_quote(order_id,body.new_check_in,body.new_check_out)}

@router.post("/v1/mobile/orders/{order_id}/change")
async def mobile_change(order_id:str,body:ChangeBody,p=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias="Idempotency-Key")):
    assert_consumer_order(p,order_id)
    token="pm_success"
    if body.payment_method_id:
        try: token=consumer_service.payment_token(p,body.payment_method_id)
        except ValueError as e: raise HTTPException(404,detail=str(e))
    from go_hotel.api.schemas import ChangeRequest
    from go_hotel.api.routes.fare import _fare_change
    request=ChangeRequest(change_quote_id=body.change_quote_id,quote_hash=body.quote_hash,confirmed=body.confirmed,payment_method_token=token)
    payload={**request.model_dump(),'order_id':order_id,'actor':p.user_id}
    return await run_idempotent_async('change',idempotency_key,payload,lambda:_fare_change(order_id,request,p.user_id),lambda r:r['data'].get('change_id'))

@router.get('/v1/mobile/orders/{order_id}/cash-after-sales')
def mobile_cash_fare_status(order_id:str,p=Depends(consumer_principal)):
    from go_hotel.services.catalog_cash_fare import status
    assert_consumer_order(p,order_id)
    return credit_sync(lambda:status(order_id))

@router.post('/v1/mobile/orders/{order_id}/cash-after-sales/{operation_id}/reconcile')
async def mobile_cash_fare_reconcile(order_id:str,operation_id:str,p=Depends(consumer_principal)):
    from go_hotel.services.catalog_cash_fare_execution import reconcile
    from go_hotel.api.routes.fare import credit_async
    assert_consumer_order(p,order_id)
    return await credit_async(lambda:reconcile(order_id,operation_id,p.user_id))

@router.post('/v1/mobile/orders/{order_id}/cash-after-sales/{operation_id}/retry-payment')
def mobile_cash_fare_retry(order_id:str,operation_id:str,body:CashFarePaymentRetryRequest,p=Depends(consumer_principal)):
    from go_hotel.services.catalog_cash_fare_execution import retry_payment
    assert_consumer_order(p,order_id)
    return credit_sync(lambda:retry_payment(order_id,operation_id,body.quote_hash,body.confirmed,body.payment_method_token,p.user_id))

@router.post("/v1/mobile/orders/{order_id}/stay-credit-quote")
def mobile_stay_credit_quote(order_id:str,p=Depends(consumer_principal)):
    assert_consumer_order(p,order_id)
    return credit_sync(lambda:fare_service.stay_credit_quote(order_id))

@router.post("/v1/mobile/orders/{order_id}/convert-to-stay-credit")
async def mobile_convert_stay_credit(order_id:str,body:StayCreditConvertRequest,p=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias="Idempotency-Key")):
    assert_consumer_order(p,order_id)
    payload={**body.model_dump(),'order_id':order_id,'actor':p.user_id}
    return await run_idempotent_async('stay_credit_convert',idempotency_key,payload,
        lambda:_fare_convert(order_id,body,p.user_id),lambda r:r['data'].get('stay_credit_id'))

# Internal worker controls for staging/testing. Production should expose these only to service identities/network policy.
@router.post("/internal/v1/mobile/engagement/ingest")
def ingest_mobile_engagement(): return {"data":{"created":mobile_engagement.ingest_domain_events()}}

@router.post("/internal/v1/mobile/engagement/process-due")
def process_mobile_engagement(): return {"data":{"processed":mobile_engagement.process_due()}}

@router.get("/internal/v1/mobile/engagement/jobs")
def engagement_jobs(user_id:str|None=None): return {"data":{"items":mobile_engagement.jobs(user_id)}}

@router.post("/internal/v1/mobile/push-receipts/process")
def process_push_receipts(p=Depends(admin_principal)):
    return {"data":{"processed":push_receipt_worker.run_once()}}

@router.get("/internal/v1/mobile/notifications/{notification_id}/push-receipts")
def push_receipts(notification_id:str,p=Depends(admin_principal)):
    return {"data":{"items":push_receipt_worker.status(notification_id)}}
