"""Content approval safety gate; real hotel authority remains unconfigured.

The only enabled approval source is explicit isolated engineering provisioning.
No public staff-role assignment can grant the reserved content approval role.
Media registration preserves unverified claims only. A legacy RIGHTS_VERIFIED
label is not independently verified rights evidence. This module does not gate
all publication paths.
"""
import hashlib,json,uuid,os
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (HostedDirectHotelRow,HostedDirectInventoryPoolRow,
 HostedContentSnapshotRow,HostedContentApprovalRow,HostedMediaAssetRow,
 HostedStaffRoleRow,IdentityUserRow,AuthSessionRow)
from go_hotel.security.service import Principal
from go_hotel.security.rbac import permissions_for
from go_hotel.autonomy.durable import transaction,db_now_ms
from go_hotel.services.travel_operational_facts import environment_allowed

SCHEMA='HOTEL_CONTENT_SNAPSHOT_V2'
ROLE='HOTEL_CONTENT_APPROVER'
APPROVAL_ROLE='ISOLATED_CONTENT_APPROVER'
def now():return datetime.now(timezone.utc)
def ident(p):return f'{p}_{uuid.uuid4().hex}'
def out(r):return {c.name:(getattr(r,c.name).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def aware(value):return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

def authority_mode():
 environment_allowed('ENGINEERING')
 if os.getenv('GO_HOSTED_CONTENT_AUTHORITY_MODE')!='ISOLATED_FIXTURE':
  raise PermissionError('HOTEL_CONTENT_REAL_AUTHORITY_UNVERIFIED')

def user_checked(s,uid,permission):
 user=s.get(IdentityUserRow,uid)
 if not user or user.status!='ACTIVE' or user.actor_type!='GO_ADMIN' or permission not in permissions_for(user.roles or []):
  raise PermissionError('HOTEL_CONTENT_PERMISSION_REQUIRED')
 return user

def principal_checked(s,p,permission):
 if not isinstance(p,Principal):raise PermissionError('HOTEL_CONTENT_AUTHENTICATED_PRINCIPAL_REQUIRED')
 user_checked(s,p.user_id,permission)
 session=s.get(AuthSessionRow,p.session_id)
 if not session or session.user_id!=p.user_id or session.status!='ACTIVE' or session.revoked_at is not None or aware(session.expires_at).timestamp()*1000<=db_now_ms(s):
  raise PermissionError('HOTEL_CONTENT_ACTIVE_SESSION_REQUIRED')
 return p.user_id

def binding_checked(s,hotel,uid):
 authority_mode()
 binding=s.scalar(select(HostedStaffRoleRow).where(HostedStaffRoleRow.hosted_hotel_id==hotel,
  HostedStaffRoleRow.staff_id==uid,HostedStaffRoleRow.role==ROLE,HostedStaffRoleRow.state=='ACTIVE').with_for_update())
 if not binding:raise PermissionError('HOTEL_CONTENT_SCOPED_AUTHORITY_REQUIRED')
 # This fixed server-held marker is engineering provenance, never hotel approval.
 if binding.evidence_reference!='isolated://hosted-content-authority/v1':
  raise PermissionError('HOTEL_CONTENT_AUTHORITY_SOURCE_UNVERIFIED')
 return binding

def binding_hash(binding):
 return digest({'id':binding.staff_role_id,'hotel':binding.hosted_hotel_id,'staff':binding.staff_id,
  'role':binding.role,'state':binding.state,'source':binding.evidence_reference,
  'created_at':aware(binding.created_at).isoformat()})

def approval_evidence(binding,snap,reference):
 result=json.dumps({'schema':'CONTENT_APPROVAL_V2','reference':reference,
  'binding_id':binding.staff_role_id,'binding_hash':binding_hash(binding),'snapshot_hash':snap.content_hash},
  sort_keys=True,separators=(',',':'),ensure_ascii=False)
 if len(result)>512:raise ValueError('CONTENT_APPROVAL_REFERENCE_TOO_LONG')
 return result

def approval_out(row):
 result=out(row)
 metadata=json.loads(row.evidence_reference)
 result['evidence_reference']=metadata['reference']
 result['approval_metadata']={key:value for key,value in metadata.items() if key!='reference'}
 return result

def snapshot_checked(s,snap):
 if not snap:raise ValueError('CONTENT_SNAPSHOT_NOT_FOUND')
 body=snap.content_json
 if (not isinstance(body,dict) or set(body)!={'schema','hosted_hotel_id','version','created_by','payload'}
  or body.get('schema')!=SCHEMA):raise ValueError('CONTENT_LEGACY_SNAPSHOT_UNVERIFIED')
 if body['hosted_hotel_id']!=snap.hosted_hotel_id or body['version']!=snap.version or not isinstance(body['created_by'],str) or digest(body)!=snap.content_hash:
  raise ValueError('CONTENT_SNAPSHOT_INTEGRITY_INVALID')
 hotel=s.get(HostedDirectHotelRow,snap.hosted_hotel_id)
 latest=s.scalar(select(HostedContentSnapshotRow).where(HostedContentSnapshotRow.hosted_hotel_id==snap.hosted_hotel_id).order_by(HostedContentSnapshotRow.version.desc(),HostedContentSnapshotRow.content_snapshot_id.desc()))
 if not hotel or not latest or latest.content_snapshot_id!=snap.content_snapshot_id:raise ValueError('CONTENT_SNAPSHOT_SUPERSEDED')
 if body['payload']!=hotel.contact_json:raise ValueError('CONTENT_SOURCE_CHANGED')
 return body

def latest_decision(s,snapshot_id):
 return s.scalar(select(HostedContentApprovalRow).where(HostedContentApprovalRow.content_snapshot_id==snapshot_id).order_by(HostedContentApprovalRow.decided_at.desc(),HostedContentApprovalRow.content_approval_id.desc()))

class Service:
 def snapshot(self,hotel_id,principal):
  with transaction(SessionLocal) as s:
   actor=principal_checked(s,principal,'admin:rules')
   h=s.get(HostedDirectHotelRow,hotel_id,with_for_update=True)
   if not h:raise ValueError('HOSTED_HOTEL_NOT_FOUND')
   version=(s.scalar(select(func.max(HostedContentSnapshotRow.version)).where(HostedContentSnapshotRow.hosted_hotel_id==hotel_id)) or 0)+1
   body={'schema':SCHEMA,'hosted_hotel_id':hotel_id,'version':version,'created_by':actor,'payload':deepcopy(h.contact_json)}
   r=HostedContentSnapshotRow(content_snapshot_id=ident('hcs'),hosted_hotel_id=hotel_id,version=version,content_json=body,content_hash=digest(body),source_status=h.contact_json.get('content_status','UNVERIFIED'),created_at=now())
   s.add(r);s.flush();return out(r)
 def approve(self,snapshot_id,b,principal):
  with transaction(SessionLocal) as s:
   actor=principal_checked(s,principal,'admin:approve')
   if not isinstance(b,dict):raise ValueError('CONTENT_APPROVAL_FIELDS_INVALID')
   if set(b)-{'approver_role','decision','evidence_reference','expected_content_hash','expected_decision_id'}:raise ValueError('CONTENT_APPROVAL_FIELDS_INVALID')
   if not isinstance(b.get('decision'),str) or b['decision'] not in {'APPROVE','REJECT'} or not isinstance(b.get('evidence_reference'),str) or not b['evidence_reference'].strip():raise ValueError('DECISION_AND_EVIDENCE_REQUIRED')
   # Legacy role input is only a compatibility label, never authorization.
   snap=s.get(HostedContentSnapshotRow,snapshot_id)
   if not snap:raise ValueError('CONTENT_SNAPSHOT_NOT_FOUND')
   s.get(HostedDirectHotelRow,snap.hosted_hotel_id,with_for_update=True)
   s.refresh(snap,with_for_update=True)
   binding=binding_checked(s,snap.hosted_hotel_id,actor)
   body=snapshot_checked(s,snap)
   if actor==body['created_by']:raise PermissionError('HOTEL_CONTENT_MAKER_CHECKER_REQUIRED')
   if not isinstance(b.get('expected_content_hash'),str) or b['expected_content_hash']!=snap.content_hash:raise ValueError('CONTENT_HASH_CHANGED_RECONFIRM_REQUIRED')
   evidence=approval_evidence(binding,snap,b['evidence_reference'].strip())
   old=latest_decision(s,snapshot_id)
   if old and old.approver_id==actor and old.approver_role==APPROVAL_ROLE and old.decision==b['decision'] and old.evidence_reference==evidence:return approval_out(old)
   if b.get('expected_decision_id')!=(old.content_approval_id if old else None):raise ValueError('CONTENT_DECISION_CHANGED_RECONFIRM_REQUIRED')
   decided=now()
   if old:decided=max(decided,aware(old.decided_at)+timedelta(microseconds=1))
   row=HostedContentApprovalRow(content_approval_id=ident('hca'),content_snapshot_id=snapshot_id,
    approver_id=actor,approver_role=APPROVAL_ROLE,decision=b['decision'],evidence_reference=evidence,decided_at=decided)
   s.add(row);s.flush();return approval_out(row)
 def media(self,hotel_id,b,principal):
  with transaction(SessionLocal) as s:
   actor=principal_checked(s,principal,'admin:rules')
   if not s.get(HostedDirectHotelRow,hotel_id,with_for_update=True):raise ValueError('HOSTED_HOTEL_NOT_FOUND')
   # Existing explicit engineering provisioning permits a scoped draft only;
   # it does not establish hotel delegation or grant media rights.
   binding_checked(s,hotel_id,actor)
   if not isinstance(b,dict) or set(b)-{'asset_role','physical_room_key','storage_reference','rights_owner','rights_evidence_reference'}:raise ValueError('MEDIA_CLAIM_FIELDS_INVALID')
   fields={}
   for name,maximum in [('storage_reference',512),('rights_owner',256),('rights_evidence_reference',512)]:
    value=b.get(name)
    if not isinstance(value,str) or not value.strip() or len(value)>maximum:raise ValueError('MEDIA_CLAIM_FIELDS_INVALID')
    fields[name]=value.strip()
   if fields['rights_owner']!='哈尔滨敖麓谷雅酒店':raise ValueError('HOTEL_OWNED_MEDIA_RIGHTS_EVIDENCE_REQUIRED')
   if b.get('asset_role') not in ('HERO','ROOM'):raise ValueError('MEDIA_ROLE_AND_STORAGE_REFERENCE_REQUIRED')
   room=b.get('physical_room_key')
   if b['asset_role']=='ROOM':
    if not isinstance(room,str) or not room.strip() or len(room)>128:raise ValueError('PHYSICAL_ROOM_KEY_REQUIRED')
    room=room.strip()
    if not s.scalar(select(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.hosted_hotel_id==hotel_id,HostedDirectInventoryPoolRow.physical_room_key==room)):raise ValueError('PHYSICAL_ROOM_POOL_NOT_FOUND')
   elif room is not None:raise ValueError('HERO_PHYSICAL_ROOM_KEY_NOT_ALLOWED')
   r=HostedMediaAssetRow(media_asset_id=ident('hma'),hosted_hotel_id=hotel_id,asset_role=b['asset_role'],physical_room_key=room,**fields,state='PENDING_RIGHTS_REVIEW',created_at=now())
   s.add(r);s.flush();return out(r)
 def gate(self,hotel_id):
  with SessionLocal() as s:
   if not s.get(HostedDirectHotelRow,hotel_id):raise ValueError('HOSTED_HOTEL_NOT_FOUND')
   snap=s.scalar(select(HostedContentSnapshotRow).where(HostedContentSnapshotRow.hosted_hotel_id==hotel_id).order_by(HostedContentSnapshotRow.version.desc(),HostedContentSnapshotRow.content_snapshot_id.desc()))
   approval=latest_decision(s,snap.content_snapshot_id) if snap else None
   block=[];content_ok=False
   try:
    body=snapshot_checked(s,snap)
    if not approval or approval.decision!='APPROVE' or approval.approver_role!=APPROVAL_ROLE:raise ValueError('HOTEL_CONTENT_APPROVAL_REQUIRED')
    user_checked(s,approval.approver_id,'admin:approve')
    binding=binding_checked(s,hotel_id,approval.approver_id)
    try: evidence=json.loads(approval.evidence_reference)
    except (ValueError,TypeError):raise ValueError('CONTENT_APPROVAL_BINDING_UNVERIFIED') from None
    if not isinstance(evidence,dict) or set(evidence)!={'schema','reference','binding_id','binding_hash','snapshot_hash'} or evidence['schema']!='CONTENT_APPROVAL_V2' or not isinstance(evidence['reference'],str) or not evidence['reference'].strip() or evidence['binding_id']!=binding.staff_role_id or evidence['binding_hash']!=binding_hash(binding) or evidence['snapshot_hash']!=snap.content_hash:
     raise ValueError('CONTENT_APPROVAL_BINDING_UNVERIFIED')
    if approval.approver_id==body['created_by']:raise ValueError('HOTEL_CONTENT_MAKER_CHECKER_REQUIRED')
    content_ok=True
   except (PermissionError,ValueError) as exc:block.append(str(exc))
   # There is no trusted Hosted media-rights resolver yet. Old labels and
   # caller-supplied storage/license references cannot stand in for one.
   # Retain all historical rows; a read never upgrades or rewrites evidence.
   rooms=set(s.scalars(select(HostedDirectInventoryPoolRow.physical_room_key).where(HostedDirectInventoryPoolRow.hosted_hotel_id==hotel_id)))
   block.extend(['HOTEL_MEDIA_RIGHTS_AUTHORITY_UNVERIFIED','HOTEL_OWNED_HERO_IMAGE_REQUIRED'])
   if rooms:block.append('HOTEL_OWNED_ROOM_IMAGES_REQUIRED')
   return {'state':'BLOCKED_PENDING_CONTENT_AND_MEDIA','blockers':block,
    'content_approval_verified':content_ok,'authority_mode':'ISOLATED_FIXTURE' if content_ok else 'HOLD',
    'media_rights_verified':False,'media_rights_state':'HOLD_UNVERIFIED',
    'real_hotel_authority_state':'HOLD_UNVERIFIED','snapshot_id':snap.content_snapshot_id if snap else None,
    'latest_content_decision':approval.decision if approval else None,'missing_room_images':sorted(rooms),
    'payment_live':False,'production_live':False}
hosted_content_acceptance_service=Service()
