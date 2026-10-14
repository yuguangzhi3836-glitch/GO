"""Consumer checkout: wallet-backed HOTEL payment and isolated non-hotel acceptance."""
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from go_hotel.api.idempotency import run_idempotent_async
from go_hotel.core.simulation import consumer_simulated_checkout_enabled
from go_hotel.db.models import (OrderRow, FlightOrderRow, RailOrderRow,
    MobilityRentalOrderRow, MobilityRideOrderRow, AttractionOrderRow,
    OrderSupplierFulfillmentRow, OmnichannelPaymentIntentRow, OmnichannelMoneyMovementRow)
from go_hotel.db.session import SessionLocal
from go_hotel.security.deps import consumer_principal
from go_hotel.security.service import Principal
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service

router = APIRouter(tags=['consumer-explicit-checkout'])
MODELS = {'HOTEL': OrderRow, 'FLIGHT': FlightOrderRow, 'RAIL': RailOrderRow,
          'RENTAL': MobilityRentalOrderRow, 'RIDE': MobilityRideOrderRow, 'ATTRACTION': AttractionOrderRow}
class CheckoutConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['CONTRACT_SIMULATOR']
    expected_amount_minor: int = Field(strict=True, gt=0)
    currency: Literal['CNY']

class WalletCheckoutConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_amount_minor: int = Field(strict=True, gt=0)
    currency: Literal['CNY']

@router.get('/v1/consumer/checkout-capabilities')
def capabilities():
    return {'data': {'simulation_available': consumer_simulated_checkout_enabled(),
                     'hotel_simulation_available': False,
                     'live_payment_available': False, 'external_live': False}}

@router.post('/v1/consumer/wallet/checkout/{order_id}')
async def wallet_hotel_checkout(order_id: str, body: WalletCheckoutConfirmation,
                   p: Principal = Depends(consumer_principal),
                   idempotency_key: str = Header(alias='Idempotency-Key', min_length=1, max_length=160)):
    """Pay a hotel order from wallet cash, then use the existing supplier booking saga."""
    with SessionLocal() as s:
        order = s.get(OrderRow, order_id)
        if not order or order.account_id != p.user_id:
            raise HTTPException(404, detail='ORDER_NOT_FOUND')
        if order.total_amount_minor != body.expected_amount_minor or order.currency != body.currency:
            raise HTTPException(409, detail='ORDER_AMOUNT_CHANGED_RECONFIRM_REQUIRED')
        order_status = str(order.status)
        if order_status not in {'PAYMENT_PENDING', 'PAYMENT_AUTHORIZED', 'BOOKING_PENDING',
                                'CAPTURE_PENDING', 'CONFIRMED', 'RECONCILIATION_REQUIRED'}:
            raise HTTPException(409, detail='ORDER_NOT_PAYABLE')
    async def execute():
        from go_hotel.consumer.service import consumer_service
        from go_hotel.services.booking import booking_service
        try:
            payment = consumer_service.authorize_wallet_hotel_payment(
                p, order_id, body.expected_amount_minor, body.currency, idempotency_key)
            order = await booking_service.confirm(order_id)
            return {'data': {'order_id': order_id, 'status': str(order.status),
                'payment_id': payment['payment_id'], 'wallet_paid': True,
                'data_mode': 'WALLET_BALANCE', 'external_live': False}}
        except ValueError as exc:
            raise HTTPException(409, detail=str(exc)) from exc
    return await run_idempotent_async('CONSUMER_HOTEL_WALLET_CHECKOUT', idempotency_key,
        {'account_id':p.user_id,'order_id':order_id,**body.model_dump()}, execute)

