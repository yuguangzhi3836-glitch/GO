from fastapi import APIRouter, Depends, HTTPException, Header, Body
from pydantic import BaseModel, Field, ConfigDict
from go_hotel.security.deps import consumer_principal, admin_principal
from go_hotel.security.service import Principal
from go_hotel.flight.service import flight_service
from go_hotel.flight.journeys import JourneySearch, JourneyCompose, search_journey, compose_journey
from go_hotel.flight.airports import AirportResolutionError, resolve_airport
from go_hotel.api.idempotency import run_idempotent, run_recoverable_idempotent
from go_hotel.api.refund_confirmation import RefundConfirmation
from go_hotel.services.booking_data_release import release_booking_data
from go_hotel.db.session import SessionLocal
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence

router=APIRouter(tags=["sprint3a-flight"])
class SearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin:str="PVG"; destination:str="NRT"; departure_date:str="2026-09-01"; cabin:str="ECONOMY"; currency:str="CNY"
    adults:int=Field(default=1,strict=True,ge=1,le=9)
class OrderBody(BaseModel):
    prebook_id:str; passengers:list[dict]=Field(default_factory=list); traveler_ids:list[str]=Field(default_factory=list)
class CheckoutBody(BaseModel): payment_method_id:str
class ExternalStateBody(BaseModel):
    state:str; evidence_reference:str; supplier_reference:str|None=None; ticket_numbers:list[str]=Field(default_factory=list); quote_id:str|None=None
class LegChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    leg_index:int=Field(strict=True,ge=0,le=5)
    new_departure_date:str
class ChangeQuoteBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    new_departure_date:str|None=None
    leg_index:int|None=Field(default=None,strict=True,ge=0,le=5)
    changes:list[LegChange]|None=Field(default=None,min_length=1,max_length=6)
class ChangeConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    quote_hash:str=Field(pattern=r'^[0-9a-f]{64}$')
    expected_total_due_minor:int=Field(strict=True,ge=0)
    currency:str
    confirmed:bool=Field(strict=True)

def wrap(fn,*args):
    try:return {"data":fn(*args)}
    except ValueError as e:
        if str(e) in {'FLIGHT_PREBOOK_CONFLICT','REFUND_QUOTE_CHANGED_RECONFIRM_REQUIRED','REFUND_HISTORICAL_CONSENT_UNAVAILABLE','REFUND_OPERATION_INTEGRITY_INVALID'}:
            raise HTTPException(409,detail=str(e))
        if str(e).startswith('FLIGHT_CHANGE_') and ('REQUIRED' in str(e) or 'REQUOTE' in str(e)) or str(e).startswith('FLIGHT_RESOLUTION_'):
            raise HTTPException(409,detail=str(e))
        raise HTTPException(422 if "INVALID" in str(e) or "CHANGEABLE" in str(e) or "REFUNDABLE" in str(e) else 404,detail=str(e))

@router.post('/v1/flights/search')
def search(body:SearchBody):
    try:
        origin = resolve_airport(body.origin)
        destination = resolve_airport(body.destination)
    except AirportResolutionError as exc:
        status = 409 if exc.code == 'AIRPORT_AMBIGUOUS' else 422
        raise HTTPException(status, detail={
            'code': exc.code, 'query': exc.query, 'candidates': list(exc.candidates),
        }) from exc
    if origin['iata'] == destination['iata']:
        raise HTTPException(422, detail={'code': 'AIRPORTS_MUST_DIFFER'})
    criteria = body.model_dump() | {
        'origin': origin['iata'], 'destination': destination['iata'],
    }
    return {'data': {
        'items': flight_service.search(**criteria),
        'resolved_airports': {'origin': origin, 'destination': destination},
        'comparison_basis': ['total_price', 'baggage', 'change_refund', 'total_travel_time'],
    }}
@router.post('/v1/flights/journeys/search')
def journey_search(body: JourneySearch): return wrap(search_journey, body)
@router.post('/v1/flights/journeys/compose')
def journey_compose(body: JourneyCompose): return wrap(compose_journey, body)

