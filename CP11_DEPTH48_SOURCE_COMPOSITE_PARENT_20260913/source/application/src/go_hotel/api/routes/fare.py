from fastapi import APIRouter, Header, Depends, HTTPException
from go_hotel.security.deps import legacy_order_access
from go_hotel.api.schemas import CancellationRequest, ChangeQuoteRequest, ChangeRequest, StayCreditRedemptionQuoteRequest, StayCreditRedeemRequest, StayCreditConvertRequest, StayCreditPaymentRetryRequest
from go_hotel.fare.service import fare_service
from go_hotel.api.idempotency import run_idempotent_async
from go_hotel.api.schemas import CashFarePaymentRetryRequest

router=APIRouter(dependencies=[Depends(legacy_order_access)])


async def _fare_cancel(order_id, body, actor=None):
    return {"data": await fare_service.cancel(order_id,body.cancellation_quote_id,body.quote_hash,body.confirmed,actor)}
async def _fare_change(order_id, body, actor=None):
    return {"data": await fare_service.change(order_id,body.change_quote_id,body.payment_method_token,body.quote_hash,body.confirmed,actor)}
def credit_actor(p):return p.user_id if p else 'LOCAL_CREDIT_CONTRACT'

def credit_sync(fn):
    try:return {'data':fn()}
    except ValueError as exc:raise HTTPException(409,detail=str(exc))

async def credit_async(fn):
    try:return {'data':await fn()}
    except ValueError as exc:raise HTTPException(409,detail=str(exc))

async def _fare_convert(order_id,body,actor):
    return await credit_async(lambda:fare_service.convert_to_stay_credit(order_id,body.quote_id,body.quote_hash,body.confirmed,actor))
async def _fare_redeem(credit_id, body, actor, principal=None):
    from go_hotel.services.catalog_stay_credit import release_traveler
    try:profile=release_traveler(actor,body.traveler_id,body.consent_id) if principal else None
    except ValueError as exc:raise HTTPException(409,detail=str(exc))
    return await credit_async(lambda:fare_service.redeem(credit_id,body.redemption_quote_id,body.quote_hash,body.confirmed,body.payment_method_token,actor,profile))

@router.post('/v1/orders/{order_id}/fare-options')
async def fare_options(order_id:str): return {"data":fare_service.fare_options(order_id)}

@router.post('/v1/orders/{order_id}/cancellation-quote')
async def cancellation_quote(order_id:str): return {"data":fare_service.cancellation_quote(order_id)}

