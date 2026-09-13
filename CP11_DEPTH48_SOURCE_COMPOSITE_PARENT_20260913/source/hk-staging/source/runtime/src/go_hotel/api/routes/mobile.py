from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel
from go_hotel.security.service import identity_service
from go_hotel.security.deps import consumer_principal, assert_consumer_order, admin_principal
from go_hotel.consumer.service import consumer_service
from go_hotel.mobile.service import mobile_service
from go_hotel.mobile.orchestration import mobile_engagement
from go_hotel.mobile.push import push_receipt_worker
from go_hotel.fare.service import fare_service
from go_hotel.repositories.sql import repo

router=APIRouter(tags=["sprint2a-mobile"])

class LoginBody(BaseModel): email:str; password:str
class RefreshBody(BaseModel): refresh_token:str
class DeviceBody(BaseModel):
    device_id:str; platform:str; app_version:str|None=None; device_model:str|None=None; os_version:str|None=None; push_provider:str|None=None; push_token:str|None=None; notifications_enabled:bool=False
class DeepLinkBody(BaseModel): url:str
class ChangeQuoteBody(BaseModel): new_check_in:str; new_check_out:str
class ChangeBody(BaseModel): change_quote_id:str; payment_method_id:str|None=None
class CancelBody(BaseModel): cancellation_quote_id:str

@router.post("/v1/mobile/auth/login")
def mobile_login(body:LoginBody,request:Request):
    try:
        t=consumer_service.login(body.email,body.password,request.client.host if request.client else None,request.headers.get("user-agent"))
        return {"data":{k:v for k,v in t.items() if k!="csrf_token"}}
    except ValueError as e: raise HTTPException(401,detail=str(e))

@router.post("/v1/mobile/auth/refresh")
def mobile_refresh(body:RefreshBody):
    try:
        t=identity_service.refresh(body.refresh_token); p=identity_service.authenticate(t["access_token"])
        if p.actor_type!="CONSUMER": raise ValueError("CONSUMER_IDENTITY_REQUIRED")
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

@router.post("/v1/mobile/orders/{order_id}/cancel")
async def mobile_cancel(order_id:str,body:CancelBody,p=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias="Idempotency-Key")):
    assert_consumer_order(p,order_id)
    return {"data":await fare_service.cancel(order_id,body.cancellation_quote_id)}

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
    return {"data":await fare_service.change(order_id,body.change_quote_id,token)}

@router.post("/v1/mobile/orders/{order_id}/stay-credit-quote")
def mobile_stay_credit_quote(order_id:str,p=Depends(consumer_principal)):
    assert_consumer_order(p,order_id)
    return {"data":fare_service.stay_credit_quote(order_id)}

@router.post("/v1/mobile/orders/{order_id}/convert-to-stay-credit")
async def mobile_convert_stay_credit(order_id:str,p=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias="Idempotency-Key")):
    assert_consumer_order(p,order_id)
    return {"data":await fare_service.convert_to_stay_credit(order_id)}

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
