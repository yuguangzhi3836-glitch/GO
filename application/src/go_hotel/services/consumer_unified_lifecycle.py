from datetime import datetime, timezone, timedelta
import hashlib, json, re
import uuid
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from go_hotel.db.session import SessionLocal
from go_hotel.db.models import ConsumerUnifiedLifecycleRow as Life, ConsumerUnifiedLifecycleEventRow as Event
from go_hotel.services.phase1_closure import VERTICALS
from go_hotel.security.external_navigation import validate_external_navigation_url

STATES = {'CONVERTED_TO_CREDIT', 'PENDING', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', 'FAILED', 'UNKNOWN_EXTERNAL_STATE', 'MANUAL_REVIEW'}
EXTERNAL_PROVIDERS = {'CTRIP', 'MEITUAN', 'FLIGGY', 'BOOKING', 'OTHER_OTA'}
PAYMENT_STATES = {'UNKNOWN_EXTERNAL_STATE', 'NOT_REQUIRED', 'PENDING', 'AUTHORIZED', 'PAID', 'CAPTURED', 'FAILED', 'CANCELLED', 'PARTIALLY_REFUNDED', 'REFUNDED'}
REFUND_STATES = {'UNKNOWN_EXTERNAL_STATE', 'NOT_REQUESTED', 'NOT_REFUNDABLE', 'REFUND_REQUESTED', 'REFUND_PROCESSING', 'REFUND_COMPLETED', 'REFUNDED', 'REFUND_FAILED'}
OFFICIAL_ADAPTERS = {'ctrip-orders-v1': 'CTRIP', 'meituan-orders-v1': 'MEITUAN', 'fliggy-orders-v1': 'FLIGGY', 'booking-orders-v1': 'BOOKING'}
SERVICE_LINK_SCHEMES = {'CTRIP': {'ctrip', 'https'}, 'MEITUAN': {'imeituan', 'meituan', 'https'}, 'FLIGGY': {'fliggy', 'https'}, 'BOOKING': {'booking', 'https'}, 'OTHER_OTA': {'https'}}
SERVICE_LINK_HOSTS = {'CTRIP': {'ctrip.com', 'trip.com'}, 'MEITUAN': {'meituan.com', 'dianping.com'}, 'FLIGGY': {'fliggy.com', 'alitrip.com'}, 'BOOKING': {'booking.com'}}
SAFE_EXTERNAL_FACTS = {'check_in','check_out','departure_at','arrival_at','origin','destination','city','currency','amount_minor','provider_status','confirmation_status','hotel_name','route_summary'}


def now(): return datetime.now(timezone.utc)
def ident(prefix): return f'{prefix}_{uuid.uuid4().hex}'
def out(row): return {column.name: (getattr(row, column.name).isoformat() if isinstance(getattr(row, column.name), datetime) else getattr(row, column.name)) for column in row.__table__.columns}


def _external_order_key(account_id, provider, external_id):
    """Opaque account-scoped key prevents cross-consumer collisions and probing."""
    digest = hashlib.sha256(f'{account_id}\0{provider}\0{external_id}'.encode()).hexdigest()[:32]
    return f'ext:{provider}:{digest}'


def _service_link(provider, value):
    if value in (None, ''): return None
    value = str(value).strip(); parsed = urlparse(value)
    if parsed.scheme.lower() not in SERVICE_LINK_SCHEMES[provider] or parsed.username or parsed.password or not (parsed.netloc or parsed.path):
        raise ValueError('INVALID_EXTERNAL_SERVICE_LINK')
    if parsed.scheme.lower() == 'https' and provider != 'OTHER_OTA':
        host = (parsed.hostname or '').lower()
        if not any(host == allowed or host.endswith('.' + allowed) for allowed in SERVICE_LINK_HOSTS[provider]):
            raise ValueError('INVALID_EXTERNAL_SERVICE_LINK')
    try:return validate_external_navigation_url(value,allowed_custom_schemes=SERVICE_LINK_SCHEMES[provider]-{'https'})
    except ValueError as exc:raise ValueError('INVALID_EXTERNAL_SERVICE_LINK') from exc


class ConsumerUnifiedLifecycleService:
 def import_external_order(self, account_id, b, *, trusted_provider=False, adapter_id=None):
  """Import a user claim or project a deterministic event from an allowlisted OTA adapter."""
  account_id=str(account_id or '').strip();provider=str(b.get('provider') or '').upper();external_id=str(b.get('external_order_id') or '').strip();vertical=str(b.get('vertical') or '').upper()
  if not account_id: raise ValueError('ACCOUNT_ID_REQUIRED')
  if provider not in EXTERNAL_PROVIDERS: raise ValueError('UNSUPPORTED_EXTERNAL_ORDER_PROVIDER')
  if not external_id or len(external_id)>256 or any(ord(ch)<32 for ch in external_id): raise ValueError('EXTERNAL_ORDER_ID_REQUIRED')
  if vertical not in VERTICALS: raise ValueError('INVALID_VERTICAL_OR_LIFECYCLE_STATE')
  official=bool(trusted_provider)
  if official:
   if OFFICIAL_ADAPTERS.get(str(adapter_id or ''))!=provider: raise ValueError('TRUSTED_OTA_ADAPTER_REQUIRED')
   source_event_id=str(b.get('source_event_id') or '').strip();provider_evidence=str(b.get('evidence_reference') or '').strip()
   if not source_event_id or not provider_evidence or not b.get('source_updated_at'): raise ValueError('COMPLETE_OTA_EVENT_EVIDENCE_REQUIRED')
   evidence=f'ota-event://{adapter_id}/{hashlib.sha256(source_event_id.encode()).hexdigest()}'
   lifecycle=str(b.get('lifecycle_state') or '').upper();payment=str(b.get('payment_state') or '').upper();refund=str(b.get('refund_state') or '').upper()
   if lifecycle not in STATES: raise ValueError('INVALID_VERTICAL_OR_LIFECYCLE_STATE')
   if payment not in PAYMENT_STATES or refund not in REFUND_STATES: raise ValueError('INVALID_EXTERNAL_MONEY_STATE')
   source_at=b['source_updated_at'];source_dt=datetime.fromisoformat(str(source_at).replace('Z','+00:00'))
   if source_dt.tzinfo is None:source_dt=source_dt.replace(tzinfo=timezone.utc)
   if source_dt>now()+timedelta(minutes=5):raise ValueError('EXTERNAL_ORDER_SOURCE_TIME_INVALID')
   event_type=str(b.get('event_type') or 'EXTERNAL_ORDER_UPDATED').upper()
   service_link=_service_link(provider,b.get('servicing_deep_link'));change_link=_service_link(provider,b.get('change_deep_link') or service_link);refund_link=_service_link(provider,b.get('refund_deep_link') or service_link)
   change_allowed=bool(b.get('change_allowed',False) and change_link);cancel_allowed=bool(b.get('cancel_allowed',False) and refund_link);verification='OFFICIAL_PROVIDER'
  else:
   lifecycle='MANUAL_REVIEW';payment=refund='UNKNOWN_EXTERNAL_STATE';source_at=now().isoformat();source_event_id=None
   provider_evidence=None;evidence=f'user-import://{provider}/{hashlib.sha256(external_id.encode()).hexdigest()[:24]}';event_type='EXTERNAL_ORDER_USER_IMPORTED'
   service_link=change_link=refund_link=None;change_allowed=cancel_allowed=False;verification='USER_SUBMITTED_PENDING_VERIFICATION'
  order_id=_external_order_key(account_id,provider,external_id)
  supplied=b.get('facts') or {}
  if not isinstance(supplied,dict):raise ValueError('EXTERNAL_ORDER_FACTS_INVALID')
  safe_facts={key:value for key,value in supplied.items() if key in SAFE_EXTERNAL_FACTS}
  # A projected amount is data, never a coercion from a display string or flag.
  # Reject invalid money before opening a transaction, including on re-import.
  if 'amount_minor' in safe_facts and (type(safe_facts['amount_minor']) is not int or safe_facts['amount_minor']<0):
   raise ValueError('EXTERNAL_ORDER_AMOUNT_INVALID')
  if len(json.dumps(safe_facts,ensure_ascii=False,default=str))>16384:raise ValueError('EXTERNAL_ORDER_FACTS_INVALID')
  masked_id='*'*max(0,len(external_id)-4)+external_id[-4:]
  facts={**safe_facts,'transaction_platform':provider,'external_order_id_masked':masked_id,'external_order_id_hash':hashlib.sha256(f'{provider}\0{external_id}'.encode()).hexdigest(),'order_origin':'EXTERNAL_OTA','fulfillment_owner':provider,'support_owner':provider,'go_role':'AGGREGATION_AND_NAVIGATION','servicing_deep_link':service_link,'service_actions':{'change':{'owner':provider,'deep_link':change_link} if change_link else None,'refund_or_cancel':{'owner':provider,'deep_link':refund_link} if refund_link else None},'imported_to_go_trips':True,'source_verification':verification,'source_event_id':source_event_id,'source_adapter_id':adapter_id if official else None,'provider_evidence_hash':hashlib.sha256(str(provider_evidence or '').encode()).hexdigest() if provider_evidence else None}
  title=str(b.get('title') or f'{provider} {vertical} 订单').strip()
  if not title or len(title)>200 or re.search(r'[\x00-\x1f]',title):raise ValueError('EXTERNAL_ORDER_TITLE_INVALID')
  payload={'account_id':account_id,'vertical':vertical,'order_id':order_id,'title':title,'lifecycle_state':lifecycle,'payment_state':payment,'refund_state':refund,'change_allowed':change_allowed,'cancel_allowed':cancel_allowed,'facts':facts,'evidence_reference':evidence,'source_updated_at':source_at,'event_type':event_type}
  with SessionLocal() as s:
   existing=s.scalar(select(Life).where(Life.account_id==account_id,Life.vertical==vertical,Life.order_id==order_id))
   if existing and not official: return out(existing)|{'stale_ignored':True}
   if existing and official and s.scalar(select(Event).where(Event.consumer_unified_lifecycle_id==existing.consumer_unified_lifecycle_id,Event.evidence_reference==evidence)):
    return out(existing)|{'stale_ignored':True}
   try:
    result=self.project_in_session(s,payload,idempotent_if_exists=not official,allow_external_verification_upgrade=official);s.commit();return result
   except IntegrityError:
    s.rollback()
    if official:raise
    existing=s.scalar(select(Life).where(Life.account_id==account_id,Life.vertical==vertical,Life.order_id==order_id))
    if not existing:raise
    return out(existing)|{'stale_ignored':True}

 def project_in_session(self,s,b,*,allow_new_refund_cycle=False,idempotent_if_exists=False,allow_external_verification_upgrade=False):
  required=('account_id','vertical','order_id','title','lifecycle_state','payment_state','refund_state','evidence_reference','source_updated_at')
  if any(b.get(x) in (None,'') for x in required):raise ValueError('COMPLETE_VERTICAL_LIFECYCLE_FACT_REQUIRED')
  if b['vertical'] not in VERTICALS or b['lifecycle_state'] not in STATES:raise ValueError('INVALID_VERTICAL_OR_LIFECYCLE_STATE')
  source_raw=b['source_updated_at'];source_at=source_raw if isinstance(source_raw,datetime) else datetime.fromisoformat(str(source_raw).replace('Z','+00:00'))
  if source_at.tzinfo is None:source_at=source_at.replace(tzinfo=timezone.utc)
  r=s.scalar(select(Life).where(Life.vertical==b['vertical'],Life.order_id==b['order_id']).with_for_update())
  if r:
   if r.account_id!=b['account_id']:raise ValueError('UNIFIED_LIFECYCLE_ACCOUNT_IMMUTABLE')
   if idempotent_if_exists:return out(r)|{'stale_ignored':True}
   existing_at=r.source_updated_at
   if existing_at.tzinfo is None:existing_at=existing_at.replace(tzinfo=timezone.utc)
   # A user-import timestamp records receipt of an unverified claim, not the
   # provider's event clock. The first authenticated provider fact may predate
   # that receipt. Promote it once, retaining its true source timestamp; normal
   # stale-event protection resumes for all subsequent provider updates.
   old_facts=r.facts_json or {};new_facts=b.get('facts') or {}
   verification_upgrade=(allow_external_verification_upgrade
    and r.lifecycle_state=='MANUAL_REVIEW'
    and old_facts.get('order_origin')=='EXTERNAL_OTA'
    and old_facts.get('source_verification')=='USER_SUBMITTED_PENDING_VERIFICATION'
    and new_facts.get('source_verification')=='OFFICIAL_PROVIDER'
    and new_facts.get('transaction_platform')==old_facts.get('transaction_platform')
    and OFFICIAL_ADAPTERS.get(new_facts.get('source_adapter_id'))==old_facts.get('transaction_platform'))
   if source_at<=existing_at and not verification_upgrade:return out(r)|{'stale_ignored':True}
   terminal={'CONVERTED_TO_CREDIT','COMPLETED','CANCELLED','FAILED'}
   if r.lifecycle_state in terminal and b['lifecycle_state']!=r.lifecycle_state:raise ValueError('UNIFIED_LIFECYCLE_TERMINAL_STATE_IMMUTABLE')
   rank={'PENDING':0,'CONFIRMED':1,'IN_PROGRESS':2,'COMPLETED':3}
   if r.lifecycle_state in rank and b['lifecycle_state'] in rank and rank[b['lifecycle_state']]<rank[r.lifecycle_state]:raise ValueError('UNIFIED_LIFECYCLE_STATE_REGRESSION')
   terminal_refunds={'REFUND_COMPLETED','REFUNDED'}
   if r.refund_state in terminal_refunds and b['refund_state'] not in terminal_refunds:
    old_cycle=(r.facts_json or {}).get('refund_cycle_count',0);new_cycle=(b.get('facts') or {}).get('refund_cycle_count',0)
    if not (allow_new_refund_cycle and b['refund_state']=='REFUND_PROCESSING' and type(new_cycle) is int and type(old_cycle) is int and new_cycle>old_cycle):raise ValueError('UNIFIED_LIFECYCLE_REFUND_STATE_IMMUTABLE')
  vals=dict(account_id=b['account_id'],supplier_id=b.get('supplier_id'),title=b['title'],lifecycle_state=b['lifecycle_state'],payment_state=b['payment_state'],refund_state=b['refund_state'],change_allowed=bool(b.get('change_allowed',False)),cancel_allowed=bool(b.get('cancel_allowed',False)),facts_json=b.get('facts',{}),evidence_reference=b['evidence_reference'],source_updated_at=source_at,updated_at=now())
  if not r:r=Life(consumer_unified_lifecycle_id=ident('cul'),vertical=b['vertical'],order_id=b['order_id'],**vals);s.add(r);s.flush()
  else:
   for k,v in vals.items():setattr(r,k,v)
  s.add(Event(consumer_unified_lifecycle_event_id=ident('cule'),consumer_unified_lifecycle_id=r.consumer_unified_lifecycle_id,event_type=b.get('event_type') or 'VERTICAL_FACT_PROJECTED',state=r.lifecycle_state,evidence_reference=r.evidence_reference,occurred_at=now()));s.flush();return out(r)|{'stale_ignored':False}
 def project(self,b):
  with SessionLocal() as s:result=self.project_in_session(s,b);s.commit();return result
 def list(self,account):
  with SessionLocal() as s:return [out(x) for x in s.scalars(select(Life).where(Life.account_id==account).order_by(Life.source_updated_at.desc())).all()]
 def detail(self,account,lid):
  with SessionLocal() as s:
   r=s.get(Life,lid)
   if not r or r.account_id!=account:raise ValueError('UNIFIED_LIFECYCLE_NOT_FOUND')
   events=s.scalars(select(Event).where(Event.consumer_unified_lifecycle_id==lid).order_by(Event.occurred_at)).all();return {'item':out(r),'events':[out(x) for x in events]}


consumer_unified_lifecycle_service=ConsumerUnifiedLifecycleService()