@router.get('/v1/flights/offers/{offer_id}')
def offer(offer_id:str): return wrap(flight_service.get_offer,offer_id)
@router.post('/v1/flights/offers/{offer_id}/prebook')
def prebook(offer_id:str): return wrap(flight_service.prebook,offer_id)
@router.post('/v1/flights/orders')
def create_order(body:OrderBody,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload={'user_id':p.user_id,**body.model_dump()}
    def execute():
        try:released=release_booking_data(p.user_id,'FLIGHT',body.traveler_ids,body.passengers,requester_id=p.user_id)
        except ValueError as exc:raise HTTPException(409,detail=str(exc)) from exc
        response=wrap(flight_service.create_order,p.user_id,body.prebook_id,released['items'])
        if released['release_ids']:
            with SessionLocal.begin() as s:
                append_vertical_evidence(s,'FLIGHT',response['data']['order_id'],'VAULT_BOOKING_DATA_RELEASED',response['data']['status'],{'release_ids':released['release_ids'],'minimum_necessary':True})
        return response
    return run_idempotent('FLIGHT_CREATE_ORDER',idempotency_key,payload,execute)
@router.post('/v1/flights/orders/{order_id}/checkout')
def checkout(order_id:str,body:CheckoutBody,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload={'user_id':p.user_id,'order_id':order_id,**body.model_dump()}
    return run_recoverable_idempotent('FLIGHT_CHECKOUT',idempotency_key,payload,order_id,
        lambda boundary:wrap(flight_service.checkout,p.user_id,order_id,body.payment_method_id,boundary),
        lambda boundary:wrap(flight_service.recover_checkout,p.user_id,order_id,body.payment_method_id,boundary))
@router.get('/v1/flights/orders/{order_id}')
def order(order_id:str,p:Principal=Depends(consumer_principal)): return wrap(flight_service.order,p.user_id,order_id)
@router.get('/v1/flights/trips')
def trips(p:Principal=Depends(consumer_principal)): return {"data":{"items":flight_service.trips(p.user_id)}}
@router.post('/v1/flights/orders/{order_id}/change-quote')
def change_quote(order_id:str,body:ChangeQuoteBody,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    changes=[x.model_dump() for x in body.changes] if body.changes is not None else None
    payload={'user_id':p.user_id,'order_id':order_id,'new_departure_date':body.new_departure_date,
             'leg_index':body.leg_index,'changes':changes}
    return run_idempotent('FLIGHT_CHANGE_QUOTE',idempotency_key,payload,
        lambda:wrap(flight_service.change_quote,p.user_id,order_id,body.new_departure_date,body.leg_index,changes))
@router.post('/v1/flights/orders/{order_id}/execute-change/{quote_id}')
def execute_change(order_id:str,quote_id:str,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key'),body:ChangeConfirmation|None=Body(default=None)):
    confirmation=body.model_dump() if body else None
    payload={'user_id':p.user_id,'order_id':order_id,'quote_id':quote_id,'confirmation':confirmation}
    return run_recoverable_idempotent('FLIGHT_EXECUTE_CHANGE',idempotency_key,payload,quote_id,
        lambda boundary:wrap(flight_service.execute_change,p.user_id,order_id,quote_id,confirmation,boundary),
        lambda boundary:wrap(flight_service.recover_execute_change,p.user_id,order_id,quote_id,confirmation,boundary))
@router.get('/v1/flights/orders/{order_id}/refund-quote')
def refund_quote(order_id:str,p:Principal=Depends(consumer_principal)): return wrap(flight_service.refund_quote,p.user_id,order_id)
@router.post('/v1/flights/orders/{order_id}/refund')
def refund(order_id:str,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload={'user_id':p.user_id,'order_id':order_id}
    return run_idempotent('FLIGHT_REFUND',idempotency_key,payload,lambda:wrap(flight_service.refund,p.user_id,order_id))

@router.post('/internal/v1/admin/flights/orders/{order_id}/external-state')
def admin_external_state(order_id:str,body:ExternalStateBody,p:Principal=Depends(admin_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload={'actor':p.user_id,'order_id':order_id,**body.model_dump()}
    return run_idempotent('FLIGHT_ADMIN_EXTERNAL_STATE',idempotency_key,payload,lambda:wrap(flight_service.admin_external_state,order_id,body.state,body.evidence_reference,p.user_id,body.supplier_reference,body.ticket_numbers,body.quote_id))

@router.post('/v1/flights/orders/{order_id}/refund-confirmed')
def refund_confirmed(order_id:str,body:RefundConfirmation,p:Principal=Depends(consumer_principal),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload={'user_id':p.user_id,'order_id':order_id,**body.model_dump()}
    return run_idempotent('FLIGHT_REFUND_CONFIRMED',idempotency_key,payload,
        lambda:wrap(flight_service.refund,p.user_id,order_id,body.quote_hash))
