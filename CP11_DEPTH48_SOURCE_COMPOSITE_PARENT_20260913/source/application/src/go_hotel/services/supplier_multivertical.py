from datetime import datetime,timezone
import uuid
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import SupplierVerticalCapabilityRow as Capability,SupplierCertificationRunRow as Run
from go_hotel.services.phase1_closure import VERTICALS,CAPABILITIES
REQUIRED={'SEARCH','DETAIL','QUOTE','REVALIDATE','ORDER','CANCEL','REFUND','RECONCILIATION'}
def now():return datetime.now(timezone.utc)
def ident(p):return f'{p}_{uuid.uuid4().hex}'
def out(r):return {c.name:(getattr(r,c.name).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}
class SupplierMultiVerticalService:
 def configure(self,supplier,vertical,capability,b):
  if vertical not in VERTICALS or capability not in CAPABILITIES:raise ValueError('UNSUPPORTED_VERTICAL_OR_CAPABILITY')
  if not b.get('authority_reference'):raise ValueError('SUPPLIER_AUTHORITY_EVIDENCE_REQUIRED')
  with SessionLocal() as s:
   r=s.scalar(select(Capability).where(Capability.supplier_id==supplier,Capability.vertical==vertical,Capability.capability==capability));vals=dict(mode=b.get('mode','API'),authority_reference=b['authority_reference'],state='CONFIGURED_NOT_CERTIFIED',updated_at=now())
   if not r:r=Capability(supplier_vertical_capability_id=ident('svc'),supplier_id=supplier,vertical=vertical,capability=capability,**vals);s.add(r)
   else:
    for k,v in vals.items():setattr(r,k,v)
   s.commit();return out(r)
 def certify(self,supplier,vertical,b,actor):
  if vertical not in VERTICALS:raise ValueError('UNSUPPORTED_VERTICAL')
  with SessionLocal() as s:
   caps=s.scalars(select(Capability).where(Capability.supplier_id==supplier,Capability.vertical==vertical)).all();present={x.capability for x in caps};checks=b.get('checks',{});block=[f'{x}_CAPABILITY_REQUIRED' for x in sorted(REQUIRED-present)]+[f'{x}_CHECK_REQUIRED' for x in sorted(REQUIRED) if not checks.get(x.lower())]
   if not b.get('evidence'):block.append('CERTIFICATION_EVIDENCE_REQUIRED')
   r=Run(supplier_certification_run_id=ident('scr'),supplier_id=supplier,vertical=vertical,checks_json=checks,evidence_json=b.get('evidence',[]),state='PASS_CONTRACT_ONLY' if not block else 'BLOCKED',blockers_json=block,requested_by=actor,created_at=now());s.add(r)
   if not block:
    for x in caps:x.state='CERTIFIED_CONTRACT_ONLY';x.updated_at=now()
   s.commit();return out(r)|{'external_live':False}
 def status(self,supplier):
  with SessionLocal() as s:return {'capabilities':[out(x) for x in s.scalars(select(Capability).where(Capability.supplier_id==supplier)).all()],'certifications':[out(x) for x in s.scalars(select(Run).where(Run.supplier_id==supplier).order_by(Run.created_at.desc())).all()],'external_live':False}
supplier_multivertical_service=SupplierMultiVerticalService()
