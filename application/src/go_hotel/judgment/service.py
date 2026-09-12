from __future__ import annotations
import json
from hashlib import sha256
from datetime import timedelta
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    ReviewSessionRow,RiskEventRuntimeRow,RiskRemediationRow,JudgmentHookRow,
    JudgmentEvidencePackageRow,JudgmentRuntimeRow,RecommendationDecisionRow,GoodHotelStandardAssessmentRow
)
from go_hotel.judgment.good_hotel_standard import good_hotel_standard_service
from go_hotel.domain.models import new_id, now_utc, Event
from go_hotel.repositories.sql import repo
from go_hotel.core.errors import not_found, unprocessable

MODEL_VERSION="GO_JUDGMENT_DETERMINISTIC_V1"
PROMPT_VERSION="NO_GENERATIVE_PROMPT_V1"
RULE_VERSION="GO_JUDGMENT_RULES_1.0"
RECOMMENDATION_RULE_VERSION="GO_RECOMMENDATION_CONSTITUTION_1.0"
COMMERCIAL_FIELDS={"subscription_amount","advertising_budget","commission","rebate","partnership_tier","investment_relationship","commercial_revenue","gmv","clicks","favorites","popularity","user_preference","traveler_fit","traveler_context","candidate_scores","personalization_score"}

RECOMMENDATION_DIMENSIONS=(
    "WORK_OF_HOSPITALITY",
    "IRREPLACEABILITY",
    "SENSE_OF_PLACE",
    "AESTHETIC_JUDGMENT",
    "EMOTIONAL_RESONANCE",
    "WORTH_THE_JOURNEY",
)
RECOMMENDATION_STATES={"STRONG","PRESENT","LIMITED","ABSENT","UNKNOWN"}

