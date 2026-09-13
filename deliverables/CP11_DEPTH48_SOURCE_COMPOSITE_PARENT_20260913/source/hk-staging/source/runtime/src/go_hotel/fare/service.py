from __future__ import annotations
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    OrderRow, PaymentRow, OfferRow, PrebookRow, FareRuleRow, CancellationQuoteRow,
    RefundRow, ChangeQuoteRow, OrderChangeRow, StayCreditRow, StayCreditRedemptionQuoteRow
)
from go_hotel.domain.models import Event, OrderStatus, PaymentStatus, PrebookStatus, new_id, now_utc, Offer, Prebook, Order, Payment
from go_hotel.repositories.sql import repo
from go_hotel.services.hotel_money_bridge import hotel_money_bridge
from go_hotel.connectors.registry import registry
from go_hotel.connectors.resilience import ResilientConnector
from go_hotel.core.config import settings
from go_hotel.core.errors import not_found, conflict, unprocessable, unavailable


def _aware(dt):
    if dt is None: return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

class FareService:
    DEFAULT_TIERS = [
        {"min_hours":168, "fee_percent":0},
        {"min_hours":72, "fee_percent":20},
        {"min_hours":24, "fee_percent":50},
        {"min_hours":0, "fee_percent":80},
    ]

    def _connector(self, connector_id: str):
        return ResilientConnector(registry.get(connector_id), timeout_seconds=settings.connector_timeout_seconds, retries=settings.connector_retry_count)

    def _context(self, order_id: str):
        with SessionLocal() as s:
            order=s.get(OrderRow, order_id)
            if not order: not_found("ORDER_NOT_FOUND","Order not found")
            pb=s.get(PrebookRow, order.prebook_id)
            offer=s.get(OfferRow, pb.offer_id) if pb else None
            if not pb or not offer: not_found("ORDER_FARE_CONTEXT_MISSING","Order fare context missing")
            latest=s.scalar(select(OrderChangeRow).where(OrderChangeRow.order_id==order_id, OrderChangeRow.status=="CONFIRMED").order_by(OrderChangeRow.confirmed_at.desc()))
            check_in=latest.new_check_in if latest else offer.check_in
            check_out=latest.new_check_out if latest else offer.check_out
            return order,pb,offer,check_in,check_out

    def _rule(self, fare_rule_id: str) -> dict:
        with SessionLocal.begin() as s:
            row=s.get(FareRuleRow, fare_rule_id)
            if row is None:
                row=FareRuleRow(fare_rule_id=fare_rule_id, fare_family="GO_STANDARD", cooling_off_minutes=0, change_allowed=True, change_fee_minor=10000, stay_credit_allowed=True, stay_credit_validity_days=365, stay_credit_scope="PROPERTY_ONLY", tiers_json=self.DEFAULT_TIERS, created_at=now_utc())
                s.add(row); s.flush()
            return {"fare_rule_id":row.fare_rule_id,"fare_family":row.fare_family,"change_allowed":row.change_allowed,"change_fee_minor":row.change_fee_minor,"stay_credit_allowed":row.stay_credit_allowed,"stay_credit_validity_days":row.stay_credit_validity_days,"stay_credit_scope":row.stay_credit_scope,"tiers":row.tiers_json}

    def fare_options(self, order_id: str) -> dict:
        order,pb,offer,check_in,check_out=self._context(order_id)
        rule=self._rule(offer.fare_rule_id)
        allowed=order.status==OrderStatus.CONFIRMED.value
        return {"order_id":order_id,"actions":[
            {"type":"CHANGE_DATE","allowed":allowed and rule["change_allowed"]},
            {"type":"CANCEL_FOR_REFUND","allowed":allowed},
            {"type":"CONVERT_TO_STAY_CREDIT","allowed":allowed and rule["stay_credit_allowed"]},
            {"type":"KEEP_BOOKING","allowed":True},
        ]}

    def cancellation_quote(self, order_id: str) -> dict:
        order,pb,offer,check_in,_=self._context(order_id)
        if order.status != OrderStatus.CONFIRMED.value: conflict("CANCELLATION_NOT_ALLOWED","Only confirmed orders can be cancelled")
        rule=self._rule(offer.fare_rule_id)
        ci=datetime.fromisoformat(check_in).replace(tzinfo=timezone.utc)
        hours=max(0,(ci-now_utc()).total_seconds()/3600)
        pct=80
        for tier in sorted(rule["tiers"], key=lambda x:x["min_hours"], reverse=True):
            if hours>=tier["min_hours"]: pct=tier["fee_percent"]; break
        fee=order.total_amount_minor*pct//100
        refund=max(order.total_amount_minor-fee,0)
        qid=new_id("cq"); exp=now_utc()+timedelta(minutes=10)
        with SessionLocal.begin() as s:
            s.add(CancellationQuoteRow(quote_id=qid,order_id=order_id,paid_amount_minor=order.total_amount_minor,cancellation_fee_minor=fee,refund_amount_minor=refund,rule_snapshot={**rule,"hours_before_checkin":round(hours,2),"fee_percent":pct},expires_at=exp,created_at=now_utc()))
        repo.append_event(Event(new_id("evt"),"CANCELLATION_QUOTE_CREATED","HOTEL_ORDER",order_id,{"quote_id":qid,"fee_minor":fee,"refund_minor":refund,"fee_percent":pct}))
        return {"quote_id":qid,"paid_amount_minor":order.total_amount_minor,"cancellation_fee_minor":fee,"refund_amount_minor":refund,"currency":order.currency,"expires_at":exp.isoformat()}

    async def cancel(self, order_id: str, quote_id: str) -> dict:
        order,pb,offer,_,_=self._context(order_id)
        with SessionLocal() as s:
            q=s.get(CancellationQuoteRow,quote_id)
            if not q or q.order_id!=order_id: not_found("CANCELLATION_QUOTE_NOT_FOUND","Cancellation quote not found")
            if _aware(q.expires_at)<=now_utc(): unprocessable("CANCELLATION_QUOTE_EXPIRED","Cancellation quote expired")
        if order.status != OrderStatus.CONFIRMED.value: conflict("ORDER_STATE_CONFLICT","Order is not cancellable")
        result=await self._connector(offer.connector_id).cancel(order.supplier_confirmation_no)
        if result!="CANCELLED": unavailable("SUPPLIER_CANCEL_FAILED","Supplier cancellation failed")
        with SessionLocal.begin() as s:
            r=s.get(OrderRow,order_id); r.status=OrderStatus.CANCELLED.value; r.version+=1; r.updated_at=now_utc()
        repo.append_event(Event(new_id("evt"),"CANCEL_CONFIRMED","HOTEL_ORDER",order_id,{"quote_id":quote_id}))
        refund=None
        if q.refund_amount_minor>0:
            refund=await self._refund_original(order_id,q.refund_amount_minor,order.currency)
        return {"order_id":order_id,"status":"CANCELLED","refund":refund,"cancellation_fee_minor":q.cancellation_fee_minor}

    async def _refund_original(self, order_id: str, amount_minor: int, currency: str) -> dict:
        with SessionLocal() as s:
            pay=s.scalar(select(PaymentRow).where(PaymentRow.order_id==order_id,PaymentRow.payment_type=="ORIGINAL_BOOKING",PaymentRow.status==PaymentStatus.CAPTURED.value).order_by(PaymentRow.created_at.desc()))
            if not pay: not_found("CAPTURED_PAYMENT_NOT_FOUND","Captured original payment not found")
        rid=new_id("ref")
        with SessionLocal.begin() as s:
            s.add(RefundRow(refund_id=rid,order_id=order_id,payment_id=pay.payment_id,amount_minor=amount_minor,currency=currency,status="PROCESSING",created_at=now_utc()))
        repo.append_event(Event(new_id("evt"),"REFUND_REQUESTED","REFUND",rid,{"order_id":order_id,"amount_minor":amount_minor}))
        try:
            movement=hotel_money_bridge.refund(order_id,amount_minor,f"hotel-refund://{rid}",f"hotel-refund:{rid}")
        except ValueError as exc:
            with SessionLocal.begin() as s: s.get(RefundRow,rid).status="FAILED"
            repo.append_event(Event(new_id("evt"),"REFUND_FAILED","REFUND",rid,{"order_id":order_id,"reason":str(exc)}))
            unavailable("REFUND_MONEY_MOVEMENT_FAILED","Unified refund movement failed")
        with SessionLocal.begin() as s:
            rr=s.get(RefundRow,rid); rr.status="COMPLETED"; rr.provider_refund_id=movement["money_movement_id"]; rr.completed_at=now_utc()
        repo.append_event(Event(new_id("evt"),"REFUND_COMPLETED","REFUND",rid,{"order_id":order_id,"amount_minor":amount_minor}))
        return {"refund_id":rid,"amount_minor":amount_minor,"currency":currency,"status":"COMPLETED"}

    async def change_quote(self, order_id: str, new_check_in: str, new_check_out: str) -> dict:
        order,pb,offer,_,_=self._context(order_id)
        if order.status != OrderStatus.CONFIRMED.value: conflict("CHANGE_NOT_ALLOWED","Only confirmed orders can be changed")
        rule=self._rule(offer.fare_rule_id)
        if not rule["change_allowed"]: unprocessable("CHANGE_NOT_ALLOWED","Fare rule does not allow change")
        offers=await self._connector(offer.connector_id).search("TYO",new_check_in,new_check_out,order.currency)
        candidates=[x for x in offers if x.hotel_id==order.hotel_id and x.room_type_id==offer.room_type_id]
        if not candidates: unprocessable("CHANGE_NOT_AVAILABLE","No matching inventory for requested dates")
        new_offer=candidates[0]
        repo.save_offer_with_event(new_offer,Event(new_id("evt"),"CHANGE_REPRICE_OFFER_CREATED","HOTEL_OFFER",new_offer.offer_id,{"order_id":order_id}))
        diff=max(new_offer.total_amount_minor-order.total_amount_minor,0)
        amount_due=diff+rule["change_fee_minor"]
        qid=new_id("chgq"); exp=now_utc()+timedelta(minutes=10)
        with SessionLocal.begin() as s:
            s.add(ChangeQuoteRow(quote_id=qid,order_id=order_id,new_check_in=new_check_in,new_check_out=new_check_out,old_value_minor=order.total_amount_minor,new_value_minor=new_offer.total_amount_minor,fare_difference_minor=diff,change_fee_minor=rule["change_fee_minor"],amount_due_minor=amount_due,rule_snapshot={**rule,"new_offer_id":new_offer.offer_id,"lower_price_difference_minor":max(order.total_amount_minor-new_offer.total_amount_minor,0),"lower_price_rule":"NO_REFUND"},expires_at=exp,created_at=now_utc()))
        repo.append_event(Event(new_id("evt"),"CHANGE_QUOTE_CREATED","HOTEL_ORDER",order_id,{"quote_id":qid,"new_value_minor":new_offer.total_amount_minor,"amount_due_minor":amount_due}))
        return {"change_quote_id":qid,"old_value_minor":order.total_amount_minor,"new_value_minor":new_offer.total_amount_minor,"fare_difference_minor":diff,"change_fee_minor":rule["change_fee_minor"],"amount_due_minor":amount_due,"lower_price_no_refund":True,"expires_at":exp.isoformat()}

    async def change(self, order_id: str, quote_id: str, payment_method_token: str) -> dict:
        order,pb,offer,_,_=self._context(order_id)
        with SessionLocal() as s:
            q=s.get(ChangeQuoteRow,quote_id)
            if not q or q.order_id!=order_id: not_found("CHANGE_QUOTE_NOT_FOUND","Change quote not found")
            if _aware(q.expires_at)<=now_utc(): unprocessable("CHANGE_QUOTE_EXPIRED","Change quote expired")
            existing=s.scalar(select(OrderChangeRow).where(OrderChangeRow.quote_id==quote_id))
            if existing and existing.status=="CONFIRMED": return {"change_id":existing.change_id,"status":"CONFIRMED","supplier_confirmation_no":existing.supplier_confirmation_no,"amount_paid_minor":existing.additional_payment_minor}
        prepared=None
        if q.amount_due_minor>0:
            opkey=f"change:{quote_id}"
            try:
                prepared=hotel_money_bridge.prepare_adjustment(order_id,"HOTEL_CHANGE",quote_id,q.amount_due_minor,f"hotel-change://{quote_id}",opkey)
            except ValueError as exc:
                unavailable("CHANGE_PAYMENT_EXECUTOR_REQUIRED",str(exc))
        change_id=new_id("chg")
        with SessionLocal.begin() as s:
            s.add(OrderChangeRow(change_id=change_id,order_id=order_id,quote_id=quote_id,new_check_in=q.new_check_in,new_check_out=q.new_check_out,additional_payment_minor=q.amount_due_minor,status="SUPPLIER_PROCESSING",created_at=now_utc()))
            r=s.get(OrderRow,order_id); r.status=OrderStatus.CHANGE_PENDING.value; r.version+=1; r.updated_at=now_utc()
        repo.append_event(Event(new_id("evt"),"CHANGE_REQUESTED","HOTEL_ORDER",order_id,{"change_id":change_id,"quote_id":quote_id}))
        try:
            confirmation=await self._connector(offer.connector_id).change(order.supplier_confirmation_no,q.new_check_in,q.new_check_out,idempotency_key=change_id)
        except Exception as exc:
            if prepared: hotel_money_bridge.release_adjustment(prepared,q.amount_due_minor,f"hotel-change-release://{change_id}",opkey)
            with SessionLocal.begin() as s:
                c=s.get(OrderChangeRow,change_id); c.status="FAILED"
                r=s.get(OrderRow,order_id); r.status=OrderStatus.CONFIRMED.value; r.version+=1; r.updated_at=now_utc()
            unavailable("SUPPLIER_CHANGE_FAILED","Supplier change failed; payment authorization voided")
        if prepared:
            captured=hotel_money_bridge.capture_adjustment(prepared,q.amount_due_minor,f"hotel-change-capture://{change_id}",opkey)
            repo.append_event(Event(new_id("evt"),"CHANGE_ADDITIONAL_PAYMENT_CAPTURED","HOTEL_ORDER",order_id,{"amount_minor":q.amount_due_minor,"money_movement_id":captured["capture_id"]}))
        with SessionLocal.begin() as s:
            c=s.get(OrderChangeRow,change_id); c.status="CONFIRMED"; c.supplier_confirmation_no=confirmation; c.confirmed_at=now_utc()
            r=s.get(OrderRow,order_id); r.status=OrderStatus.CONFIRMED.value; r.supplier_confirmation_no=confirmation; r.version+=1; r.updated_at=now_utc()
        repo.append_event(Event(new_id("evt"),"CHANGE_CONFIRMED","HOTEL_ORDER",order_id,{"change_id":change_id,"new_check_in":q.new_check_in,"new_check_out":q.new_check_out,"amount_paid_minor":q.amount_due_minor}))
        return {"change_id":change_id,"status":"CONFIRMED","supplier_confirmation_no":confirmation,"amount_paid_minor":q.amount_due_minor}

    def stay_credit_quote(self, order_id: str) -> dict:
        order,pb,offer,_,_=self._context(order_id)
        if order.status != OrderStatus.CONFIRMED.value: conflict("STAY_CREDIT_NOT_ALLOWED","Only confirmed orders can convert to credit")
        rule=self._rule(offer.fare_rule_id)
        if not rule["stay_credit_allowed"]: unprocessable("STAY_CREDIT_NOT_ALLOWED","Fare rule does not allow Stay Credit")
        expires=now_utc()+timedelta(days=rule["stay_credit_validity_days"])
        return {"credit_value_minor":order.total_amount_minor,"currency":order.currency,"property_id":order.hotel_id,"scope":"PROPERTY_ONLY","validity_days":rule["stay_credit_validity_days"],"expires_at":expires.isoformat(),"higher_price_rule":"PAY_DIFFERENCE","lower_price_rule":"NO_REFUND_NO_BALANCE"}

    async def convert_to_stay_credit(self, order_id: str) -> dict:
        order,pb,offer,_,_=self._context(order_id)
        quote=self.stay_credit_quote(order_id)
        with SessionLocal() as s:
            existing=s.scalar(select(StayCreditRow).where(StayCreditRow.original_order_id==order_id))
            if existing: return self._credit_dict(existing)
        credit_id=new_id("sc"); valid_from=now_utc(); expires=valid_from+timedelta(days=quote["validity_days"])
        with SessionLocal.begin() as s:
            s.add(StayCreditRow(stay_credit_id=credit_id,original_order_id=order_id,account_id=order.account_id,property_id=order.hotel_id,credit_value_minor=order.total_amount_minor,currency=order.currency,valid_from=valid_from,expires_at=expires,status="RESERVED",created_at=valid_from))
        repo.append_event(Event(new_id("evt"),"STAY_CREDIT_RESERVED","STAY_CREDIT",credit_id,{"order_id":order_id,"credit_value_minor":order.total_amount_minor}))
        result=await self._connector(offer.connector_id).cancel(order.supplier_confirmation_no)
        if result!="CANCELLED": unavailable("STAY_CREDIT_RELEASE_FAILED","Could not release original stay; credit remains reserved for recovery")
        with SessionLocal.begin() as s:
            cr=s.get(StayCreditRow,credit_id); cr.status="ACTIVE"
            r=s.get(OrderRow,order_id); r.status=OrderStatus.CONVERTED_TO_CREDIT.value; r.version+=1; r.updated_at=now_utc()
        repo.append_event(Event(new_id("evt"),"STAY_CREDIT_ACTIVATED","STAY_CREDIT",credit_id,{"order_id":order_id,"scope":"PROPERTY_ONLY","expires_at":expires.isoformat()}))
        with SessionLocal() as s: return self._credit_dict(s.get(StayCreditRow,credit_id))

    def get_credit(self, credit_id: str) -> dict:
        with SessionLocal() as s:
            c=s.get(StayCreditRow,credit_id)
            if not c: not_found("STAY_CREDIT_NOT_FOUND","Stay Credit not found")
            if c.status=="ACTIVE" and _aware(c.expires_at)<=now_utc():
                pass
            return self._credit_dict(c)

    async def redemption_quote(self, credit_id: str, check_in: str, check_out: str) -> dict:
        with SessionLocal() as s:
            c=s.get(StayCreditRow,credit_id)
            if not c: not_found("STAY_CREDIT_NOT_FOUND","Stay Credit not found")
            if c.status!="ACTIVE": conflict("STAY_CREDIT_NOT_ACTIVE","Stay Credit is not active")
            if _aware(c.expires_at)<=now_utc(): unprocessable("STAY_CREDIT_EXPIRED","Stay Credit expired")
            original=s.get(OrderRow,c.original_order_id); pb=s.get(PrebookRow,original.prebook_id); off=s.get(OfferRow,pb.offer_id)
        offers=await self._connector(off.connector_id).search("TYO",check_in,check_out,c.currency)
        candidates=[o for o in offers if o.hotel_id==c.property_id]
        if not candidates: unprocessable("STAY_CREDIT_NO_INVENTORY","No inventory at original property")
        o=candidates[0]; o.supplier_id=original.supplier_id; repo.save_offer_with_event(o,Event(new_id("evt"),"STAY_CREDIT_REDEMPTION_OFFER_CREATED","HOTEL_OFFER",o.offer_id,{"stay_credit_id":credit_id}))
        due=max(o.total_amount_minor-c.credit_value_minor,0); forfeited=max(c.credit_value_minor-o.total_amount_minor,0)
        qid=new_id("scrq"); exp=now_utc()+timedelta(minutes=10)
        with SessionLocal.begin() as s:
            s.add(StayCreditRedemptionQuoteRow(quote_id=qid,stay_credit_id=credit_id,offer_id=o.offer_id,new_value_minor=o.total_amount_minor,credit_value_minor=c.credit_value_minor,amount_due_minor=due,forfeited_difference_minor=forfeited,expires_at=exp,created_at=now_utc()))
        return {"quote_id":qid,"new_value_minor":o.total_amount_minor,"credit_value_minor":c.credit_value_minor,"amount_due_minor":due,"forfeited_difference_minor":forfeited,"lower_price_no_refund_no_balance":True,"expires_at":exp.isoformat()}

    async def redeem(self, credit_id: str, quote_id: str, payment_method_token: str="pm_success") -> dict:
        with SessionLocal() as s:
            c=s.get(StayCreditRow,credit_id); q=s.get(StayCreditRedemptionQuoteRow,quote_id) if c else None
            if not c or not q or q.stay_credit_id!=credit_id: not_found("STAY_CREDIT_REDEMPTION_QUOTE_NOT_FOUND","Redemption quote not found")
            if c.status!="ACTIVE": conflict("STAY_CREDIT_ALREADY_REDEEMED","Stay Credit is not active")
            if _aware(q.expires_at)<=now_utc(): unprocessable("STAY_CREDIT_REDEMPTION_QUOTE_EXPIRED","Redemption quote expired")
            offer=s.get(OfferRow,q.offer_id); original=s.get(OrderRow,c.original_order_id)
        conn=self._connector(offer.connector_id)
        pb=await conn.prebook(repo._offer(offer))
        if pb.status!=PrebookStatus.PREBOOKED: unprocessable("STAY_CREDIT_NO_INVENTORY","Inventory unavailable during redemption")
        repo.save_prebook_with_event(pb,Event(new_id("evt"),"STAY_CREDIT_REDEMPTION_PREBOOKED","PREBOOK",pb.prebook_id,{"stay_credit_id":credit_id}))
        new_order=Order(new_id("ord"),pb.prebook_id,c.property_id,c.account_id,q.new_value_minor,c.currency,OrderStatus.BOOKING_PENDING,supplier_id=original.supplier_id)
        repo.create_order_with_event(new_order,Event(new_id("evt"),"STAY_CREDIT_REDEMPTION_ORDER_CREATED","HOTEL_ORDER",new_order.order_id,{"stay_credit_id":credit_id,"credit_value_minor":c.credit_value_minor,"amount_due_minor":q.amount_due_minor}))
        prepared=None
        if q.amount_due_minor>0:
            try:
                prepared=hotel_money_bridge.prepare_adjustment(new_order.order_id,"HOTEL_STAY_CREDIT_REDEMPTION",quote_id,q.amount_due_minor,f"stay-credit://{credit_id}/quote/{quote_id}",f"stay-credit:{quote_id}")
            except ValueError as exc:
                unavailable("STAY_CREDIT_DIFFERENCE_EXECUTOR_REQUIRED",str(exc))
        try:
            confirmation=await conn.book(new_order.order_id,pb,idempotency_key=quote_id+":book")
        except Exception:
            if prepared: hotel_money_bridge.release_adjustment(prepared,q.amount_due_minor,f"stay-credit-release://{quote_id}",f"stay-credit:{quote_id}")
            raise
        if prepared:
            captured=hotel_money_bridge.capture_adjustment(prepared,q.amount_due_minor,f"stay-credit-capture://{quote_id}",f"stay-credit:{quote_id}")
            repo.append_event(Event(new_id("evt"),"STAY_CREDIT_DIFFERENCE_CAPTURED","HOTEL_ORDER",new_order.order_id,{"amount_minor":q.amount_due_minor,"money_movement_id":captured["capture_id"]}))
        with SessionLocal.begin() as s:
            cr=s.get(StayCreditRow,credit_id); cr.status="REDEEMED"; cr.redemption_order_id=new_order.order_id; cr.redeemed_at=now_utc()
            r=s.get(OrderRow,new_order.order_id); r.status="CONFIRMED"; r.supplier_confirmation_no=confirmation; r.version+=1; r.updated_at=now_utc()
        repo.append_event(Event(new_id("evt"),"STAY_CREDIT_REDEEMED","STAY_CREDIT",credit_id,{"redemption_order_id":new_order.order_id,"amount_due_minor":q.amount_due_minor,"forfeited_difference_minor":q.forfeited_difference_minor}))
        return {"stay_credit_id":credit_id,"status":"REDEEMED","order_id":new_order.order_id,"supplier_confirmation_no":confirmation,"amount_due_minor":q.amount_due_minor,"forfeited_difference_minor":q.forfeited_difference_minor}

    @staticmethod
    def _credit_dict(c):
        return {"stay_credit_id":c.stay_credit_id,"original_order_id":c.original_order_id,"account_id":c.account_id,"property_id":c.property_id,"credit_value_minor":c.credit_value_minor,"currency":c.currency,"scope":"PROPERTY_ONLY","status":c.status,"valid_from":_aware(c.valid_from).isoformat(),"expires_at":_aware(c.expires_at).isoformat(),"redemption_order_id":c.redemption_order_id}

fare_service=FareService()
