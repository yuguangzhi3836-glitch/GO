from datetime import datetime,timezone
import hashlib,json,uuid
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import GoodHotelStandardVersionRow,GoodHotelStandardGovernanceEventRow
def now():return datetime.now(timezone.utc)
def ident(p):return f'{p}_{uuid.uuid4().hex}'
DEFAULT={'dimensions':['FULFILLMENT_TRUTH','ROOM_ACCURACY','CLEANLINESS','SAFETY','SLEEP_QUALITY','SERVICE_RECOVERY','POLICY_TRANSPARENCY','WORK_OF_HOSPITALITY','IRREPLACEABILITY','SENSE_OF_PLACE','AESTHETIC_JUDGMENT','EMOTIONAL_RESONANCE','WORTH_THE_JOURNEY'],'thresholds':{'minimum_completed_reviews_for_go_score':1},'disqualifiers':['UNRESOLVED_CONFIRMED_SERIOUS_RISK'],'evidence_requirements':{'required':['GO_TRUTH_OR_VERIFIED_OPERATIONAL_EVIDENCE'],'recommendation_requires_independent_assessment':True,'recommendation_not_derived_from_go_score':True,'worth_the_journey_explicit_yes_required':True,'commercial_independence_attestation_required':True,'commercial_fields_forbidden':True,'price_value_fields_excluded':True,'city_quota_forbidden':True,'fixed_recommendation_ratio_forbidden':True}}
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def out(r):return {c.name:(getattr(r,c.name).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}
class GoodHotelStandardService:
 def _event(self,s,row,event,actor,payload):s.add(GoodHotelStandardGovernanceEventRow(good_hotel_standard_governance_event_id=ident('ghse'),good_hotel_standard_version_id=row.good_hotel_standard_version_id,event_type=event,payload_json=payload,actor_id=actor,created_at=now()))
 def bootstrap(self):
  with SessionLocal() as s:
   row=s.scalar(select(GoodHotelStandardVersionRow).where(GoodHotelStandardVersionRow.state=='ACTIVE').order_by(GoodHotelStandardVersionRow.version_no.desc()))
   if row:return row
   row=GoodHotelStandardVersionRow(good_hotel_standard_version_id='ghsv_system_v1',version_no=1,standard_key='GO_GOOD_HOTEL_STANDARD',dimensions_json=DEFAULT['dimensions'],thresholds_json=DEFAULT['thresholds'],disqualifiers_json=DEFAULT['disqualifiers'],evidence_requirements_json=DEFAULT['evidence_requirements'],content_hash=digest(DEFAULT),state='ACTIVE',requested_by='SYSTEM_BOOTSTRAP',approved_by='SYSTEM_CONSTITUTION',effective_at=now(),created_at=now());s.add(row);self._event(s,row,'INITIAL_STANDARD_ACTIVATED','SYSTEM_CONSTITUTION',{'immutable_baseline':True});s.commit();return row
 def active(self):return self.bootstrap()
 def create(self,b,actor):
  forbidden={'price_threshold','commission','subscription','advertising','gmv','popularity'};raw={k:b[k] for k in ('dimensions','thresholds','disqualifiers','evidence_requirements')}
  if forbidden & set(raw['thresholds']):raise ValueError('COMMERCIAL_OR_POPULARITY_STANDARD_FIELD_FORBIDDEN')
  with SessionLocal() as s:
   n=(s.scalar(select(func.max(GoodHotelStandardVersionRow.version_no))) or 0)+1;row=GoodHotelStandardVersionRow(good_hotel_standard_version_id=ident('ghsv'),version_no=n,standard_key='GO_GOOD_HOTEL_STANDARD',dimensions_json=raw['dimensions'],thresholds_json=raw['thresholds'],disqualifiers_json=raw['disqualifiers'],evidence_requirements_json=raw['evidence_requirements'],content_hash=digest(raw),state='DRAFT',requested_by=actor,created_at=now());s.add(row);self._event(s,row,'STANDARD_VERSION_CREATED',actor,{});s.commit();return out(row)
 def approve(self,version_id,actor):
  with SessionLocal() as s:
   row=s.get(GoodHotelStandardVersionRow,version_id)
   if not row:raise ValueError('GOOD_HOTEL_STANDARD_NOT_FOUND')
   if row.requested_by==actor:raise ValueError('GOOD_HOTEL_STANDARD_MAKER_CHECKER_REQUIRED')
   for old in s.scalars(select(GoodHotelStandardVersionRow).where(GoodHotelStandardVersionRow.state=='ACTIVE')).all():old.state='SUPERSEDED';old.retired_at=now();self._event(s,old,'STANDARD_SUPERSEDED',actor,{'replacement_id':version_id})
   row.state='ACTIVE';row.approved_by=actor;row.effective_at=now();self._event(s,row,'STANDARD_ACTIVATED',actor,{});s.commit();return out(row)
 def status(self):
  with SessionLocal() as s:return {'versions':[out(x) for x in s.scalars(select(GoodHotelStandardVersionRow).order_by(GoodHotelStandardVersionRow.version_no.desc())).all()]}
good_hotel_standard_service=GoodHotelStandardService()
