from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from fastapi import Body
from go_hotel.security.deps import consumer_principal, order_admin_principal, optional_consumer_principal
from go_hotel.security.service import Principal
from go_hotel.rail.service import rail_service
from go_hotel.api.idempotency import run_idempotent
from go_hotel.api.refund_confirmation import RefundConfirmation
from go_hotel.services.booking_data_release import release_booking_data
from go_hotel.db.session import SessionLocal
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence

router=APIRouter(tags=["sprint3b-rail"])
class SearchBody(BaseModel):
    origin_station:str="SHA"; destination_station:str="HZH"; travel_date:str="2026-09-01"; currency:str="CNY"
class PrebookBody(BaseModel):
    quantity:int=Field(default=1,ge=1,le=9,strict=True)
class OrderBody(BaseModel):
    prebook_id:str; passengers:list[dict]=Field(default_factory=list); traveler_ids:list[str]=Field(default_factory=list)
class CheckoutBody(BaseModel): payment_method_id:str
class ExternalStateBody(BaseModel):
    state:str; evidence_reference:str; supplier_reference:str|None=None; ticket_numbers:list[str]=Field(default_factory=list); quote_id:str|None=None
class ChangeQuoteBody(BaseModel):
    new_travel_date:str; new_seat_class:str|None=None

def wrap(fn,*args):
    try:return {"data":fn(*args)}
    except ValueError as e:
        msg=str(e)
        if msg=='REFUND_QUOTE_CHANGED_RECONFIRM_REQUIRED':raise HTTPException(409,detail=msg)
        if msg in {'REFUND_ALREADY_PROCESSING','REFUND_LEASE_LOST','RAIL_RESOLUTION_CONFLICT','RAIL_RESOLUTION_ALREADY_PROCESSING','RAIL_RESOLUTION_LEASE_LOST','RAIL_RESOLUTION_QUOTE_ID_REQUIRED','UNPAID_CANCELLATION_NOT_ALLOWED','PAYMENT_ALREADY_STARTED_RECONCILIATION_REQUIRED'}:raise HTTPException(409,detail=msg)
        code=503 if "PROVIDER_TRUTH_REQUIRED" in msg else (422 if any(x in msg for x in ("INVALID","CHANGEABLE","REFUNDABLE","SOLD_OUT","INVENTORY_CHANGED")) else 404); raise HTTPException(code,detail=msg)

@router.post('/v1/rail/search')
def search(body:SearchBody):
    try: items=rail_service.search(**body.model_dump())
    except ValueError as e:
        msg=str(e); raise HTTPException(503 if "PROVIDER_TRUTH_REQUIRED" in msg else 422,detail=msg)
    return {"data":{"items":items,"comparison_basis":["total_price","seat_class","stations","change_refund","total_travel_time"]}}
@router.get('/v1/rail/offers/{offer_id}')
def offer(offer_id:str): return wrap(rail_service.get_offer,offer_id)
@router.post('/v1/rail/offers/{offer_id}/prebook')
def prebook(offer_id:str,body:PrebookBody|None=Body(default=None),p:Principal|None=Depends(optional_consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    quantity=body.quantity if body else 1;account=p.user_id if p else None
    return run_idempotent('RAIL_PREBOOK',idempotency_key,{'account':account,'offer_id':offer_id,'quantity':quantity},lambda:wrap(rail_service.prebook,offer_id,quantity,account))
@router.post('/v1/rail/orders')
def create_order(body:OrderBody,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload={'user_id':p.user_id,**body.model_dump()}
    def execute():
        released=release_booking_data(p.user_id,'RAIL',body.traveler_ids,body.passengers,requester_id=p.user_id)
        response=wrap(rail_service.create_order,p.user_id,body.prebook_id,released['items'],body.traveler_ids)
        if released['release_ids']:
            with SessionLocal.begin() as s:
                append_vertical_evidence(s,'RAIL',response['data']['order_id'],'VAULT_BOOKING_DATA_RELEASED',response['data']['status'],{'release_ids':released['release_ids'],'minimum_necessary':True})
        return response
    return run_idempotent('RAIL_CREATE_ORDER',idempotency_key,payload,execute)
@router.post('/v1/rail/orders/{order_id}/checkout')
def checkout(order_id:str,body:CheckoutBody,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload={'user_id':p.user_id,'order_id':order_id,**body.model_dump()}
    return run_idempotent('RAIL_CHECKOUT',idempotency_key,payload,lambda:wrap(rail_service.checkout,p.user_id,order_id,body.payment_method_id))
@router.get('/v1/rail/orders/{order_id}')
def order(order_id:str,p:Principal=Depends(consumer_principal)): return wrap(rail_service.order,p.user_id,order_id)
@router.get('/v1/rail/trips')
def trips(p:Principal=Depends(consumer_principal)): return {"data":{"items":rail_service.trips(p.user_id)}}
@router.post('/v1/rail/orders/{order_id}/change-quote')
def change_quote(order_id:str,body:ChangeQuoteBody,p:Principal=Depends(consumer_principal)): return wrap(rail_service.change_quote,p.user_id,order_id,body.new_travel_date,body.new_seat_class)
@router.post('/v1/rail/orders/{order_id}/execute-change/{quote_id}')
def execute_change(order_id:str,quote_id:str,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload={'user_id':p.user_id,'order_id':order_id,'quote_id':quote_id}
    return run_idempotent('RAIL_EXECUTE_CHANGE',idempotency_key,payload,lambda:wrap(rail_service.execute_change,p.user_id,order_id,quote_id))
@router.get('/v1/rail/orders/{order_id}/refund-quote')
def refund_quote(order_id:str,p:Principal=Depends(consumer_principal)): return wrap(rail_service.refund_quote,p.user_id,order_id)
@router.post('/v1/rail/orders/{order_id}/refund')
def refund(order_id:str,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload={'user_id':p.user_id,'order_id':order_id}
    return run_idempotent('RAIL_REFUND',idempotency_key,payload,lambda:wrap(rail_service.refund,p.user_id,order_id))

@router.post('/internal/v1/admin/rail/orders/{order_id}/external-state')
def admin_external_state(order_id:str,body:ExternalStateBody,p:Principal=Depends(order_admin_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload={'actor':p.user_id,'order_id':order_id,**body.model_dump()}
    return run_idempotent('RAIL_ADMIN_EXTERNAL_STATE',idempotency_key,payload,lambda:wrap(rail_service.admin_external_state,order_id,body.state,body.evidence_reference,p.user_id,body.supplier_reference,body.ticket_numbers,body.quote_id))

@router.post('/v1/rail/orders/{order_id}/refund-confirmed')
def refund_confirmed(order_id:str,body:RefundConfirmation,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload={'user_id':p.user_id,'order_id':order_id,**body.model_dump()}
    return run_idempotent('RAIL_REFUND_CONFIRMED',idempotency_key,payload,
        lambda:wrap(rail_service.refund,p.user_id,order_id,body.quote_hash))

@router.post('/v1/rail/orders/{order_id}/cancel-unpaid')
def cancel_unpaid(order_id:str,p:Principal=Depends(consumer_principal)):
    from go_hotel.services.vertical_capacity import cancel_unpaid as cancel
    return wrap(cancel,'RAIL',p.user_id,order_id,rail_service._order)
