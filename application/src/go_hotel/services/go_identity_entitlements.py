from datetime import datetime,timezone,timedelta
import hashlib,json
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import GoIdentityCredentialRow as C,GoIdentityEvidenceRow as E,GoIdentityEventRow as V,GoIdentitySupplierProgramRow as P,GoFriendsFamilyInvitationRow as F
from go_hotel.domain.models import new_id

RULE='GO_IDENTITY_V1'; ACTIVE={'ACTIVE'}; TYPES={'MEMBER','STAFF','FRIENDS_FAMILY','OWNER'}
def now():return datetime.now(timezone.utc)
def as_utc(value):
 if value is None:return None
 return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
def sha(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
def out(x):return {k:v for k,v in x.__dict__.items() if not k.startswith('_')}

class GoIdentityEntitlementService:
 def configuration(self,supplier_id):
  from go_hotel.db.models import HotelPartnerPropertyRow as Hotel,HotelPartnerRoomTypeRow as Room
  with SessionLocal() as s:
   programs=[out(x) for x in s.scalars(select(P).where(P.supplier_id==supplier_id).order_by(P.program_type)).all()]
   rooms=[{'room_type_id':r.room_type_id,'name':r.name_zh,'property_name':h.name_zh} for r,h in s.execute(select(Room,Hotel).join(Hotel,Hotel.property_id==Room.property_id).where(Hotel.supplier_id==supplier_id,Room.state=='ACTIVE').order_by(Hotel.name_zh,Room.name_zh)).all()]
   return {'programs':programs,'rooms':rooms,'revision':sha(programs)}
 def configure_programs(self,supplier_id,programs,revision,actor):
  """Atomically save named room selections; tenancy and authority are server facts."""
  from go_hotel.db.models import HotelPartnerPropertyRow as Hotel,HotelPartnerRoomTypeRow as Room
  types={'STAFF_RATE','OWNER_RATE','OWNER_BENEFITS','FRIENDS_FAMILY'}
  if len(programs)!=len({x['program_type'] for x in programs}) or any(x['program_type'] not in types for x in programs):raise ValueError('INVALID_PROGRAM_TYPE')
  with SessionLocal() as s:
   # Lock the supplier's properties even on the first configuration.
   s.scalars(select(Hotel).where(Hotel.supplier_id==supplier_id).order_by(Hotel.property_id).with_for_update()).all()
   current=s.scalars(select(P).where(P.supplier_id==supplier_id).order_by(P.program_type).with_for_update()).all()
   if sha([out(x) for x in current])!=revision:raise ValueError('PROGRAM_CONFIGURATION_CHANGED')
   room_ids=set(s.scalars(select(Room.room_type_id).join(Hotel,Hotel.property_id==Room.property_id).where(Hotel.supplier_id==supplier_id,Room.state=='ACTIVE')).all())
   existing={x.program_type:x for x in current}
   for item in programs:
    chosen=item['eligible_room_ids']
    if item['enabled'] and not chosen:raise ValueError('PROGRAM_ROOMS_REQUIRED')
    if not set(chosen)<=room_ids:raise ValueError('PROGRAM_ROOM_NOT_AVAILABLE')
    previous=existing.get(item['program_type'])
    prior_benefits=previous.benefits_json if previous else []
    benefits=item.get('benefits')
    if benefits is not None and not set(benefits)<=set(prior_benefits)|{'UPGRADE_PRIORITY','BREAKFAST','LATE_CHECKOUT'}:raise ValueError('INVALID_PROGRAM_BENEFIT')
    if item['program_type']=='OWNER_BENEFITS' and item['enabled'] and not (prior_benefits if benefits is None else benefits):raise ValueError('PROGRAM_BENEFITS_REQUIRED')
   t=now()
   for item in programs:
    typ=item['program_type'];row=existing.get(typ)
    if not row:
     row=P(supplier_program_id=new_id('gisp'),supplier_id=supplier_id,program_type=typ,open_date_ranges_json=[],benefits_json=[],rule_version=RULE)
     s.add(row)
    row.enabled=item['enabled'];row.eligible_room_ids_json=list(dict.fromkeys(item['eligible_room_ids']))
    if item.get('benefits') is not None:row.benefits_json=list(dict.fromkeys(item['benefits']))
    row.authorization_reference='SUPPLIER_CONSOLE:'+actor;row.updated_at=t
   s.commit()
  return self.configuration(supplier_id)
 def _event(self,s,c,event,actor,payload):
  h=sha({'credential_id':c.credential_id,'event':event,'state':c.state,'payload':payload})
  s.add(V(event_id=new_id('gievt'),credential_id=c.credential_id,event_type=event,previous_state=payload.get('previous_state'),current_state=c.state,actor_id=actor,evidence_hash=h,payload_json=payload,occurred_at=now()))
 def apply(self,account_id,credential_type,supplier_id=None):
  if credential_type not in TYPES:raise ValueError('INVALID_CREDENTIAL_TYPE')
  with SessionLocal() as s:
   old=s.scalar(select(C).where(C.account_id==account_id,C.credential_type==credential_type,C.state.in_(['PENDING','ACTIVE','REVIEW','SUSPENDED'])))
   if old:return out(old)
   t=now();state='ACTIVE' if credential_type=='MEMBER' else 'PENDING'
   c=C(credential_id=new_id('gic'),account_id=account_id,credential_type=credential_type,subject_supplier_id=supplier_id,state=state,selected_privilege=None,review_due_at=None,expires_at=None,revocation_reason=None,rule_version=RULE,created_at=t,updated_at=t);s.add(c);self._event(s,c,'IDENTITY_APPLICATION_SUBMITTED',account_id,{});s.commit();return out(c)
 def evidence(self,credential_id,b,actor):
  with SessionLocal() as s:
   c=s.get(C,credential_id)
   if not c:raise ValueError('CREDENTIAL_NOT_FOUND')
   if c.state in {'REVOKED','EXPIRED'}:raise ValueError('CREDENTIAL_TERMINAL')
   payload={k:b.get(k) for k in ['evidence_type','source_type','source_reference','subject_match','confidence_bps','valid_until']};h=sha(payload)
   if s.scalar(select(E).where(E.evidence_hash==h)):return self.get(c.account_id,credential_id)
   valid=b.get('valid_until');valid=datetime.fromisoformat(valid.replace('Z','+00:00')) if isinstance(valid,str) else valid
   e=E(evidence_id=new_id('gie'),credential_id=credential_id,evidence_type=b['evidence_type'],source_type=b['source_type'],source_reference=b['source_reference'],subject_match=bool(b['subject_match']),confidence_bps=int(b['confidence_bps']),valid_until=valid,evidence_hash=h,received_at=now());s.add(e)
   previous=c.state;qualified=e.subject_match and e.confidence_bps>=8000 and (not valid or valid>now())
   c.state='ACTIVE' if qualified else 'REVIEW';c.review_due_at=(now()+timedelta(days=90)) if qualified else now();c.updated_at=now()
   self._event(s,c,'STAFF_VERIFIED' if qualified and c.credential_type=='STAFF' else 'OWNER_VERIFIED' if qualified and c.credential_type=='OWNER' else 'IDENTITY_REVIEW_REQUIRED',actor,{'previous_state':previous,'evidence_id':e.evidence_id});s.commit();return out(c)
 def transition(self,credential_id,state,reason,actor):
  allowed={'ACTIVE':{'REVIEW','SUSPENDED','EXPIRED','REVOKED'},'REVIEW':{'ACTIVE','SUSPENDED','EXPIRED','REVOKED'},'SUSPENDED':{'REVIEW','ACTIVE','REVOKED'},'PENDING':{'REVIEW','ACTIVE','REVOKED'}}
  with SessionLocal() as s:
   c=s.get(C,credential_id)
   if not c:raise ValueError('CREDENTIAL_NOT_FOUND')
   if state not in allowed.get(c.state,set()):raise ValueError('INVALID_IDENTITY_TRANSITION')
   previous=c.state;c.state=state;c.revocation_reason=reason if state in {'REVOKED','SUSPENDED','EXPIRED'} else None;c.updated_at=now();self._event(s,c,'STAFF_'+state if c.credential_type=='STAFF' else 'IDENTITY_'+state,actor,{'previous_state':previous,'reason':reason});s.commit();return out(c)
 def select_owner_privilege(self,account_id,credential_id,privilege):
  if privilege not in {'OWNER_RATE','OWNER_BENEFITS'}:raise ValueError('INVALID_OWNER_PRIVILEGE')
  with SessionLocal() as s:
   c=s.get(C,credential_id)
   if not c or c.account_id!=account_id or c.credential_type!='OWNER' or c.state!='ACTIVE':raise ValueError('ACTIVE_OWNER_CREDENTIAL_REQUIRED')
   c.selected_privilege=privilege;c.updated_at=now();self._event(s,c,'IDENTITY_PRIVILEGE_SELECTED',account_id,{'privilege':privilege});s.commit();return out(c)
 def program(self,supplier_id,b,actor):
  typ=b['program_type']
  if typ not in {'STAFF_RATE','OWNER_RATE','OWNER_BENEFITS','FRIENDS_FAMILY'}:raise ValueError('INVALID_PROGRAM_TYPE')
  with SessionLocal() as s:
   p=s.scalar(select(P).where(P.supplier_id==supplier_id,P.program_type==typ));t=now()
   vals=dict(enabled=bool(b['enabled']),eligible_room_ids_json=b.get('eligible_room_ids',[]),open_date_ranges_json=b.get('open_date_ranges',[]),inventory_limit=b.get('inventory_limit'),benefits_json=b.get('benefits',[]),authorization_reference=b['authorization_reference'],rule_version=RULE,updated_at=t)
   if p:
    for k,v in vals.items():setattr(p,k,v)
   else:p=P(supplier_program_id=new_id('gisp'),supplier_id=supplier_id,program_type=typ,**vals);s.add(p)
   s.commit();return out(p)
 def entitlement(self,account_id,supplier_id,room_id,stay_date,bar_minor):
  with SessionLocal() as s:
   creds=s.scalars(select(C).where(C.account_id==account_id,C.state=='ACTIVE')).all();programs=s.scalars(select(P).where(P.supplier_id==supplier_id,P.enabled==True)).all()
   by_type={x.credential_type:x for x in creds};progs={x.program_type:x for x in programs}
   def open_for(p):
    if p.eligible_room_ids_json and room_id not in p.eligible_room_ids_json:return False
    return not p.open_date_ranges_json or any(x['start']<=stay_date<=x['end'] for x in p.open_date_ranges_json)
   selected='MEMBER';price=bar_minor;benefits=[];recognition=None
   owner=by_type.get('OWNER')
   if owner and owner.selected_privilege=='OWNER_RATE' and progs.get('OWNER_RATE') and open_for(progs['OWNER_RATE']):selected='OWNER';price=bar_minor*60//100;recognition='OWNER'
   elif owner and owner.selected_privilege=='OWNER_BENEFITS' and progs.get('OWNER_BENEFITS') and open_for(progs['OWNER_BENEFITS']):selected='OWNER';benefits=progs['OWNER_BENEFITS'].benefits_json;recognition='OWNER'
   elif by_type.get('STAFF') and progs.get('STAFF_RATE') and open_for(progs['STAFF_RATE']):selected='STAFF';price=bar_minor*60//100
   elif by_type.get('FRIENDS_FAMILY') and progs.get('FRIENDS_FAMILY') and open_for(progs['FRIENDS_FAMILY']):selected='FRIENDS_FAMILY';price=max(bar_minor*61//100,bar_minor*int(80)//100)
   return {'identity':selected,'price_minor':price,'discount_bps':10000-price*10000//bar_minor if bar_minor else 0,'benefits':benefits,'owner_recognition':recognition,'stacking_allowed':False,'rule_version':RULE}
 def invite(self,account_id,staff_id,invitee_id,name,expires_at,limit=2):
  with SessionLocal() as s:
   c=s.get(C,staff_id)
   if not c or c.account_id!=account_id or c.credential_type!='STAFF' or c.state!='ACTIVE':raise ValueError('ACTIVE_STAFF_CREDENTIAL_REQUIRED')
   active=s.scalars(select(F).where(F.staff_credential_id==staff_id,F.state=='ACTIVE')).all()
   if len(active)>=limit:raise ValueError('FRIENDS_FAMILY_INVITATION_LIMIT_REACHED')
   exp=datetime.fromisoformat(expires_at.replace('Z','+00:00'));f=F(invitation_id=new_id('giff'),staff_credential_id=staff_id,invitee_account_id=invitee_id,invitee_name_hash=hashlib.sha256(name.strip().lower().encode()).hexdigest(),state='ACTIVE',annual_usage_limit=limit,used_count=0,transferable=False,expires_at=exp,created_at=now());s.add(f)
   cred=C(credential_id=new_id('gic'),account_id=invitee_id,credential_type='FRIENDS_FAMILY',subject_supplier_id=c.subject_supplier_id,state='ACTIVE',selected_privilege=None,review_due_at=exp,expires_at=exp,revocation_reason=None,rule_version=RULE,created_at=now(),updated_at=now());s.add(cred);self._event(s,cred,'FRIENDS_FAMILY_INVITED',account_id,{'invitation_id':f.invitation_id});s.commit();return out(f)
 def get(self,account_id,credential_id):
  with SessionLocal() as s:
   c=s.get(C,credential_id)
   if not c or c.account_id!=account_id:raise ValueError('CREDENTIAL_NOT_FOUND')
   return out(c)
 def list(self,account_id):
  with SessionLocal() as s:return [out(x) for x in s.scalars(select(C).where(C.account_id==account_id).order_by(C.created_at)).all()]
 def all_credentials(self,state=None):
  with SessionLocal() as s:
   q=select(C).order_by(C.updated_at.desc())
   if state:q=q.where(C.state==state)
   return [out(x) for x in s.scalars(q).all()]
 def programs(self,supplier_id):
  with SessionLocal() as s:return [out(x) for x in s.scalars(select(P).where(P.supplier_id==supplier_id).order_by(P.program_type)).all()]
 def revalidate_due(self,actor):
  t=now();changed=[]
  with SessionLocal() as s:
   rows=s.scalars(select(C).where(C.state.in_(['ACTIVE','REVIEW']),((C.expires_at!=None)&(C.expires_at<=t))|((C.review_due_at!=None)&(C.review_due_at<=t)))).all()
   for c in rows:
    previous=c.state
    if c.expires_at and c.expires_at<=t:c.state='EXPIRED';c.revocation_reason='CREDENTIAL_EXPIRED';event='IDENTITY_EXPIRED'
    else:c.state='REVIEW';event='STAFF_REVIEW_REQUIRED' if c.credential_type=='STAFF' else 'IDENTITY_REVIEW_REQUIRED'
    c.updated_at=t;self._event(s,c,event,actor,{'previous_state':previous,'reason':'SCHEDULED_REVALIDATION'});changed.append(c.credential_id)
   s.commit();return {'processed':len(changed),'credential_ids':changed,'supplier_fact_unchanged':True}
 def risk_signal(self,credential_id,b,actor):
  score=int(b['risk_score_bps'])
  with SessionLocal() as s:
   c=s.get(C,credential_id)
   if not c:raise ValueError('CREDENTIAL_NOT_FOUND')
   previous=c.state
   if score>=9000:c.state='SUSPENDED';event='STAFF_SUSPENDED' if c.credential_type=='STAFF' else 'IDENTITY_SUSPENDED'
   elif score>=7000:c.state='REVIEW';event='STAFF_REVIEW_REQUIRED' if c.credential_type=='STAFF' else 'IDENTITY_REVIEW_REQUIRED'
   else:return out(c)
   c.revocation_reason=b['reason_code'];c.updated_at=now();self._event(s,c,event,actor,{'previous_state':previous,'risk_score_bps':score,'reason_code':b['reason_code'],'evidence_reference':b['evidence_reference']});s.commit();return out(c)
 def consume_invitation(self,invitee_account_id,invitation_id):
  with SessionLocal() as s:
   f=s.get(F,invitation_id)
   if not f or f.invitee_account_id!=invitee_account_id or f.state!='ACTIVE':raise ValueError('ACTIVE_INVITATION_REQUIRED')
   if as_utc(f.expires_at)<=now():f.state='EXPIRED';s.commit();raise ValueError('INVITATION_EXPIRED')
   if f.used_count>=f.annual_usage_limit:raise ValueError('FRIENDS_FAMILY_USAGE_LIMIT_REACHED')
   f.used_count+=1
   if f.used_count>=f.annual_usage_limit:f.state='CONSUMED'
   s.commit();return out(f)

go_identity_entitlement_service=GoIdentityEntitlementService()
