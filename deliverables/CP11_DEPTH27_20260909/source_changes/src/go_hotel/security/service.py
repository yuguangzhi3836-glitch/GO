from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import time, uuid, hmac, json
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import IdentityUserRow, AuthSessionRow, RefreshTokenRow, ApprovalRequestRow, AuditEventRow
from go_hotel.core.config import settings
from .crypto import hash_password, verify_password, encode_jwt, decode_jwt, random_token, token_hash
from .mfa import verify_totp, new_secret, provisioning_uri, seal, unseal
from .rbac import permissions_for, HIGH_RISK_OPERATIONS

UTC=timezone.utc
def now(): return datetime.now(UTC)
def aware(dt):
    if dt is None: return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
def uid(prefix): return f"{prefix}_{uuid.uuid4().hex}"

@dataclass(frozen=True)
class Principal:
    user_id:str; username:str; actor_type:str; supplier_id:str|None; roles:list[str]; session_id:str; permissions:set[str]

class IdentityService:
    def bootstrap(self):
        self.ensure_user(settings.bootstrap_admin_username, settings.bootstrap_admin_password, "GO_ADMIN", None, ["GO_GOVERNANCE"])
        self.ensure_user(settings.bootstrap_supplier_username, settings.bootstrap_supplier_password, "SUPPLIER_USER", settings.bootstrap_supplier_id, ["SUPPLIER_OWNER"])
    def ensure_user(self, username,password,actor_type,supplier_id,roles):
        with SessionLocal() as s:
            row=s.scalar(select(IdentityUserRow).where(IdentityUserRow.username==username))
            if row: return row.user_id
            t=now(); row=IdentityUserRow(user_id=uid('usr'),username=username,password_hash=hash_password(password),actor_type=actor_type,supplier_id=supplier_id,roles=roles,status='ACTIVE',token_version=1,created_at=t,updated_at=t)
            s.add(row); s.commit(); return row.user_id
    def create_user(self, username,password,actor_type,supplier_id,roles): return self.ensure_user(username,password,actor_type,supplier_id,roles)
    def _create_session(self, s, u, client_ip=None, user_agent=None, auth_method='PASSWORD', mfa_verified_at=None):
        t=now(); sid=uid('ses'); csrf=random_token()
        session=AuthSessionRow(session_id=sid,user_id=u.user_id,status='ACTIVE',client_ip=client_ip,user_agent=user_agent,created_at=t,last_seen_at=t,expires_at=t+timedelta(days=settings.refresh_token_days),auth_method=auth_method,mfa_verified_at=mfa_verified_at,csrf_token_hash=token_hash(csrf))
        refresh=random_token(); rt=RefreshTokenRow(token_id=uid('rt'),session_id=sid,user_id=u.user_id,token_hash=token_hash(refresh),status='ACTIVE',expires_at=t+timedelta(days=settings.refresh_token_days),created_at=t)
        s.add_all([session,rt]); s.commit()
        return self._tokens(u,sid,refresh,csrf)

    def login(self, username,password,client_ip=None,user_agent=None,totp_code=None,auth_method="PASSWORD",expected_actor_type=None):
        with SessionLocal() as s:
            u=s.scalar(select(IdentityUserRow).where(IdentityUserRow.username==username))
            if not u or u.status!='ACTIVE' or not verify_password(password,u.password_hash): raise ValueError('INVALID_CREDENTIALS')
            if expected_actor_type and u.actor_type != expected_actor_type: raise ValueError('ACCOUNT_TYPE_MISMATCH')
            must_mfa = bool(u.mfa_enabled_at) or (settings.mfa_required_for_admin and u.actor_type=='GO_ADMIN')
            if must_mfa and not u.mfa_enabled_at: raise ValueError('MFA_ENROLLMENT_REQUIRED')
            mfa_verified_at=None
            if must_mfa:
                if not totp_code or not verify_totp(unseal(u.mfa_secret_ciphertext),totp_code): raise ValueError('MFA_REQUIRED_OR_INVALID')
                mfa_verified_at=now()
            return self._create_session(s,u,client_ip,user_agent,auth_method,mfa_verified_at)

    def begin_admin_mfa_enrollment(self, username:str, password:str):
        """Password-gated, least-privilege bootstrap for an admin's first MFA binding.
        The returned token is purpose-bound and cannot be used as an application session.
        """
        with SessionLocal() as s:
            u=s.scalar(select(IdentityUserRow).where(IdentityUserRow.username==username))
            if not u or u.status!='ACTIVE' or not verify_password(password,u.password_hash): raise ValueError('INVALID_CREDENTIALS')
            if u.actor_type!='GO_ADMIN': raise ValueError('ADMIN_MFA_ENROLLMENT_ONLY')
            if u.mfa_enabled_at: raise ValueError('MFA_ALREADY_ENABLED')
            secret=new_secret(); u.mfa_secret_ciphertext=seal(secret); u.updated_at=now(); s.commit()
            iat=int(time.time()); ttl=600
            claims={'sub':u.user_id,'username':u.username,'actor_type':u.actor_type,'purpose':'MFA_ENROLLMENT','ver':u.token_version,'iat':iat,'exp':iat+ttl,'jti':uid('mfa')}
            return {'enrollment_token':encode_jwt(claims),'expires_in':ttl,'secret':secret,'provisioning_uri':provisioning_uri(u.username,secret)}

    def confirm_admin_mfa_enrollment(self, enrollment_token:str, code:str, client_ip=None, user_agent=None):
        claims=decode_jwt(enrollment_token)
        if claims.get('purpose')!='MFA_ENROLLMENT' or claims.get('actor_type')!='GO_ADMIN': raise ValueError('INVALID_MFA_ENROLLMENT_TOKEN')
        with SessionLocal() as s:
            u=s.get(IdentityUserRow,claims.get('sub'))
            if not u or u.status!='ACTIVE' or u.actor_type!='GO_ADMIN' or u.token_version!=claims.get('ver'): raise ValueError('INVALID_MFA_ENROLLMENT_TOKEN')
            if u.mfa_enabled_at: raise ValueError('MFA_ALREADY_ENABLED')
            if not u.mfa_secret_ciphertext: raise ValueError('MFA_SETUP_NOT_STARTED')
            if not verify_totp(unseal(u.mfa_secret_ciphertext),code): raise ValueError('INVALID_MFA_CODE')
            u.mfa_enabled_at=now(); u.updated_at=now(); u.token_version+=1; s.flush()
            return self._create_session(s,u,client_ip,user_agent,'PASSWORD_MFA_ENROLLMENT',now())
    def _tokens(self,u,sid,refresh,csrf=None):
        iat=int(time.time()); exp=iat+settings.access_token_minutes*60
        claims={'sub':u.user_id,'username':u.username,'actor_type':u.actor_type,'supplier_id':u.supplier_id,'roles':u.roles,'sid':sid,'ver':u.token_version,'iat':iat,'exp':exp,'jti':uid('jti')}
        out={'access_token':encode_jwt(claims),'token_type':'bearer','expires_in':settings.access_token_minutes*60,'refresh_token':refresh}
        if csrf: out['csrf_token']=csrf
        return out
    def authenticate(self, token:str)->Principal:
        c=decode_jwt(token)
        with SessionLocal() as s:
            u=s.get(IdentityUserRow,c['sub']); ses=s.get(AuthSessionRow,c['sid'])
            if not u or u.status!='ACTIVE' or u.token_version!=c.get('ver') or not ses or ses.status!='ACTIVE' or aware(ses.expires_at)<now(): raise ValueError('SESSION_REVOKED')
            ses.last_seen_at=now(); s.commit()
            return Principal(u.user_id,u.username,u.actor_type,u.supplier_id,list(u.roles or []),ses.session_id,permissions_for(list(u.roles or [])))
    def refresh(self, refresh_token:str):
        h=token_hash(refresh_token)
        with SessionLocal() as s:
            rt=s.scalar(select(RefreshTokenRow).where(RefreshTokenRow.token_hash==h));
            if not rt or rt.status!='ACTIVE' or aware(rt.expires_at)<now(): raise ValueError('INVALID_REFRESH_TOKEN')
            ses=s.get(AuthSessionRow,rt.session_id); u=s.get(IdentityUserRow,rt.user_id)
            if not ses or ses.status!='ACTIVE' or aware(ses.expires_at)<now() or not u or u.status!='ACTIVE': raise ValueError('SESSION_REVOKED')
            rt.status='REVOKED'; rt.revoked_at=now(); new_refresh=random_token(); nrt=RefreshTokenRow(token_id=uid('rt'),session_id=ses.session_id,user_id=u.user_id,token_hash=token_hash(new_refresh),status='ACTIVE',expires_at=now()+timedelta(days=settings.refresh_token_days),created_at=now())
            csrf=random_token(); ses.csrf_token_hash=token_hash(csrf); s.add(nrt); s.commit(); return self._tokens(u,ses.session_id,new_refresh,csrf)


    def login_sso(self, provider:str, subject:str, username:str, client_ip=None, user_agent=None):
        with SessionLocal() as s:
            u=s.scalar(select(IdentityUserRow).where(IdentityUserRow.sso_provider==provider, IdentityUserRow.sso_subject==subject))
            if not u:
                existing=s.scalar(select(IdentityUserRow).where(IdentityUserRow.username==username))
                if existing:
                    u=existing; u.sso_provider=provider; u.sso_subject=subject
                else:
                    roles=[r.strip() for r in settings.oidc_default_roles.split(',') if r.strip()]
                    u=IdentityUserRow(user_id=uid('usr'),username=username,password_hash=hash_password(random_token()),actor_type=settings.oidc_default_actor_type,supplier_id=None,roles=roles,status='ACTIVE',token_version=1,sso_provider=provider,sso_subject=subject,created_at=now(),updated_at=now())
                    s.add(u)
            if u.status!='ACTIVE': raise ValueError('USER_INACTIVE')
            t=now(); sid=uid('ses'); csrf=random_token(); session=AuthSessionRow(session_id=sid,user_id=u.user_id,status='ACTIVE',client_ip=client_ip,user_agent=user_agent,created_at=t,last_seen_at=t,expires_at=t+timedelta(days=settings.refresh_token_days),auth_method='OIDC',mfa_verified_at=t,csrf_token_hash=token_hash(csrf))
            refresh=random_token(); rt=RefreshTokenRow(token_id=uid('rt'),session_id=sid,user_id=u.user_id,token_hash=token_hash(refresh),status='ACTIVE',expires_at=t+timedelta(days=settings.refresh_token_days),created_at=t)
            s.add_all([session,rt]); s.commit(); return self._tokens(u,sid,refresh,csrf)

    def begin_mfa_enrollment(self, p:Principal):
        with SessionLocal() as s:
            u=s.get(IdentityUserRow,p.user_id)
            if not u: raise ValueError('USER_NOT_FOUND')
            secret=new_secret(); u.mfa_secret_ciphertext=seal(secret); u.updated_at=now(); s.commit()
            return {'secret':secret,'provisioning_uri':provisioning_uri(u.username,secret)}
    def confirm_mfa_enrollment(self, p:Principal, code:str):
        with SessionLocal() as s:
            u=s.get(IdentityUserRow,p.user_id)
            if not u or not u.mfa_secret_ciphertext: raise ValueError('MFA_SETUP_NOT_STARTED')
            if not verify_totp(unseal(u.mfa_secret_ciphertext),code): raise ValueError('INVALID_MFA_CODE')
            u.mfa_enabled_at=now(); u.updated_at=now(); u.token_version+=1; s.commit()
            return {'status':'MFA_ENABLED','enabled_at':u.mfa_enabled_at.isoformat()}
    def verify_csrf(self, session_id:str, csrf_token:str)->bool:
        with SessionLocal() as s:
            ses=s.get(AuthSessionRow,session_id)
            return bool(ses and ses.status=='ACTIVE' and ses.csrf_token_hash and hmac.compare_digest(ses.csrf_token_hash,token_hash(csrf_token)))

    def revoke_session(self, session_id:str):
        with SessionLocal() as s:
            ses=s.get(AuthSessionRow,session_id)
            if ses: ses.status='REVOKED'; ses.revoked_at=now()
            for rt in s.scalars(select(RefreshTokenRow).where(RefreshTokenRow.session_id==session_id)).all(): rt.status='REVOKED'; rt.revoked_at=now()
            s.commit()

