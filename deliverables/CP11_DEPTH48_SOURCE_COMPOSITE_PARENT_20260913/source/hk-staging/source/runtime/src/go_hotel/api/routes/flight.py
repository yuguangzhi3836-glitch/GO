from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from go_hotel.security.deps import consumer_principal, admin_principal
from go_hotel.security.service import Principal
from go_hotel.flight.service import flight_service
from go_hotel.api.idempotency import run_idempotent
from go_hotel.services.booking_data_release import release_booking_data
from go_hotel.db.session import SessionLocal
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence

router=APIRouter(tags=["sprint3a-flight"])
class SearchBody(BaseModel):
    origin:str="PVG"; destination:str="NRT"; departure_date:str="2026-09-01"; cabin:str="ECONOMY"; currency:str="CNY"
class OrderBody(BaseModel):
    prebook_id:str; passengers:list[dict]=Field(default_factory=lambda:[{"full_name":"GO Traveler","type":"ADT"}]); traveler_ids:list[str]=Field(default_factory=list); vault_release_ids:list[str]=Field(default_factory=list)
class CheckoutBody(BaseModel): payment_method_id:str
class ExternalStateBody(BaseModel):
    state:str; evidence_reference:str; supplier_reference:str|None=None; ticket_numbers:list[str]=Field(default_factory=list)
class ChangeQuoteBody(BaseModel): new_departure_date:str

def wrap(fn,*args):
    try:return {"data":fn(*args)}
    except ValueError as e: raise HTTPException(422 if "INVALID" in str(e) or "CHANGEABLE" in str(e) or "REFUNDABLE" in str(e) else 404,detail=str(e))

@router.post('/v1/flights/search')
def search(body:SearchBody): return {"data":{"items":flight_service.search(**body.model_dump()),"comparison_basis":["total_price","baggage","change_refund","total_travel_time"]}}
@router.get('/v1/flights/offers/{offer_id}')
def offer(offer_id:str): return wrap(flight_service.get_offer,offer_id)
@router.post('/v1/flights/offers/{offer_id}/prebook')
def prebook(offer_id:str): return wrap(flight_service.prebook,offer_id)
@router.post('/v1/flights/orders')
def create_order(body:OrderBody,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload={'user_id':p.user_id,**body.model_dump()}
    def execute():
        released=release_booking_data(p.user_id,'FLIGHT',body.traveler_ids,body.passengers,vault_release_ids=body.vault_release_ids,requester_id=p.user_id)
        response=wrap(flight_service.create_order,p.user_id,body.prebook_id,released['items'])
        if released['release_ids']:
            with SessionLocal.begin() as s:
                append_vertical_evidence(s,'FLIGHT',response['data']['order_id'],'VAULT_BOOKING_DATA_RELEASED',response['data']['status'],{'traveler_ids':released.get('traveler_ids',body.traveler_ids),'release_ids':released['release_ids'],'purpose':'TRAVEL_BOOKING','minimum_necessary':True})
        return response
    return run_idempotent('FLIGHT_CREATE_ORDER',idempotency_key,payload,execute)
@router.post('/v1/flights/orders/{order_id}/checkout')
def checkout(order_id:str,body:CheckoutBody,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload={'user_id':p.user_id,'order_id':order_id,**body.model_dump()}
    return run_idempotent('FLIGHT_CHECKOUT',idempotency_key,payload,lambda:wrap(flight_service.checkout,p.user_id,order_id,body.payment_method_id))
@router.get('/v1/flights/orders/{order_id}')
def order(order_id:str,p:Principal=Depends(consumer_principal)): return wrap(flight_service.order,p.user_id,order_id)
@router.get('/v1/flights/trips')
def trips(p:Principal=Depends(consumer_principal)): return {"data":{"items":flight_service.trips(p.user_id)}}
@router.post('/v1/flights/orders/{order_id}/change-quote')
def change_quote(order_id:str,body:ChangeQuoteBody,p:Principal=Depends(consumer_principal)): return wrap(flight_service.change_quote,p.user_id,order_id,body.new_departure_date)
@router.post('/v1/flights/orders/{order_id}/execute-change/{quote_id}')
def execute_change(order_id:str,quote_id:str,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload={'user_id':p.user_id,'order_id':order_id,'quote_id':quote_id}
    return run_idempotent('FLIGHT_EXECUTE_CHANGE',idempotency_key,payload,lambda:wrap(flight_service.execute_change,p.user_id,order_id,quote_id))
@router.get('/v1/flights/orders/{order_id}/refund-quote')
def refund_quote(order_id:str,p:Principal=Depends(consumer_principal)): return wrap(flight_service.refund_quote,p.user_id,order_id)
@router.post('/v1/flights/orders/{order_id}/refund')
def refund(order_id:str,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload={'user_id':p.user_id,'order_id':order_id}
    return run_idempotent('FLIGHT_REFUND',idempotency_key,payload,lambda:wrap(flight_service.refund,p.user_id,order_id))

@router.post('/internal/v1/admin/flights/orders/{order_id}/external-state')
def admin_external_state(order_id:str,body:ExternalStateBody,p:Principal=Depends(admin_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload={'actor':p.user_id,'order_id':order_id,**body.model_dump()}
    return run_idempotent('FLIGHT_ADMIN_EXTERNAL_STATE',idempotency_key,payload,lambda:wrap(flight_service.admin_external_state,order_id,body.state,body.evidence_reference,p.user_id,body.supplier_reference,body.ticket_numbers))
