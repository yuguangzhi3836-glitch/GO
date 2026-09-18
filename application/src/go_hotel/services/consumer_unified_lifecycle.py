from datetime import datetime,timezone
import uuid
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import ConsumerUnifiedLifecycleRow as Life,ConsumerUnifiedLifecycleEventRow as Event
from go_hotel.services.phase1_closure import VERTICALS
STATES={'CONVERTED_TO_CREDIT','PENDING','CONFIRMED','IN_PROGRESS','COMPLETED','CANCELLED','FAILED','UNKNOWN_EXTERNAL_STATE','MANUAL_REVIEW'}
def now():return datetime.now(timezone.utc)
def ident(p):return f'{p}_{uuid.uuid4().hex}'
def out(r):return {c.name:(getattr(r,c.name).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}

class ConsumerUnifiedLifecycleService:
 def import_external_order(self,account_id,b,*,trusted_provider=False):
  provider=str(b.get('provider') or '').upper();external_id=str(b.get('external_order_id') or '').strip();vertical=str(b.get('vertical') or '').upper()
  if provider not in {'CTRIP','MEITUAN','FLIGGY','BOOKING','OTHER_OTA'}:raise ValueError('UNSUPPORTED_EXTERNAL_ORDER_PROVIDER')
  if not external_id:raise ValueError('EXTERNAL_ORDER_ID_REQUIRED')
  if vertical not in VERTICALS:raise ValueError('INVALID_VERTICAL_OR_LIFECYCLE_STATE')
  source_updated_at=b.get('source_updated_at') or now().isoformat()
  requested_state=str(b.get('lifecycle_state') or 'CONFIRMED').upper()
  lifecycle_state=requested_state if trusted_provider and requested_state in STATES else 'MANUAL_REVIEW'
  payment_state=str(b.get('payment_state') or 'UNKNOWN_EXTERNAL_STATE').upper() if trusted_provider else 'UNKNOWN_EXTERNAL_STATE'
  refund_state=str(b.get('refund_state') or 'NOT_REQUESTED').upper() if trusted_provider else 'UNKNOWN_EXTERNAL_STATE'
  deep_link=b.get('servicing_deep_link')
  facts={**(b.get('facts') or {}),'transaction_platform':provider,'external_order_id':external_id,'fulfillment_owner':provider,'servicing_deep_link':deep_link,'imported_to_go_trips':True,'source_verification':'OFFICIAL_PROVIDER' if trusted_provider else 'USER_SUBMITTED_PENDING_VERIFICATION'}
  return self.project({'account_id':account_id,'vertical':vertical,'order_id':f'ext:{provider}:{external_id}','title':b.get('title') or f'{provider} {vertical} 订单','lifecycle_state':lifecycle_state,'payment_state':payment_state,'refund_state':refund_state,'change_allowed':False,'cancel_allowed':False,'facts':facts,'evidence_reference':b.get('evidence_reference') if trusted_provider else f'user-import://{provider}/{external_id}','source_updated_at':source_updated_at,'event_type':'EXTERNAL_ORDER_IMPORTED'})
 def project_in_session(self,s,b,*,allow_new_refund_cycle=False):
  required=('account_id','vertical','order_id','title','lifecycle_state','payment_state','refund_state','evidence_reference','source_updated_at')
  if any(b.get(x) in (None,'') for x in required):raise ValueError('COMPLETE_VERTICAL_LIFECYCLE_FACT_REQUIRED')
  if b['vertical'] not in VERTICALS or b['lifecycle_state'] not in STATES:raise ValueError('INVALID_VERTICAL_OR_LIFECYCLE_STATE')
  source_raw=b['source_updated_at']
  if isinstance(source_raw,datetime): source_at=source_raw
  else: source_at=datetime.fromisoformat(str(source_raw).replace('Z','+00:00'))
  if source_at.tzinfo is None: source_at=source_at.replace(tzinfo=timezone.utc)
  r=s.scalar(select(Life).where(Life.vertical==b['vertical'],Life.order_id==b['order_id']))
  if r:
   if r.account_id!=b['account_id']:raise ValueError('UNIFIED_LIFECYCLE_ACCOUNT_IMMUTABLE')
   existing_at=r.source_updated_at
   if existing_at.tzinfo is None: existing_at=existing_at.replace(tzinfo=timezone.utc)
   if source_at<=existing_at:return out(r)|{'stale_ignored':True}
   terminal={'CONVERTED_TO_CREDIT','COMPLETED','CANCELLED','FAILED'}
   if r.lifecycle_state in terminal and b['lifecycle_state']!=r.lifecycle_state:raise ValueError('UNIFIED_LIFECYCLE_TERMINAL_STATE_IMMUTABLE')
   rank={'PENDING':0,'CONFIRMED':1,'IN_PROGRESS':2,'COMPLETED':3}
   if r.lifecycle_state in rank and b['lifecycle_state'] in rank and rank[b['lifecycle_state']]<rank[r.lifecycle_state]:raise ValueError('UNIFIED_LIFECYCLE_STATE_REGRESSION')
   terminal_refunds={'REFUND_COMPLETED','REFUNDED'}
   if r.refund_state in terminal_refunds and b['refund_state'] not in terminal_refunds:
    old_cycle=(r.facts_json or {}).get('refund_cycle_count',0)
    new_cycle=(b.get('facts') or {}).get('refund_cycle_count',0)
    if not (allow_new_refund_cycle and b['refund_state']=='REFUND_PROCESSING' and type(new_cycle) is int and type(old_cycle) is int and new_cycle>old_cycle):
     raise ValueError('UNIFIED_LIFECYCLE_REFUND_STATE_IMMUTABLE')
  vals=dict(account_id=b['account_id'],supplier_id=b.get('supplier_id'),title=b['title'],lifecycle_state=b['lifecycle_state'],payment_state=b['payment_state'],refund_state=b['refund_state'],change_allowed=bool(b.get('change_allowed',False)),cancel_allowed=bool(b.get('cancel_allowed',False)),facts_json=b.get('facts',{}),evidence_reference=b['evidence_reference'],source_updated_at=source_at,updated_at=now())
  if not r:r=Life(consumer_unified_lifecycle_id=ident('cul'),vertical=b['vertical'],order_id=b['order_id'],**vals);s.add(r);s.flush()
  else:
   for k,v in vals.items():setattr(r,k,v)
  s.add(Event(consumer_unified_lifecycle_event_id=ident('cule'),consumer_unified_lifecycle_id=r.consumer_unified_lifecycle_id,event_type=b.get('event_type') or 'VERTICAL_FACT_PROJECTED',state=r.lifecycle_state,evidence_reference=r.evidence_reference,occurred_at=now()));s.flush();return out(r)|{'stale_ignored':False}
 def project(self,b):
  with SessionLocal() as s:
   result=self.project_in_session(s,b);s.commit();return result
 def list(self,account):
  with SessionLocal() as s:return [out(x) for x in s.scalars(select(Life).where(Life.account_id==account).order_by(Life.source_updated_at.desc())).all()]
 def detail(self,account,lid):
  with SessionLocal() as s:
   r=s.get(Life,lid)
   if not r or r.account_id!=account:raise ValueError('UNIFIED_LIFECYCLE_NOT_FOUND')
   events=s.scalars(select(Event).where(Event.consumer_unified_lifecycle_id==lid).order_by(Event.occurred_at)).all();return {'item':out(r),'events':[out(x) for x in events]}
consumer_unified_lifecycle_service=ConsumerUnifiedLifecycleService()