class ApprovalService:
    def request(self,p:Principal,operation_type,subject_type,subject_id,payload):
        if operation_type not in HIGH_RISK_OPERATIONS: raise ValueError('OPERATION_NOT_HIGH_RISK')
        with SessionLocal() as s:
            r=ApprovalRequestRow(approval_id=uid('apr'),operation_type=operation_type,subject_type=subject_type,subject_id=subject_id,requested_by=p.user_id,status='PENDING',request_payload=payload,created_at=now(),expires_at=now()+timedelta(minutes=30))
            s.add(r); s.commit(); return self.serialize(r)
    def approve(self,p:Principal,approval_id,note=None):
        if 'admin:approve' not in p.permissions: raise PermissionError('APPROVAL_PERMISSION_REQUIRED')
        with SessionLocal() as s:
            r=s.get(ApprovalRequestRow,approval_id)
            if not r or r.status!='PENDING' or aware(r.expires_at)<now(): raise ValueError('APPROVAL_NOT_PENDING')
            if r.requested_by==p.user_id: raise ValueError('DUAL_CONTROL_REQUIRES_DISTINCT_ACTOR')
            r.status='APPROVED'; r.approved_by=p.user_id; r.approval_note=note; r.approved_at=now(); s.commit(); return self.serialize(r)
    def consume(self,p:Principal,approval_id,operation_type,subject_id):
        with SessionLocal() as s:
            r=s.get(ApprovalRequestRow,approval_id)
            if not r or r.status!='APPROVED' or aware(r.expires_at)<now() or r.consumed_at is not None: raise PermissionError('VALID_SECOND_APPROVAL_REQUIRED')
            if r.operation_type!=operation_type or r.subject_id!=subject_id: raise PermissionError('APPROVAL_SCOPE_MISMATCH')
            if r.requested_by!=p.user_id: raise PermissionError('APPROVAL_REQUESTOR_MISMATCH')
            r.status='CONSUMED'; r.consumed_at=now(); s.commit(); return self.serialize(r)
    def serialize(self,r): return {'approval_id':r.approval_id,'operation_type':r.operation_type,'subject_type':r.subject_type,'subject_id':r.subject_id,'requested_by':r.requested_by,'approved_by':r.approved_by,'status':r.status,'expires_at':r.expires_at.isoformat()}

