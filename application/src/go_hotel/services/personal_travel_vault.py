from __future__ import annotations
from datetime import datetime, timezone, timedelta
import hashlib, hmac, json, os, secrets
from urllib.parse import urlencode
from sqlalchemy import select, update
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    TravelerProfileRow, ProfileImportJobRow, ProfileImportItemRow, ProfileFactRow,
    ProfileConsentRow, ProfileTravelerPermissionRow, ProfileDataReleaseAuditRow,
    ProfileAccessAuditRow, ConsumerProfileRow,
)
from go_hotel.security.crypto import encrypt_secret, decrypt_secret
from go_hotel.security.external_navigation import validate_external_navigation_url
from go_hotel.domain.models import new_id
from go_hotel.services.personal_vault_management import (VaultManagementMixin, mutation_session,
    owned_traveler, permission, revision, validate_value)

SENSITIVE_FIELDS={
    'ID_CARD_NUMBER','PASSPORT_NUMBER','PASSPORT_IMAGE','VISA_NUMBER','VISA_IMAGE',
    'DATE_OF_BIRTH','DRIVER_LICENSE_NUMBER','MINOR_IDENTITY','EMERGENCY_CONTACT_DETAIL',
}
MULTI_VALUE_FIELDS={
    'PASSPORT_NUMBER','VISA_NUMBER','LOYALTY_AIRLINE','LOYALTY_HOTEL','LOYALTY_RAIL',
    'LOYALTY_RENTAL','EMAIL','MOBILE','ADDRESS','COMPANY_INVOICE','PERSONAL_INVOICE',
}
ALLOWED_SOURCE_TYPES={'MANUAL','OFFICIAL_API','USER_DATA_PACKAGE','SHARE_TO_GO','SCREENSHOT_AI','IMAGE_AI','PDF_AI','TEXT_IMPORT','FILE_IMPORT','DOCUMENT_SCAN'}
ALLOWED_RELATIONSHIPS={'SELF','SPOUSE','CHILD','PARENT','FAMILY','ASSISTANT','COLLEAGUE','BUSINESS_TRAVELER','FREQUENT_TRAVELER','OTHER'}
ALLOWED_PERMISSIONS={'VIEW','USE_FOR_BOOKING','EDIT','SHARE','SENSITIVE_DATA'}

def now(): return datetime.now(timezone.utc)
def norm(v):
    if v is None:return ''
    if isinstance(v,(dict,list)):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return ' '.join(str(v).strip().lower().split())
def h(v): return hashlib.sha256(norm(v).encode()).hexdigest()
def mask(v,sensitive=False):
    s=str(v) if v is not None else ''
    if not sensitive:return s if len(s)<=80 else s[:77]+'...'
    if len(s)<=4:return '*'*len(s)
    return '*'*max(4,len(s)-4)+s[-4:]
def dt(v):
    if not v:return None
    if isinstance(v,datetime):return v
    return datetime.fromisoformat(str(v).replace('Z','+00:00'))

def usable_fact(f):
    if f.verification_status in {'CANDIDATE','REJECTED','INVALID','EXTRACTED'}:
        return False
    if f.trust_level == 'L0_EXTRACTED' and not f.user_confirmed:
        return False
    for raw, is_start in ((f.valid_from, True), (f.valid_until, False)):
        if not raw:
            continue
        try:
            boundary = dt(raw)
            if boundary.tzinfo is None:
                boundary = boundary.replace(tzinfo=timezone.utc)
            # A date-only expiry includes that whole calendar date.
            if not is_start and len(str(raw)) == 10:
                from datetime import timedelta
                boundary += timedelta(days=1)
            if (is_start and now() < boundary) or (not is_start and now() >= boundary):
                return False
        except (ValueError, TypeError):
            return False
    return True

def trust_for(source_type,user_confirmed,verification_method=None,adapter_verified=False):
    if adapter_verified and source_type in {'OFFICIAL_API','DOCUMENT_SCAN'} and verification_method in {'NFC','MRZ','GOVERNMENT_ID_VERIFICATION'}:return ('L4_VERIFIED_DOCUMENT','VERIFIED')
    if source_type=='OFFICIAL_API':return ('L3_OFFICIAL_PROVIDER','USER_CONFIRMED' if user_confirmed else 'SOURCE_ASSERTED')
    if source_type=='USER_DATA_PACKAGE':return ('L2_STRUCTURED_SOURCE','USER_CONFIRMED' if user_confirmed else 'SOURCE_ASSERTED')
    if user_confirmed:return ('L1_USER_CONFIRMED','USER_CONFIRMED')
    return ('L0_EXTRACTED','CANDIDATE')

def _growth_profile_created(user_id):
    try:
        from go_hotel.services.consumer_growth_direct_value import consumer_growth_direct_value_service
        consumer_growth_direct_value_service.record_event(user_id,'PROFILE_CREATED',source_surface='PERSONAL_VAULT',object_type='PROFILE')
    except Exception:
        pass