@router.post('/v1/consumer/checkout/{vertical}/{order_id}')
async def checkout(vertical: str, order_id: str, body: CheckoutConfirmation,
                   p: Principal = Depends(consumer_principal),
                   idempotency_key: str = Header(alias='Idempotency-Key', min_length=1, max_length=160)):
    vertical = vertical.upper()
    model = MODELS.get(vertical)
    if not model:
        raise HTTPException(404, detail='VERTICAL_NOT_FOUND')
    if vertical == 'HOTEL':
        raise HTTPException(403, detail='HOTEL_WALLET_CHECKOUT_REQUIRED')
    if not consumer_simulated_checkout_enabled(vertical):
        raise HTTPException(403, detail='SIMULATED_CHECKOUT_FORBIDDEN_IN_THIS_ENVIRONMENT')
    with SessionLocal() as s:
        order = s.get(model, order_id)
        if not order or order.account_id != p.user_id:
            raise HTTPException(404, detail='ORDER_NOT_FOUND')
        if order.total_amount_minor != body.expected_amount_minor or order.currency != body.currency:
            raise HTTPException(409, detail='ORDER_AMOUNT_CHANGED_RECONFIRM_REQUIRED')
        order_status = str(order.status)
        if order_status not in {'PAYMENT_PENDING', 'PAYMENT_AUTHORIZED', 'PAYMENT_CONFIRMED_AWAITING_SUPPLIER', 'CONFIRMED', 'TICKETED'}:
            raise HTTPException(409, detail='ORDER_NOT_PAYABLE')
    async def execute():
        try:
            with SessionLocal() as s:
                fulfillment=s.scalar(select(OrderSupplierFulfillmentRow).where(
                    OrderSupplierFulfillmentRow.business_type==f'{vertical}_ORDER',
                    OrderSupplierFulfillmentRow.business_id==order_id))
                if fulfillment and fulfillment.state in {'UNKNOWN_EXTERNAL_STATE', 'SUPPLIER_FAILED'}:
                    raise ValueError('SUPPLIER_RECONCILIATION_REQUIRED')
                # A confirmed mobility order is a read-only replay. Re-entering
                # the unpaid deadline guard would reject a second device's key.
                current = s.get(model, order_id)
                if vertical in {'RIDE', 'RENTAL'} and current.status == 'CONFIRMED':
                    intent = s.scalar(select(OmnichannelPaymentIntentRow).where(
                        OmnichannelPaymentIntentRow.business_type == f'{vertical}_ORDER',
                        OmnichannelPaymentIntentRow.business_id == order_id,
                        OmnichannelPaymentIntentRow.payer_id == p.user_id))
                    if not intent or not fulfillment or fulfillment.payment_intent_id != intent.payment_intent_id or fulfillment.state != 'SUPPLIER_CONFIRMED':
                        raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
                    captures = list(s.scalars(select(OmnichannelMoneyMovementRow).where(
                        OmnichannelMoneyMovementRow.root_payment_intent_id == intent.payment_intent_id,
                        OmnichannelMoneyMovementRow.movement_type == 'CAPTURE',
                        OmnichannelMoneyMovementRow.state == 'CONFIRMED')))
                    if len(captures) != 1 or captures[0].amount_minor != body.expected_amount_minor or captures[0].currency != body.currency:
                        raise ValueError('PAYMENT_RECONCILIATION_REQUIRED')
                    return {'data': {'order_id': order_id, 'status': current.status,
                        'payment_intent_id': intent.payment_intent_id,
                        'supplier_fulfillment_id': fulfillment.order_supplier_fulfillment_id,
                        'data_mode': 'SIMULATION', 'external_live': False}}
            tx=vertical_transaction_bridge.checkout_contract(vertical, order_id, p.user_id,
                f'{vertical.lower()}-engineering-source', f'contract-simulator://{vertical}/{order_id}')
            ref=f'SIM-{order_id}'
            fact={'state':'SUPPLIER_CONFIRMED','supplier_confirmation_reference':ref,
                  'external_operation_id':ref,'evidence_reference':f'contract-simulator://{vertical}/{order_id}'}
            if vertical in {'FLIGHT','RAIL'}:
                passenger_count=len(order.passengers or []) or 1
                independent_legs=len(order.current_itinerary or []) if vertical=='FLIGHT' else 1
                fact['ticket_numbers']=[f'{ref}-L{leg+1}-P{person+1}' for leg in range(max(1,independent_legs)) for person in range(passenger_count)]
            if vertical=='ATTRACTION':fact['voucher_code']=ref
            result=order_supplier_fulfillment_service.record_supplier_fact(tx['supplier_fulfillment_id'], fact)
            return {'data': {'order_id':order_id,'status':'TICKETED' if vertical in {'FLIGHT','RAIL'} else 'CONFIRMED',
                'payment_intent_id':tx['payment_intent_id'],'supplier_fulfillment_id':tx['supplier_fulfillment_id'],
                'data_mode':'SIMULATION','external_live':False}}
        except ValueError as exc:
            raise HTTPException(409, detail=str(exc)) from exc
    return await run_idempotent_async('CONSUMER_EXPLICIT_CHECKOUT', idempotency_key,
        {'account_id':p.user_id,'vertical':vertical,'order_id':order_id,**body.model_dump()}, execute)
