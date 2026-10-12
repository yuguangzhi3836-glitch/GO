from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    GoJourneyRow, GoJourneyItemRow, JourneyDisruptionSignalRow,
    JourneyImpactRow, JourneyAdviceRow,
)


def now(): return datetime.now(timezone.utc)

def parse_dt(v):
    if not v: return None
    try: return datetime.fromisoformat(str(v).replace('Z','+00:00'))
    except Exception: return None

def minutes(a,b):
    if not a or not b: return None
    return int((b-a).total_seconds()//60)

class JourneyIntelligenceService:
    """Advisory-only cross-vertical journey intelligence.

    It may detect impact and recommend actions, but it MUST NOT mutate supplier orders.
    Any execution remains in the owning vertical workflow and requires its own rule checks.
    """
    def _journey(self,s,account_id,journey_id):
        j=s.get(GoJourneyRow,journey_id)
        if not j or j.account_id!=account_id: raise ValueError('JOURNEY_NOT_FOUND')
        return j

    def evaluate(self,account_id,journey_id,payload):
        with SessionLocal() as s:
            j=self._journey(s,account_id,journey_id)
            source_item_id=payload.get('source_item_id')
            source=None
            if source_item_id:
                source=s.get(GoJourneyItemRow,source_item_id)
                if not source or source.journey_id!=j.journey_id: raise ValueError('SOURCE_ITEM_NOT_FOUND')
            else:
                source=s.execute(select(GoJourneyItemRow).where(
                    GoJourneyItemRow.journey_id==j.journey_id,
                    GoJourneyItemRow.vertical==str(payload.get('source_vertical','')).upper(),
                    GoJourneyItemRow.order_id==payload.get('source_order_id')
                )).scalar_one_or_none()
                if not source: raise ValueError('SOURCE_ITEM_NOT_FOUND')

            event_type=str(payload.get('event_type') or '').upper()
            facts=payload.get('facts') or {}
            sig=JourneyDisruptionSignalRow(
                signal_id=f"jds_{uuid4().hex[:18]}", journey_id=j.journey_id, account_id=account_id,
                source_item_id=source.item_id, source_vertical=source.vertical, source_order_id=source.order_id,
                event_type=event_type, severity=str(payload.get('severity') or 'MEDIUM').upper(),
                event_at=payload.get('event_at') or now().isoformat(), facts_json=facts,
                status='EVALUATED', created_at=now())
            s.add(sig); s.flush()

            items=s.execute(select(GoJourneyItemRow).where(
                GoJourneyItemRow.journey_id==j.journey_id
            ).order_by(GoJourneyItemRow.sort_key,GoJourneyItemRow.created_at)).scalars().all()
            impacts=[]
            if source.vertical=='FLIGHT' and event_type in {'FLIGHT_DELAY','SCHEDULE_CHANGE','FLIGHT_CANCELLED'}:
                impacts=self._flight_impacts(sig,source,items,facts)
            elif source.vertical=='RAIL' and event_type in {'RAIL_DELAY','RAIL_CANCELLED','SCHEDULE_CHANGE'}:
                impacts=self._rail_impacts(sig,source,items,facts)
            else:
                impacts=self._generic_impacts(sig,source,items,facts)
            for x in impacts: s.add(x)
            s.flush()
            actions=[x.recommended_action_json for x in impacts if x.recommended_action_json]
            summary=self._summary(sig,impacts)
            advice=JourneyAdviceRow(
                advice_id=f"jad_{uuid4().hex[:18]}",journey_id=j.journey_id,account_id=account_id,
                signal_id=sig.signal_id,status='OPEN',summary=summary,recommended_actions_json=actions,
                execution_boundary='ADVISORY_ONLY_VERTICAL_WORKFLOW_REQUIRED',created_at=now(),acknowledged_at=None)
            s.add(advice);s.commit()
            return self._serialize(s,sig,impacts,advice)

    def _impact(self,sig,item,kind,severity,reason,action,confidence=0.9):
        return JourneyImpactRow(
            impact_id=f"jim_{uuid4().hex[:18]}",signal_id=sig.signal_id,journey_id=sig.journey_id,
            account_id=sig.account_id,affected_item_id=item.item_id,affected_vertical=item.vertical,
            affected_order_id=item.order_id,impact_type=kind,severity=severity,reason=reason,
            confidence_milli=int(confidence*1000),status='OPEN',recommended_action_json=action,
            created_at=now())

    def _action(self,item,action,label,requires_user_confirmation,execution_route,auto_execute=False):
        return {
            'action':action,
            'label':label,
            'requires_user_confirmation':requires_user_confirmation,
            'execution_route':execution_route,
            'auto_execute':auto_execute,
            'target':{
                'entity_type':'JOURNEY_ITEM_ORDER',
                'item_id':item.item_id,
                'vertical':item.vertical,
                'order_id':item.order_id,
            },
        }

    def _flight_impacts(self,sig,source,items,facts):
        old_arr=parse_dt(facts.get('original_arrival_at'))
        new_arr=parse_dt(facts.get('estimated_arrival_at')) or parse_dt(facts.get('new_arrival_at'))
        delay=facts.get('delay_minutes')
        if delay is None and old_arr and new_arr: delay=minutes(old_arr,new_arr)
        delay=int(delay or 0)
        impacts=[]
        for item in items:
            if item.item_id==source.item_id: continue
            start=parse_dt(item.starts_at)
            if item.vertical=='RIDE':
                flight_match=(item.facts_json or {}).get('flight_no') and (item.facts_json or {}).get('flight_no')==(source.facts_json or {}).get('flight_number')
                if flight_match or (new_arr and start and abs(minutes(new_arr,start) or 9999)<=180):
                    impacts.append(self._impact(sig,item,'PICKUP_AT_RISK','HIGH',
                        f"航班预计延误 {delay} 分钟，接送机时间可能与实际到达冲突。",
                        self._action(item,'REVIEW_RIDE_PICKUP','检查并调整接送时间',True,item.detail_route)))
            elif item.vertical=='HOTEL':
                impacts.append(self._impact(sig,item,'CHECKIN_CONTEXT_CHANGED','LOW',
                    '到达时间变化，入住提醒与预计抵店时间应同步更新；不自动修改酒店订单。',
                    self._action(item,'ADJUST_CHECKIN_REMINDER','更新入住提醒',False,'Notifications'),0.95))
            elif item.vertical=='RAIL' and new_arr and start:
                gap=minutes(new_arr,start)
                if gap is not None and gap < 120:
                    sev='CRITICAL' if gap<45 else 'HIGH'
                    impacts.append(self._impact(sig,item,'CONNECTION_AT_RISK',sev,
                        f"新预计到达与铁路发车仅剩约 {max(gap,0)} 分钟，存在衔接风险。",
                        self._action(item,'REVIEW_RAIL_CHANGE','查看铁路改签方案',True,item.detail_route)))
            elif item.vertical=='ATTRACTION' and new_arr and start:
                gap=minutes(new_arr,start)
                if gap is not None and gap < 180:
                    impacts.append(self._impact(sig,item,'ACTIVITY_AT_RISK','MEDIUM',
                        '航班延误可能影响已预约的场次或入场时间。',
                        self._action(item,'REVIEW_ATTRACTION_CHANGE','查看门票/体验改期规则',True,item.detail_route),0.8))
        return impacts

    def _rail_impacts(self,sig,source,items,facts):
        new_arr=parse_dt(facts.get('estimated_arrival_at'))
        impacts=[]
        for item in items:
            if item.item_id==source.item_id: continue
            start=parse_dt(item.starts_at)
            if item.vertical in {'RIDE','RENTAL','ATTRACTION'} and new_arr and start:
                gap=minutes(new_arr,start)
                if gap is not None and gap<90:
                    impacts.append(self._impact(sig,item,'DOWNSTREAM_TIMING_AT_RISK','HIGH',
                        f"铁路到达变化后与下一项安排仅剩约 {max(gap,0)} 分钟。",
                        self._action(item,'REVIEW_DOWNSTREAM_ORDER','检查后续安排',True,item.detail_route)))
        return impacts

    def _generic_impacts(self,sig,source,items,facts):
        return []

    def _summary(self,sig,impacts):
        if not impacts: return 'GO 已检查本次变化，暂未发现明确的后续行程冲突。'
        high=sum(1 for x in impacts if x.severity in {'HIGH','CRITICAL'})
        return f"GO 检测到 {len(impacts)} 项可能受影响的后续安排，其中 {high} 项需要优先确认。所有实际修改仍需进入对应供应商/品类规则。"

    def latest(self,account_id,journey_id):
        with SessionLocal() as s:
            self._journey(s,account_id,journey_id)
            sig=s.execute(select(JourneyDisruptionSignalRow).where(
                JourneyDisruptionSignalRow.journey_id==journey_id,
                JourneyDisruptionSignalRow.account_id==account_id
            ).order_by(JourneyDisruptionSignalRow.created_at.desc())).scalars().first()
            if not sig: return None
            impacts=s.execute(select(JourneyImpactRow).where(JourneyImpactRow.signal_id==sig.signal_id)).scalars().all()
            advice=s.execute(select(JourneyAdviceRow).where(JourneyAdviceRow.signal_id==sig.signal_id).order_by(JourneyAdviceRow.created_at.desc())).scalars().first()
            return self._serialize(s,sig,impacts,advice)

    def acknowledge(self,account_id,journey_id,advice_id):
        with SessionLocal() as s:
            self._journey(s,account_id,journey_id)
            a=s.get(JourneyAdviceRow,advice_id)
            if not a or a.account_id!=account_id or a.journey_id!=journey_id: raise ValueError('ADVICE_NOT_FOUND')
            a.status='ACKNOWLEDGED';a.acknowledged_at=now();s.commit();return {'advice_id':a.advice_id,'status':a.status}

    def _serialize(self,s,sig,impacts,advice):
        return {
            'signal':{'signal_id':sig.signal_id,'event_type':sig.event_type,'severity':sig.severity,'source_vertical':sig.source_vertical,'source_order_id':sig.source_order_id,'facts':sig.facts_json,'status':sig.status},
            'impacts':[{'impact_id':x.impact_id,'affected_item_id':x.affected_item_id,'vertical':x.affected_vertical,'order_id':x.affected_order_id,'impact_type':x.impact_type,'severity':x.severity,'reason':x.reason,'confidence':x.confidence_milli/1000,'status':x.status,'recommended_action':x.recommended_action_json} for x in impacts],
            'advice':None if not advice else {'advice_id':advice.advice_id,'status':advice.status,'summary':advice.summary,'actions':advice.recommended_actions_json,'execution_boundary':advice.execution_boundary,'created_at':advice.created_at.isoformat()},
            'auto_mutation_performed':False,
        }

journey_intelligence_service=JourneyIntelligenceService()
