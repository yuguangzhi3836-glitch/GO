from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    OrderRow, ReviewSessionRow, ReviewTagRow, RiskEventRuntimeRow,
    RiskEvidenceRuntimeRow, RiskRemediationRow, JudgmentHookRow,
)
from go_hotel.domain.models import Event, OrderStatus, new_id, now_utc
from go_hotel.repositories.sql import repo
from go_hotel.core.errors import not_found, conflict, unprocessable

TAG_MAP = {
    "CHECKIN_WAIT_TOO_LONG": ("CHECK_IN", "NEGATIVE", "NORMAL", ["CHECK_IN", "SERVICE"]),
    "ROOM_NOT_AS_BOOKED": ("ORDER", "NEGATIVE", "MATERIAL", ["ROOM_ACCURACY", "CHECK_IN"]),
    "ROOM_NOT_CLEAN": ("CLEANLINESS", "NEGATIVE", "NORMAL", ["CLEANLINESS"]),
    "BATHROOM_HYGIENE": ("CLEANLINESS", "NEGATIVE", "MATERIAL", ["CLEANLINESS"]),
    "BEDDING_HYGIENE": ("CLEANLINESS", "NEGATIVE", "MATERIAL", ["CLEANLINESS", "SLEEP"]),
    "SERVICE_SLOW": ("SERVICE", "NEGATIVE", "NORMAL", ["SERVICE"]),
    "NOISE_SLEEP": ("SLEEP", "NEGATIVE", "NORMAL", ["SLEEP"]),
    "BREAKFAST_ISSUE": ("DINING", "NEGATIVE", "NORMAL", ["BREAKFAST"]),
    "BENEFIT_NOT_HONORED": ("BENEFIT", "NEGATIVE", "MATERIAL", ["BENEFIT_FULFILLMENT", "SERVICE"]),
    "ABNORMAL_CHARGE": ("CHARGE", "NEGATIVE", "SERIOUS", ["BILLING"]),
    "SERIOUS_HYGIENE": ("CLEANLINESS", "NEGATIVE", "SERIOUS", ["CLEANLINESS"]),
    "SAFETY": ("SAFETY", "NEGATIVE", "SERIOUS", ["SAFETY"]),
    "NO_ROOM": ("FULFILLMENT", "NEGATIVE", "SERIOUS", ["FULFILLMENT"]),
    "FRAUD": ("FRAUD", "NEGATIVE", "SERIOUS", ["TRUST"]),
    "ROOM_VERY_CLEAN": ("CLEANLINESS", "POSITIVE", "NORMAL", ["CLEANLINESS"]),
    "GREAT_SERVICE": ("SERVICE", "POSITIVE", "NORMAL", ["SERVICE"]),
    "SLEPT_WELL": ("SLEEP", "POSITIVE", "NORMAL", ["SLEEP"]),
    "GREAT_LOCATION": ("LOCATION", "POSITIVE", "NORMAL", ["LOCATION"]),
    "GOOD_BREAKFAST": ("DINING", "POSITIVE", "NORMAL", ["BREAKFAST"]),
    "BENEFITS_HONORED": ("BENEFIT", "POSITIVE", "NORMAL", ["BENEFIT_FULFILLMENT"]),
}
RISK_TAGS={"SERIOUS_HYGIENE":"SERIOUS_HYGIENE","SAFETY":"SAFETY","NO_ROOM":"NO_ROOM","FRAUD":"FRAUD","ABNORMAL_CHARGE":"ABNORMAL_CHARGE"}

