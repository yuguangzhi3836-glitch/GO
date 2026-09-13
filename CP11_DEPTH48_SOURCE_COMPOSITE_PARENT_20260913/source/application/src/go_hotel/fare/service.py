from __future__ import annotations
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OrderRow, OfferRow, PrebookRow, OrderChangeRow, StayCreditRow
from go_hotel.domain.models import OrderStatus
from go_hotel.core.errors import not_found, conflict, unprocessable


class FareService:
    def _context(self, order_id: str):
        with SessionLocal() as s:
            order=s.get(OrderRow, order_id)
            if not order: not_found("ORDER_NOT_FOUND","Order not found")
            from go_hotel.db.models import CatalogCreditAllocationRow
            if s.get(CatalogCreditAllocationRow,order_id):conflict('CREDIT_ORDER_AFTERSALES_REQUIRED','Use the credit-aware after-sales process')
            if s.scalar(select(StayCreditRow).where(StayCreditRow.original_order_id==order_id)):conflict('CREDIT_SOURCE_ORDER_FROZEN','Source stay value is reserved for credit')
            from go_hotel.db.models import SupplierFaultCaseRow
            if s.scalar(select(SupplierFaultCaseRow).where(SupplierFaultCaseRow.order_id==order_id,SupplierFaultCaseRow.status!='COMPLETED')):conflict('SUPPLIER_REMEDY_ORDER_FROZEN','Supplier cancellation is under independent review')
            pb=s.get(PrebookRow, order.prebook_id)
            offer=s.get(OfferRow, pb.offer_id) if pb else None
            if not pb or not offer: not_found("ORDER_FARE_CONTEXT_MISSING","Order fare context missing")
            latest=s.scalar(select(OrderChangeRow).where(OrderChangeRow.order_id==order_id, OrderChangeRow.status=="CONFIRMED").order_by(OrderChangeRow.confirmed_at.desc()))
            check_in=latest.new_check_in if latest else offer.check_in
            check_out=latest.new_check_out if latest else offer.check_out
            return order,pb,offer,check_in,check_out

    def _order_rule(self, order_id):
        from go_hotel.services.catalog_fare_snapshot import order_rule
        try:return order_rule(order_id)
        except ValueError as exc:conflict(str(exc), 'The original order fare rules require reconciliation')

    def fare_options(self, order_id: str) -> dict:
        order,pb,offer,check_in,check_out=self._context(order_id)
        rule=self._order_rule(order_id)
        allowed=order.status==OrderStatus.CONFIRMED.value
        return {"order_id":order_id,"actions":[
            {"type":"CHANGE_DATE","allowed":allowed and rule["change_allowed"]},
            {"type":"CANCEL_FOR_REFUND","allowed":allowed},
            {"type":"CONVERT_TO_STAY_CREDIT","allowed":allowed and rule["stay_credit_allowed"]},
            {"type":"KEEP_BOOKING","allowed":True},
        ]}

    def cancellation_quote(self, order_id: str) -> dict:
        from go_hotel.services.catalog_cash_fare import cancellation_quote
        try: return cancellation_quote(order_id)
        except ValueError as exc: conflict(str(exc), 'A current cancellation quote could not be established')

    async def cancel(self, order_id: str, quote_id: str, quote_hash=None, confirmed=False, actor=None) -> dict:
        from go_hotel.services.catalog_cash_fare_execution import start
        try: return await start(order_id, quote_id, quote_hash, confirmed, actor, action='CANCEL')
        except ValueError as exc:
            if str(exc) == 'CASH_FARE_QUOTE_EXPIRED': unprocessable(str(exc), 'Cancellation quote expired')
            conflict(str(exc), 'Cancellation requires the accepted quote and reconciled order facts')

    async def change_quote(self, order_id: str, new_check_in: str, new_check_out: str) -> dict:
        from go_hotel.services.catalog_cash_fare import change_quote
        try: return await change_quote(order_id, new_check_in, new_check_out)
        except ValueError as exc: conflict(str(exc), 'A current change quote could not be established')

    async def change(self, order_id: str, quote_id: str, payment_method_token: str,
                     quote_hash=None, confirmed=False, actor=None) -> dict:
        from go_hotel.services.catalog_cash_fare_execution import start
        try: return await start(order_id, quote_id, quote_hash, confirmed, actor, payment_method_token, action='CHANGE')
        except ValueError as exc:
            if str(exc) == 'CASH_FARE_QUOTE_EXPIRED': unprocessable(str(exc), 'Change quote expired')
            conflict(str(exc), 'Change requires the accepted quote and reconciled order facts')

    def stay_credit_quote(self, order_id: str) -> dict:
        from go_hotel.services.catalog_stay_credit import conversion_quote
        return conversion_quote(order_id)

    async def convert_to_stay_credit(self, order_id, quote_id, quote_hash, confirmed, actor):
        from go_hotel.services.catalog_stay_credit import convert
        return await convert(order_id, quote_id, quote_hash, confirmed, actor)

    def get_credit(self, credit_id):
        from go_hotel.services.catalog_stay_credit import get_credit
        return get_credit(credit_id)

    async def redemption_quote(self, credit_id, check_in, check_out):
        from go_hotel.services.catalog_stay_credit import redemption_quote
        return await redemption_quote(credit_id, check_in, check_out)

    async def redeem(self, credit_id, quote_id, quote_hash, confirmed, payment_method_token, actor, profile_release=None):
        from go_hotel.services.catalog_stay_credit import redeem
        return await redeem(credit_id, quote_id, quote_hash, confirmed, payment_method_token, actor, profile_release)

fare_service=FareService()
