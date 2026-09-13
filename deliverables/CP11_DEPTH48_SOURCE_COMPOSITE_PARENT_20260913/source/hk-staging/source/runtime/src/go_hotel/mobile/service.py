from __future__ import annotations
from datetime import datetime, timezone
import hashlib, uuid
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import ConsumerDeviceRow, ConsumerNotificationRow
from go_hotel.security.mfa import seal
UTC=timezone.utc
def now(): return datetime.now(UTC)
def uid(p): return f"{p}_{uuid.uuid4().hex}"
class MobileService:
    def register_device(self,p,device_id,platform,app_version=None,device_model=None,os_version=None,push_provider=None,push_token=None,notifications_enabled=False):
        platform=platform.upper()
        if platform not in {"IOS","ANDROID"}: raise ValueError("UNSUPPORTED_MOBILE_PLATFORM")
        if push_provider and push_provider.upper() not in {"APNS","FCM"}: raise ValueError("UNSUPPORTED_PUSH_PROVIDER")
        with SessionLocal() as s:
            r=s.get(ConsumerDeviceRow,device_id); t=now()
            if r and r.user_id!=p.user_id: raise ValueError("DEVICE_OWNERSHIP_CONFLICT")
            if not r:
                r=ConsumerDeviceRow(device_id=device_id,user_id=p.user_id,platform=platform,created_at=t,last_seen_at=t,updated_at=t,status="ACTIVE")
                s.add(r)
            r.platform=platform; r.app_version=app_version; r.device_model=device_model; r.os_version=os_version; r.last_seen_at=t; r.updated_at=t; r.status="ACTIVE"; r.notifications_enabled=bool(notifications_enabled)
            if push_token:
                r.push_provider=(push_provider or ("APNS" if platform=="IOS" else "FCM")).upper()
                r.push_token_ciphertext=seal(push_token); r.push_token_hash=hashlib.sha256(push_token.encode()).hexdigest()
            s.commit(); return self._device(r)
    def unregister_device(self,p,device_id):
        with SessionLocal() as s:
            r=s.get(ConsumerDeviceRow,device_id)
            if not r or r.user_id!=p.user_id: raise ValueError("DEVICE_NOT_FOUND")
            r.status="REVOKED"; r.notifications_enabled=False; r.push_token_ciphertext=None; r.push_token_hash=None; r.updated_at=now(); s.commit()
    def devices(self,p):
        with SessionLocal() as s: return [self._device(x) for x in s.scalars(select(ConsumerDeviceRow).where(ConsumerDeviceRow.user_id==p.user_id,ConsumerDeviceRow.status=="ACTIVE")).all()]
    def notifications(self,p):
        with SessionLocal() as s:
            rows=s.scalars(select(ConsumerNotificationRow).where(ConsumerNotificationRow.user_id==p.user_id).order_by(ConsumerNotificationRow.created_at.desc()).limit(100)).all()
            return [self._notification(x) for x in rows]
    def mark_read(self,p,notification_id):
        with SessionLocal() as s:
            r=s.get(ConsumerNotificationRow,notification_id)
            if not r or r.user_id!=p.user_id: raise ValueError("NOTIFICATION_NOT_FOUND")
            if not r.read_at: r.read_at=now()
            s.commit(); return self._notification(r)
    def create_notification(self,user_id,notification_type,title,body,deep_link=None,payload=None):
        with SessionLocal() as s:
            r=ConsumerNotificationRow(notification_id=uid("ntf"),user_id=user_id,notification_type=notification_type,title=title,body=body,deep_link=deep_link,payload_json={**(payload or {}), **({"deep_link": deep_link} if deep_link else {})},delivery_status="PENDING",created_at=now())
            s.add(r); s.commit(); return self._notification(r)
    def resolve_deep_link(self,p,url):
        # Allow only GO application routes and typed entity identifiers; no arbitrary external redirects.
        if url.startswith("go://trips/order/"):
            return {"route":"ORDER_DETAIL","order_id":url.rsplit("/",1)[-1]}
        if url.startswith("go://reviews/"):
            return {"route":"QUICK_REVIEW","review_id":url.rsplit("/",1)[-1]}
        if url.startswith("go://wallet"):
            return {"route":"WALLET"}
        if url.startswith("go://home"):
            return {"route":"HOME"}
        raise ValueError("UNSUPPORTED_DEEP_LINK")
    def _device(self,r): return {"device_id":r.device_id,"platform":r.platform,"app_version":r.app_version,"device_model":r.device_model,"os_version":r.os_version,"push_provider":r.push_provider,"notifications_enabled":r.notifications_enabled,"status":r.status,"last_seen_at":r.last_seen_at.isoformat()}
    def _notification(self,r): return {"notification_id":r.notification_id,"type":r.notification_type,"title":r.title,"body":r.body,"deep_link":r.deep_link,"payload":r.payload_json,"delivery_status":r.delivery_status,"read_at":r.read_at.isoformat() if r.read_at else None,"created_at":r.created_at.isoformat()}
mobile_service=MobileService()