class JudgmentService:
    def _evidence(self, hotel_id:str)->dict:
        with SessionLocal() as s:
            reviews=s.scalars(select(ReviewSessionRow).where(ReviewSessionRow.hotel_id==hotel_id,ReviewSessionRow.status=="COMPLETED").order_by(ReviewSessionRow.completed_at)).all()
            risks=s.scalars(select(RiskEventRuntimeRow).where(RiskEventRuntimeRow.hotel_id==hotel_id).order_by(RiskEventRuntimeRow.created_at)).all()
            rems=[]
            for r in risks:
                rems.extend(s.scalars(select(RiskRemediationRow).where(RiskRemediationRow.risk_event_id==r.risk_event_id)).all())
        source_refs=[]; dims={}; experience=[]
        for r in reviews:
            source_refs.append({"type":"GO_TRUTH_REVIEW","id":r.review_id,"at":r.completed_at.isoformat() if r.completed_at else None})
            if r.experience_score_milli is not None: experience.append(r.experience_score_milli)
            for k,v in (r.dimension_result or {}).items():
                d=dims.setdefault(k,{"negative":0,"positive":0})
                if v=="NEGATIVE": d["negative"]+=1
                elif v=="POSITIVE": d["positive"]+=1
        confirmed=[r for r in risks if r.status in ("CONFIRMED","REMEDIATION_REQUIRED")]
        monitoring=[r for r in risks if r.status in ("REMEDIATION_VERIFIED","MONITORING")]
        for r in risks:
            source_refs.append({"type":"RISK_EVENT","id":r.risk_event_id,"status":r.status,"risk_type":r.risk_type,"at":r.created_at.isoformat()})
        for r in rems:
            source_refs.append({"type":"REMEDIATION","id":r.remediation_id,"status":r.status,"risk_event_id":r.risk_event_id,"at":r.submitted_at.isoformat()})
        avg_exp=(sum(experience)/len(experience)) if experience else None
        feature={
            "completed_review_count":len(reviews),
            "structured_experience_avg_milli":round(avg_exp) if avg_exp is not None else None,
            "dimension_summary":dims,
            "confirmed_serious_risk_count":len(confirmed),
            "monitoring_risk_count":len(monitoring),
            "verified_remediation_count":sum(1 for x in rems if x.status=="VERIFIED"),
        }
        return {"source_refs":source_refs,"feature_snapshot":feature,"source_summary":{"reviews":len(reviews),"risks":len(risks),"remediations":len(rems)}}

    def _score(self, f:dict)->tuple[int,dict,dict,int]:
        # V1 is deliberately deterministic and independent from raw user stars.
        # GO Truth structured outcomes and verified risks are evidence inputs, not a copied rating average.
        score=4600
        dims={"QUALITY_BASELINE":4600}
        negative=sum(v.get("negative",0) for v in f["dimension_summary"].values())
        positive=sum(v.get("positive",0) for v in f["dimension_summary"].values())
        score += min(200, positive*40)
        score -= min(500, negative*100)
        score -= f["confirmed_serious_risk_count"]*700
        score -= f["monitoring_risk_count"]*250
        score += min(150, f["verified_remediation_count"]*100)
        # Structured GO Truth score can refine confidence/quality slightly; raw star never enters this function.
        avg=f.get("structured_experience_avg_milli")
        if avg is not None:
            score += max(-200,min(200,int((avg-4000)*0.2)))
        score=max(1000,min(5000,score))
        dims.update({"STRUCTURED_NEGATIVE_SIGNALS":negative,"STRUCTURED_POSITIVE_SIGNALS":positive,"CONFIRMED_SERIOUS_RISKS":f["confirmed_serious_risk_count"],"MONITORING_RISKS":f["monitoring_risk_count"],"VERIFIED_REMEDIATIONS":f["verified_remediation_count"]})
        why=[]
        if f["confirmed_serious_risk_count"]: why.append("CONFIRMED_SERIOUS_RISK")
        if f["monitoring_risk_count"]: why.append("RISK_UNDER_MONITORING")
        if negative: why.append("STRUCTURED_EXPERIENCE_ISSUES")
        if f["verified_remediation_count"]: why.append("VERIFIED_REMEDIATION")
        if not why: why.append("NO_MATERIAL_NEGATIVE_EVIDENCE")
        confidence=min(9500,4500+f["completed_review_count"]*500+len(why)*150)
        explanation={"why_recommended_or_not":why,"strongest_value":"Evidence-backed baseline quality" if score>=4000 else "No positive claim beyond available evidence","main_shortcoming":"Confirmed/structured risks" if score<4300 else "No material shortcoming established","why_not_higher":"GO Judgment V1 remains conservative and evidence-limited","suitable_for":"Travelers who value independently audited fulfillment evidence","uncertainty":"Score may change when new verified evidence arrives"}
        return score,dims,explanation,confidence

    def _recommend(self, score:int, f:dict)->tuple[str,list[str],int|None]:
        # GO Recommendation Constitution 1.0: GO Score / review volume NEVER auto-create endorsement.
        # Operational facts may inform or veto an independent recommendation assessment, but are not the verdict itself.
        if f["confirmed_serious_risk_count"]>0:
            return "GO_NOT_RECOMMENDED",["UNRESOLVED_CONFIRMED_SERIOUS_RISK"],None
        assessment=f.get("recommendation_assessment")
        if not isinstance(assessment,dict):
            return "NOT_YET_RATED",["RECOMMENDATION_ASSESSMENT_REQUIRED"],None
        if assessment.get("commercial_independence_attested") is not True:
            return "NOT_YET_RATED",["COMMERCIAL_INDEPENDENCE_ATTESTATION_REQUIRED"],None
        dims=assessment.get("dimensions")
        if not isinstance(dims,dict) or any(k not in dims for k in RECOMMENDATION_DIMENSIONS):
            return "NOT_YET_RATED",["RECOMMENDATION_SIX_DIMENSION_EVIDENCE_INCOMPLETE"],None
        for key in RECOMMENDATION_DIMENSIONS:
            item=dims.get(key)
            if not isinstance(item,dict) or item.get("state") not in RECOMMENDATION_STATES or not str(item.get("evidence_summary") or "").strip():
                return "NOT_YET_RATED",["RECOMMENDATION_SIX_DIMENSION_EVIDENCE_INCOMPLETE"],None
        worth=assessment.get("worth_the_journey")
        verdict=assessment.get("verdict")
        if verdict=="GO_RECOMMENDED":
            if worth!="YES":
                return "NOT_YET_RATED",["WORTH_THE_JOURNEY_EXPLICIT_YES_REQUIRED"],None
            return "GO_RECOMMENDED",["GO_RECOMMENDATION_CONSTITUTION_PASSED","WORTH_THE_JOURNEY_YES","COMMERCIAL_INDEPENDENCE_ATTESTED"],score
        if verdict=="GO_NOT_RECOMMENDED":
            return "GO_NOT_RECOMMENDED",["GO_INDEPENDENT_RECOMMENDATION_NOT_ENDORSED"],None
        return "NOT_YET_RATED",["OBSERVATION_REQUIRED"],None


    def _assert_no_forbidden_features(self,value,path="extra_features"):
        if isinstance(value,dict):
            for k,v in value.items():
                if k in COMMERCIAL_FIELDS:
                    unprocessable("JUDGMENT_COMMERCIAL_FIELD_FORBIDDEN",f"Commercial/popularity/user-fit field forbidden at {path}.{k}")
                self._assert_no_forbidden_features(v,f"{path}.{k}")
        elif isinstance(value,list):
            for i,v in enumerate(value): self._assert_no_forbidden_features(v,f"{path}[{i}]")

    def reevaluate(self,hotel_id:str,extra_features:dict|None=None)->dict:
        if extra_features:
            self._assert_no_forbidden_features(extra_features)
        now=now_utc(); standard=good_hotel_standard_service.active();ev=self._evidence(hotel_id); feature=dict(ev["feature_snapshot"])
        if extra_features: feature.update(extra_features)
        raw=json.dumps({"hotel_id":hotel_id,"source_refs":ev["source_refs"],"feature_snapshot":feature},sort_keys=True,separators=(",",":"),default=str).encode()
        digest=sha256(raw).hexdigest(); package_id=new_id("evpkg"); judgment_id=new_id("jud"); decision_id=new_id("rec")
        score,dims,explanation,confidence=self._score(feature)
        rec_status,reasons,public_score=self._recommend(score,feature)
        with SessionLocal.begin() as s:
            prior=s.scalar(select(JudgmentRuntimeRow).where(JudgmentRuntimeRow.hotel_id==hotel_id,JudgmentRuntimeRow.status=="ACTIVE").order_by(JudgmentRuntimeRow.created_at.desc()))
            if prior: prior.status="SUPERSEDED"; prior.valid_to=now
            prior_rec=s.scalar(select(RecommendationDecisionRow).where(RecommendationDecisionRow.hotel_id==hotel_id,RecommendationDecisionRow.valid_to.is_(None)).order_by(RecommendationDecisionRow.created_at.desc()))
            if prior_rec: prior_rec.valid_to=now
            s.add(JudgmentEvidencePackageRow(package_id=package_id,hotel_id=hotel_id,source_refs=ev["source_refs"],source_summary=ev["source_summary"],feature_snapshot=feature,excluded_commercial_fields=sorted(COMMERCIAL_FIELDS),content_hash=digest,sealed_at=now,created_at=now))
            s.add(GoodHotelStandardAssessmentRow(good_hotel_standard_assessment_id=new_id('ghsa'),hotel_id=hotel_id,good_hotel_standard_version_id=standard.good_hotel_standard_version_id,evidence_package_id=package_id,dimension_result_json=dims,disqualifier_result_json=[x for x in standard.disqualifiers_json if x in reasons],assessment_state=rec_status,reason_codes_json=reasons,assessed_at=now))
            s.add(JudgmentRuntimeRow(judgment_id=judgment_id,hotel_id=hotel_id,evidence_package_id=package_id,go_score_milli=score,dimension_result=dims,explanation=explanation,confidence_bps=confidence,model_version=MODEL_VERSION,prompt_version=PROMPT_VERSION,rule_version=RULE_VERSION,good_hotel_standard_version_id=standard.good_hotel_standard_version_id,status="ACTIVE",public_at=now if rec_status=="GO_RECOMMENDED" else None,valid_from=now,valid_to=None,created_at=now))
            s.add(RecommendationDecisionRow(decision_id=decision_id,hotel_id=hotel_id,judgment_id=judgment_id,status=rec_status,reason_codes=reasons,public_go_score_milli=public_score,rule_version=RECOMMENDATION_RULE_VERSION,good_hotel_standard_version_id=standard.good_hotel_standard_version_id,valid_from=now,valid_to=None,created_at=now))
            hooks=s.scalars(select(JudgmentHookRow).where(JudgmentHookRow.hotel_id==hotel_id,JudgmentHookRow.status=="REQUESTED")).all()
            for h in hooks: h.status="COMPLETED"
        repo.append_event(Event(new_id("evt"),"JUDGMENT_CREATED","HOTEL",hotel_id,{"judgment_id":judgment_id,"evidence_package_id":package_id,"go_score_milli":score}))
        repo.append_event(Event(new_id("evt"),"GO_SCORE_UPDATED","HOTEL",hotel_id,{"judgment_id":judgment_id,"go_score_milli":score}))
        repo.append_event(Event(new_id("evt"),"RECOMMENDATION_STATUS_CHANGED","HOTEL",hotel_id,{"decision_id":decision_id,"status":rec_status,"judgment_id":judgment_id}))
        return self.get_judgment(judgment_id)

    def process_hook(self,hook_id:str)->dict:
        with SessionLocal() as s:
            h=s.get(JudgmentHookRow,hook_id)
            if not h: not_found("JUDGMENT_HOOK_NOT_FOUND","Judgment hook not found")
            hotel_id=h.hotel_id
            if h.status=="COMPLETED":
                latest=s.scalar(select(JudgmentRuntimeRow).where(JudgmentRuntimeRow.hotel_id==hotel_id).order_by(JudgmentRuntimeRow.created_at.desc()))
                if latest: return self.get_judgment(latest.judgment_id)
        return self.reevaluate(hotel_id)

    def process_pending(self,limit:int=100)->list[dict]:
        with SessionLocal() as s:
            ids=[x.hook_id for x in s.scalars(select(JudgmentHookRow).where(JudgmentHookRow.status=="REQUESTED").order_by(JudgmentHookRow.created_at).limit(limit)).all()]
        return [self.process_hook(x) for x in ids]

    def public_summary_or_default(self,hotel_id:str)->dict:
        with SessionLocal() as s:
            j=s.scalar(select(JudgmentRuntimeRow).where(JudgmentRuntimeRow.hotel_id==hotel_id,JudgmentRuntimeRow.status=="ACTIVE").order_by(JudgmentRuntimeRow.created_at.desc()))
            if not j:
                return {"judgment_id":None,"go_score":None,"recommendation_status":"NOT_YET_RATED","reason_codes":["INSUFFICIENT_EVIDENCE"]}
            r=s.scalar(select(RecommendationDecisionRow).where(RecommendationDecisionRow.judgment_id==j.judgment_id).order_by(RecommendationDecisionRow.created_at.desc()))
            return {"judgment_id":j.judgment_id,"go_score":None if not r or r.public_go_score_milli is None else r.public_go_score_milli/1000,"recommendation_status":r.status if r else "NOT_YET_RATED","reason_codes":r.reason_codes if r else ["DECISION_PENDING"]}

    def public_view(self,hotel_id:str)->dict:
        latest=self.get_latest(hotel_id)
        return {"judgment_id":latest["judgment_id"],"hotel_id":hotel_id,"go_score":latest["public_go_score"],"recommendation":latest["recommendation"],"explanation":latest["explanation"],"confidence_bps":latest["confidence_bps"],"evidence_package_id":latest["evidence_package"]["package_id"],"validity":{"status":latest["status"]}}

    def get_latest(self,hotel_id:str)->dict:
        with SessionLocal() as s:
            j=s.scalar(select(JudgmentRuntimeRow).where(JudgmentRuntimeRow.hotel_id==hotel_id,JudgmentRuntimeRow.status=="ACTIVE").order_by(JudgmentRuntimeRow.created_at.desc()))
            if not j: not_found("JUDGMENT_NOT_FOUND","No judgment exists for hotel")
            jid=j.judgment_id
        return self.get_judgment(jid)

    def get_judgment(self,judgment_id:str)->dict:
        with SessionLocal() as s:
            j=s.get(JudgmentRuntimeRow,judgment_id)
            if not j: not_found("JUDGMENT_NOT_FOUND","Judgment not found")
            p=s.get(JudgmentEvidencePackageRow,j.evidence_package_id)
            r=s.scalar(select(RecommendationDecisionRow).where(RecommendationDecisionRow.judgment_id==judgment_id).order_by(RecommendationDecisionRow.created_at.desc()))
            return {"judgment_id":j.judgment_id,"hotel_id":j.hotel_id,"go_score":j.go_score_milli/1000,"public_go_score":None if not r or r.public_go_score_milli is None else r.public_go_score_milli/1000,"dimension_result":j.dimension_result,"explanation":j.explanation,"confidence_bps":j.confidence_bps,"model_version":j.model_version,"prompt_version":j.prompt_version,"rule_version":j.rule_version,"good_hotel_standard_version_id":j.good_hotel_standard_version_id,"status":j.status,"recommendation":{"decision_id":r.decision_id,"status":r.status,"reason_codes":r.reason_codes,"rule_version":r.rule_version,"good_hotel_standard_version_id":r.good_hotel_standard_version_id} if r else None,"evidence_package":{"package_id":p.package_id,"content_hash":p.content_hash,"source_refs":p.source_refs,"source_summary":p.source_summary,"feature_snapshot":p.feature_snapshot,"excluded_commercial_fields":p.excluded_commercial_fields,"sealed_at":p.sealed_at.isoformat()}}

judgment_service=JudgmentService()
