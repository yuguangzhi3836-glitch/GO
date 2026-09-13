from __future__ import annotations
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import GoJourneyRow, GoJourneyItemRow, JourneyAdviceRow, JourneyImpactRow, JourneyRecoveryPlanRow, JourneyRecoveryOptionRow


def now(): return datetime.now(timezone.utc)

def parse_dt(v):
    if not v: return None
    try: return datetime.fromisoformat(str(v).replace('Z','+00:00'))
    except Exception: return None

def iso(v): return v.isoformat() if v else None

class JourneyRecoveryService:
    """Builds comparison-ready recovery options without bypassing vertical rules.

    Options are quote-like, expiring facts. Selection does NOT mutate supplier orders.
    Execution must happen through the indicated vertical workflow.
    """
    def _journey(self,s,account_id,journey_id):
        j=s.get(GoJourneyRow,journey_id)
        if not j or j.account_id!=account_id: raise ValueError('JOURNEY_NOT_FOUND')
        return j

    def build(self,account_id,journey_id,advice_id=None):
        with SessionLocal() as s:
            j=self._journey(s,account_id,journey_id)
            advice = s.get(JourneyAdviceRow,advice_id) if advice_id else s.execute(select(JourneyAdviceRow).where(JourneyAdviceRow.journey_id==journey_id,JourneyAdviceRow.account_id==account_id).order_by(JourneyAdviceRow.created_at.desc())).scalars().first()
            if not advice or advice.account_id!=account_id: raise ValueError('ADVICE_NOT_FOUND')
            impacts=s.execute(select(JourneyImpactRow).where(JourneyImpactRow.signal_id==advice.signal_id).order_by(JourneyImpactRow.created_at)).scalars().all()
            plan=JourneyRecoveryPlanRow(plan_id=f"jrp_{uuid4().hex[:18]}",journey_id=journey_id,account_id=account_id,advice_id=advice.advice_id,status='READY',currency='CNY',summary='GO 已拉取受影响节点的可执行恢复选项。请比较后选择；实际执行仍进入各品类规则与供应商确认。',selected_option_ids_json=[],execution_boundary='SELECT_ONLY_NO_AUTO_MUTATION',expires_at=now()+timedelta(minutes=15),created_at=now(),updated_at=now())
            s.add(plan);s.flush()
            options=[]
            for impact in impacts:
                item=s.get(GoJourneyItemRow,impact.affected_item_id)
                if not item: continue
                options += self._options_for(plan,item,impact)
            for o in options:s.add(o)
            s.commit()
            return self._serialize(plan,options)

    def _opt(self,plan,item,impact,kind,title,subtitle,total_delta_minor,rank,execution_route,facts,requires_confirmation=True):
        return JourneyRecoveryOptionRow(option_id=f"jro_{uuid4().hex[:18]}",plan_id=plan.plan_id,journey_id=plan.journey_id,account_id=plan.account_id,impact_id=impact.impact_id,vertical=item.vertical,order_id=item.order_id,option_type=kind,title=title,subtitle=subtitle,total_delta_minor=total_delta_minor,currency=plan.currency,rank_score=rank,status='AVAILABLE',execution_route=execution_route,requires_user_confirmation=requires_confirmation,quote_facts_json=facts,expires_at=plan.expires_at,created_at=now())

    def _options_for(self,plan,item,impact):
        start=parse_dt(item.starts_at)
        route=item.detail_route
        facts=item.facts_json or {}
        out=[]
        if item.vertical=='RIDE':
            out.append(self._opt(plan,item,impact,'RESCHEDULE','延后接送时间','把接送调整到预计落地后 60 分钟',0,980,route,{'pickup_at':iso((start+timedelta(hours=2)) if start else None),'supplier_revalidation_required':True}))
            out.append(self._opt(plan,item,impact,'KEEP','保留原接送','不修改订单，承担误车/等待风险',0,520,route,{'current_pickup_at':item.starts_at,'risk':'PICKUP_MISS_POSSIBLE'}))
        elif item.vertical=='RAIL':
            out.append(self._opt(plan,item,impact,'CHANGE','下一班铁路','建议改到晚 2 小时的班次；最终席位与差价需重新确认',12000,940,route,{'proposed_departure_at':iso((start+timedelta(hours=2)) if start else None),'seat_class':facts.get('seat_class'),'inventory_revalidation_required':True,'fare_difference_estimate_minor':12000}))
            out.append(self._opt(plan,item,impact,'KEEP','保留当前车次','不产生改签费用，但衔接风险较高',0,410,route,{'current_departure_at':item.starts_at,'risk':'CONNECTION_MISS_POSSIBLE'}))
        elif item.vertical=='HOTEL':
            out.append(self._opt(plan,item,impact,'LATE_ARRIVAL_NOTICE','确认晚到保留','向酒店发送预计晚到信息；不改变房价和入住日期',0,995,route,{'late_arrival_notice':True,'supplier_ack_required':True},True))
            out.append(self._opt(plan,item,impact,'KEEP','保持酒店订单','订单本身不修改，仅更新 GO 入住提醒',0,900,route,{'reminder_only':True},False))
        elif item.vertical=='ATTRACTION':
            out.append(self._opt(plan,item,impact,'CHANGE_SESSION','改到下一场','尝试更换至晚 2 小时场次；库存和费用需重新确认',0,900,route,{'proposed_session_at':iso((start+timedelta(hours=2)) if start else None),'inventory_revalidation_required':True}))
            out.append(self._opt(plan,item,impact,'KEEP','保留原场次','不修改，但可能因延误无法入场',0,350,route,{'risk':'ENTRY_MISS_POSSIBLE'}))
        elif item.vertical=='RENTAL':
            out.append(self._opt(plan,item,impact,'MODIFY_PICKUP','延后取车','延后取车时间，价格与库存需重新确认',0,880,route,{'proposed_pickup_at':iso((start+timedelta(hours=2)) if start else None),'supplier_revalidation_required':True}))
        return out

    def get(self,account_id,journey_id,plan_id):
        with SessionLocal() as s:
            self._journey(s,account_id,journey_id)
            p=s.get(JourneyRecoveryPlanRow,plan_id)
            if not p or p.account_id!=account_id or p.journey_id!=journey_id: raise ValueError('RECOVERY_PLAN_NOT_FOUND')
            opts=s.execute(select(JourneyRecoveryOptionRow).where(JourneyRecoveryOptionRow.plan_id==plan_id).order_by(JourneyRecoveryOptionRow.rank_score.desc())).scalars().all()
            return self._serialize(p,opts)

    def select(self,account_id,journey_id,plan_id,option_ids):
        with SessionLocal() as s:
            self._journey(s,account_id,journey_id)
            p=s.get(JourneyRecoveryPlanRow,plan_id)
            if not p or p.account_id!=account_id or p.journey_id!=journey_id: raise ValueError('RECOVERY_PLAN_NOT_FOUND')
            if p.expires_at and p.expires_at.replace(tzinfo=p.expires_at.tzinfo or timezone.utc) < now(): raise ValueError('RECOVERY_PLAN_EXPIRED')
            opts=s.execute(select(JourneyRecoveryOptionRow).where(JourneyRecoveryOptionRow.plan_id==plan_id)).scalars().all()
            by_id={o.option_id:o for o in opts}
            chosen=[];seen_impacts=set()
            for oid in option_ids:
                o=by_id.get(oid)
                if not o or o.status!='AVAILABLE': raise ValueError('RECOVERY_OPTION_NOT_AVAILABLE')
                if o.impact_id in seen_impacts: raise ValueError('ONE_OPTION_PER_IMPACT')
                seen_impacts.add(o.impact_id);chosen.append(o)
            p.selected_option_ids_json=[o.option_id for o in chosen];p.status='SELECTED';p.updated_at=now();s.commit()
            return {'plan_id':p.plan_id,'status':p.status,'selected_options':[self._option(o) for o in chosen],'auto_mutation_performed':False,'next_step':'EXECUTE_EACH_OPTION_VIA_VERTICAL_WORKFLOW'}

    def _option(self,o):
        return {'option_id':o.option_id,'impact_id':o.impact_id,'vertical':o.vertical,'order_id':o.order_id,'option_type':o.option_type,'title':o.title,'subtitle':o.subtitle,'total_delta_minor':o.total_delta_minor,'currency':o.currency,'rank_score':o.rank_score,'status':o.status,'execution_route':o.execution_route,'requires_user_confirmation':o.requires_user_confirmation,'quote_facts':o.quote_facts_json,'expires_at':o.expires_at.isoformat()}
    def _serialize(self,p,opts):
        return {'plan_id':p.plan_id,'journey_id':p.journey_id,'advice_id':p.advice_id,'status':p.status,'summary':p.summary,'currency':p.currency,'expires_at':p.expires_at.isoformat(),'execution_boundary':p.execution_boundary,'selected_option_ids':p.selected_option_ids_json,'options':[self._option(o) for o in sorted(opts,key=lambda x:x.rank_score,reverse=True)],'auto_mutation_performed':False}

journey_recovery_service=JourneyRecoveryService()
