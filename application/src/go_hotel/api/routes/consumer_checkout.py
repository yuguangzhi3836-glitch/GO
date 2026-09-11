"""Explicit checkout for isolated product acceptance, with authoritative amounts.

This route does not activate any external supplier or payment provider.
"""
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from go_hotel.api.idempotency import run_idempotent_async
from go_hotel.core.config import settings
from go_hotel.db.models import (OrderRow, FlightOrderRow, RailOrderRow,
    MobilityRentalOrderRow, MobilityRideOrderRow, AttractionOrderRow,
    OrderSupplierFulfillmentRow)
from go_hotel.db.session import SessionLocal
from go_hotel.security.deps import consumer_principal
from go_hotel.security.service import Principal
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge
from go_hotel.services.order_supplier_fulfillment import order_supplier_fulfillment_service

router = APIRouter(tags=['consumer-explicit-checkout'])
MODELS = {'HOTEL': OrderRow, 'FLIGHT': FlightOrderRow, 'RAIL': RailOrderRow,
          'RENTAL': MobilityRentalOrderRow, 'RIDE': MobilityRideOrderRow, 'ATTRACTION': AttractionOrderRow}
ACCEPTANCE_ENVS = {'local', 'test', 'demo'}

class CheckoutConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['CONTRACT_SIMULATOR']
    expected_amount_minor: int = Field(strict=True, gt=0)
    currency: Literal['CNY']

@router.get('/v1/consumer/checkout-capabilities')
def capabilities():
    return {'data': {'simulation_available': settings.app_env.lower() in ACCEPTANCE_ENVS,
                     'live_payment_available': False, 'external_live': False}}

@router.post('/v1/consumer/checkout/{vertical}/{order_id}')
async def checkout(vertical: str, order_id: str, body: CheckoutConfirmation,
                   p: Principal = Depends(consumer_principal),
                   idempotency_key: str = Header(alias='Idempotency-Key', min_length=1, max_length=160)):
    if settings.app_env.lower() not in ACCEPTANCE_ENVS:
        raise HTTPException(403, detail='SIMULATED_CHECKOUT_FORBIDDEN_IN_THIS_ENVIRONMENT')
    vertical = vertical.upper()
    model = MODELS.get(vertical)
    if not model:
        raise HTTPException(404, detail='VERTICAL_NOT_FOUND')
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
            if vertical == 'HOTEL':
                from go_hotel.services.booking import booking_service
                from go_hotel.repositories.sql import repo
                from go_hotel.domain.models import OrderStatus
                current = repo.get_order(order_id)
                if current.status != OrderStatus.CONFIRMED:
                    await booking_service.pay(order_id, body.expected_amount_minor, body.currency, 'pm_success')
                    current = await booking_service.confirm(order_id)
                return {'data': {'order_id': order_id, 'status': str(current.status),
                    'supplier_confirmation_reference': current.supplier_confirmation_no,
                    'data_mode': 'SIMULATION', 'external_live': False}}
            with SessionLocal() as s:
                fulfillment=s.scalar(select(OrderSupplierFulfillmentRow).where(
                    OrderSupplierFulfillmentRow.business_type==f'{vertical}_ORDER',
                    OrderSupplierFulfillmentRow.business_id==order_id))
                if fulfillment and fulfillment.state in {'UNKNOWN_EXTERNAL_STATE', 'SUPPLIER_FAILED'}:
                    raise ValueError('SUPPLIER_RECONCILIATION_REQUIRED')
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
