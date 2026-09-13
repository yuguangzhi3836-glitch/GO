from fastapi import APIRouter, Header
from go_hotel.api.schemas import CancellationRequest, ChangeQuoteRequest, ChangeRequest, StayCreditRedemptionQuoteRequest, StayCreditRedeemRequest
from go_hotel.fare.service import fare_service
from go_hotel.api.idempotency import run_idempotent_async

router=APIRouter()


async def _fare_cancel(order_id, body):
    return {"data": await fare_service.cancel(order_id,body.cancellation_quote_id)}
async def _fare_change(order_id, body):
    return {"data": await fare_service.change(order_id,body.change_quote_id,body.payment_method_token)}
async def _fare_convert(order_id):
    return {"data": await fare_service.convert_to_stay_credit(order_id)}
async def _fare_redeem(credit_id, body):
    return {"data": await fare_service.redeem(credit_id,body.redemption_quote_id,body.payment_method_token)}

@router.post('/v1/orders/{order_id}/fare-options')
async def fare_options(order_id:str): return {"data":fare_service.fare_options(order_id)}

@router.post('/v1/orders/{order_id}/cancellation-quote')
async def cancellation_quote(order_id:str): return {"data":fare_service.cancellation_quote(order_id)}

@router.post('/v1/orders/{order_id}/cancel')
async def cancel(order_id:str, body:CancellationRequest, idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload=body.model_dump()|{"order_id":order_id}
    return await run_idempotent_async('cancel',idempotency_key,payload,lambda: _fare_cancel(order_id,body),lambda r: order_id)

@router.post('/v1/orders/{order_id}/change-quote')
async def change_quote(order_id:str, body:ChangeQuoteRequest): return {"data":await fare_service.change_quote(order_id,body.new_check_in,body.new_check_out)}

@router.post('/v1/orders/{order_id}/change')
async def change(order_id:str, body:ChangeRequest, idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload=body.model_dump()|{"order_id":order_id}
    return await run_idempotent_async('change',idempotency_key,payload,lambda: _fare_change(order_id,body),lambda r: r['data'].get('change_id'))

@router.post('/v1/orders/{order_id}/stay-credit-quote')
async def stay_credit_quote(order_id:str): return {"data":fare_service.stay_credit_quote(order_id)}

@router.post('/v1/orders/{order_id}/convert-to-stay-credit')
async def convert_to_stay_credit(order_id:str, idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload={"order_id":order_id}
    return await run_idempotent_async('stay_credit_convert',idempotency_key,payload,lambda: _fare_convert(order_id),lambda r: r['data'].get('stay_credit_id'))

@router.get('/v1/stay-credits/{credit_id}')
async def get_stay_credit(credit_id:str): return {"data":fare_service.get_credit(credit_id)}

@router.post('/v1/stay-credits/{credit_id}/redemption-quote')
async def redemption_quote(credit_id:str, body:StayCreditRedemptionQuoteRequest): return {"data":await fare_service.redemption_quote(credit_id,body.check_in,body.check_out)}

@router.post('/v1/stay-credits/{credit_id}/redeem')
async def redeem(credit_id:str, body:StayCreditRedeemRequest, idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    payload=body.model_dump()|{"credit_id":credit_id}
    return await run_idempotent_async('stay_credit_redeem',idempotency_key,payload,lambda: _fare_redeem(credit_id,body),lambda r: r['data'].get('order_id'))