class TruthService:
    def create_eligibility(self, order_id:str, verified_stay:bool, trigger_source:str="FIRST_INVITE") -> dict:
        with SessionLocal() as s:
            order=s.get(OrderRow,order_id)
            if not order: not_found("ORDER_NOT_FOUND","Order not found")
            existing=s.scalar(select(ReviewSessionRow).where(ReviewSessionRow.order_id==order_id))
            if existing: return self.get_review(existing.review_id)
            if not verified_stay: unprocessable("REVIEW_ORDER_NOT_VERIFIED","Verified stay is required")
            if order.status not in (OrderStatus.CONFIRMED.value,):
                unprocessable("REVIEW_NOT_ELIGIBLE","Only a verified fulfilled booking can become review eligible")
            rid=new_id("rev"); now=now_utc()
        with SessionLocal.begin() as s:
            s.add(ReviewSessionRow(review_id=rid,order_id=order_id,hotel_id=order.hotel_id,account_id=order.account_id,verified_stay=True,trigger_source=trigger_source,status="ELIGIBLE",trust_weight_bps=10000,public_status="PENDING",dimension_result={},photo_refs=[],created_at=now,updated_at=now))
        repo.append_event(Event(new_id("evt"),"REVIEW_ELIGIBLE","REVIEW",rid,{"order_id":order_id,"verified_stay":True}))
        return self.get_review(rid)

    def send_first_invite(self, review_id:str)->dict:
        with SessionLocal.begin() as s:
            r=s.get(ReviewSessionRow,review_id)
            if not r: not_found("REVIEW_NOT_FOUND","Review not found")
            if r.completed_at is not None: return self._review_dict(r, s)
            if r.status not in ("ELIGIBLE","FIRST_INVITE_SENT","NOT_REVIEWED"):
                conflict("REVIEW_STATE_CONFLICT","Review cannot receive first invite")
            r.status="FIRST_INVITE_SENT"; r.trigger_source="FIRST_INVITE"; r.updated_at=now_utc()
        repo.append_event(Event(new_id("evt"),"FIRST_REVIEW_INVITE_SENT","REVIEW",review_id,{}))
        return self.get_review(review_id)

    def mark_not_reviewed(self, review_id:str)->dict:
        with SessionLocal.begin() as s:
            r=s.get(ReviewSessionRow,review_id)
            if not r: not_found("REVIEW_NOT_FOUND","Review not found")
            if r.completed_at is not None: return self._review_dict(r,s)
            r.status="NOT_REVIEWED"; r.updated_at=now_utc()
        return self.get_review(review_id)

    def pending(self, account_id:str)->list[dict]:
        with SessionLocal() as s:
            rows=s.scalars(select(ReviewSessionRow).where(ReviewSessionRow.account_id==account_id,ReviewSessionRow.status.in_(["NOT_REVIEWED","SECOND_TRIGGERED"])).order_by(ReviewSessionRow.created_at.desc())).all()
            return [self._review_dict(r,s) for r in rows]

    def trigger_second(self, review_id:str)->dict:
        with SessionLocal.begin() as s:
            r=s.get(ReviewSessionRow,review_id)
            if not r: not_found("REVIEW_NOT_FOUND","Review not found")
            if r.completed_at is not None: return self._review_dict(r,s)
            if r.status not in ("NOT_REVIEWED","SECOND_TRIGGERED"):
                conflict("REVIEW_STATE_CONFLICT","Second trigger requires NOT_REVIEWED")
            r.status="SECOND_TRIGGERED"; r.trigger_source="SECOND_QUICK_REVIEW"; r.updated_at=now_utc()
        repo.append_event(Event(new_id("evt"),"SECOND_REVIEW_TRIGGERED","REVIEW",review_id,{}))
        return self.get_review(review_id)

    def submit_star(self, review_id:str, star:int)->dict:
        if star < 1 or star > 5: unprocessable("REVIEW_STAR_INVALID","Star must be between 1 and 5")
        with SessionLocal.begin() as s:
            r=s.get(ReviewSessionRow,review_id)
            if not r: not_found("REVIEW_NOT_FOUND","Review not found")
            if r.completed_at is not None: conflict("REVIEW_ALREADY_COMPLETED","Review submission is immutable after completion")
            r.raw_star_input=star; r.updated_at=now_utc()
        repo.append_event(Event(new_id("evt"),"RAW_STAR_SUBMITTED","REVIEW",review_id,{"star":star}))
        if star in (4,5): return self.complete(review_id)
        return self.get_review(review_id)

    def add_tags(self, review_id:str, tags:list[str])->dict:
        if not tags: unprocessable("REVIEW_TAG_REQUIRED","At least one tag is required")
        now=now_utc()
        with SessionLocal.begin() as s:
            r=s.get(ReviewSessionRow,review_id)
            if not r: not_found("REVIEW_NOT_FOUND","Review not found")
            if r.completed_at is not None: conflict("REVIEW_ALREADY_COMPLETED","Review submission is immutable after completion")
            for code in tags[:5]:
                if code not in TAG_MAP: unprocessable("REVIEW_TAG_INVALID",f"Unknown review tag: {code}")
                cat,pol,sev,dims=TAG_MAP[code]
                existing=s.scalar(select(ReviewTagRow).where(ReviewTagRow.review_id==review_id,ReviewTagRow.tag_code==code))
                if not existing: s.add(ReviewTagRow(review_tag_id=new_id("rtag"),review_id=review_id,category=cat,tag_code=code,polarity=pol,severity=sev,mapped_dimensions=dims,created_at=now))
            r.updated_at=now
        repo.append_event(Event(new_id("evt"),"REVIEW_TAGS_SUBMITTED","REVIEW",review_id,{"tags":tags[:5]}))
        return self.get_review(review_id)

    def add_content(self, review_id:str,text:str|None,voice_ref:str|None,photo_refs:list[str])->dict:
        with SessionLocal.begin() as s:
            r=s.get(ReviewSessionRow,review_id)
            if not r: not_found("REVIEW_NOT_FOUND","Review not found")
            if r.completed_at is not None: conflict("REVIEW_ALREADY_COMPLETED","Review submission is immutable after completion")
            r.content_text=text; r.voice_ref=voice_ref; r.photo_refs=photo_refs; r.updated_at=now_utc()
        return self.get_review(review_id)

    def _experience(self, star:int,tags:list[ReviewTagRow])->tuple[int,dict]:
        # User raw 1-5 is not public score. Public normal-experience contribution is clamped to 3.0-5.0.
        base={1:3300,2:3500,3:3800,4:4400,5:4900}[star]
        dims={}
        for t in tags:
            for d in t.mapped_dimensions:
                dims[d] = "NEGATIVE" if t.polarity=="NEGATIVE" else "POSITIVE"
        serious=sum(1 for t in tags if t.severity=="SERIOUS")
        score=max(3000,min(5000,base - serious*100))
        return score,dims

    def complete(self,review_id:str)->dict:
        now=now_utc(); risk_codes=[]
        with SessionLocal.begin() as s:
            r=s.get(ReviewSessionRow,review_id)
            if not r: not_found("REVIEW_NOT_FOUND","Review not found")
            if r.completed_at is not None: return self._review_dict(r,s)
            if r.raw_star_input is None: unprocessable("REVIEW_STAR_REQUIRED","Star input is required")
            tags=s.scalars(select(ReviewTagRow).where(ReviewTagRow.review_id==review_id)).all()
            if r.raw_star_input <=3 and not tags: unprocessable("REVIEW_TAG_REQUIRED","1-3 stars require at least one structured issue tag")
            score,dims=self._experience(r.raw_star_input,tags)
            r.experience_score_milli=score; r.dimension_result=dims; r.status="COMPLETED"; r.public_status="PUBLISHED"; r.completed_at=now; r.updated_at=now
            risk_codes=[t.tag_code for t in tags if t.tag_code in RISK_TAGS]
        repo.append_event(Event(new_id("evt"),"REVIEW_COMPLETED","REVIEW",review_id,{"experience_score_milli":score,"raw_star_input":r.raw_star_input}))
        created=[]
        for code in risk_codes:
            created.append(self._create_risk_candidate(review_id,code))
        out=self.get_review(review_id); out["risk_candidates"]=created
        return out

    def _create_risk_candidate(self,review_id:str,tag_code:str)->dict:
        with SessionLocal() as s:
            r=s.get(ReviewSessionRow,review_id)
            existing=s.scalar(select(RiskEventRuntimeRow).where(RiskEventRuntimeRow.review_id==review_id,RiskEventRuntimeRow.risk_type==RISK_TAGS[tag_code]))
            if existing: return self.get_risk(existing.risk_event_id)
            rid=new_id("risk"); now=now_utc(); photos=list(r.photo_refs or []); text=r.content_text
        with SessionLocal.begin() as s:
            s.add(RiskEventRuntimeRow(risk_event_id=rid,hotel_id=r.hotel_id,order_id=r.order_id,review_id=review_id,risk_type=RISK_TAGS[tag_code],severity="R2",status="CANDIDATE",confidence_bps=2500,rule_version="RISK_RULES_1.0",created_at=now,updated_at=now))
            s.add(RiskEvidenceRuntimeRow(evidence_id=new_id("evd"),risk_event_id=rid,source_actor="SYSTEM",evidence_type="VERIFIED_STAY",payload={"verified_stay":True,"order_id":r.order_id},credibility_bps=10000,created_at=now))
            if text: s.add(RiskEvidenceRuntimeRow(evidence_id=new_id("evd"),risk_event_id=rid,source_actor="GUEST",evidence_type="REVIEW_TEXT",payload={"text":text},credibility_bps=6000,created_at=now))
            for p in photos: s.add(RiskEvidenceRuntimeRow(evidence_id=new_id("evd"),risk_event_id=rid,source_actor="GUEST",evidence_type="PHOTO",content_ref=p,payload={},credibility_bps=7500,created_at=now))
        repo.append_event(Event(new_id("evt"),"RISK_EVENT_CANDIDATE_CREATED","RISK_EVENT",rid,{"review_id":review_id,"risk_type":RISK_TAGS[tag_code]}))
        return self.get_risk(rid)

    def supplier_evidence(self,risk_event_id:str,evidence_type:str,payload:dict,content_ref:str|None=None)->dict:
        with SessionLocal.begin() as s:
            risk=s.get(RiskEventRuntimeRow,risk_event_id)
            if not risk: not_found("RISK_EVENT_NOT_FOUND","Risk event not found")
            if risk.status in ("REJECTED","REVERSED","ARCHIVED"): conflict("RISK_EVENT_ALREADY_FINALIZED","Risk event is finalized")
            eid=new_id("evd")
            s.add(RiskEvidenceRuntimeRow(evidence_id=eid,risk_event_id=risk_event_id,source_actor="SUPPLIER",evidence_type=evidence_type,content_ref=content_ref,payload=payload,credibility_bps=7000,created_at=now_utc()))
            risk.status="UNDER_REVIEW"; risk.updated_at=now_utc()
        repo.append_event(Event(new_id("evt"),"SUPPLIER_EVIDENCE_SUBMITTED","RISK_EVENT",risk_event_id,{"evidence_id":eid}))
        return self.get_risk(risk_event_id)

    def decide_risk(self,risk_event_id:str,decision:str,confidence_bps:int=8000)->dict:
        allowed={"CONFIRM":"CONFIRMED","DOWNGRADE":"DOWNGRADED","REJECT":"REJECTED"}
        if decision not in allowed: unprocessable("RISK_DECISION_INVALID","Unsupported risk decision")
        now=now_utc(); status=allowed[decision]; did=new_id("dec")
        with SessionLocal.begin() as s:
            risk=s.get(RiskEventRuntimeRow,risk_event_id)
            if not risk: not_found("RISK_EVENT_NOT_FOUND","Risk event not found")
            if risk.status in ("REJECTED","REVERSED","ARCHIVED"): conflict("RISK_EVENT_ALREADY_FINALIZED","Risk event is finalized")
            risk.status=status; risk.confidence_bps=max(0,min(10000,confidence_bps)); risk.decision_id=did; risk.updated_at=now
            if status=="CONFIRMED":
                risk.confirmed_at=now; risk.public_notice={"type":risk.risk_type,"status":"CONFIRMED","message":"A verified serious fulfillment risk event was recorded."}
                hook=new_id("jhook"); s.add(JudgmentHookRow(hook_id=hook,hotel_id=risk.hotel_id,source_type="RISK_EVENT",source_id=risk_event_id,reason_code="RISK_EVENT_CONFIRMED",status="REQUESTED",payload={"decision_id":did,"risk_type":risk.risk_type,"severity":risk.severity},created_at=now))
            elif status=="REJECTED": risk.public_notice=None
        repo.append_event(Event(new_id("evt"),f"RISK_EVENT_{status}","RISK_EVENT",risk_event_id,{"decision_id":did,"confidence_bps":confidence_bps}))
        if status=="CONFIRMED": repo.append_event(Event(new_id("evt"),"JUDGMENT_REEVALUATION_REQUESTED","HOTEL",risk.hotel_id,{"source_id":risk_event_id,"reason":"RISK_EVENT_CONFIRMED"}))
        return self.get_risk(risk_event_id)

    def submit_remediation(self,risk_event_id:str,action:str,evidence_ids:list[str])->dict:
        now=now_utc(); rem=new_id("rem")
        with SessionLocal.begin() as s:
            risk=s.get(RiskEventRuntimeRow,risk_event_id)
            if not risk: not_found("RISK_EVENT_NOT_FOUND","Risk event not found")
            if risk.status not in ("CONFIRMED","REMEDIATION_REQUIRED","REMEDIATION_VERIFIED","MONITORING"):
                conflict("RISK_REMEDIATION_NOT_ALLOWED","Risk must be confirmed before remediation")
            s.add(RiskRemediationRow(remediation_id=rem,risk_event_id=risk_event_id,supplier_action=action,evidence_ids=evidence_ids,status="SUBMITTED",submitted_at=now))
            risk.status="REMEDIATION_REQUIRED"; risk.updated_at=now
        repo.append_event(Event(new_id("evt"),"REMEDIATION_SUBMITTED","RISK_EVENT",risk_event_id,{"remediation_id":rem}))
        return self.get_risk(risk_event_id)

    def verify_remediation(self,risk_event_id:str)->dict:
        now=now_utc()
        with SessionLocal.begin() as s:
            risk=s.get(RiskEventRuntimeRow,risk_event_id)
            if not risk: not_found("RISK_EVENT_NOT_FOUND","Risk event not found")
            rem=s.scalar(select(RiskRemediationRow).where(RiskRemediationRow.risk_event_id==risk_event_id).order_by(RiskRemediationRow.submitted_at.desc()))
            if not rem: unprocessable("RISK_REMEDIATION_MISSING","No remediation submitted")
            rem.status="VERIFIED"; rem.verified_at=now; risk.status="MONITORING"; risk.updated_at=now
            hook=new_id("jhook"); s.add(JudgmentHookRow(hook_id=hook,hotel_id=risk.hotel_id,source_type="RISK_EVENT",source_id=risk_event_id,reason_code="RISK_REMEDIATION_VERIFIED",status="REQUESTED",payload={"remediation_id":rem.remediation_id},created_at=now))
        repo.append_event(Event(new_id("evt"),"REMEDIATION_VERIFIED","RISK_EVENT",risk_event_id,{"remediation_id":rem.remediation_id}))
        repo.append_event(Event(new_id("evt"),"JUDGMENT_REEVALUATION_REQUESTED","HOTEL",risk.hotel_id,{"source_id":risk_event_id,"reason":"RISK_REMEDIATION_VERIFIED"}))
        return self.get_risk(risk_event_id)

    def get_review(self,review_id:str)->dict:
        with SessionLocal() as s:
            r=s.get(ReviewSessionRow,review_id)
            if not r: not_found("REVIEW_NOT_FOUND","Review not found")
            return self._review_dict(r,s)

    def _review_dict(self,r,s)->dict:
        tags=s.scalars(select(ReviewTagRow).where(ReviewTagRow.review_id==r.review_id)).all()
        return {"review_id":r.review_id,"order_id":r.order_id,"hotel_id":r.hotel_id,"account_id":r.account_id,"verified_stay":r.verified_stay,"raw_star_input":r.raw_star_input,"trigger_source":r.trigger_source,"status":r.status,"public_status":r.public_status,"experience_score":None if r.experience_score_milli is None else r.experience_score_milli/1000,"dimension_result":r.dimension_result,"tags":[{"tag_code":t.tag_code,"category":t.category,"polarity":t.polarity,"severity":t.severity,"mapped_dimensions":t.mapped_dimensions} for t in tags],"content":{"text":r.content_text,"voice_ref":r.voice_ref,"photo_refs":r.photo_refs},"completed_at":r.completed_at.isoformat() if r.completed_at else None}

    def get_risk(self,risk_event_id:str)->dict:
        with SessionLocal() as s:
            r=s.get(RiskEventRuntimeRow,risk_event_id)
            if not r: not_found("RISK_EVENT_NOT_FOUND","Risk event not found")
            ev=s.scalars(select(RiskEvidenceRuntimeRow).where(RiskEvidenceRuntimeRow.risk_event_id==risk_event_id).order_by(RiskEvidenceRuntimeRow.created_at)).all()
            rem=s.scalars(select(RiskRemediationRow).where(RiskRemediationRow.risk_event_id==risk_event_id)).all()
            hooks=s.scalars(select(JudgmentHookRow).where(JudgmentHookRow.source_id==risk_event_id)).all()
            return {"risk_event_id":r.risk_event_id,"hotel_id":r.hotel_id,"order_id":r.order_id,"review_id":r.review_id,"risk_type":r.risk_type,"severity":r.severity,"status":r.status,"confidence_bps":r.confidence_bps,"decision_id":r.decision_id,"public_notice":r.public_notice,"evidence":[{"evidence_id":x.evidence_id,"source_actor":x.source_actor,"evidence_type":x.evidence_type,"content_ref":x.content_ref,"payload":x.payload} for x in ev],"remediations":[{"remediation_id":x.remediation_id,"action":x.supplier_action,"status":x.status,"evidence_ids":x.evidence_ids} for x in rem],"judgment_hooks":[{"hook_id":x.hook_id,"reason_code":x.reason_code,"status":x.status} for x in hooks]}

truth_service=TruthService()
