from __future__ import annotations
from datetime import datetime, timezone, timedelta, time
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import EventRow, OrderRow, ReviewSessionRow, MobileEngagementJobRow, PrebookRow, OfferRow
from go_hotel.mobile.service import mobile_service
from go_hotel.truth.service import truth_service
UTC=timezone.utc

def now(): return datetime.now(UTC)
def jid():
    import uuid
    return f"meng_{uuid.uuid4().hex}"

def parse_checkin(value):
    if not value: return None
    if isinstance(value, datetime): return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        d=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except Exception:
        try:
            d=datetime.strptime(str(value),'%Y-%m-%d').date()
            return datetime.combine(d,time(hour=9),tzinfo=UTC)
        except Exception: return None

class MobileEngagementOrchestrator:
    """Turns immutable domain facts into idempotent mobile engagement jobs.

    It never changes booking/payment truth and never invents fulfillment facts. Domain facts create
    deduped scheduled intents; a separate delivery worker creates consumer notifications/push jobs.
    """
    EVENT_COPY={
      "ORDER_CONFIRMED":("BOOKING_CONFIRMED","预订成功","酒店已确认你的预订。"),
      "REFUND_COMPLETED":("REFUND_COMPLETED","退款已完成","退款已完成，请在 GO Trips 查看到账状态。"),
      "COMPENSATION_COMPLETED":("COMPENSATION_COMPLETED","履约赔付已完成","酒店责任赔付已完成，请查看订单资金明细。"),
    }
    def _enqueue(self,*,dedupe_key,user_id,event_type,notification_type,title,body,deep_link=None,payload=None,scheduled_at=None,order_id=None,review_id=None):
        with SessionLocal.begin() as s:
            if s.scalar(select(MobileEngagementJobRow).where(MobileEngagementJobRow.dedupe_key==dedupe_key)): return False
            s.add(MobileEngagementJobRow(job_id=jid(),dedupe_key=dedupe_key,user_id=user_id,order_id=order_id,review_id=review_id,event_type=event_type,notification_type=notification_type,title=title,body=body,deep_link=deep_link,payload_json=payload or {},scheduled_at=scheduled_at or now(),status="SCHEDULED",created_at=now()))
        return True
    def _order_checkin(self,s,order):
        pb=s.get(PrebookRow,order.prebook_id) if order.prebook_id else None
        off=s.get(OfferRow,pb.offer_id) if pb else None
        return parse_checkin(off.check_in if off else None)
    def ingest_domain_events(self,limit=500):
        created=0
        with SessionLocal() as s:
            events=s.scalars(select(EventRow).order_by(EventRow.occurred_at.desc()).limit(limit)).all()
            order_ids=[e.aggregate_id for e in events]
            orders={o.order_id:o for o in s.scalars(select(OrderRow).where(OrderRow.order_id.in_(order_ids))).all()} if order_ids else {}
            reviews={r.order_id:r for r in s.scalars(select(ReviewSessionRow).where(ReviewSessionRow.order_id.in_(list(orders.keys())))).all()} if orders else {}
            checkins={oid:self._order_checkin(s,o) for oid,o in orders.items()}
        for e in reversed(events):
            order=orders.get(e.aggregate_id)
            if not order: continue
            if e.event_type in self.EVENT_COPY:
                typ,title,body=self.EVENT_COPY[e.event_type]
                created+=int(self._enqueue(dedupe_key=f"event:{e.event_id}",user_id=order.account_id,event_type=e.event_type,notification_type=typ,title=title,body=body,deep_link=f"go://trips/order/{order.order_id}",payload={"order_id":order.order_id,**(e.payload or {})},order_id=order.order_id))
                if e.event_type=="ORDER_CONFIRMED":
                    ci=checkins.get(order.order_id)
                    if ci:
                        # 24h before check-in; if already inside that window, deliver shortly after ingestion.
                        due=max(now()+timedelta(seconds=1),ci-timedelta(hours=24))
                        created+=int(self._enqueue(dedupe_key=f"checkin:{order.order_id}",user_id=order.account_id,event_type="CHECKIN_REMINDER_DUE",notification_type="CHECKIN_REMINDER",title="即将入住",body="你的酒店行程即将开始，打开 GO 查看入住信息。",deep_link=f"go://trips/order/{order.order_id}",payload={"order_id":order.order_id},scheduled_at=due,order_id=order.order_id))
            if e.event_type=="FULFILLMENT_COMPLETED":
                review=reviews.get(order.order_id)
                if not review:
                    try: truth_service.create_eligibility(order.order_id,True,"FIRST_INVITE")
                    except Exception: pass
                    with SessionLocal() as s: review=s.scalar(select(ReviewSessionRow).where(ReviewSessionRow.order_id==order.order_id))
                if review and review.status!="COMPLETED":
                    # deterministic four-hour default inside the locked 2-10 hour product window.
                    due=e.occurred_at+timedelta(hours=4)
                    created+=int(self._enqueue(dedupe_key=f"review-first:{review.review_id}",user_id=order.account_id,event_type=e.event_type,notification_type="FIRST_REVIEW_INVITE",title="这次入住怎么样？",body="用几秒告诉 GO 这次真实入住体验。",deep_link=f"go://reviews/{review.review_id}",payload={"order_id":order.order_id,"review_id":review.review_id},scheduled_at=due,order_id=order.order_id,review_id=review.review_id))
        return created
    def schedule_checkin_reminder(self,order_id,user_id,when:datetime):
        return self._enqueue(dedupe_key=f"checkin:{order_id}",user_id=user_id,event_type="CHECKIN_REMINDER_DUE",notification_type="CHECKIN_REMINDER",title="即将入住",body="你的酒店行程即将开始，打开 GO 查看入住信息。",deep_link=f"go://trips/order/{order_id}",payload={"order_id":order_id},scheduled_at=when,order_id=order_id)
    def process_due(self,limit=100):
        done=0
        with SessionLocal() as s:
            jobs=s.scalars(select(MobileEngagementJobRow).where(MobileEngagementJobRow.status=="SCHEDULED",MobileEngagementJobRow.scheduled_at<=now()).order_by(MobileEngagementJobRow.scheduled_at).limit(limit)).all()
            ids=[j.job_id for j in jobs]
        for job_id in ids:
            with SessionLocal() as s:
                j=s.get(MobileEngagementJobRow,job_id)
                if not j or j.status!="SCHEDULED": continue
                if j.review_id:
                    r=s.get(ReviewSessionRow,j.review_id)
                    if not r or r.status=="COMPLETED":
                        j.status="CANCELLED"; j.processed_at=now(); s.commit(); continue
                user_id=j.user_id; typ=j.notification_type; title=j.title; body=j.body; link=j.deep_link; payload=j.payload_json; review_id=j.review_id
            if review_id:
                try:
                    truth_service.send_first_invite(review_id)
                    truth_service.mark_not_reviewed(review_id)
                except Exception: pass
            mobile_service.create_notification(user_id,typ,title,body,link,payload)
            with SessionLocal.begin() as s:
                j=s.get(MobileEngagementJobRow,job_id)
                if j and j.status=="SCHEDULED": j.status="DELIVERED"; j.processed_at=now()
            done+=1
        return done
    def on_app_open(self,user_id):
        pending=truth_service.pending(user_id)
        if not pending: return {"action":"NONE"}
        # Only the newest pending completed-stay review blocks the next app entry.
        r=pending[0]
        if r.get("status") in {"ELIGIBLE","FIRST_INVITE_SENT"}:
            try: truth_service.mark_not_reviewed(r["review_id"])
            except Exception: pass
            r=truth_service.get_review(r["review_id"])
        if r.get("status")=="NOT_REVIEWED": r=truth_service.trigger_second(r["review_id"])
        if r.get("status")=="COMPLETED": return {"action":"NONE"}
        return {"action":"SHOW_QUICK_REVIEW","review_id":r["review_id"],"deep_link":f"go://reviews/{r['review_id']}"}
    def jobs(self,user_id=None):
        with SessionLocal() as s:
            q=select(MobileEngagementJobRow).order_by(MobileEngagementJobRow.created_at.desc())
            if user_id: q=q.where(MobileEngagementJobRow.user_id==user_id)
            rows=s.scalars(q.limit(100)).all()
            return [{"job_id":x.job_id,"dedupe_key":x.dedupe_key,"user_id":x.user_id,"order_id":x.order_id,"review_id":x.review_id,"event_type":x.event_type,"notification_type":x.notification_type,"scheduled_at":x.scheduled_at.isoformat(),"status":x.status} for x in rows]
mobile_engagement=MobileEngagementOrchestrator()