class AuditService:
    def append(self,p:Principal,action,resource_type,resource_id=None,request_id=None,client_ip=None,http_method=None,path=None,before=None,after=None,decision_id=None,evidence_id=None,approval_id=None,metadata=None):
        def json_safe(value):
            if value is None: return None
            return json.loads(json.dumps(value,default=lambda item:item.isoformat() if isinstance(item,datetime) else str(item)))
        with SessionLocal() as s:
            r=AuditEventRow(audit_id=uid('aud'),actor_id=p.user_id,actor_type=p.actor_type,supplier_id=p.supplier_id,roles=p.roles,session_id=p.session_id,action=action,resource_type=resource_type,resource_id=resource_id,request_id=request_id,client_ip=client_ip,http_method=http_method,path=path,before_state=json_safe(before),after_state=json_safe(after),decision_id=decision_id,evidence_id=evidence_id,approval_id=approval_id,metadata_json=json_safe(metadata) or {},created_at=now())
            s.add(r); s.commit(); return r.audit_id
    def list(self,limit=100,actor_id=None,resource_id=None):
        with SessionLocal() as s:
            q=select(AuditEventRow)
            if actor_id: q=q.where(AuditEventRow.actor_id==actor_id)
            if resource_id: q=q.where(AuditEventRow.resource_id==resource_id)
            rows=s.scalars(q.order_by(AuditEventRow.created_at.desc()).limit(limit)).all()
            return [{'audit_id':r.audit_id,'actor_id':r.actor_id,'actor_type':r.actor_type,'supplier_id':r.supplier_id,'roles':r.roles,'session_id':r.session_id,'action':r.action,'resource_type':r.resource_type,'resource_id':r.resource_id,'request_id':r.request_id,'client_ip':r.client_ip,'method':r.http_method,'path':r.path,'before_state':r.before_state,'after_state':r.after_state,'decision_id':r.decision_id,'evidence_id':r.evidence_id,'approval_id':r.approval_id,'metadata':r.metadata_json,'created_at':r.created_at.isoformat()} for r in rows]

identity_service=IdentityService(); approval_service=ApprovalService(); audit_service=AuditService()
