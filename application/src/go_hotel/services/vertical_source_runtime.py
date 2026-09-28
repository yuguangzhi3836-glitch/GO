from datetime import datetime, timezone
import hashlib, json, uuid
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import VerticalSourceDecisionRow as Decision
from go_hotel.autonomy.durable import insert_once
from go_hotel.services.phase1_closure import VERTICALS, OFFICIAL, SourceCandidate

def now(): return datetime.now(timezone.utc)
def ident(p): return f'{p}_{uuid.uuid4().hex}'
def digest(v): return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def out(r): return {c.name:(getattr(r,c.name).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}

class VerticalSourceRuntimeService:
    def decide(self, vertical, business_id, candidates):
        with SessionLocal() as s:
            result=self.decide_in(s,vertical,business_id,candidates)
            s.commit()
            return result

    def decide_in(self, s, vertical, business_id, candidates):
        """Caller owns commit/rollback with the native order, when applicable."""
        if vertical not in VERTICALS: raise ValueError('UNSUPPORTED_VERTICAL')
        parsed=[SourceCandidate(**x) for x in candidates]
        official=[x for x in parsed if x.source_type==OFFICIAL[vertical] and x.authorized and x.available and x.evidence_reference]
        fallback=[x for x in parsed if x.source_type=='AUTHORIZED_FALLBACK' and x.authorized and x.available and x.evidence_reference]
        selected=(official or fallback or [None])[0]
        route='OFFICIAL_DIRECT' if official else ('AUTHORIZED_FALLBACK' if fallback else 'UNAVAILABLE')
        reasons=['DIRECT_FIRST','AUTHORIZED_AVAILABLE_OFFICIAL_SOURCE'] if official else (['OFFICIAL_UNAVAILABLE','EXPLICIT_FALLBACK_AUTHORITY_AND_EVIDENCE'] if fallback else ['NO_AUTHORIZED_EVIDENCED_SOURCE'])
        snapshot=[x.__dict__ for x in parsed]
        payload={'vertical':vertical,'business_id':business_id,'selected_source_id':selected.source_id if selected else None,'selected_source_type':selected.source_type if selected else None,'route':route,'candidate_snapshot':snapshot,'reason_codes':reasons}
        row=Decision(vertical_source_decision_id=ident('vsd'),vertical=vertical,business_id=business_id,selected_source_id=selected.source_id if selected else None,selected_source_type=selected.source_type if selected else None,route=route,authority_reference=(selected.source_id if selected else None),evidence_reference=(selected.evidence_reference if selected else None),candidate_snapshot_json=snapshot,reason_codes_json=reasons,decision_hash=digest(payload),created_at=now())
        # The hash is the durable identity across workers. Reuse exactly
        # that decision; unrelated constraints and database errors still fail.
        insert_once(s,Decision,{c.name:getattr(row,c.name) for c in row.__table__.columns},['decision_hash'])
        persisted=s.scalar(select(Decision).where(Decision.decision_hash==row.decision_hash))
        return out(persisted)
    def latest(self, vertical, business_id):
        with SessionLocal() as s:
            r=s.scalar(select(Decision).where(Decision.vertical==vertical,Decision.business_id==business_id).order_by(Decision.created_at.desc()))
            return out(r) if r else None

vertical_source_runtime_service=VerticalSourceRuntimeService()
