from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
    TravelerProfileRow, ProfileImportJobRow, ProfileImportItemRow, ProfileFactRow,
    ProfileConsentRow, ProfileTravelerPermissionRow, ProfileDataReleaseAuditRow,
    ProfileAccessAuditRow, ConsumerProfileRow,
)
from go_hotel.security.crypto import encrypt_secret, decrypt_secret
from go_hotel.domain.models import new_id

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

def trust_for(source_type,user_confirmed,verification_method=None):
    if verification_method in {'NFC','MRZ','GOVERNMENT_ID_VERIFICATION'}:return ('L4_VERIFIED_DOCUMENT','VERIFIED')
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

class PersonalTravelVaultService:
    def bootstrap_vault(self,user_id,b=None):
        b=b or {}
        with SessionLocal() as s:
            profile=s.get(ConsumerProfileRow,user_id)
            if not profile: raise ValueError('CONSUMER_PROFILE_NOT_FOUND')
            traveler=s.scalar(select(TravelerProfileRow).where(TravelerProfileRow.user_id==user_id,TravelerProfileRow.relationship_type=='SELF',TravelerProfileRow.status=='ACTIVE').order_by(TravelerProfileRow.is_primary.desc(),TravelerProfileRow.created_at))
            created=False
            if not traveler:
                full_name=str(b.get('full_name') or profile.display_name or '').strip()
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
        provider=(b.get('source_provider') or '').strip() or None
        source_ref=b.get('source_reference')
        fingerprint=b.get('source_fingerprint') or h({'type':source_type,'provider':provider,'ref':source_ref,'content':b.get('content_hash') or b.get('items',[])})
        content_hash=b.get('content_hash') or h(b.get('items',[]))
        with SessionLocal() as s:
            existing=s.scalar(select(ProfileImportJobRow).where(ProfileImportJobRow.user_id==user_id,ProfileImportJobRow.source_fingerprint==fingerprint,ProfileImportJobRow.content_hash==content_hash).order_by(ProfileImportJobRow.created_at.desc()))
            if existing:return self.get_import(user_id,existing.import_job_id)|{'idempotent_replay':True}
            t=now();job=ProfileImportJobRow(import_job_id=new_id('pij'),user_id=user_id,source_type=source_type,source_provider=provider,source_reference=source_ref,source_fingerprint=fingerprint,content_hash=content_hash,status='RECEIVED',consent_id=b.get('consent_id'),item_count=0,accepted_count=0,rejected_count=0,conflict_count=0,metadata_json=b.get('metadata') or {},created_at=t,updated_at=t,completed_at=None);s.add(job)
            for raw in b.get('items') or []:
                et=(raw.get('entity_type') or 'PROFILE_FACT').upper();ft=(raw.get('field_type') or '').upper() or None
                value=raw.get('value');sens=bool(raw.get('sensitive',ft in SENSITIVE_FIELDS));conf=max(0,min(10000,int(raw.get('confidence_bps',7000))))
                status='NEEDS_REVIEW' if (sens or conf<9500 or source_type in {'SCREENSHOT_AI','IMAGE_AI','PDF_AI','TEXT_IMPORT','SHARE_TO_GO'}) else 'EXTRACTED'
                item=ProfileImportItemRow(import_item_id=new_id('pii'),import_job_id=job.import_job_id,user_id=user_id,entity_type=et,traveler_ref=raw.get('traveler_ref'),field_type=ft,candidate_value_ciphertext=encrypt_secret(json.dumps(value,ensure_ascii=False)) if value is not None else None,normalized_value_hash=h(value) if value is not None else None,preview_masked=mask(value,sens),sensitive=sens,confidence_bps=conf,source_payload_json={k:v for k,v in raw.items() if k not in {'value'}},status=status,resolution_traveler_id=None,conflict_fact_id=None,review_action=None,created_at=t,updated_at=t);s.add(item);job.item_count+=1
            job.status='EXTRACTED' if job.item_count else 'RECEIVED';job.updated_at=t;self._audit(s,user_id,user_id,'CONSUMER','PROFILE_IMPORT_RECEIVED',purpose='BUILD_PERSONAL_TRAVEL_VAULT',metadata={'import_job_id':job.import_job_id,'source_type':source_type,'item_count':job.item_count});s.commit();return self.get_import(user_id,job.import_job_id)

    def _item_value(self,item):
        if not item.candidate_value_ciphertext:return None
        return json.loads(decrypt_secret(item.candidate_value_ciphertext))

    def get_import(self,user_id,job_id):
        with SessionLocal() as s:
            j=s.get(ProfileImportJobRow,job_id)
            if not j or j.user_id!=user_id:raise ValueError('PROFILE_IMPORT_NOT_FOUND')
            items=s.scalars(select(ProfileImportItemRow).where(ProfileImportItemRow.import_job_id==job_id).order_by(ProfileImportItemRow.created_at)).all()
            return {'import_job_id':j.import_job_id,'source_type':j.source_type,'source_provider':j.source_provider,'source_reference':j.source_reference,'source_fingerprint':j.source_fingerprint,'content_hash':j.content_hash,'status':j.status,'item_count':j.item_count,'accepted_count':j.accepted_count,'rejected_count':j.rejected_count,'conflict_count':j.conflict_count,'created_at':j.created_at.isoformat(),'completed_at':j.completed_at.isoformat() if j.completed_at else None,'items':[{'import_item_id':x.import_item_id,'entity_type':x.entity_type,'traveler_ref':x.traveler_ref,'field_type':x.field_type,'preview_masked':x.preview_masked,'sensitive':x.sensitive,'confidence_bps':x.confidence_bps,'status':x.status,'resolution_traveler_id':x.resolution_traveler_id,'conflict_fact_id':x.conflict_fact_id,'review_action':x.review_action} for x in items]}

    def review_item(self,user_id,job_id,item_id,action):
        action=action.upper()
        if action not in {'ACCEPT','REJECT','KEEP_BOTH','USE_EXISTING','REPLACE_EXISTING'}:raise ValueError('INVALID_PROFILE_REVIEW_ACTION')
        with SessionLocal() as s:
            j=s.get(ProfileImportJobRow,job_id);i=s.get(ProfileImportItemRow,item_id)
            if not j or j.user_id!=user_id or not i or i.import_job_id!=job_id:raise ValueError('PROFILE_IMPORT_ITEM_NOT_FOUND')
            i.review_action=action;i.status='REJECTED' if action=='REJECT' else 'ACCEPTED';i.updated_at=now();j.updated_at=now();s.commit()
        return self.get_import(user_id,job_id)

    def _resolve_traveler(self,s,user_id,traveler_payload,source_type):
        full_name=(traveler_payload.get('full_name') or traveler_payload.get('name') or '').strip()
        if not full_name:raise ValueError('TRAVELER_NAME_REQUIRED')
        dob=traveler_payload.get('date_of_birth');nat=traveler_payload.get('nationality');doc=traveler_payload.get('document_number')
        if doc:
            doc_hash=h(doc)
            facts=s.scalars(select(ProfileFactRow).where(ProfileFactRow.user_id==user_id,ProfileFactRow.normalized_value_hash==doc_hash,ProfileFactRow.field_type.in_(['PASSPORT_NUMBER','ID_CARD_NUMBER','DRIVER_LICENSE_NUMBER']),ProfileFactRow.status=='ACTIVE')).all()
            if facts:
                return s.get(TravelerProfileRow,facts[0].traveler_id),False
        candidates=s.scalars(select(TravelerProfileRow).where(TravelerProfileRow.user_id==user_id,TravelerProfileRow.status=='ACTIVE')).all()
        key=h([full_name,dob or '',nat or ''])
        for r in candidates:
            if h([r.full_name,r.date_of_birth or '',r.nationality or ''])==key:return r,False
        rel=(traveler_payload.get('relationship_type') or ('SELF' if not candidates else 'FREQUENT_TRAVELER')).upper()
        if rel not in ALLOWED_RELATIONSHIPS:rel='OTHER'
        t=now();r=TravelerProfileRow(traveler_id=new_id('trav'),user_id=user_id,full_name=full_name,date_of_birth=dob,nationality=nat,document_type=traveler_payload.get('document_type') if source_type=='MANUAL' else None,document_ciphertext=encrypt_secret(doc) if (doc and source_type=='MANUAL') else None,relationship_type=rel,booking_permission=bool(traveler_payload.get('booking_permission',True)),guardian_traveler_id=traveler_payload.get('guardian_traveler_id'),guardian_consent_status=traveler_payload.get('guardian_consent_status'),source_type=source_type,is_primary=bool(traveler_payload.get('is_primary',rel=='SELF' and not candidates)),status='ACTIVE',created_at=t,updated_at=t);s.add(r);s.flush()
        for ptype in ALLOWED_PERMISSIONS:
            allowed=True if rel=='SELF' else ptype in {'VIEW','USE_FOR_BOOKING'}
            s.add(ProfileTravelerPermissionRow(permission_id=new_id('ptp'),user_id=user_id,traveler_id=r.traveler_id,permission_type=ptype,allowed=allowed,source='IMPORT_DEFAULT',created_at=t,updated_at=t))
        return r,True

    def commit_import(self,user_id,job_id):
        with SessionLocal() as s:
            j=s.get(ProfileImportJobRow,job_id)
            if not j or j.user_id!=user_id:raise ValueError('PROFILE_IMPORT_NOT_FOUND')
            if j.status=='COMMITTED':return self.get_import(user_id,job_id)|{'idempotent_replay':True}
            items=s.scalars(select(ProfileImportItemRow).where(ProfileImportItemRow.import_job_id==job_id).order_by(ProfileImportItemRow.created_at)).all()
            travelers={}; accepted=rejected=conflicts=0
            # traveler declarations first
            for i in items:
                if i.entity_type!='TRAVELER':continue
                if i.status=='REJECTED':rejected+=1;continue
                if i.status=='NEEDS_REVIEW' and i.review_action is None:continue
                payload=self._item_value(i) or {}
                r,_=self._resolve_traveler(s,user_id,payload,j.source_type);i.resolution_traveler_id=r.traveler_id;i.status='COMMITTED';i.updated_at=now();travelers[i.traveler_ref or i.import_item_id]=r.traveler_id;accepted+=1
            for i in items:
                if i.entity_type=='TRAVELER':continue
                if i.status=='REJECTED':rejected+=1;continue
                if i.status=='NEEDS_REVIEW' and i.review_action is None:continue
                value=self._item_value(i);ft=(i.field_type or '').upper()
                tid=i.resolution_traveler_id or travelers.get(i.traveler_ref or '')
                if not tid:
                    prim=s.scalar(select(TravelerProfileRow).where(TravelerProfileRow.user_id==user_id,TravelerProfileRow.status=='ACTIVE').order_by(TravelerProfileRow.is_primary.desc(),TravelerProfileRow.created_at))
                    if not prim:
                        i.status='NEEDS_REVIEW';i.updated_at=now();continue
                    tid=prim.traveler_id
                existing=s.scalars(select(ProfileFactRow).where(ProfileFactRow.user_id==user_id,ProfileFactRow.traveler_id==tid,ProfileFactRow.field_type==ft,ProfileFactRow.status=='ACTIVE')).all()
                exact=next((x for x in existing if x.normalized_value_hash==i.normalized_value_hash),None)
                if exact:
                    i.resolution_traveler_id=tid;i.status='COMMITTED';accepted+=1;continue
                conflict=next(iter(existing),None)
                if conflict and ft not in MULTI_VALUE_FIELDS and i.review_action not in {'REPLACE_EXISTING','USE_EXISTING'}:
                    i.status='CONFLICT';i.conflict_fact_id=conflict.fact_id;i.resolution_traveler_id=tid;conflicts+=1;continue
                if conflict and i.review_action=='USE_EXISTING':
                    i.status='COMMITTED';i.resolution_traveler_id=tid;accepted+=1;continue
                tlevel,vstatus=trust_for(j.source_type,True if i.review_action in {'ACCEPT','KEEP_BOTH','REPLACE_EXISTING'} else False,i.source_payload_json.get('verification_method'))
                # AI-imported sensitive facts never become VERIFIED solely from extraction/review.
                if j.source_type in {'SCREENSHOT_AI','IMAGE_AI','PDF_AI','TEXT_IMPORT','SHARE_TO_GO'} and i.sensitive:
                    tlevel='L1_USER_CONFIRMED' if i.review_action else 'L0_EXTRACTED';vstatus='USER_CONFIRMED' if i.review_action else 'CANDIDATE'
                f=ProfileFactRow(fact_id=new_id('pff'),user_id=user_id,traveler_id=tid,field_type=ft,value_ciphertext=encrypt_secret(json.dumps(value,ensure_ascii=False)),normalized_value_hash=i.normalized_value_hash or h(value),sensitive=i.sensitive,source_type=j.source_type,source_provider=j.source_provider,source_reference=j.source_reference,source_fingerprint=j.source_fingerprint,confidence_bps=i.confidence_bps,user_confirmed=bool(i.review_action),trust_level=tlevel,verification_status=vstatus,verification_method=i.source_payload_json.get('verification_method'),valid_from=i.source_payload_json.get('valid_from'),valid_until=i.source_payload_json.get('valid_until'),superseded_by=None,status='ACTIVE',created_at=now(),updated_at=now());s.add(f);s.flush()
                if conflict and i.review_action=='REPLACE_EXISTING':conflict.status='SUPERSEDED';conflict.superseded_by=f.fact_id;conflict.updated_at=now()
                i.resolution_traveler_id=tid;i.status='COMMITTED';i.updated_at=now();accepted+=1
            j.accepted_count=accepted;j.rejected_count=rejected;j.conflict_count=conflicts;j.status='CONFLICT' if conflicts else ('NEEDS_REVIEW' if any(x.status=='NEEDS_REVIEW' for x in items) else 'COMMITTED');j.updated_at=now();j.completed_at=now() if j.status=='COMMITTED' else None
            self._audit(s,user_id,user_id,'CONSUMER','PROFILE_IMPORT_COMMIT',purpose='BUILD_PERSONAL_TRAVEL_VAULT',metadata={'import_job_id':job_id,'accepted':accepted,'rejected':rejected,'conflicts':conflicts});s.commit()
        return self.get_import(user_id,job_id)

    def grant_consent(self,user_id,b):
        t=now();cid=new_id('pcn')
        with SessionLocal() as s:
            tid=b.get('traveler_id')
            if tid:
                tr=s.get(TravelerProfileRow,tid)
                if not tr or tr.user_id!=user_id:raise ValueError('TRAVELER_NOT_FOUND')
            c=ProfileConsentRow(consent_id=cid,user_id=user_id,traveler_id=tid,consent_type=(b.get('consent_type') or 'SENSITIVE_DATA_RELEASE').upper(),purpose=b.get('purpose') or 'TRAVEL_BOOKING',scope_json=[x.upper() for x in (b.get('scope') or [])],status='ACTIVE',granted_at=t,expires_at=dt(b.get('expires_at')),revoked_at=None);s.add(c);self._audit(s,user_id,user_id,'CONSUMER','PROFILE_CONSENT_GRANTED',tid,b.get('purpose'),b.get('scope'),{'consent_id':cid});s.commit();return {'consent_id':cid,'status':'ACTIVE','traveler_id':tid,'purpose':c.purpose,'scope':c.scope_json,'expires_at':c.expires_at.isoformat() if c.expires_at else None}

    def revoke_consent(self,user_id,consent_id):
        with SessionLocal() as s:
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
        with SessionLocal() as s:
            tr=s.get(TravelerProfileRow,tid)
            if not tr or tr.user_id!=user_id or tr.status!='ACTIVE':raise ValueError('TRAVELER_NOT_FOUND')
            facts=s.scalars(select(ProfileFactRow).where(ProfileFactRow.user_id==user_id,ProfileFactRow.traveler_id==tid,ProfileFactRow.field_type.in_(fields),ProfileFactRow.status=='ACTIVE')).all()
            by_field={}
            rank={'L4_VERIFIED_DOCUMENT':4,'L3_OFFICIAL_PROVIDER':3,'L2_STRUCTURED_SOURCE':2,'L1_USER_CONFIRMED':1,'L0_EXTRACTED':0}
            for f in facts:
                cur=by_field.get(f.field_type)
                if not cur or rank.get(f.trust_level,0)>rank.get(cur.trust_level,0):by_field[f.field_type]=f
            core_values={}
            if 'LEGAL_NAME' in fields and tr.full_name:core_values['LEGAL_NAME']=tr.full_name
            if 'DATE_OF_BIRTH' in fields and tr.date_of_birth:core_values['DATE_OF_BIRTH']=tr.date_of_birth
            if 'NATIONALITY' in fields and tr.nationality:core_values['NATIONALITY']=tr.nationality
            sensitive=[f.field_type for f in by_field.values() if f.sensitive]
            if 'DATE_OF_BIRTH' in core_values:sensitive.append('DATE_OF_BIRTH')
            permissions={x.permission_type:x.allowed for x in s.scalars(select(ProfileTravelerPermissionRow).where(ProfileTravelerPermissionRow.user_id==user_id,ProfileTravelerPermissionRow.traveler_id==tid)).all()}
            if tr.relationship_type!='SELF' and not permissions.get('USE_FOR_BOOKING',False):
                rid=new_id('pdr');s.add(ProfileDataReleaseAuditRow(release_id=rid,user_id=user_id,traveler_id=tid,requester_type=requester_type,requester_id=requester_id,vertical=vertical,purpose=purpose,destination=destination,booking_id=booking_id,requested_fields_json=fields,released_fields_json=[],consent_id=None,decision='DENY',reason_code='TRAVELER_BOOKING_PERMISSION_REQUIRED',created_at=now()));s.commit();raise ValueError('TRAVELER_BOOKING_PERMISSION_REQUIRED')
            if sensitive and tr.relationship_type!='SELF' and not permissions.get('SENSITIVE_DATA',False):
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
                out.append({'traveler_id':tr.traveler_id,'full_name':tr.full_name,'relationship_type':tr.relationship_type,'booking_permission':tr.booking_permission,'guardian_traveler_id':tr.guardian_traveler_id,'guardian_consent_status':tr.guardian_consent_status,'is_primary':tr.is_primary,'source_type':tr.source_type,'facts':[{'fact_id':f.fact_id,'field_type':f.field_type,'value_masked':mask(json.loads(decrypt_secret(f.value_ciphertext)),f.sensitive),'sensitive':f.sensitive,'source_type':f.source_type,'source_provider':f.source_provider,'confidence_bps':f.confidence_bps,'user_confirmed':f.user_confirmed,'trust_level':f.trust_level,'verification_status':f.verification_status,'valid_until':f.valid_until} for f in facts]})
            self._audit(s,user_id,actor_id or user_id,actor_type,'PROFILE_VAULT_VIEWED',purpose='USER_PROFILE_MANAGEMENT',fields=[]);s.commit();return {'travelers':out,'traveler_count':len(out),'secure_vault_boundary':'SENSITIVE_FACT_VALUES_MASKED','ai_full_vault_access':False}

    def set_permission(self,user_id,traveler_id,permission_type,allowed):
        permission_type=permission_type.upper()
        if permission_type not in ALLOWED_PERMISSIONS:raise ValueError('INVALID_TRAVELER_PERMISSION')
        with SessionLocal() as s:
            tr=s.get(TravelerProfileRow,traveler_id)
            if not tr or tr.user_id!=user_id:raise ValueError('TRAVELER_NOT_FOUND')
            p=s.scalar(select(ProfileTravelerPermissionRow).where(ProfileTravelerPermissionRow.user_id==user_id,ProfileTravelerPermissionRow.traveler_id==traveler_id,ProfileTravelerPermissionRow.permission_type==permission_type));t=now()
            if p:p.allowed=bool(allowed);p.updated_at=t
            else:p=ProfileTravelerPermissionRow(permission_id=new_id('ptp'),user_id=user_id,traveler_id=traveler_id,permission_type=permission_type,allowed=bool(allowed),source='USER',created_at=t,updated_at=t);s.add(p)
            self._audit(s,user_id,user_id,'CONSUMER','TRAVELER_PERMISSION_UPDATED',traveler_id,'TRAVELER_MANAGEMENT',[permission_type],{'allowed':bool(allowed)});s.commit();return {'traveler_id':traveler_id,'permission_type':permission_type,'allowed':bool(allowed)}

    def delete_fact(self,user_id,fact_id):
        with SessionLocal() as s:
            f=s.get(ProfileFactRow,fact_id)
            if not f or f.user_id!=user_id:raise ValueError('PROFILE_FACT_NOT_FOUND')
            f.status='DELETED';f.updated_at=now();self._audit(s,user_id,user_id,'CONSUMER','PROFILE_FACT_DELETED',f.traveler_id,'USER_DELETE',[f.field_type],{'fact_id':fact_id});s.commit();return {'fact_id':fact_id,'status':'DELETED'}

    def delete_source(self,user_id,source_fingerprint):
        with SessionLocal() as s:
            rows=s.scalars(select(ProfileFactRow).where(ProfileFactRow.user_id==user_id,ProfileFactRow.source_fingerprint==source_fingerprint,ProfileFactRow.status=='ACTIVE')).all()
            for f in rows:f.status='DELETED';f.updated_at=now()
            self._audit(s,user_id,user_id,'CONSUMER','PROFILE_SOURCE_DELETED',purpose='USER_DELETE',metadata={'source_fingerprint':source_fingerprint,'deleted_facts':len(rows)});s.commit();return {'source_fingerprint':source_fingerprint,'deleted_facts':len(rows)}

    def completeness(self,user_id):
        with SessionLocal() as s:
            trs=s.scalars(select(TravelerProfileRow).where(TravelerProfileRow.user_id==user_id,TravelerProfileRow.status=='ACTIVE')).all();primary=next((x for x in trs if x.is_primary),trs[0] if trs else None)
            if not primary:return {'profile_ready':False,'capabilities':{'DOMESTIC_FLIGHT_READY':False,'INTERNATIONAL_FLIGHT_READY':False,'HOTEL_READY':False,'RAIL_READY':False,'CAR_RENTAL_READY':False,'INVOICE_READY':False},'missing':['PRIMARY_TRAVELER']}
            facts=s.scalars(select(ProfileFactRow).where(ProfileFactRow.user_id==user_id,ProfileFactRow.traveler_id==primary.traveler_id,ProfileFactRow.status=='ACTIVE')).all();have={x.field_type for x in facts}
            base_name=bool(primary.full_name);dob=bool(primary.date_of_birth) or 'DATE_OF_BIRTH' in have;nat=bool(primary.nationality) or 'NATIONALITY' in have;passport='PASSPORT_NUMBER' in have;mobile='MOBILE' in have;email='EMAIL' in have;invoice=bool({'PERSONAL_INVOICE','COMPANY_INVOICE'} & have);license_='DRIVER_LICENSE_NUMBER' in have
            caps={'DOMESTIC_FLIGHT_READY':base_name and dob,'INTERNATIONAL_FLIGHT_READY':base_name and dob and nat and passport,'HOTEL_READY':base_name and (mobile or email),'RAIL_READY':base_name and dob,'CAR_RENTAL_READY':base_name and license_,'INVOICE_READY':invoice}
            missing=[]
            if not passport:missing.append('PASSPORT_NUMBER')
            if not dob:missing.append('DATE_OF_BIRTH')
            if not mobile and not email:missing.append('MOBILE_OR_EMAIL')
            return {'profile_ready':any(caps.values()),'traveler_id':primary.traveler_id,'capabilities':caps,'missing':missing,'ready_count':sum(1 for x in caps.values() if x),'capability_count':len(caps)}

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
