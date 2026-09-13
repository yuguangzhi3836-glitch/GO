from __future__ import annotations
import hashlib, json, re, uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select, func

from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    TravelEntityRow, TravelEntityAliasRow, TravelEntityFactRow, TravelEntityRelationRow, TravelIntentRow, TravelIntentConstraintRow,
    TravelBehaviorEventRow, AIDecisionRow, AIDecisionModelCallRow, TransactionRelationRow, TravelerProfileRow
)
from .contracts import EVENT_TYPES, ACTOR_TYPES, SOURCES, PRIVACY_CLASSES, RETENTION_CLASSES, ENTITY_TYPES, TRANSACTION_TRUTH_DOMAINS
from .cost_governor import model_cost_governor

UTC=timezone.utc
def now(): return datetime.now(UTC)
def canonical_hash(value:Any)->str:
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str).encode()
    return hashlib.sha256(raw).hexdigest()

def _uuid(value:str|uuid.UUID|None)->uuid.UUID|None:
    if value is None:return None
    return value if isinstance(value,uuid.UUID) else uuid.UUID(str(value))

def _simple_intent(raw:str)->dict[str,Any]:
    text=" ".join(raw.strip().split())
    out={"raw_normalized":text}
    m=re.search(r"(?:预算|budget)\s*[:：]?\s*[¥￥$]?\s*(\d+(?:\.\d+)?)",text,re.I)
    if m: out["budget_max"]=float(m.group(1))
    m=re.search(r"(\d+)\s*(?:晚|night)",text,re.I)
    if m: out["nights"]=int(m.group(1))
    return out

