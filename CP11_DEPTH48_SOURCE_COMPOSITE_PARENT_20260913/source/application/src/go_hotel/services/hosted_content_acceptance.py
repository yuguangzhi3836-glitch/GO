import hashlib,json,uuid
from datetime import datetime,timezone
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import HostedDirectHotelRow,HostedDirectInventoryPoolRow,HostedContentSnapshotRow,HostedContentApprovalRow,HostedMediaAssetRow
def now():return datetime.now(timezone.utc)
def ident(p):return f'{p}_{uuid.uuid4().hex}'
def out(r):return {c.name:(getattr(r,c.name).isoformat() if isinstance(getattr(r,c.name),datetime) else getattr(r,c.name)) for c in r.__table__.columns}
class Service:
 def snapshot(self,hotel_id,actor):
  with SessionLocal() as s:
   h=s.get(HostedDirectHotelRow,hotel_id)
   if not h:raise ValueError('HOSTED_HOTEL_NOT_FOUND')
   v=(s.scalar(select(func.max(HostedContentSnapshotRow.version)).where(HostedContentSnapshotRow.hosted_hotel_id==hotel_id)) or 0)+1;c=h.contact_json;digest=hashlib.sha256(json.dumps(c,sort_keys=True,ensure_ascii=False).encode()).hexdigest();r=HostedContentSnapshotRow(content_snapshot_id=ident('hcs'),hosted_hotel_id=hotel_id,version=v,content_json=c,content_hash=digest,source_status=c.get('content_status','UNVERIFIED'),created_at=now());s.add(r);s.commit();return out(r)
 def approve(self,snapshot_id,b,actor):
  if b.get('approver_role')!='HOTEL_AUTHORIZED_OPERATOR':raise ValueError('HOTEL_AUTHORIZED_OPERATOR_REQUIRED')
  if b.get('decision') not in ('APPROVE','REJECT') or not b.get('evidence_reference'):raise ValueError('DECISION_AND_EVIDENCE_REQUIRED')
  with SessionLocal() as s:
   if not s.get(HostedContentSnapshotRow,snapshot_id):raise ValueError('CONTENT_SNAPSHOT_NOT_FOUND')
   r=HostedContentApprovalRow(content_approval_id=ident('hca'),content_snapshot_id=snapshot_id,approver_id=actor,approver_role=b['approver_role'],decision=b['decision'],evidence_reference=b['evidence_reference'],decided_at=now());s.add(r);s.commit();return out(r)
 def media(self,hotel_id,b,actor):
  if b.get('rights_owner')!='哈尔滨敖麓谷雅酒店' or not b.get('rights_evidence_reference'):raise ValueError('HOTEL_OWNED_MEDIA_RIGHTS_EVIDENCE_REQUIRED')
  if b.get('asset_role') not in ('HERO','ROOM') or not b.get('storage_reference'):raise ValueError('MEDIA_ROLE_AND_STORAGE_REFERENCE_REQUIRED')
  if b.get('asset_role')=='ROOM' and not b.get('physical_room_key'):raise ValueError('PHYSICAL_ROOM_KEY_REQUIRED')
  with SessionLocal() as s:
   if not s.get(HostedDirectHotelRow,hotel_id):raise ValueError('HOSTED_HOTEL_NOT_FOUND')
   if b.get('asset_role')=='ROOM' and not s.scalar(select(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.hosted_hotel_id==hotel_id,HostedDirectInventoryPoolRow.physical_room_key==b['physical_room_key'])):raise ValueError('PHYSICAL_ROOM_POOL_NOT_FOUND')
   r=HostedMediaAssetRow(media_asset_id=ident('hma'),hosted_hotel_id=hotel_id,asset_role=b['asset_role'],physical_room_key=b.get('physical_room_key'),storage_reference=b['storage_reference'],rights_owner=b['rights_owner'],rights_evidence_reference=b['rights_evidence_reference'],state='RIGHTS_VERIFIED',created_at=now());s.add(r);s.commit();return out(r)
 def gate(self,hotel_id):
  with SessionLocal() as s:
   if not s.get(HostedDirectHotelRow,hotel_id):raise ValueError('HOSTED_HOTEL_NOT_FOUND')
   snap=s.scalar(select(HostedContentSnapshotRow).where(HostedContentSnapshotRow.hosted_hotel_id==hotel_id).order_by(HostedContentSnapshotRow.version.desc()));approval=s.scalar(select(HostedContentApprovalRow).where(HostedContentApprovalRow.content_snapshot_id==snap.content_snapshot_id,HostedContentApprovalRow.decision=='APPROVE')) if snap else None;assets=s.scalars(select(HostedMediaAssetRow).where(HostedMediaAssetRow.hosted_hotel_id==hotel_id,HostedMediaAssetRow.state=='RIGHTS_VERIFIED')).all();roles={x.asset_role for x in assets};rooms={x.physical_room_key for x in s.scalars(select(HostedDirectInventoryPoolRow).where(HostedDirectInventoryPoolRow.hosted_hotel_id==hotel_id)).all()};covered={x.physical_room_key for x in assets if x.asset_role=='ROOM'};block=[]
   if not approval:block.append('HOTEL_CONTENT_APPROVAL_REQUIRED')
   if 'HERO' not in roles:block.append('HOTEL_OWNED_HERO_IMAGE_REQUIRED')
   if rooms-covered:block.append('HOTEL_OWNED_ROOM_IMAGES_REQUIRED')
   return {'state':'OPERATIONS_ACCEPTED' if not block else 'BLOCKED_PENDING_CONTENT_AND_MEDIA','blockers':block,'missing_room_images':sorted(rooms-covered),'payment_live':False,'production_live':False}
hosted_content_acceptance_service=Service()