@router.post('/v1/orders/{order_id}/cancel')
async def cancel(order_id:str, body:CancellationRequest, p=Depends(legacy_order_access), idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    actor=p.user_id if p else None
    payload=body.model_dump()|{"order_id":order_id,'actor':actor}
    return await run_idempotent_async('cancel',idempotency_key,payload,lambda: _fare_cancel(order_id,body,actor),lambda r: order_id)

@router.post('/v1/orders/{order_id}/change-quote')
async def change_quote(order_id:str, body:ChangeQuoteRequest): return {"data":await fare_service.change_quote(order_id,body.new_check_in,body.new_check_out)}

@router.post('/v1/orders/{order_id}/change')
async def change(order_id:str, body:ChangeRequest, p=Depends(legacy_order_access), idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    actor=p.user_id if p else None
    payload=body.model_dump()|{"order_id":order_id,'actor':actor}
    return await run_idempotent_async('change',idempotency_key,payload,lambda: _fare_change(order_id,body,actor),lambda r: r['data'].get('change_id'))

@router.get('/v1/orders/{order_id}/cash-after-sales')
async def cash_fare_status(order_id:str):
    from go_hotel.services.catalog_cash_fare import status
    return credit_sync(lambda:status(order_id))

@router.post('/v1/orders/{order_id}/cash-after-sales/{operation_id}/reconcile')
async def cash_fare_reconcile(order_id:str,operation_id:str,p=Depends(legacy_order_access)):
    from go_hotel.services.catalog_cash_fare_execution import reconcile
    return await credit_async(lambda:reconcile(order_id,operation_id,p.user_id if p else None))

@router.post('/v1/orders/{order_id}/cash-after-sales/{operation_id}/retry-payment')
async def cash_fare_retry(order_id:str,operation_id:str,body:CashFarePaymentRetryRequest,p=Depends(legacy_order_access)):
    from go_hotel.services.catalog_cash_fare_execution import retry_payment
    return credit_sync(lambda:retry_payment(order_id,operation_id,body.quote_hash,body.confirmed,body.payment_method_token,p.user_id if p else None))

@router.post('/v1/orders/{order_id}/stay-credit-quote')
async def stay_credit_quote(order_id:str): return credit_sync(lambda:fare_service.stay_credit_quote(order_id))

@router.post('/v1/orders/{order_id}/convert-to-stay-credit')
async def convert_to_stay_credit(order_id:str, body:StayCreditConvertRequest, p=Depends(legacy_order_access), idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload=body.model_dump()|{"order_id":order_id,'actor':credit_actor(p)}
    return await run_idempotent_async('stay_credit_convert',idempotency_key,payload,lambda: _fare_convert(order_id,body,credit_actor(p)),lambda r: r['data'].get('stay_credit_id'))

@router.get('/v1/stay-credits/{credit_id}')
async def get_stay_credit(credit_id:str): return credit_sync(lambda:fare_service.get_credit(credit_id))

@router.post('/v1/stay-credits/{credit_id}/redemption-quote')
async def redemption_quote(credit_id:str, body:StayCreditRedemptionQuoteRequest): return await credit_async(lambda:fare_service.redemption_quote(credit_id,body.check_in,body.check_out))

@router.post('/v1/stay-credits/{credit_id}/redeem')
async def redeem(credit_id:str, body:StayCreditRedeemRequest, p=Depends(legacy_order_access), idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload=body.model_dump()|{"credit_id":credit_id,'actor':credit_actor(p)}
    return await run_idempotent_async('stay_credit_redeem',idempotency_key,payload,lambda: _fare_redeem(credit_id,body,credit_actor(p),p),lambda r: r['data'].get('order_id'))

@router.post('/v1/stay-credits/{credit_id}/reconcile-conversion')
async def reconcile_credit_conversion(credit_id:str,p=Depends(legacy_order_access)):
    from go_hotel.services.catalog_stay_credit import reconcile_conversion
    return await credit_async(lambda:reconcile_conversion(credit_id,credit_actor(p)))

def credit_redemption_access(credit_id,redemption_id):
    from go_hotel.db.models import CatalogCreditAllocationRow
    from go_hotel.db.session import SessionLocal
    with SessionLocal() as s:
        a=s.get(CatalogCreditAllocationRow,redemption_id)
        if not a or a.credit_id!=credit_id:raise HTTPException(404,detail='CREDIT_REDEMPTION_NOT_FOUND')

@router.post('/v1/stay-credits/{credit_id}/redemptions/{redemption_id}/reconcile')
async def reconcile_credit_redemption(credit_id:str,redemption_id:str,p=Depends(legacy_order_access)):
    from go_hotel.services.catalog_stay_credit import reconcile_redemption
    credit_redemption_access(credit_id,redemption_id)
    return await credit_async(lambda:reconcile_redemption(redemption_id,credit_actor(p)))

@router.post('/v1/stay-credits/{credit_id}/redemptions/{redemption_id}/retry-payment')
async def retry_credit_payment(credit_id:str,redemption_id:str,body:StayCreditPaymentRetryRequest,p=Depends(legacy_order_access)):
    from go_hotel.services.catalog_stay_credit import retry_payment
    credit_redemption_access(credit_id,redemption_id)
    return credit_sync(lambda:retry_payment(redemption_id,body.quote_hash,body.confirmed,body.payment_method_token,credit_actor(p)))

@router.post('/v1/stay-credits/{credit_id}/redemptions/{redemption_id}/cancellation-quote')
async def credit_cancellation_quote(credit_id:str,redemption_id:str,p=Depends(legacy_order_access)):
    from go_hotel.services.catalog_credit_after_sales import cancellation_quote
    credit_redemption_access(credit_id,redemption_id)
    return credit_sync(lambda:cancellation_quote(redemption_id))

@router.post('/v1/stay-credits/{credit_id}/redemptions/{redemption_id}/cancel')
async def credit_cancel(credit_id:str,redemption_id:str,body:StayCreditConvertRequest,p=Depends(legacy_order_access)):
    from go_hotel.services.catalog_credit_after_sales import cancel
    credit_redemption_access(credit_id,redemption_id)
    return await credit_async(lambda:cancel(redemption_id,body.quote_id,body.quote_hash,body.confirmed,credit_actor(p)))

@router.post('/v1/stay-credits/{credit_id}/redemptions/{redemption_id}/reconcile-cancellation')
async def credit_cancel_reconcile(credit_id:str,redemption_id:str,p=Depends(legacy_order_access)):
    from go_hotel.services.catalog_credit_after_sales import reconcile
    credit_redemption_access(credit_id,redemption_id)
    return await credit_async(lambda:reconcile(redemption_id,credit_actor(p)))