class TravelIntelligenceService:
    def create_decision(self, *, input_snapshot:dict, evidence_snapshot:dict, output_snapshot:dict, correlation_id:str, rule_version:str="TI_P0_RULES_1.0", prompt_version:str="NONE", model_version:str="DETERMINISTIC") -> AIDecisionRow:
        with SessionLocal.begin() as s:
            prev=s.scalar(select(AIDecisionRow).order_by(AIDecisionRow.created_at.desc()).limit(1))
            previous_hash=prev.decision_hash if prev else None
            ih=canonical_hash(input_snapshot); eh=canonical_hash(evidence_snapshot)
            body={"previous_hash":previous_hash,"input_snapshot_hash":ih,"evidence_snapshot_hash":eh,"rule_version":rule_version,"prompt_version":prompt_version,"model_version":model_version,"output_snapshot":output_snapshot,"correlation_id":correlation_id}
            dh=canonical_hash(body)
            row=AIDecisionRow(decision_id=uuid.uuid4(),previous_hash=previous_hash,decision_hash=dh,input_snapshot_hash=ih,evidence_snapshot_hash=eh,rule_version=rule_version,prompt_version=prompt_version,model_version=model_version,input_snapshot=input_snapshot,evidence_snapshot=evidence_snapshot,output_snapshot=output_snapshot,correlation_id=correlation_id,created_at=now())
            s.add(row); s.flush(); return row

    def create_intent(self, *, traveler_id:str, session_id:str, raw_input:str, consent_scope:list[str], correlation_id:str)->dict:
        with SessionLocal() as s:
            traveler=s.get(TravelerProfileRow,traveler_id)
            if not traveler or traveler.status!="ACTIVE": raise ValueError("TRAVELER_NOT_FOUND")
        normalized=_simple_intent(raw_input)
        decision=self.create_decision(input_snapshot={"traveler_id":traveler_id,"session_id":session_id,"raw_input":raw_input},evidence_snapshot={"consent_scope":consent_scope},output_snapshot={"normalized_intent":normalized},correlation_id=correlation_id,rule_version="INTENT_NORMALIZATION_P0_1.0")
        iid=uuid.uuid4(); t=now()
        with SessionLocal.begin() as s:
            s.add(TravelIntentRow(intent_id=iid,traveler_id=traveler_id,session_id=session_id,raw_input=raw_input,normalized_intent=normalized,consent_scope=consent_scope,status="ACTIVE",created_at=t,updated_at=t))
        return {"intent_id":str(iid),"decision_id":str(decision.decision_id),"status":"ACTIVE","constraints":[]}

    def refine_intent(self, intent_id:str, *, traveler_id:str, session_id:str, raw_input:str, consent_scope:list[str], correlation_id:str)->dict:
        iid=_uuid(intent_id)
        with SessionLocal.begin() as s:
            row=s.get(TravelIntentRow,iid)
            if not row: raise ValueError("TRAVEL_INTENT_NOT_FOUND")
            if row.traveler_id!=traveler_id: raise ValueError("TRAVEL_INTENT_TRAVELER_MISMATCH")
            normalized=_simple_intent(raw_input); row.raw_input=raw_input; row.normalized_intent=normalized; row.consent_scope=consent_scope; row.updated_at=now()
        decision=self.create_decision(input_snapshot={"intent_id":intent_id,"raw_input":raw_input},evidence_snapshot={"consent_scope":consent_scope},output_snapshot={"normalized_intent":normalized},correlation_id=correlation_id,rule_version="INTENT_REFINEMENT_P0_1.0")
        return {"intent_id":intent_id,"decision_id":str(decision.decision_id),"status":"ACTIVE","constraints":[]}

    def create_entity(self, *, entity_type:str, canonical_name:str, source_type:str|None=None, source_entity_id:str|None=None)->dict:
        entity_type=entity_type.upper()
        if entity_type not in ENTITY_TYPES: raise ValueError("TRAVEL_ENTITY_TYPE_INVALID")
        eid=uuid.uuid4(); t=now()
        with SessionLocal.begin() as s:
            s.add(TravelEntityRow(go_entity_id=eid,entity_type=entity_type,canonical_name=canonical_name.strip(),status="ACTIVE",created_at=t,updated_at=t))
            if source_type and source_entity_id:
                s.add(TravelEntityAliasRow(alias_id=uuid.uuid4(),go_entity_id=eid,source_type=source_type.upper(),source_entity_id=source_entity_id,normalized_name=canonical_name.strip().casefold(),created_at=t))
        return {"go_entity_id":str(eid),"entity_type":entity_type,"canonical_name":canonical_name.strip(),"status":"ACTIVE"}

    def get_entity(self, entity_id:str)->dict:
        with SessionLocal() as s:
            row=s.get(TravelEntityRow,_uuid(entity_id))
            if not row: raise ValueError("TRAVEL_ENTITY_NOT_FOUND")
            aliases=s.scalars(select(TravelEntityAliasRow).where(TravelEntityAliasRow.go_entity_id==row.go_entity_id)).all()
            return {"go_entity_id":str(row.go_entity_id),"entity_type":row.entity_type,"canonical_name":row.canonical_name,"status":row.status,"aliases":[{"source_type":a.source_type,"source_entity_id":a.source_entity_id} for a in aliases]}

    def resolve_entity(self, *, source_type:str, source_entity_id:str)->dict:
        with SessionLocal() as s:
            rows=s.scalars(select(TravelEntityAliasRow).where(TravelEntityAliasRow.source_type==source_type.upper(),TravelEntityAliasRow.source_entity_id==source_entity_id)).all()
            if not rows: raise ValueError("TRAVEL_ENTITY_ALIAS_NOT_FOUND")
            ids={r.go_entity_id for r in rows}
            if len(ids)!=1: raise ValueError("TRAVEL_ENTITY_RESOLUTION_AMBIGUOUS")
            row=s.get(TravelEntityRow,next(iter(ids)))
            return {"go_entity_id":str(row.go_entity_id),"entity_type":row.entity_type,"canonical_name":row.canonical_name,"resolution":"EXACT_ALIAS"}

    def append_event(self, event:dict)->dict:
        if event.get("event_type") not in EVENT_TYPES: raise ValueError("TRAVEL_EVENT_TYPE_INVALID")
        if event.get("actor_type") not in ACTOR_TYPES: raise ValueError("TRAVEL_EVENT_ACTOR_INVALID")
        if event.get("source") not in SOURCES: raise ValueError("TRAVEL_EVENT_SOURCE_INVALID")
        if event.get("privacy_class") not in PRIVACY_CLASSES: raise ValueError("TRAVEL_EVENT_PRIVACY_INVALID")
        if event.get("retention_class") not in RETENTION_CLASSES: raise ValueError("TRAVEL_EVENT_RETENTION_INVALID")
        if event.get("schema_version")!="1.0": raise ValueError("TRAVEL_EVENT_SCHEMA_VERSION_INVALID")
        key=event["idempotency_key"]
        with SessionLocal.begin() as s:
            existing=s.scalar(select(TravelBehaviorEventRow).where(TravelBehaviorEventRow.idempotency_key==key))
            if existing:
                same=existing.event_type==event["event_type"] and existing.correlation_id==event["correlation_id"] and canonical_hash(existing.payload)==canonical_hash(event.get("payload") or {})
                if same:return {"event_id":str(existing.event_id),"status":"DUPLICATE_ACCEPTED"}
                raise ValueError("TRAVEL_EVENT_IDEMPOTENCY_CONFLICT")
            eid=_uuid(event.get("event_id")) or uuid.uuid4()
            occurred=event.get("occurred_at")
            if isinstance(occurred,str): occurred=datetime.fromisoformat(occurred.replace("Z","+00:00"))
            row=TravelBehaviorEventRow(event_id=eid,event_type=event["event_type"],occurred_at=occurred or now(),actor_type=event["actor_type"],actor_id=event.get("actor_id"),tenant_id=event.get("tenant_id"),organization_id=event.get("organization_id"),traveler_id=event.get("traveler_id"),session_id=event.get("session_id"),intent_id=_uuid(event.get("intent_id")),entity_id=_uuid(event.get("entity_id")),decision_id=_uuid(event.get("decision_id")),trip_id=event.get("trip_id"),order_id=event.get("order_id"),transaction_root_id=event.get("transaction_root_id"),source=event["source"],schema_version="1.0",correlation_id=event["correlation_id"],causation_id=event.get("causation_id"),idempotency_key=key,privacy_class=event["privacy_class"],retention_class=event["retention_class"],payload_schema=event.get("payload_schema"),payload=event.get("payload") or {},created_at=now())
            s.add(row); s.flush(); return {"event_id":str(eid),"status":"ACCEPTED"}

    def prepare_judgment_evidence(self, *, intent_id:str, candidate_entity_ids:list[str], context:dict, correlation_id:str)->dict:
        # C07 owns traveler/context truth only. It may prepare purpose-bound evidence for C09,
        # but it must not rank, admit, recommend, or manufacture GO Judgment truth.
        forbidden={"ad_spend","advertising_payment","commission","subscription_fee","rebate","investment_relationship","commercial_boost"}
        clean_context={k:v for k,v in context.items() if k not in forbidden}
        contaminated=sorted(k for k in context if k in forbidden and context.get(k) not in (None,0,False,"",[]))
        candidate_context=[]
        score_map=clean_context.get("candidate_scores") or {}
        for eid in candidate_entity_ids:
            raw=score_map.get(eid)
            fit=None
            if raw is not None:
                fit=max(0.0,min(float(raw),1.0))
            candidate_context.append({"entity_id":eid,"traveler_fit_evidence":fit})
        output={
            "evidence_scope":"C07_TRAVELER_CONTEXT_ONLY",
            "final_judgment_authority":"C09",
            "candidate_context":candidate_context,
            "commercial_signals_excluded":contaminated,
            "admission_or_recommendation":None,
        }
        decision=self.create_decision(
            input_snapshot={"intent_id":intent_id,"candidate_entity_ids":candidate_entity_ids,"context":clean_context},
            evidence_snapshot={"evidence_role":"TRAVELER_CONTEXT_PROVIDER","final_judgment_authority":"C09"},
            output_snapshot=output,
            correlation_id=correlation_id,
            rule_version="C07_TRAVELER_CONTEXT_EVIDENCE_1.0",
        )
        return {"evidence_bundle_id":str(decision.decision_id),**output,"explanation_ref":f"/internal/v1/intelligence/decisions/{decision.decision_id}/explain"}

    def evaluate_judgment(self, *, intent_id:str, candidate_entity_ids:list[str], context:dict, correlation_id:str)->dict:
        raise ValueError("C07_JUDGMENT_AUTHORITY_FORBIDDEN")

    def upsert_entity_alias(self, *, entity_type:str, canonical_name:str, source_type:str, source_entity_id:str)->dict:
        entity_type=entity_type.upper(); source_type=source_type.upper()
        if entity_type not in ENTITY_TYPES: raise ValueError("TRAVEL_ENTITY_TYPE_INVALID")
        with SessionLocal.begin() as s:
            alias=s.scalar(select(TravelEntityAliasRow).where(TravelEntityAliasRow.source_type==source_type,TravelEntityAliasRow.source_entity_id==source_entity_id))
            if alias:
                row=s.get(TravelEntityRow,alias.go_entity_id)
                return {"go_entity_id":str(row.go_entity_id),"entity_type":row.entity_type,"canonical_name":row.canonical_name,"status":row.status,"idempotent":True}
            eid=uuid.uuid4(); t=now()
            s.add(TravelEntityRow(go_entity_id=eid,entity_type=entity_type,canonical_name=canonical_name.strip(),status="ACTIVE",created_at=t,updated_at=t))
            s.add(TravelEntityAliasRow(alias_id=uuid.uuid4(),go_entity_id=eid,source_type=source_type,source_entity_id=source_entity_id,normalized_name=canonical_name.strip().casefold(),created_at=t))
        return {"go_entity_id":str(eid),"entity_type":entity_type,"canonical_name":canonical_name.strip(),"status":"ACTIVE","idempotent":False}

    def append_entity_fact(self, *, entity_id:str, fact_type:str, fact_value:dict, provenance:str, source_id:str|None, confidence:float, verification_state:str, evidence_ref:str|None=None)->dict:
        eid=_uuid(entity_id); confidence=float(confidence)
        if confidence<0 or confidence>1: raise ValueError("TRAVEL_ENTITY_FACT_CONFIDENCE_INVALID")
        fp=canonical_hash({"entity_id":str(eid),"fact_type":fact_type,"fact_value":fact_value,"provenance":provenance,"source_id":source_id,"evidence_ref":evidence_ref})
        with SessionLocal.begin() as s:
            if not s.get(TravelEntityRow,eid): raise ValueError("TRAVEL_ENTITY_NOT_FOUND")
            rows=s.scalars(select(TravelEntityFactRow).where(TravelEntityFactRow.go_entity_id==eid,TravelEntityFactRow.fact_type==fact_type)).all()
            for r in rows:
                if canonical_hash({"entity_id":str(eid),"fact_type":r.fact_type,"fact_value":r.fact_value,"provenance":r.provenance,"source_id":r.source_id,"evidence_ref":r.evidence_ref})==fp:
                    return {"fact_id":str(r.fact_id),"idempotent":True}
            fid=uuid.uuid4(); s.add(TravelEntityFactRow(fact_id=fid,go_entity_id=eid,fact_type=fact_type,fact_value=fact_value,provenance=provenance,source_id=source_id,observed_at=now(),valid_from=None,valid_to=None,confidence=confidence,verification_state=verification_state,evidence_ref=evidence_ref,created_at=now()))
        return {"fact_id":str(fid),"idempotent":False}

    def link_entities(self, *, from_entity_id:str, relation_type:str, to_entity_id:str)->dict:
        a=_uuid(from_entity_id); b=_uuid(to_entity_id)
        if a==b: raise ValueError("TRAVEL_ENTITY_RELATION_SELF_FORBIDDEN")
        with SessionLocal.begin() as s:
            if not s.get(TravelEntityRow,a) or not s.get(TravelEntityRow,b): raise ValueError("TRAVEL_ENTITY_NOT_FOUND")
            rows=s.scalars(select(TravelEntityRelationRow).where(TravelEntityRelationRow.from_entity_id==a,TravelEntityRelationRow.relation_type==relation_type.upper(),TravelEntityRelationRow.to_entity_id==b)).all()
            if rows: return {"relation_id":str(rows[0].relation_id),"idempotent":True}
            rid=uuid.uuid4(); s.add(TravelEntityRelationRow(relation_id=rid,from_entity_id=a,relation_type=relation_type.upper(),to_entity_id=b,valid_from=now(),valid_to=None,created_at=now()))
        return {"relation_id":str(rid),"idempotent":False}

    def traveler_graph(self, traveler_id:str, *, purpose:str)->dict:
        if not purpose.strip(): raise ValueError("TRAVELER_GRAPH_PURPOSE_REQUIRED")
        with SessionLocal() as s:
            traveler=s.get(TravelerProfileRow,traveler_id)
            if not traveler or traveler.status!="ACTIVE": raise ValueError("TRAVELER_NOT_FOUND")
            intents=s.scalars(select(TravelIntentRow).where(TravelIntentRow.traveler_id==traveler_id).order_by(TravelIntentRow.updated_at.desc()).limit(20)).all()
            events=s.scalars(select(TravelBehaviorEventRow).where(TravelBehaviorEventRow.traveler_id==traveler_id).order_by(TravelBehaviorEventRow.occurred_at.desc()).limit(100)).all()
        # Session behavior is evidence, not permanent preference. No implicit durable preference mutation.
        return {"traveler_id":traveler_id,"purpose":purpose,"identity":{"relationship_type":traveler.relationship_type,"nationality":traveler.nationality},"recent_intents":[x.normalized_intent for x in intents],"behavior_evidence_count":len(events),"durable_preferences":[],"policy":"SESSION_SIGNAL_NEVER_AUTO_PROMOTES_TO_PERMANENT_PREFERENCE"}

    def independent_judgment(self, *, intent_id:str, candidate_entity_ids:list[str], context:dict, correlation_id:str)->dict:
        raise ValueError("C07_JUDGMENT_AUTHORITY_FORBIDDEN")

    def get_decision(self, decision_id:str)->dict:
        with SessionLocal() as s:
            row=s.get(AIDecisionRow,_uuid(decision_id))
            if not row: raise ValueError("AI_DECISION_NOT_FOUND")
            return {"decision_id":str(row.decision_id),"previous_hash":row.previous_hash,"decision_hash":row.decision_hash,"input_snapshot_hash":row.input_snapshot_hash,"evidence_snapshot_hash":row.evidence_snapshot_hash,"rule_version":row.rule_version,"prompt_version":row.prompt_version,"model_version":row.model_version,"input":row.input_snapshot,"evidence":row.evidence_snapshot,"output":row.output_snapshot,"correlation_id":row.correlation_id,"created_at":row.created_at.isoformat()}

    def explain_decision(self, decision_id:str)->dict:
        d=self.get_decision(decision_id)
        return {"decision_id":decision_id,"evidence_backed":True,"rule_version":d["rule_version"],"model_version":d["model_version"],"result":d["output"],"evidence":d["evidence"],"decision_hash":d["decision_hash"]}

    def entity_evidence(self, entity_id:str, *, limit:int=50)->list[dict]:
        with SessionLocal() as s:
            rows=s.scalars(select(TravelEntityFactRow).where(TravelEntityFactRow.go_entity_id==_uuid(entity_id)).order_by(TravelEntityFactRow.observed_at.desc()).limit(limit)).all()
            return [{"fact_id":str(r.fact_id),"fact_type":r.fact_type,"value":r.fact_value,"provenance":r.provenance,"source_id":r.source_id,"confidence":r.confidence,"verification_state":r.verification_state,"evidence_ref":r.evidence_ref,"observed_at":r.observed_at.isoformat()} for r in rows]

    def model_cost_summary(self, *, session_id:str, cost_scope:str|None=None, business_reference_id:str|None=None)->dict:
        with SessionLocal() as s:
            q=select(
                func.coalesce(func.sum(AIDecisionModelCallRow.estimated_cost_usd),0.0),
                func.coalesce(func.sum(AIDecisionModelCallRow.attributed_revenue_usd),0.0),
            ).where(AIDecisionModelCallRow.session_id==session_id)
            if cost_scope: q=q.where(AIDecisionModelCallRow.cost_scope==cost_scope.upper())
            if business_reference_id: q=q.where(AIDecisionModelCallRow.business_reference_id==business_reference_id)
            total_cost,total_revenue=s.execute(q).one()
        total_cost=float(total_cost or 0.0); total_revenue=float(total_revenue or 0.0)
        return {"session_id":session_id,"cost_scope":cost_scope.upper() if cost_scope else None,"business_reference_id":business_reference_id,"cost_usd":round(total_cost,8),"attributed_revenue_usd":round(total_revenue,8),"ai_cost_over_revenue":None if total_revenue<=0 else round(total_cost/total_revenue,8)}

    def model_invoke(self, *, capability:str, input_data:dict, privacy_class:str, latency_budget_ms:int|None, cost_budget_usd:float|None, complexity:float, correlation_id:str, session_id:str, cost_scope:str="JUDGMENT", business_reference_id:str|None=None, attributed_revenue_usd:float=0.0, estimated_quality:float=1.0, estimated_call_cost_usd:float=0.0, input_tokens:int=0, output_tokens:int=0, price_snapshot_id:str="LOCAL_ZERO_COST_V1", circuit_open:bool=False)->dict:
        cost_scope=cost_scope.upper()
        if cost_scope not in {"JUDGMENT","RECOMMENDATION","BOOKING"}: raise ValueError("MODEL_GATEWAY_COST_SCOPE_INVALID")
        if attributed_revenue_usd < 0: raise ValueError("MODEL_GATEWAY_REVENUE_INVALID")
        local_available=capability.upper() in {"INTENT_EXTRACTION","ENTITY_RESOLUTION","QUERY_REWRITE","EXPLANATION"}
        session_spend=self.model_cost_summary(session_id=session_id)["cost_usd"]
        route=model_cost_governor.route(
            capability=capability,complexity=complexity,privacy_class=privacy_class,
            latency_budget_ms=latency_budget_ms,cost_budget_usd=cost_budget_usd,
            local_capability_available=local_available,self_hosted_available=False,explicit_external_policy=False,
            estimated_quality=estimated_quality,estimated_call_cost_usd=estimated_call_cost_usd,
            session_spend_usd=session_spend,input_tokens=input_tokens,output_tokens=output_tokens,
            price_snapshot_id=price_snapshot_id,model_version="RULE_SEARCH_DATABASE",circuit_open=circuit_open,
        )
        if route.tier!=0: raise ValueError("MODEL_GATEWAY_ROUTE_NOT_IMPLEMENTED_P0")
        cap=capability.upper()
        if cap=="INTENT_EXTRACTION": output={"intent":_simple_intent(str(input_data.get("text") or input_data.get("message") or "")),"confidence":1.0,"execution":"DETERMINISTIC"}
        elif cap=="QUERY_REWRITE": output={"query":" ".join(str(input_data.get("query") or "").split()),"confidence":1.0,"execution":"DETERMINISTIC"}
        elif cap=="ENTITY_RESOLUTION": output={"status":"REQUIRES_ALIAS_KEYS","confidence":1.0,"execution":"DETERMINISTIC"}
        elif cap=="EXPLANATION": output={"explanation":input_data.get("facts") or input_data,"confidence":1.0,"execution":"DETERMINISTIC"}
        else: raise ValueError("MODEL_GATEWAY_LOCAL_CAPABILITY_UNAVAILABLE")
        decision=self.create_decision(input_snapshot={"capability":capability,"input":input_data,"privacy_class":privacy_class,"session_id":session_id,"cost_scope":cost_scope},evidence_snapshot={"route":route.__dict__},output_snapshot=output,correlation_id=correlation_id,rule_version="MODEL_COST_GOVERNOR_1.0",model_version="RULE_SEARCH_DATABASE")
        with SessionLocal.begin() as s:
            s.add(AIDecisionModelCallRow(
                model_call_id=uuid.uuid4(),decision_id=decision.decision_id,routing_decision_id=route.routing_decision_id,
                session_id=session_id,capability=cap,tier=route.tier,cost_scope=cost_scope,business_reference_id=business_reference_id,
                provider_id=None,model_version="RULE_SEARCH_DATABASE",price_snapshot_id=price_snapshot_id,
                estimated_quality=estimated_quality,input_tokens=input_tokens,output_tokens=output_tokens,
                estimated_cost_usd=estimated_call_cost_usd,attributed_revenue_usd=attributed_revenue_usd,
                latency_ms=0,status="SUCCEEDED",created_at=now(),
            ))
        summary=self.model_cost_summary(session_id=session_id)
        scoped=self.model_cost_summary(session_id=session_id,cost_scope=cost_scope,business_reference_id=business_reference_id) if business_reference_id else self.model_cost_summary(session_id=session_id,cost_scope=cost_scope)
        return {"routing_decision_id":route.routing_decision_id,"decision_id":str(decision.decision_id),"tier":route.tier,"tier_name":route.tier_name,"model_version":"RULE_SEARCH_DATABASE","estimated_cost_usd":estimated_call_cost_usd,"external_egress":False,"price_snapshot_id":price_snapshot_id,"session_cost_usd":summary["cost_usd"],"scope_cost_usd":scoped["cost_usd"],"ai_cost_over_revenue":summary["ai_cost_over_revenue"],"output":output}

    def project_transaction_relation(self, *, source_truth_domain:str, source_truth_id:str, relation_type:str, subject_id:str, object_id:str, source_event_id:str)->dict:
        domain=source_truth_domain.upper()
        if domain not in TRANSACTION_TRUTH_DOMAINS: raise ValueError("TRANSACTION_PROJECTION_SOURCE_DOMAIN_INVALID")
        rid=uuid.uuid4()
        with SessionLocal.begin() as s:
            row=TransactionRelationRow(relation_id=rid,source_truth_domain=domain,source_truth_id=source_truth_id,relation_type=relation_type.upper(),subject_id=subject_id,object_id=object_id,source_event_id=source_event_id,projected_at=now())
            s.add(row)
        return {"relation_id":str(rid),"projection_only":True}

travel_intelligence_service=TravelIntelligenceService()