class PersonalTravelVaultService(VaultManagementMixin):
    PROFILE_PROVIDERS={
        'CTRIP':{'label':'携程','authorization_env':'GO_CTRIP_PROFILE_AUTHORIZATION_URL'},
        'MEITUAN':{'label':'美团','authorization_env':'GO_MEITUAN_PROFILE_AUTHORIZATION_URL'},
        'FLIGGY':{'label':'飞猪','authorization_env':'GO_FLIGGY_PROFILE_AUTHORIZATION_URL'},
        'BOOKING':{'label':'Booking.com','authorization_env':'GO_BOOKING_PROFILE_AUTHORIZATION_URL'},
        'OTHER_OTA':{'label':'其他平台','authorization_env':'GO_OTHER_OTA_PROFILE_AUTHORIZATION_URL'},
    }
    CONNECTION_METHODS={'OFFICIAL_AUTHORIZATION','DATA_EXPORT','FILE_UPLOAD','SCREENSHOT'}
    CONNECTION_TTL=timedelta(minutes=15)

    def bootstrap_vault(self,user_id,b=None):
        b=b or {}
        with mutation_session() as s:
            profile=s.get(ConsumerProfileRow,user_id)
            if not profile: raise ValueError('CONSUMER_PROFILE_NOT_FOUND')
            traveler=s.scalar(select(TravelerProfileRow).where(TravelerProfileRow.user_id==user_id,TravelerProfileRow.relationship_type=='SELF',TravelerProfileRow.status=='ACTIVE').order_by(TravelerProfileRow.is_primary.desc(),TravelerProfileRow.created_at))
            created=False
            if not traveler:
                full_name=str(b.get('full_name') or '').strip()
                if not full_name: raise ValueError('PERSONAL_VAULT_FULL_NAME_REQUIRED')
                traveler,created=self._resolve_traveler(s,user_id,{'full_name':full_name,'relationship_type':'SELF','is_primary':True,'booking_permission':True},'MANUAL')
            facts_created=[]
            values=[('EMAIL',profile.email,True),('MOBILE',b.get('phone'),True)]
            for ft,value,sensitive in values:
                if not value: continue
                exists=s.scalar(select(ProfileFactRow).where(ProfileFactRow.user_id==user_id,ProfileFactRow.traveler_id==traveler.traveler_id,ProfileFactRow.field_type==ft,ProfileFactRow.normalized_value_hash==h(value),ProfileFactRow.status=='ACTIVE'))
                if exists: continue
                t=now();s.add(ProfileFactRow(fact_id=new_id('pff'),user_id=user_id,traveler_id=traveler.traveler_id,field_type=ft,value_ciphertext=encrypt_secret(json.dumps(value,ensure_ascii=False)),normalized_value_hash=h(value),sensitive=sensitive,source_type='MANUAL',source_provider='GO_ACCOUNT_REGISTRATION',source_reference='consumer-registration',source_fingerprint=h([user_id,ft,value]),confidence_bps=10000,user_confirmed=True,trust_level='L1_USER_CONFIRMED',verification_status='USER_CONFIRMED',verification_method='USER_REGISTRATION',valid_from=None,valid_until=None,superseded_by=None,status='ACTIVE',created_at=t,updated_at=t));facts_created.append(ft)
            self._audit(s,user_id,user_id,'CONSUMER','PROFILE_VAULT_BOOTSTRAPPED',traveler.traveler_id,'BUILD_PERSONAL_TRAVEL_VAULT',facts_created,{'traveler_created':created,'one_click':True,'no_automatic_external_sharing':True})
            s.commit()
        _growth_profile_created(user_id)
        return {'status':'READY','traveler_id':traveler.traveler_id,'traveler_created':created,'facts_created':facts_created,'sharing':'CONSENT_REQUIRED','completeness':self.completeness(user_id)}

    def _audit(self,s,user_id,actor_id,actor_type,action,traveler_id=None,purpose=None,fields=None,metadata=None):
        s.add(ProfileAccessAuditRow(access_id=new_id('pva'),user_id=user_id,traveler_id=traveler_id,actor_id=actor_id,actor_type=actor_type,action=action,purpose=purpose,fields_json=fields or [],metadata_json=metadata or {},created_at=now()))

    def create_import(self,user_id,b,trusted_source=False):
        source_type=b.get('source_type','MANUAL').upper()
        if source_type not in ALLOWED_SOURCE_TYPES:raise ValueError('UNSUPPORTED_PROFILE_IMPORT_SOURCE')
        if source_type in {'OFFICIAL_API','DOCUMENT_SCAN'} and not trusted_source:raise ValueError('TRUSTED_PROFILE_SOURCE_ADAPTER_REQUIRED')
        if not isinstance(b.get('items',[]),list) or len(b.get('items',[]))>250:raise ValueError('PROFILE_IMPORT_ITEM_LIMIT')
        provider=(b.get('source_provider') or '').strip() or None
        source_ref=b.get('source_reference')
        fingerprint=b.get('source_fingerprint') or h({'type':source_type,'provider':provider,'ref':source_ref,'content':b.get('content_hash') or b.get('items',[])})
        content_hash=b.get('content_hash') or h(b.get('items',[]))
        with mutation_session() as s:
            prior=s.scalars(select(ProfileImportJobRow).where(ProfileImportJobRow.user_id==user_id,ProfileImportJobRow.source_fingerprint==fingerprint)).all()
            if any((j.metadata_json or {}).get('source_disconnected') for j in prior):raise ValueError('PROFILE_SOURCE_DISCONNECTED')
            existing=s.scalar(select(ProfileImportJobRow).where(ProfileImportJobRow.user_id==user_id,ProfileImportJobRow.source_fingerprint==fingerprint,ProfileImportJobRow.content_hash==content_hash).order_by(ProfileImportJobRow.created_at.desc()))
            if existing and not (existing.metadata_json or {}).get('values_deleted'):return self.get_import(user_id,existing.import_job_id)|{'idempotent_replay':True}
            t=now();job=ProfileImportJobRow(import_job_id=new_id('pij'),user_id=user_id,source_type=source_type,source_provider=provider,source_reference=source_ref,source_fingerprint=fingerprint,content_hash=content_hash,status='RECEIVED',consent_id=b.get('consent_id'),item_count=0,accepted_count=0,rejected_count=0,conflict_count=0,metadata_json=b.get('metadata') or {},created_at=t,updated_at=t,completed_at=None);s.add(job)
            declaration_refs=set()
            for raw in b.get('items') or []:
                if not isinstance(raw,dict):raise ValueError('PROFILE_IMPORT_ENTITY_INVALID')
                et=(raw.get('entity_type') or 'PROFILE_FACT').upper();ft=(raw.get('field_type') or '').upper() or None
                if et not in {'TRAVELER','PROFILE_FACT'} or (et=='PROFILE_FACT' and not ft):raise ValueError('PROFILE_IMPORT_ENTITY_INVALID')
                if et=='TRAVELER' and not isinstance(raw.get('value'),dict):raise ValueError('PROFILE_IMPORT_ENTITY_INVALID')
                if et=='TRAVELER' and raw.get('traveler_ref'):
                    if raw['traveler_ref'] in declaration_refs:raise ValueError('PROFILE_TRAVELER_REFERENCE_AMBIGUOUS')
                    declaration_refs.add(raw['traveler_ref'])
                value=raw.get('value');sens=bool(raw.get('sensitive')) or ft in SENSITIVE_FIELDS or (et=='TRAVELER' and isinstance(value,dict) and any(value.get(k) for k in ('document_number','date_of_birth')));conf=max(0,min(10000,int(raw.get('confidence_bps',7000))))
                source_payload={k:v for k,v in raw.items() if k in {'entity_type','traveler_ref','field_type','confidence_bps','valid_from','valid_until'}}
                if trusted_source and source_type in {'OFFICIAL_API','DOCUMENT_SCAN'}:
                    source_payload['verification_method']=raw.get('verification_method')
                    source_payload['adapter_verified']=True
                status='NEEDS_REVIEW' if (sens or conf<9500 or source_type in {'SCREENSHOT_AI','IMAGE_AI','PDF_AI','TEXT_IMPORT','SHARE_TO_GO'}) else 'EXTRACTED'
                item=ProfileImportItemRow(import_item_id=new_id('pii'),import_job_id=job.import_job_id,user_id=user_id,entity_type=et,traveler_ref=raw.get('traveler_ref'),field_type=ft,candidate_value_ciphertext=encrypt_secret(json.dumps(value,ensure_ascii=False)) if value is not None else None,normalized_value_hash=h(value) if value is not None else None,preview_masked=mask(value,sens),sensitive=sens,confidence_bps=conf,source_payload_json=source_payload,status=status,resolution_traveler_id=None,conflict_fact_id=None,review_action=None,created_at=t,updated_at=t);s.add(item);job.item_count+=1
            job.status='EXTRACTED' if job.item_count else 'RECEIVED';job.updated_at=t;self._audit(s,user_id,user_id,'CONSUMER','PROFILE_IMPORT_RECEIVED',purpose='BUILD_PERSONAL_TRAVEL_VAULT',metadata={'import_job_id':job.import_job_id,'source_type':source_type,'item_count':job.item_count});s.commit();return self.get_import(user_id,job.import_job_id)

    def _item_value(self,item):
        if not item.candidate_value_ciphertext:return None
        return json.loads(decrypt_secret(item.candidate_value_ciphertext))

    def get_import(self,user_id,job_id):
        with SessionLocal() as s:
            j=s.get(ProfileImportJobRow,job_id)
            if not j or j.user_id!=user_id:raise ValueError('PROFILE_IMPORT_NOT_FOUND')
            items=s.scalars(select(ProfileImportItemRow).where(ProfileImportItemRow.import_job_id==job_id).order_by(ProfileImportItemRow.created_at)).all()
            return {'import_job_id':j.import_job_id,'source_type':j.source_type,'source_provider':j.source_provider,'source_reference':j.source_reference,'source_fingerprint':j.source_fingerprint,'content_hash':j.content_hash,'status':j.status,'item_count':j.item_count,'accepted_count':j.accepted_count,'rejected_count':j.rejected_count,'conflict_count':j.conflict_count,'created_at':j.created_at.isoformat(),'completed_at':j.completed_at.isoformat() if j.completed_at else None,'items':[{'import_item_id':x.import_item_id,'revision':revision(x),'entity_type':x.entity_type,'traveler_ref':x.traveler_ref,'field_type':x.field_type,'preview_masked':mask(self._item_value(x),True) if x.sensitive or x.field_type in SENSITIVE_FIELDS else x.preview_masked,'sensitive':bool(x.sensitive or x.field_type in SENSITIVE_FIELDS),'confidence_bps':x.confidence_bps,'status':x.status,'resolution_traveler_id':x.resolution_traveler_id,'conflict_fact_id':x.conflict_fact_id,'review_action':x.review_action} for x in items]}

    def review_item(self,user_id,job_id,item_id,action):
        action=action.upper()
        if action not in {'ACCEPT','REJECT','KEEP_BOTH','USE_EXISTING','REPLACE_EXISTING'}:raise ValueError('INVALID_PROFILE_REVIEW_ACTION')
        with mutation_session() as s:
            j=s.get(ProfileImportJobRow,job_id);i=s.get(ProfileImportItemRow,item_id)
            if not j or j.user_id!=user_id or not i or i.import_job_id!=job_id:raise ValueError('PROFILE_IMPORT_ITEM_NOT_FOUND')
            if j.status=='COMMITTED' or i.status=='COMMITTED':raise ValueError('PROFILE_IMPORT_ITEM_FINALIZED')
            if (j.metadata_json or {}).get('values_deleted'):raise ValueError('PROFILE_IMPORT_VALUE_REMOVED')
            if (j.metadata_json or {}).get('source_disconnected'):raise ValueError('PROFILE_SOURCE_DISCONNECTED')
            if action in {'REPLACE_EXISTING','USE_EXISTING'} and not i.conflict_fact_id:raise ValueError('PROFILE_CONFLICT_REVIEW_REQUIRED')
            i.review_action=action;i.status='REJECTED' if action=='REJECT' else 'ACCEPTED';i.updated_at=now();j.updated_at=now();s.commit()
        return self.get_import(user_id,job_id)

    def _resolve_traveler(self,s,user_id,traveler_payload,source_type):
        selected = traveler_payload.get('existing_traveler_id')
        if selected:
            existing = owned_traveler(s,user_id,selected,edit=True)
            return existing, False
        full_name=(traveler_payload.get('full_name') or traveler_payload.get('name') or '').strip()
        if not full_name:raise ValueError('TRAVELER_NAME_REQUIRED')
        dob=traveler_payload.get('date_of_birth');nat=traveler_payload.get('nationality');doc=traveler_payload.get('document_number')
        for flag in ('booking_permission','is_primary'):
            if flag in traveler_payload and type(traveler_payload[flag]) is not bool:raise ValueError('PERMISSION_BOOLEAN_REQUIRED')
        if doc:
            doc_hash=h(doc)
            facts=s.scalars(select(ProfileFactRow).where(ProfileFactRow.user_id==user_id,ProfileFactRow.normalized_value_hash==doc_hash,ProfileFactRow.field_type.in_(['PASSPORT_NUMBER','ID_CARD_NUMBER','DRIVER_LICENSE_NUMBER']),ProfileFactRow.status=='ACTIVE')).all()
            if facts:
                return owned_traveler(s,user_id,facts[0].traveler_id,edit=True),False
        candidates=s.scalars(select(TravelerProfileRow).where(TravelerProfileRow.user_id==user_id,TravelerProfileRow.status=='ACTIVE')).all()
        key=h([full_name,dob or '',nat or ''])
        for r in candidates:
            if dob and nat and h([r.full_name,r.date_of_birth or '',r.nationality or ''])==key:return owned_traveler(s,user_id,r.traveler_id,edit=True),False
        validate_value('LEGAL_NAME',full_name)
        if dob:validate_value('DATE_OF_BIRTH',dob)
        if nat:validate_value('NATIONALITY',nat);nat=nat.upper()
        rel=(traveler_payload.get('relationship_type') or ('SELF' if not candidates else 'FREQUENT_TRAVELER')).upper()
        if rel not in ALLOWED_RELATIONSHIPS:rel='OTHER'
        t=now();r=TravelerProfileRow(traveler_id=new_id('trav'),user_id=user_id,full_name=full_name,date_of_birth=dob,nationality=nat,document_type=traveler_payload.get('document_type') if source_type=='MANUAL' else None,document_ciphertext=encrypt_secret(doc) if (doc and source_type=='MANUAL') else None,relationship_type=rel,booking_permission=bool(traveler_payload.get('booking_permission',True)),guardian_traveler_id=traveler_payload.get('guardian_traveler_id'),guardian_consent_status=traveler_payload.get('guardian_consent_status'),source_type=source_type,is_primary=bool(traveler_payload.get('is_primary',rel=='SELF' and not candidates)),status='ACTIVE',created_at=t,updated_at=t);s.add(r);s.flush()
        for ptype in ALLOWED_PERMISSIONS:
            allowed=True if rel=='SELF' else ptype in {'VIEW','USE_FOR_BOOKING'}
            s.add(ProfileTravelerPermissionRow(permission_id=new_id('ptp'),user_id=user_id,traveler_id=r.traveler_id,permission_type=ptype,allowed=allowed,source='IMPORT_DEFAULT',created_at=t,updated_at=t))
        return r,True

    def commit_import(self,user_id,job_id):
        with mutation_session() as s:
            j=s.get(ProfileImportJobRow,job_id)
            if not j or j.user_id!=user_id:raise ValueError('PROFILE_IMPORT_NOT_FOUND')
            if (j.metadata_json or {}).get('source_disconnected'):raise ValueError('PROFILE_SOURCE_DISCONNECTED')
            if (j.metadata_json or {}).get('values_deleted'):raise ValueError('PROFILE_IMPORT_VALUE_REMOVED')
            if j.status=='COMMITTED':return self.get_import(user_id,job_id)|{'idempotent_replay':True}
            items=s.scalars(select(ProfileImportItemRow).where(ProfileImportItemRow.import_job_id==job_id).order_by(ProfileImportItemRow.created_at)).all()
            travelers={}; accepted=rejected=conflicts=0
            for item in items:
                declaration=self._item_value(item) if item.entity_type=='TRAVELER' else None
                if item.field_type in SENSITIVE_FIELDS or (isinstance(declaration,dict) and any(declaration.get(k) for k in ('document_number','date_of_birth'))):
                    item.sensitive=True
                    item.preview_masked=mask(self._item_value(item),True)
                    if item.status=='EXTRACTED' and not item.review_action:
                        item.status='NEEDS_REVIEW'
            # traveler declarations first
            for i in items:
                if i.entity_type!='TRAVELER':continue
                if i.status=='COMMITTED' and i.resolution_traveler_id:
                    travelers[i.traveler_ref or i.import_item_id]=i.resolution_traveler_id;accepted+=1;continue
                if i.status=='REJECTED':rejected+=1;continue
                if i.status=='NEEDS_REVIEW' and i.review_action is None:continue
                payload=self._item_value(i) or {}
                r,created=self._resolve_traveler(s,user_id,payload,j.source_type)
                i.source_payload_json={**(i.source_payload_json or {}),'created_traveler_in_job':created}
                i.resolution_traveler_id=r.traveler_id;i.status='COMMITTED';i.updated_at=now();travelers[i.traveler_ref or i.import_item_id]=r.traveler_id;accepted+=1
            for i in items:
                if i.entity_type=='TRAVELER':continue
                if i.status=='COMMITTED':accepted+=1;continue
                if i.status=='REJECTED':rejected+=1;continue
                if i.status=='NEEDS_REVIEW' and i.review_action is None:continue
                value=self._item_value(i);ft=(i.field_type or '').upper()
                tid=i.resolution_traveler_id or travelers.get(i.traveler_ref or '')
                if i.traveler_ref and not tid:
                    i.status='NEEDS_REVIEW';i.updated_at=now();continue
                if not tid:
                    candidates=s.scalars(select(TravelerProfileRow).where(TravelerProfileRow.user_id==user_id,TravelerProfileRow.status=='ACTIVE')).all()
                    if len(candidates)!=1:
                        i.status='NEEDS_REVIEW';i.updated_at=now();continue
                    tid=candidates[0].traveler_id
                tr=owned_traveler(s,user_id,tid)
                # A just-declared companion can receive its initial reviewed import;
                # later writes require the independently controlled edit permission.
                declared=next((x for x in items if x.entity_type=='TRAVELER' and x.resolution_traveler_id==tid),None)
                initial=bool(declared and (declared.source_payload_json or {}).get('created_traveler_in_job'))
                if not initial and not permission(s,user_id,tr,'EDIT'):raise ValueError('TRAVELER_EDIT_PERMISSION_REQUIRED')
                if not initial and i.sensitive and not permission(s,user_id,tr,'SENSITIVE_DATA'):raise ValueError('TRAVELER_SENSITIVE_PERMISSION_REQUIRED')
                validate_value(ft,value)
                existing=s.scalars(select(ProfileFactRow).where(ProfileFactRow.user_id==user_id,ProfileFactRow.traveler_id==tid,ProfileFactRow.field_type==ft,ProfileFactRow.status=='ACTIVE')).all()
                exact=next((x for x in existing if x.normalized_value_hash==i.normalized_value_hash),None)
                if exact:
                    i.resolution_traveler_id=tid;i.status='COMMITTED';accepted+=1;continue
                conflict=next(iter(existing),None)
                if i.conflict_fact_id and i.review_action in {'REPLACE_EXISTING','USE_EXISTING'}:
                    selected=next((f for f in existing if f.fact_id==i.conflict_fact_id),None)
                    if not selected:
                        i.status='CONFLICT' if conflict else 'NEEDS_REVIEW';i.conflict_fact_id=conflict.fact_id if conflict else None;i.review_action=None
                        if conflict:conflicts+=1
                        continue
                    conflict=selected
                if conflict and ft not in MULTI_VALUE_FIELDS and i.review_action not in {'REPLACE_EXISTING','USE_EXISTING'}:
                    i.status='CONFLICT';i.conflict_fact_id=conflict.fact_id;i.resolution_traveler_id=tid;conflicts+=1;continue
                if conflict and i.review_action=='USE_EXISTING':
                    i.status='COMMITTED';i.resolution_traveler_id=tid;accepted+=1;continue
                tlevel,vstatus=trust_for(j.source_type,True if i.review_action in {'ACCEPT','KEEP_BOTH','REPLACE_EXISTING'} else False,i.source_payload_json.get('verification_method'),i.source_payload_json.get('adapter_verified') is True)
                # AI-imported sensitive facts never become VERIFIED solely from extraction/review.
                if j.source_type in {'SCREENSHOT_AI','IMAGE_AI','PDF_AI','TEXT_IMPORT','SHARE_TO_GO'} and i.sensitive:
                    tlevel='L1_USER_CONFIRMED' if i.review_action else 'L0_EXTRACTED';vstatus='USER_CONFIRMED' if i.review_action else 'CANDIDATE'
                f=ProfileFactRow(fact_id=new_id('pff'),user_id=user_id,traveler_id=tid,field_type=ft,value_ciphertext=encrypt_secret(json.dumps(value,ensure_ascii=False)),normalized_value_hash=i.normalized_value_hash or h(value),sensitive=i.sensitive,source_type=j.source_type,source_provider=j.source_provider,source_reference=j.source_reference,source_fingerprint=j.source_fingerprint,confidence_bps=i.confidence_bps,user_confirmed=bool(i.review_action),trust_level=tlevel,verification_status=vstatus,verification_method=i.source_payload_json.get('verification_method'),valid_from=i.source_payload_json.get('valid_from'),valid_until=i.source_payload_json.get('valid_until'),superseded_by=None,status='ACTIVE',created_at=now(),updated_at=now());s.add(f);s.flush()
                if conflict and i.review_action=='REPLACE_EXISTING':conflict.status='SUPERSEDED';conflict.superseded_by=f.fact_id;conflict.updated_at=now()
                attr={'LEGAL_NAME':'full_name','DATE_OF_BIRTH':'date_of_birth','NATIONALITY':'nationality'}.get(ft)
                if attr:setattr(tr,attr,value.upper() if ft=='NATIONALITY' else value);tr.updated_at=now()
                i.resolution_traveler_id=tid;i.status='COMMITTED';i.updated_at=now();accepted+=1
            j.accepted_count=accepted;j.rejected_count=rejected;j.conflict_count=conflicts;j.status='CONFLICT' if conflicts else ('NEEDS_REVIEW' if any(x.status=='NEEDS_REVIEW' for x in items) else 'COMMITTED');j.updated_at=now();j.completed_at=now() if j.status=='COMMITTED' else None
            self._audit(s,user_id,user_id,'CONSUMER','PROFILE_IMPORT_COMMIT',purpose='BUILD_PERSONAL_TRAVEL_VAULT',metadata={'import_job_id':job_id,'accepted':accepted,'rejected':rejected,'conflicts':conflicts});s.commit()
        return self.get_import(user_id,job_id)

    def grant_consent(self,user_id,b):
        t=now();cid=new_id('pcn')
        with mutation_session() as s:
            tid=b.get('traveler_id')
            if tid:
                tr=s.get(TravelerProfileRow,tid)
                if not tr or tr.user_id!=user_id or tr.status!='ACTIVE':raise ValueError('TRAVELER_NOT_FOUND')
            c=ProfileConsentRow(consent_id=cid,user_id=user_id,traveler_id=tid,consent_type=(b.get('consent_type') or 'SENSITIVE_DATA_RELEASE').upper(),purpose=b.get('purpose') or 'TRAVEL_BOOKING',scope_json=[x.upper() for x in (b.get('scope') or [])],status='ACTIVE',granted_at=t,expires_at=dt(b.get('expires_at')),revoked_at=None);s.add(c);self._audit(s,user_id,user_id,'CONSUMER','PROFILE_CONSENT_GRANTED',tid,b.get('purpose'),b.get('scope'),{'consent_id':cid});s.commit();return {'consent_id':cid,'status':'ACTIVE','traveler_id':tid,'purpose':c.purpose,'scope':c.scope_json,'expires_at':c.expires_at.isoformat() if c.expires_at else None}

    def revoke_consent(self,user_id,consent_id):
        with mutation_session() as s:
            c=s.get(ProfileConsentRow,consent_id)
            if not c or c.user_id!=user_id:raise ValueError('CONSENT_NOT_FOUND')
            c.status='REVOKED';c.revoked_at=now();self._audit(s,user_id,user_id,'CONSUMER','PROFILE_CONSENT_REVOKED',c.traveler_id,c.purpose,c.scope_json,{'consent_id':consent_id});s.commit();return {'consent_id':consent_id,'status':'REVOKED'}

    def _active_consent(self,s,user_id,traveler_id,purpose,fields):
        rows=s.scalars(select(ProfileConsentRow).where(ProfileConsentRow.user_id==user_id,ProfileConsentRow.status=='ACTIVE')).all();t=now()
        for c in rows:
            if c.consent_type!='SENSITIVE_DATA_RELEASE':continue
            exp=c.expires_at
            if exp and exp.tzinfo is None: exp=exp.replace(tzinfo=timezone.utc)
            if exp and exp<=t:continue
            if c.traveler_id not in {None,traveler_id}:continue
            if c.purpose not in {purpose,'TRAVEL_BOOKING','ANY_TRAVEL_BOOKING'}:continue
            scope=set(c.scope_json or [])
            if '*' in scope or set(fields).issubset(scope):return c
        return None

    def release(self,user_id,b,requester_id=None,requester_type='CONSUMER'):
        tid=b['traveler_id'];fields=[x.upper() for x in b.get('requested_fields',[])];purpose=b.get('purpose') or 'TRAVEL_BOOKING';vertical=(b.get('vertical') or 'UNKNOWN').upper();destination=b.get('destination') or 'GO_VERTICAL';booking_id=b.get('booking_id')
        if not fields:raise ValueError('REQUESTED_FIELDS_REQUIRED')
        with mutation_session() as s:
            tr=s.get(TravelerProfileRow,tid)
            if not tr or tr.user_id!=user_id or tr.status!='ACTIVE':raise ValueError('TRAVELER_NOT_FOUND')
            facts=s.scalars(select(ProfileFactRow).where(ProfileFactRow.user_id==user_id,ProfileFactRow.traveler_id==tid,ProfileFactRow.field_type.in_(fields),ProfileFactRow.status=='ACTIVE')).all()
            by_field={}
            rank={'L4_VERIFIED_DOCUMENT':4,'L3_OFFICIAL_PROVIDER':3,'L2_STRUCTURED_SOURCE':2,'L1_USER_CONFIRMED':1,'L0_EXTRACTED':0}
            for f in facts:
                if not usable_fact(f):continue
                cur=by_field.get(f.field_type)
                if not cur or rank.get(f.trust_level,0)>rank.get(cur.trust_level,0):by_field[f.field_type]=f
            core_values={}
            if 'LEGAL_NAME' in fields and tr.full_name:core_values['LEGAL_NAME']=tr.full_name
            if 'DATE_OF_BIRTH' in fields and tr.date_of_birth:core_values['DATE_OF_BIRTH']=tr.date_of_birth
            if 'NATIONALITY' in fields and tr.nationality:core_values['NATIONALITY']=tr.nationality
            sensitive=[f.field_type for f in by_field.values() if f.sensitive or f.field_type in SENSITIVE_FIELDS]
            if 'DATE_OF_BIRTH' in core_values:sensitive.append('DATE_OF_BIRTH')
            permissions={x.permission_type:x.allowed for x in s.scalars(select(ProfileTravelerPermissionRow).where(ProfileTravelerPermissionRow.user_id==user_id,ProfileTravelerPermissionRow.traveler_id==tid)).all()}
            if not tr.booking_permission or not permissions.get('USE_FOR_BOOKING',tr.relationship_type=='SELF'):
                rid=new_id('pdr');s.add(ProfileDataReleaseAuditRow(release_id=rid,user_id=user_id,traveler_id=tid,requester_type=requester_type,requester_id=requester_id,vertical=vertical,purpose=purpose,destination=destination,booking_id=booking_id,requested_fields_json=fields,released_fields_json=[],consent_id=None,decision='DENY',reason_code='TRAVELER_BOOKING_PERMISSION_REQUIRED',created_at=now()));s.commit();raise ValueError('TRAVELER_BOOKING_PERMISSION_REQUIRED')
            if sensitive and not permissions.get('SENSITIVE_DATA',tr.relationship_type=='SELF'):
                rid=new_id('pdr');s.add(ProfileDataReleaseAuditRow(release_id=rid,user_id=user_id,traveler_id=tid,requester_type=requester_type,requester_id=requester_id,vertical=vertical,purpose=purpose,destination=destination,booking_id=booking_id,requested_fields_json=fields,released_fields_json=[],consent_id=None,decision='DENY',reason_code='TRAVELER_SENSITIVE_PERMISSION_REQUIRED',created_at=now()));s.commit();raise ValueError('TRAVELER_SENSITIVE_PERMISSION_REQUIRED')
            if sensitive and tr.relationship_type=='CHILD' and tr.guardian_consent_status not in {'GRANTED','ACTIVE'}:
                rid=new_id('pdr');s.add(ProfileDataReleaseAuditRow(release_id=rid,user_id=user_id,traveler_id=tid,requester_type=requester_type,requester_id=requester_id,vertical=vertical,purpose=purpose,destination=destination,booking_id=booking_id,requested_fields_json=fields,released_fields_json=[],consent_id=None,decision='DENY',reason_code='GUARDIAN_CONSENT_REQUIRED',created_at=now()));s.commit();raise ValueError('GUARDIAN_CONSENT_REQUIRED')
            consent=self._active_consent(s,user_id,tid,purpose,sensitive) if sensitive else None
            if sensitive and not consent:
                rid=new_id('pdr');s.add(ProfileDataReleaseAuditRow(release_id=rid,user_id=user_id,traveler_id=tid,requester_type=requester_type,requester_id=requester_id,vertical=vertical,purpose=purpose,destination=destination,booking_id=booking_id,requested_fields_json=fields,released_fields_json=[],consent_id=None,decision='DENY',reason_code='SENSITIVE_CONSENT_REQUIRED',created_at=now()));self._audit(s,user_id,requester_id or user_id,requester_type,'PROFILE_DATA_RELEASE_DENIED',tid,purpose,fields,{'destination':destination,'vertical':vertical});s.commit();raise ValueError('SENSITIVE_CONSENT_REQUIRED')
            released=dict(core_values)
            for ft,f in by_field.items():released[ft]=json.loads(decrypt_secret(f.value_ciphertext))
            rid=new_id('pdr');s.add(ProfileDataReleaseAuditRow(release_id=rid,user_id=user_id,traveler_id=tid,requester_type=requester_type,requester_id=requester_id,vertical=vertical,purpose=purpose,destination=destination,booking_id=booking_id,requested_fields_json=fields,released_fields_json=list(released),consent_id=consent.consent_id if consent else None,decision='ALLOW',reason_code='MINIMUM_NECESSARY_FIELDS_RELEASED',created_at=now()));self._audit(s,user_id,requester_id or user_id,requester_type,'PROFILE_DATA_RELEASED',tid,purpose,list(released),{'release_id':rid,'destination':destination,'vertical':vertical});s.commit();return {'release_id':rid,'traveler_id':tid,'released_fields':released,'missing_fields':[x for x in fields if x not in released],'consent_id':consent.consent_id if consent else None,'purpose':purpose,'destination':destination,'minimum_necessary':True}

    def vault(self,user_id,actor_id=None,actor_type='CONSUMER'):
        with SessionLocal() as s:
            trs=s.scalars(select(TravelerProfileRow).where(TravelerProfileRow.user_id==user_id,TravelerProfileRow.status=='ACTIVE').order_by(TravelerProfileRow.is_primary.desc(),TravelerProfileRow.created_at)).all();out=[]
            for tr in trs:
                facts=s.scalars(select(ProfileFactRow).where(ProfileFactRow.user_id==user_id,ProfileFactRow.traveler_id==tr.traveler_id,ProfileFactRow.status=='ACTIVE').order_by(ProfileFactRow.field_type,ProfileFactRow.created_at.desc())).all()
                out.append({'traveler_id':tr.traveler_id,'full_name':tr.full_name,'relationship_type':tr.relationship_type,'booking_permission':tr.booking_permission,'guardian_traveler_id':tr.guardian_traveler_id,'guardian_consent_status':tr.guardian_consent_status,'is_primary':tr.is_primary,'source_type':tr.source_type,'nationality':tr.nationality,'revision':revision(tr),'permissions':{p.permission_type:p.allowed for p in s.scalars(select(ProfileTravelerPermissionRow).where(ProfileTravelerPermissionRow.user_id==user_id,ProfileTravelerPermissionRow.traveler_id==tr.traveler_id)).all()},'facts':[{'fact_id':f.fact_id,'revision':revision(f),'field_type':f.field_type,'value_masked':mask(json.loads(decrypt_secret(f.value_ciphertext)),f.sensitive or f.field_type in SENSITIVE_FIELDS),'sensitive':f.sensitive or f.field_type in SENSITIVE_FIELDS,'source_type':f.source_type,'source_provider':f.source_provider,'confidence_bps':f.confidence_bps,'user_confirmed':f.user_confirmed,'trust_level':f.trust_level,'verification_status':f.verification_status,'valid_until':f.valid_until} for f in facts]})
            self._audit(s,user_id,actor_id or user_id,actor_type,'PROFILE_VAULT_VIEWED',purpose='USER_PROFILE_MANAGEMENT',fields=[]);s.commit();return {'travelers':out,'traveler_count':len(out),'secure_vault_boundary':'SENSITIVE_FACT_VALUES_MASKED','ai_full_vault_access':False}

    def set_permission(self,user_id,traveler_id,permission_type,allowed):
        permission_type=permission_type.upper()
        if permission_type not in ALLOWED_PERMISSIONS:raise ValueError('INVALID_TRAVELER_PERMISSION')
        with mutation_session() as s:
            tr=s.get(TravelerProfileRow,traveler_id)
            if not tr or tr.user_id!=user_id:raise ValueError('TRAVELER_NOT_FOUND')
            if tr.status!='ACTIVE':raise ValueError('TRAVELER_NOT_FOUND')
            if type(allowed) is not bool:raise ValueError('PERMISSION_BOOLEAN_REQUIRED')
            if permission_type=='USE_FOR_BOOKING':tr.booking_permission=allowed;tr.updated_at=now()
            p=s.scalar(select(ProfileTravelerPermissionRow).where(ProfileTravelerPermissionRow.user_id==user_id,ProfileTravelerPermissionRow.traveler_id==traveler_id,ProfileTravelerPermissionRow.permission_type==permission_type));t=now()
            if p:p.allowed=bool(allowed);p.updated_at=t
            else:p=ProfileTravelerPermissionRow(permission_id=new_id('ptp'),user_id=user_id,traveler_id=traveler_id,permission_type=permission_type,allowed=bool(allowed),source='USER',created_at=t,updated_at=t);s.add(p)
            self._audit(s,user_id,user_id,'CONSUMER','TRAVELER_PERMISSION_UPDATED',traveler_id,'TRAVELER_MANAGEMENT',[permission_type],{'allowed':bool(allowed)});s.commit();return {'traveler_id':traveler_id,'permission_type':permission_type,'allowed':bool(allowed)}

    def delete_fact(self,user_id,fact_id):
        with mutation_session() as s:
            fact=s.get(ProfileFactRow,fact_id)
            if not fact or fact.user_id!=user_id:raise ValueError('PROFILE_FACT_NOT_FOUND')
            if fact.status=='DELETED':return {'fact_id':fact_id,'status':'DELETED','replayed':True}
            if fact.status!='ACTIVE':raise ValueError('PROFILE_CHANGED_RELOAD_REQUIRED')
            rows=s.scalars(select(ProfileFactRow).where(ProfileFactRow.user_id==user_id,
                ProfileFactRow.traveler_id==fact.traveler_id,ProfileFactRow.field_type==fact.field_type)).all()
            selected={fact.fact_id};changed=True
            while changed:
                previous=len(selected)
                selected.update(f.fact_id for f in rows if f.superseded_by in selected)
                changed=len(selected)!=previous
            self._erase_fact_rows(s,user_id,[f for f in rows if f.fact_id in selected])
            self._audit(s,user_id,user_id,'CONSUMER','PROFILE_FACT_DELETED',fact.traveler_id,'USER_DELETE',
                [fact.field_type],{'fact_id':fact_id,'erased_revision_count':len(selected)})
            return {'fact_id':fact_id,'status':'DELETED','erased_revision_count':len(selected)}

    def delete_source(self,user_id,source_fingerprint):
        with mutation_session() as s:
            rows=s.scalars(select(ProfileFactRow).where(ProfileFactRow.user_id==user_id,
                ProfileFactRow.source_fingerprint==source_fingerprint,ProfileFactRow.status!='DELETED')).all()
            jobs=s.scalars(select(ProfileImportJobRow).where(ProfileImportJobRow.user_id==user_id,
                ProfileImportJobRow.source_fingerprint==source_fingerprint)).all()
            if not rows and not jobs:raise ValueError('PROFILE_SOURCE_NOT_FOUND')
            self._erase_fact_rows(s,user_id,rows)
            for job in jobs:
                job.metadata_json={**(job.metadata_json or {}),'source_disconnected':True,'values_deleted':True}
                for item in s.scalars(select(ProfileImportItemRow).where(ProfileImportItemRow.import_job_id==job.import_job_id)).all():
                    if item.entity_type=='TRAVELER' and item.resolution_traveler_id and item.candidate_value_ciphertext:
                        tr=s.get(TravelerProfileRow,item.resolution_traveler_id)
                        if tr and tr.status=='ACTIVE':
                            tr=owned_traveler(s,user_id,tr.traveler_id,edit=True);payload=self._item_value(item) or {}
                            for attr,ft in {'full_name':'LEGAL_NAME','date_of_birth':'DATE_OF_BIRTH','nationality':'NATIONALITY'}.items():
                                value=payload.get(attr,payload.get('name') if attr=='full_name' else None)
                                if value is None or h(getattr(tr,attr))!=h(value):continue
                                retained=s.scalar(select(ProfileFactRow).where(ProfileFactRow.user_id==user_id,
                                    ProfileFactRow.traveler_id==tr.traveler_id,ProfileFactRow.field_type==ft,
                                    ProfileFactRow.status=='ACTIVE',ProfileFactRow.source_fingerprint!=source_fingerprint))
                                if not retained:setattr(tr,attr,'' if attr=='full_name' else None)
                            if payload.get('document_number') and tr.document_ciphertext and h(decrypt_secret(tr.document_ciphertext))==h(payload['document_number']):
                                tr.document_ciphertext=None;tr.document_type=None
                            tr.updated_at=now()
                    item.candidate_value_ciphertext=None;item.normalized_value_hash=None;item.preview_masked='[DELETED]'
                    item.status='REJECTED';item.updated_at=now()
            self._audit(s,user_id,user_id,'CONSUMER','PROFILE_SOURCE_DELETED',purpose='USER_DELETE',
                metadata={'source_fingerprint':source_fingerprint,'deleted_facts':len(rows)})
            return {'source_fingerprint':source_fingerprint,'deleted_facts':len(rows),'status':'DISCONNECTED'}

    def consent_list(self, user_id):
        with SessionLocal() as s:
            rows = s.scalars(select(ProfileConsentRow).where(ProfileConsentRow.user_id == user_id).order_by(ProfileConsentRow.granted_at.desc())).all()
            return {'items': [{'consent_id': c.consent_id, 'traveler_id': c.traveler_id,
                'purpose': c.purpose, 'scope': c.scope_json, 'status': c.status,
                'expires_at': c.expires_at.isoformat() if c.expires_at else None} for c in rows]}

    def export_owned(self, user_id, confirmed=False):
        """Owner-initiated portability; never an AI or supplier data-release path."""
        if confirmed is not True:
            raise ValueError('PROFILE_EXPORT_CONFIRMATION_REQUIRED')
        with SessionLocal() as s:
            travelers = s.scalars(select(TravelerProfileRow).where(TravelerProfileRow.user_id == user_id, TravelerProfileRow.status == 'ACTIVE')).all()
            result = []; excluded = []
            for tr in travelers:
                permissions = {p.permission_type: p.allowed for p in s.scalars(select(ProfileTravelerPermissionRow).where(ProfileTravelerPermissionRow.user_id == user_id, ProfileTravelerPermissionRow.traveler_id == tr.traveler_id)).all()}
                if not permissions.get('SHARE', tr.relationship_type == 'SELF'):
                    excluded.append({'traveler_id': tr.traveler_id, 'reason': 'TRAVELER_SHARE_PERMISSION_REQUIRED'})
                    continue
                sensitive_allowed = permissions.get('SENSITIVE_DATA', tr.relationship_type == 'SELF')
                facts = s.scalars(select(ProfileFactRow).where(ProfileFactRow.user_id == user_id, ProfileFactRow.traveler_id == tr.traveler_id, ProfileFactRow.status.in_(['ACTIVE','SUPERSEDED']))).all()
                out_facts = []
                for f in facts:
                    if (f.sensitive or f.field_type in SENSITIVE_FIELDS) and not sensitive_allowed:
                        continue
                    out_facts.append({'fact_id': f.fact_id, 'field_type': f.field_type,
                        'value': json.loads(decrypt_secret(f.value_ciphertext)), 'status': f.status,
                        'sensitive': f.sensitive or f.field_type in SENSITIVE_FIELDS,
                        'source_type': f.source_type, 'source_provider': f.source_provider,
                        'source_reference': f.source_reference, 'source_fingerprint': f.source_fingerprint,
                        'trust_level': f.trust_level, 'verification_status': f.verification_status,
                        'user_confirmed': f.user_confirmed, 'valid_from': f.valid_from,
                        'valid_until': f.valid_until, 'superseded_by': f.superseded_by})
                result.append({'traveler_id': tr.traveler_id, 'full_name': tr.full_name,
                    'relationship_type': tr.relationship_type, 'nationality': tr.nationality,
                    'date_of_birth': tr.date_of_birth if sensitive_allowed else None,
                    'facts': out_facts})
            self._audit(s, user_id, user_id, 'CONSUMER', 'PROFILE_OWNER_EXPORT',
                purpose='USER_REQUESTED_PORTABILITY', metadata={'traveler_count': len(result), 'excluded_count': len(excluded)})
            s.commit()
            return {'format': 'GO_PERSONAL_TRAVEL_VAULT', 'schema_version': 1,
                'exported_at': now().isoformat(), 'travelers': result, 'excluded': excluded,
                'payment_credentials_included': False}

    def delete_traveler(self, user_id, traveler_id):
        """Remove reusable profile data; historical transaction records remain separate."""
        with mutation_session() as s:
            tr = s.scalar(select(TravelerProfileRow).where(TravelerProfileRow.traveler_id == traveler_id).with_for_update())
            if not tr or tr.user_id != user_id:
                raise ValueError('TRAVELER_NOT_FOUND')
            if tr.status == 'DELETED':
                return {'traveler_id': traveler_id, 'status': 'DELETED', 'replayed': True}
            tr.status = 'DELETED'; tr.full_name = '[DELETED]'; tr.date_of_birth = None
            tr.nationality = None; tr.document_ciphertext = None; tr.document_type = None
            tr.booking_permission = False; tr.guardian_consent_status = None; tr.updated_at = now()
            facts = s.scalars(select(ProfileFactRow).where(ProfileFactRow.user_id == user_id, ProfileFactRow.traveler_id == traveler_id)).all()
            for f in facts:
                f.status = 'DELETED'; f.value_ciphertext = encrypt_secret('null')
                f.normalized_value_hash = h(['DELETED', f.fact_id]); f.source_reference = None; f.updated_at = now()
            items = s.scalars(select(ProfileImportItemRow).where(ProfileImportItemRow.user_id == user_id, ProfileImportItemRow.resolution_traveler_id == traveler_id)).all()
            for item in items:
                item.status = 'REJECTED'; item.candidate_value_ciphertext = None
                item.preview_masked = '[DELETED]'; item.normalized_value_hash = None; item.updated_at = now()
            for c in s.scalars(select(ProfileConsentRow).where(ProfileConsentRow.user_id == user_id, ProfileConsentRow.traveler_id == traveler_id)).all():
                c.status = 'REVOKED'; c.revoked_at = now()
            for p in s.scalars(select(ProfileTravelerPermissionRow).where(ProfileTravelerPermissionRow.user_id == user_id, ProfileTravelerPermissionRow.traveler_id == traveler_id)).all():
                p.allowed = False; p.updated_at = now()
            self._audit(s, user_id, user_id, 'CONSUMER', 'PROFILE_TRAVELER_DELETED', traveler_id,
                'USER_DELETE', metadata={'deleted_facts': len(facts)})
            return {'traveler_id': traveler_id, 'status': 'DELETED', 'deleted_facts': len(facts)}

    def completeness(self,user_id):
        with SessionLocal() as s:
            trs=s.scalars(select(TravelerProfileRow).where(TravelerProfileRow.user_id==user_id,TravelerProfileRow.status=='ACTIVE')).all();primary=next((x for x in trs if x.is_primary),trs[0] if trs else None)
            if not primary:return {'profile_ready':False,'capabilities':{'DOMESTIC_FLIGHT_READY':False,'INTERNATIONAL_FLIGHT_READY':False,'HOTEL_READY':False,'RAIL_READY':False,'CAR_RENTAL_READY':False,'INVOICE_READY':False},'missing':['PRIMARY_TRAVELER']}
            facts=s.scalars(select(ProfileFactRow).where(ProfileFactRow.user_id==user_id,ProfileFactRow.traveler_id==primary.traveler_id,ProfileFactRow.status=='ACTIVE')).all();have={x.field_type for x in facts if usable_fact(x)}
            base_name=bool(primary.full_name);dob=bool(primary.date_of_birth) or 'DATE_OF_BIRTH' in have;nat=bool(primary.nationality) or 'NATIONALITY' in have;passport='PASSPORT_NUMBER' in have;mobile='MOBILE' in have;email='EMAIL' in have;invoice=bool({'PERSONAL_INVOICE','COMPANY_INVOICE'} & have);license_='DRIVER_LICENSE_NUMBER' in have
            caps={'DOMESTIC_FLIGHT_READY':base_name and dob,'INTERNATIONAL_FLIGHT_READY':base_name and dob and nat and passport,'HOTEL_READY':base_name and (mobile or email),'RAIL_READY':base_name and dob,'CAR_RENTAL_READY':base_name and license_,'INVOICE_READY':invoice}
            missing=[]
            if not passport:missing.append('PASSPORT_NUMBER')
            if not dob:missing.append('DATE_OF_BIRTH')
            if not mobile and not email:missing.append('MOBILE_OR_EMAIL')
            return {'profile_ready':any(caps.values()),'traveler_id':primary.traveler_id,'capabilities':caps,'missing':missing,'ready_count':sum(1 for x in caps.values() if x),'capability_count':len(caps)}

    @staticmethod
    def _reject_provider_credentials(value,path='request'):
        forbidden={'password','passwd','otp','captcha','cookie','cookies','session','access_token','refresh_token','authorization_code'}
        if isinstance(value,dict):
            for key,nested in value.items():
                if str(key).lower() in forbidden:raise ValueError('OTA_CREDENTIALS_NOT_ACCEPTED')
                PersonalTravelVaultService._reject_provider_credentials(nested,f'{path}.{key}')
        elif isinstance(value,list):
            for index,nested in enumerate(value):PersonalTravelVaultService._reject_provider_credentials(nested,f'{path}[{index}]')

    def provider_options(self):
        return {'providers':[{
            'provider':key,'label':value['label'],
            'official_authorization_available':bool(os.getenv(value['authorization_env'])),
            'fallback_methods':['DATA_EXPORT','FILE_UPLOAD','SCREENSHOT'],
        } for key,value in self.PROFILE_PROVIDERS.items()],
        'credential_policy':'PROVIDER_HOSTED_LOGIN_ONLY','state_ttl_seconds':int(self.CONNECTION_TTL.total_seconds())}

    def _connection_view(self,job):
        metadata=job.metadata_json or {}
        return {'connection_id':job.import_job_id,'provider':job.source_provider,'method':metadata.get('method'),
            'status':job.status,'created_at':job.created_at.isoformat(),'expires_at':metadata.get('expires_at'),
            'import_job_id':metadata.get('import_job_id'),'credentials_received_by_go':False}

    def provider_connections(self,user_id):
        with SessionLocal() as s:
            rows=s.scalars(select(ProfileImportJobRow).where(ProfileImportJobRow.user_id==user_id).order_by(ProfileImportJobRow.created_at.desc())).all()
            return {'items':[self._connection_view(row) for row in rows if (row.metadata_json or {}).get('connection_intent')]}

    def create_provider_connection(self,user_id,b):
        self._reject_provider_credentials(b)
        provider=str(b.get('provider') or '').upper();method=str(b.get('method') or 'OFFICIAL_AUTHORIZATION').upper()
        if provider not in self.PROFILE_PROVIDERS:raise ValueError('UNSUPPORTED_PROFILE_PROVIDER')
        if method not in self.CONNECTION_METHODS:raise ValueError('UNSUPPORTED_PROFILE_CONNECTION_METHOD')
        if b.get('account_holder_confirmed') is not True:raise ValueError('ACCOUNT_HOLDER_CONFIRMATION_REQUIRED')
        authorization_base=os.getenv(self.PROFILE_PROVIDERS[provider]['authorization_env']) if method=='OFFICIAL_AUTHORIZATION' else None
        if authorization_base:
            try:authorization_base=validate_external_navigation_url(authorization_base,reject_sensitive_query=False)
            except ValueError as exc:raise ValueError('PROFILE_PROVIDER_AUTHORIZATION_URL_INVALID') from exc
        state=secrets.token_urlsafe(32);t=now();expires=t+self.CONNECTION_TTL;connection_id=new_id('pij')
        effective_method=method if authorization_base or method!='OFFICIAL_AUTHORIZATION' else 'FILE_UPLOAD'
        status='AWAITING_PROVIDER_AUTHORIZATION' if authorization_base else 'AWAITING_USER_UPLOAD'
        metadata={'connection_intent':True,'provider':provider,'method':effective_method,
            'requested_method':method,'account_holder_confirmed':True,'state_hash':h(state),
            'expires_at':expires.isoformat(),'credentials_received_by_go':False}
        with mutation_session() as s:
            s.add(ProfileImportJobRow(import_job_id=connection_id,user_id=user_id,source_type='OFFICIAL_API' if authorization_base else 'USER_DATA_PACKAGE',source_provider=provider,source_reference='account-holder-connection',source_fingerprint=h([user_id,provider,connection_id]),content_hash=h([]),status=status,consent_id=None,item_count=0,accepted_count=0,rejected_count=0,conflict_count=0,metadata_json=metadata,created_at=t,updated_at=t,completed_at=None))
            self._audit(s,user_id,user_id,'CONSUMER','PROFILE_PROVIDER_CONNECTION_STARTED',purpose='BUILD_PERSONAL_TRAVEL_VAULT',metadata={'provider':provider,'method':effective_method,'connection_id':connection_id})
        result={'connection_id':connection_id,'status':status,'provider':provider,'method':effective_method,
            'credentials_received_by_go':False,'expires_at':expires.isoformat()}
        if authorization_base:
            query=urlencode({'state':state,'connection_id':connection_id})
            return result|{'authorization_url':authorization_base+('&' if '?' in authorization_base else '?')+query,'login_surface':'PROVIDER_HOSTED'}
        return result|{'authorization_url':None,'next_step':'UPLOAD_PROVIDER_EXPORT_FOR_PREVIEW',
            'upload_endpoint':f'/v1/consumer/profile/provider-connections/{connection_id}/upload'}

    def complete_provider_connection(self,connection_id,b):
        """Trusted adapter callback. Consume state before parsing provider data so it cannot be replayed."""
        if b.get('account_holder_verified') is not True:raise ValueError('PROVIDER_ACCOUNT_HOLDER_NOT_VERIFIED')
        subject=str(b.get('provider_account_subject') or '').strip()
        evidence=str(b.get('authorization_evidence_reference') or '').strip()
        if not subject or len(subject)>512 or not evidence or len(evidence)>512:raise ValueError('PROVIDER_AUTHORIZATION_EVIDENCE_REQUIRED')
        supplied_state=str(b.get('state') or '')
        expired=False
        with mutation_session() as s:
            job=s.get(ProfileImportJobRow,connection_id)
            metadata=(job.metadata_json or {}) if job else {}
            if not job or not metadata.get('connection_intent'):raise ValueError('PROFILE_PROVIDER_CONNECTION_NOT_FOUND')
            if job.status!='AWAITING_PROVIDER_AUTHORIZATION':raise ValueError('PROFILE_PROVIDER_STATE_ALREADY_USED')
            expires=dt(metadata.get('expires_at'))
            if not expires or now()>=expires:
                job.status='AUTHORIZATION_EXPIRED';job.updated_at=now()
                job.metadata_json={**metadata,'state_hash':None};expired=True
            else:
                if not hmac.compare_digest(h(supplied_state),str(metadata.get('state_hash') or '')):raise ValueError('PROFILE_PROVIDER_STATE_INVALID')
                consumed=s.execute(update(ProfileImportJobRow).where(ProfileImportJobRow.import_job_id==connection_id,
                    ProfileImportJobRow.status=='AWAITING_PROVIDER_AUTHORIZATION').values(status='AUTHORIZATION_CONSUMED',updated_at=now())).rowcount
                if consumed!=1:raise ValueError('PROFILE_PROVIDER_STATE_ALREADY_USED')
                user_id=job.user_id;provider=job.source_provider
                job.metadata_json={**metadata,'state_hash':None,'provider_account_subject_hash':h(subject),
                    'authorization_evidence_hash':h(evidence),'account_holder_verified':True,'authorized_at':now().isoformat()}
                self._audit(s,user_id,'provider-adapter','SYSTEM','PROFILE_PROVIDER_AUTHORIZATION_CONSUMED',purpose='BUILD_PERSONAL_TRAVEL_VAULT',metadata={'provider':provider,'connection_id':connection_id,'evidence_hash':h(evidence)})
        if expired:raise ValueError('PROFILE_PROVIDER_STATE_EXPIRED')
        imported=self.create_import(user_id,{'source_type':'OFFICIAL_API','source_provider':provider,
            'source_reference':connection_id,'source_fingerprint':h([connection_id,'official-import']),
            'items':b.get('items') or [],'metadata':{'provider_connection_id':connection_id,
            'account_holder_authorized':True}},trusted_source=True)
        with mutation_session() as s:
            job=s.get(ProfileImportJobRow,connection_id);job.status='PREVIEW_READY';job.updated_at=now()
            job.metadata_json={**(job.metadata_json or {}),'import_job_id':imported['import_job_id']}
        return self._connection_view(job)|{'preview':imported}

    def upload_provider_export(self,user_id,connection_id,b):
        self._reject_provider_credentials(b)
        if b.get('account_holder_confirmed') is not True:raise ValueError('ACCOUNT_HOLDER_CONFIRMATION_REQUIRED')
        with mutation_session() as s:
            connection=s.get(ProfileImportJobRow,connection_id)
            if not connection or connection.user_id!=user_id or not (connection.metadata_json or {}).get('connection_intent'):raise ValueError('PROFILE_PROVIDER_CONNECTION_NOT_FOUND')
            if connection.status!='AWAITING_USER_UPLOAD':raise ValueError('PROFILE_PROVIDER_UPLOAD_ALREADY_RECEIVED')
            provider=connection.source_provider
            claimed=s.execute(update(ProfileImportJobRow).where(ProfileImportJobRow.import_job_id==connection_id,
                ProfileImportJobRow.user_id==user_id,ProfileImportJobRow.status=='AWAITING_USER_UPLOAD').values(status='UPLOAD_CONSUMED',updated_at=now())).rowcount
            if claimed!=1:raise ValueError('PROFILE_PROVIDER_UPLOAD_ALREADY_RECEIVED')
        imported=self.create_import(user_id,{'source_type':'USER_DATA_PACKAGE','source_provider':provider,
            'source_reference':connection_id,'source_fingerprint':h([connection_id,'user-export']),
            'items':b.get('items') or [],'metadata':{'provider_connection_id':connection_id,
            'account_holder_confirmed':True,'upload_kind':str(b.get('upload_kind') or 'DATA_EXPORT').upper()}})
        with mutation_session() as s:
            connection=s.get(ProfileImportJobRow,connection_id)
            if connection.status!='UPLOAD_CONSUMED':raise ValueError('PROFILE_PROVIDER_UPLOAD_ALREADY_RECEIVED')
            connection.status='PREVIEW_READY';connection.updated_at=now()
            connection.metadata_json={**(connection.metadata_json or {}),'state_hash':None,'import_job_id':imported['import_job_id']}
            self._audit(s,user_id,user_id,'CONSUMER','PROFILE_PROVIDER_EXPORT_UPLOADED',purpose='BUILD_PERSONAL_TRAVEL_VAULT',metadata={'provider':provider,'connection_id':connection_id,'import_job_id':imported['import_job_id']})
        return self._connection_view(connection)|{'preview':imported}

    def disconnect_provider_connection(self,user_id,connection_id,delete_values=False):
        with SessionLocal() as s:
            connection=s.get(ProfileImportJobRow,connection_id)
            if not connection or connection.user_id!=user_id or not (connection.metadata_json or {}).get('connection_intent'):raise ValueError('PROFILE_PROVIDER_CONNECTION_NOT_FOUND')
            metadata=connection.metadata_json or {};import_job_id=metadata.get('import_job_id')
            imported=s.get(ProfileImportJobRow,import_job_id) if import_job_id else None
            fingerprint=imported.source_fingerprint if imported else None
        deleted=None
        if delete_values and fingerprint:
            deleted=self.delete_source(user_id,fingerprint)
        with mutation_session() as s:
            connection=s.get(ProfileImportJobRow,connection_id)
            metadata=connection.metadata_json or {}
            connection.status='DELETED' if delete_values else 'DISCONNECTED';connection.updated_at=now();connection.completed_at=now()
            connection.metadata_json={**metadata,'state_hash':None,'provider_account_subject_hash':None,
                'authorization_evidence_hash':None,'authorization_evidence_reference':None,
                'disconnected_at':now().isoformat(),'values_deleted':bool(delete_values)}
            self._audit(s,user_id,user_id,'CONSUMER','PROFILE_PROVIDER_CONNECTION_DELETED' if delete_values else 'PROFILE_PROVIDER_CONNECTION_DISCONNECTED',purpose='USER_DELETE',metadata={'provider':connection.source_provider,'connection_id':connection_id,'values_deleted':bool(delete_values)})
        return self._connection_view(connection)|{'imported_values':deleted}

    def admin_imports(self,limit=100,status=None):
        with SessionLocal() as s:
            q=select(ProfileImportJobRow)
            if status:q=q.where(ProfileImportJobRow.status==status)
            rows=s.scalars(q.order_by(ProfileImportJobRow.created_at.desc()).limit(limit)).all()
            return [{'import_job_id':x.import_job_id,'user_id':x.user_id,'source_type':x.source_type,'source_provider':x.source_provider,'status':x.status,'item_count':x.item_count,'accepted_count':x.accepted_count,'rejected_count':x.rejected_count,'conflict_count':x.conflict_count,'created_at':x.created_at.isoformat()} for x in rows]

    def admin_releases(self,limit=100,decision=None):
        with SessionLocal() as s:
            q=select(ProfileDataReleaseAuditRow)
            if decision:q=q.where(ProfileDataReleaseAuditRow.decision==decision)
            rows=s.scalars(q.order_by(ProfileDataReleaseAuditRow.created_at.desc()).limit(limit)).all()
            return [{'release_id':x.release_id,'user_id':x.user_id,'traveler_id':x.traveler_id,'requester_type':x.requester_type,'requester_id':x.requester_id,'vertical':x.vertical,'purpose':x.purpose,'destination':x.destination,'booking_id':x.booking_id,'requested_fields':x.requested_fields_json,'released_fields':x.released_fields_json,'consent_id':x.consent_id,'decision':x.decision,'reason_code':x.reason_code,'created_at':x.created_at.isoformat()} for x in rows]

personal_travel_vault_service=PersonalTravelVaultService()
