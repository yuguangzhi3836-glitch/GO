"""Owner-managed profile revisions and import controls; no provider credentials."""
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
from sqlalchemy import select, text
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (TravelerProfileRow, ProfileFactRow, ProfileImportJobRow,
    ProfileImportItemRow, ProfileTravelerPermissionRow)
from go_hotel.domain.models import new_id
from go_hotel.security.crypto import encrypt_secret, decrypt_secret

@contextmanager
def mutation_session():
    with SessionLocal() as session:
        if session.bind.dialect.name == 'sqlite':session.execute(text('BEGIN IMMEDIATE'))
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise

def revision(row):
    fields=('traveler_id','full_name','nationality','date_of_birth','relationship_type',
        'booking_permission','is_primary','fact_id','normalized_value_hash','status','updated_at',
        'import_item_id','resolution_traveler_id','review_action','conflict_fact_id')
    return hashlib.sha256(json.dumps({k:getattr(row,k) for k in fields if hasattr(row,k)},
        sort_keys=True,default=str).encode()).hexdigest()

def permission(session, user, traveler, kind):
    row=session.scalar(select(ProfileTravelerPermissionRow).where(
        ProfileTravelerPermissionRow.user_id==user,ProfileTravelerPermissionRow.traveler_id==traveler.traveler_id,
        ProfileTravelerPermissionRow.permission_type==kind))
    return row.allowed if row is not None else traveler.relationship_type=='SELF'

def owned_traveler(session,user,tid,edit=False):
    tr=session.get(TravelerProfileRow,tid,with_for_update=True)
    if not tr or tr.user_id!=user or tr.status!='ACTIVE':raise ValueError('TRAVELER_NOT_FOUND')
    if edit and not permission(session,user,tr,'EDIT'):raise ValueError('TRAVELER_EDIT_PERMISSION_REQUIRED')
    return tr

def confirmed_revision(row, body):
    if body.get('confirmed') is not True:raise ValueError('PROFILE_EDIT_CONFIRMATION_REQUIRED')
    if not body.get('expected_revision'):raise ValueError('PROFILE_REVISION_REQUIRED')
    if body['expected_revision']!=revision(row):raise ValueError('PROFILE_CHANGED_RELOAD_REQUIRED')

def validate_value(field,value):
    if value is None or value=='' or len(json.dumps(value,ensure_ascii=False))>16000:
        raise ValueError('PROFILE_VALUE_INVALID')
    if field=='DATE_OF_BIRTH':
        try:parsed=date.fromisoformat(value)
        except (ValueError,TypeError):raise ValueError('PROFILE_BIRTH_DATE_INVALID') from None
        if not date(1900,1,1)<=parsed<=date.today():raise ValueError('PROFILE_BIRTH_DATE_INVALID')
    if field in {'LEGAL_NAME','MOBILE','EMAIL','NATIONALITY','PASSPORT_NUMBER','ID_CARD_NUMBER','DRIVER_LICENSE_NUMBER'}:
        if not isinstance(value,str) or not value.strip() or len(value)>160:raise ValueError('PROFILE_VALUE_INVALID')
    if field=='NATIONALITY' and (not isinstance(value,str) or len(value)!=3 or not value.isalpha()):
        raise ValueError('PROFILE_NATIONALITY_INVALID')

class VaultManagementMixin:
    def _manual_fact(self,session,user,traveler,field,value,previous=None,valid_from=None,valid_until=None):
        from go_hotel.services.personal_travel_vault import SENSITIVE_FIELDS,h,now,dt
        validate_value(field,value)
        try:
            start,end=dt(valid_from),dt(valid_until)
            if start and start.tzinfo is None:start=start.replace(tzinfo=timezone.utc)
            if end and end.tzinfo is None:end=end.replace(tzinfo=timezone.utc)
            if start and end and start>end:raise ValueError()
        except (ValueError,TypeError):raise ValueError('PROFILE_VALIDITY_RANGE_INVALID') from None
        fid=new_id('pff');t=now()
        fact=ProfileFactRow(fact_id=fid,user_id=user,traveler_id=traveler.traveler_id,field_type=field,
            value_ciphertext=encrypt_secret(json.dumps(value,ensure_ascii=False)),normalized_value_hash=h(value),
            sensitive=field in SENSITIVE_FIELDS or bool(previous and previous.sensitive),source_type='MANUAL',
            source_provider='USER',source_reference=None,source_fingerprint='manual-edit:'+fid,confidence_bps=10000,
            user_confirmed=True,trust_level='L1_USER_CONFIRMED',verification_status='USER_CONFIRMED',
            verification_method='USER_EDIT',valid_from=valid_from,valid_until=valid_until,superseded_by=None,
            status='ACTIVE',created_at=t,updated_at=t)
        session.add(fact);session.flush()
        if previous:previous.status='SUPERSEDED';previous.superseded_by=fid;previous.updated_at=t
        return fact

    def edit_traveler(self,user,tid,body):
        from go_hotel.services.personal_travel_vault import now
        allowed={'full_name':'LEGAL_NAME','nationality':'NATIONALITY','date_of_birth':'DATE_OF_BIRTH'}
        if set(body)-set(allowed)-{'confirmed','expected_revision'}:raise ValueError('PROFILE_EDIT_FIELD_NOT_ALLOWED')
        with mutation_session() as s:
            tr=owned_traveler(s,user,tid,edit=True);confirmed_revision(tr,body);changed=[]
            if 'date_of_birth' in body and not permission(s,user,tr,'SENSITIVE_DATA'):
                raise ValueError('TRAVELER_SENSITIVE_PERMISSION_REQUIRED')
            for attr,field in allowed.items():
                if attr not in body:continue
                value=body[attr]
                if attr=='full_name' or value is not None:validate_value(field,value)
                if attr=='nationality' and value:value=value.upper()
                if getattr(tr,attr)==value:continue
                old=s.scalars(select(ProfileFactRow).where(ProfileFactRow.user_id==user,
                    ProfileFactRow.traveler_id==tid,ProfileFactRow.field_type==field,ProfileFactRow.status=='ACTIVE')).all()
                if value is not None:
                    fact=self._manual_fact(s,user,tr,field,value)
                    for f in old:f.status='SUPERSEDED';f.superseded_by=fact.fact_id;f.updated_at=now()
                else:
                    from go_hotel.services.personal_travel_vault import h
                    previous_hash=h(getattr(tr,attr))
                    history=s.scalars(select(ProfileFactRow).where(ProfileFactRow.user_id==user,
                        ProfileFactRow.traveler_id==tid,ProfileFactRow.field_type==field,ProfileFactRow.status!='DELETED')).all()
                    self._erase_fact_rows(s,user,history)
                    for item in s.scalars(select(ProfileImportItemRow).where(ProfileImportItemRow.user_id==user,
                        ProfileImportItemRow.resolution_traveler_id==tid,ProfileImportItemRow.entity_type=='TRAVELER')).all():
                        payload=self._item_value(item) or {}
                        if attr in payload and h(payload[attr])==previous_hash:
                            payload.pop(attr);item.candidate_value_ciphertext=encrypt_secret(json.dumps(payload,ensure_ascii=False))
                            item.preview_masked='[REDACTED AFTER DELETE]';item.normalized_value_hash=h(payload)
                setattr(tr,attr,value);changed.append(field)
            tr.updated_at=now()
            self._audit(s,user,user,'CONSUMER','PROFILE_TRAVELER_EDITED',tid,'USER_PROFILE_MANAGEMENT',changed)
        return {'traveler_id':tid,'status':'UPDATED','fields':changed}

    def edit_fact(self,user,fid,body):
        from go_hotel.services.personal_travel_vault import SENSITIVE_FIELDS, now
        if set(body)-{'value','valid_from','valid_until','confirmed','expected_revision'}:raise ValueError('PROFILE_EDIT_FIELD_NOT_ALLOWED')
        with mutation_session() as s:
            old=s.get(ProfileFactRow,fid,with_for_update=True)
            if not old or old.user_id!=user:raise ValueError('PROFILE_FACT_NOT_FOUND')
            if old.status!='ACTIVE':raise ValueError('PROFILE_CHANGED_RELOAD_REQUIRED')
            tr=owned_traveler(s,user,old.traveler_id,edit=True);confirmed_revision(old,body)
            if (old.sensitive or old.field_type in SENSITIVE_FIELDS) and not permission(s,user,tr,'SENSITIVE_DATA'):
                raise ValueError('TRAVELER_SENSITIVE_PERMISSION_REQUIRED')
            value=body.get('value')
            if old.field_type=='NATIONALITY' and isinstance(value,str):value=value.upper()
            new=self._manual_fact(s,user,tr,old.field_type,value,old,body.get('valid_from',old.valid_from),body.get('valid_until',old.valid_until))
            attr={'LEGAL_NAME':'full_name','DATE_OF_BIRTH':'date_of_birth','NATIONALITY':'nationality'}.get(old.field_type)
            if attr:setattr(tr,attr,value);tr.updated_at=now()
            self._audit(s,user,user,'CONSUMER','PROFILE_FACT_EDITED',tr.traveler_id,'USER_PROFILE_MANAGEMENT',[old.field_type],{'previous_fact_id':fid,'fact_id':new.fact_id})
            return {'fact_id':new.fact_id,'superseded_fact_id':fid,'status':'UPDATED','trust_level':'L1_USER_CONFIRMED'}

    def import_list(self,user,limit=50):
        with SessionLocal() as s:
            rows=s.scalars(select(ProfileImportJobRow).where(ProfileImportJobRow.user_id==user)
                .order_by(ProfileImportJobRow.created_at.desc()).limit(max(1,min(limit,100)))).all()
            return {'items':[{'import_job_id':r.import_job_id,'source_provider':r.source_provider,
                'source_type':r.source_type,'status':r.status,'conflict_count':r.conflict_count,
                'source_fingerprint':r.source_fingerprint,'item_count':r.item_count,
                'source_disconnected':bool((r.metadata_json or {}).get('source_disconnected'))} for r in rows]}

    def source_list(self,user):
        with SessionLocal() as s:
            jobs=s.scalars(select(ProfileImportJobRow).where(ProfileImportJobRow.user_id==user)
                .order_by(ProfileImportJobRow.created_at.desc())).all();result={}
            for job in jobs:
                if job.source_fingerprint in result:continue
                count=s.query(ProfileFactRow).filter(ProfileFactRow.user_id==user,
                    ProfileFactRow.source_fingerprint==job.source_fingerprint,ProfileFactRow.status=='ACTIVE').count()
                result[job.source_fingerprint]={'source_fingerprint':job.source_fingerprint,
                    'source_type':job.source_type,'source_provider':job.source_provider,'active_facts':count,
                    'status':'DISCONNECTED' if (job.metadata_json or {}).get('source_disconnected') else 'IMPORT_ENABLED',
                    'scope':'THIS_IMPORT_SOURCE','external_oauth_connection':False}
            return {'items':list(result.values())}

    def set_source_connection(self,user,fingerprint,enabled):
        if type(enabled) is not bool:raise ValueError('PERMISSION_BOOLEAN_REQUIRED')
        with mutation_session() as s:
            jobs=s.scalars(select(ProfileImportJobRow).where(ProfileImportJobRow.user_id==user,
                ProfileImportJobRow.source_fingerprint==fingerprint).with_for_update()).all()
            if not jobs:raise ValueError('PROFILE_SOURCE_NOT_FOUND')
            for j in jobs:j.metadata_json={**(j.metadata_json or {}),'source_disconnected':not enabled}
            self._audit(s,user,user,'CONSUMER','PROFILE_SOURCE_RECONNECTED' if enabled else 'PROFILE_SOURCE_DISCONNECTED',
                purpose='USER_SOURCE_MANAGEMENT',metadata={'source_fingerprint':fingerprint,'retained_existing_facts':True})
            return {'source_fingerprint':fingerprint,'status':'IMPORT_ENABLED' if enabled else 'DISCONNECTED','existing_facts_retained':True}

    def _erase_fact_rows(self,session,user,rows):
        """Erase selected values and their import copies, retaining audit identities."""
        from go_hotel.services.personal_travel_vault import h,now
        grouped={}
        for fact in rows:
            grouped.setdefault(fact.traveler_id,{}).setdefault(fact.field_type,set()).add(fact.normalized_value_hash)
            fact.status='DELETED';fact.value_ciphertext=encrypt_secret('null')
            fact.normalized_value_hash=h(['DELETED',fact.fact_id]);fact.source_reference=None;fact.updated_at=now()
        for tid,fields in grouped.items():
            tr=owned_traveler(session,user,tid,edit=True)
            for field,attr in {'LEGAL_NAME':'full_name','DATE_OF_BIRTH':'date_of_birth','NATIONALITY':'nationality'}.items():
                if h(getattr(tr,attr)) in fields.get(field,set()):setattr(tr,attr,'' if attr=='full_name' else None)
            if tr.document_ciphertext:
                hashes=set().union(*(fields.get(ft,set()) for ft in ('PASSPORT_NUMBER','ID_CARD_NUMBER','DRIVER_LICENSE_NUMBER')))
                if h(decrypt_secret(tr.document_ciphertext)) in hashes:tr.document_ciphertext=None;tr.document_type=None
            tr.updated_at=now()
            items=session.scalars(select(ProfileImportItemRow).where(ProfileImportItemRow.user_id==user,
                ProfileImportItemRow.resolution_traveler_id==tid)).all()
            for item in items:
                if item.normalized_value_hash in fields.get(item.field_type,set()):
                    item.candidate_value_ciphertext=None;item.preview_masked='[DELETED]';item.normalized_value_hash=None
                elif item.entity_type=='TRAVELER' and item.candidate_value_ciphertext:
                    payload=self._item_value(item);changed=False
                    for attr,field in {'full_name':'LEGAL_NAME','name':'LEGAL_NAME','date_of_birth':'DATE_OF_BIRTH','nationality':'NATIONALITY'}.items():
                        if attr in payload and h(payload[attr]) in fields.get(field,set()):payload.pop(attr);changed=True
                    if 'document_number' in payload and any(h(payload['document_number']) in fields.get(ft,set()) for ft in ('PASSPORT_NUMBER','ID_CARD_NUMBER','DRIVER_LICENSE_NUMBER')):
                        payload.pop('document_number');changed=True
                    if changed:
                        item.candidate_value_ciphertext=encrypt_secret(json.dumps(payload,ensure_ascii=False))
                        item.normalized_value_hash=h(payload);item.preview_masked='[REDACTED AFTER DELETE]'

    def inspect_import_item(self,user,job_id,item_id,confirmed):
        from go_hotel.services.personal_travel_vault import SENSITIVE_FIELDS
        if confirmed is not True:raise ValueError('PROFILE_INSPECTION_CONFIRMATION_REQUIRED')
        with mutation_session() as s:
            job=s.get(ProfileImportJobRow,job_id);item=s.get(ProfileImportItemRow,item_id)
            if not job or job.user_id!=user or not item or item.import_job_id!=job_id or item.user_id!=user:
                raise ValueError('PROFILE_IMPORT_ITEM_NOT_FOUND')
            if not item.candidate_value_ciphertext:raise ValueError('PROFILE_IMPORT_VALUE_REMOVED')
            tid=item.resolution_traveler_id
            if not tid and item.entity_type=='TRAVELER':tid=(self._item_value(item) or {}).get('existing_traveler_id')
            if not tid and item.traveler_ref:
                declarations=s.scalars(select(ProfileImportItemRow).where(ProfileImportItemRow.import_job_id==job_id,
                    ProfileImportItemRow.entity_type=='TRAVELER',ProfileImportItemRow.traveler_ref==item.traveler_ref)).all()
                if declarations:
                    declaration=self._item_value(declarations[0]) or {};tid=declaration.get('existing_traveler_id')
            if tid:
                tr=owned_traveler(s,user,tid,edit=True)
                if (item.sensitive or item.field_type in SENSITIVE_FIELDS) and not permission(s,user,tr,'SENSITIVE_DATA'):
                    raise ValueError('TRAVELER_SENSITIVE_PERMISSION_REQUIRED')
            self._audit(s,user,user,'CONSUMER','PROFILE_IMPORT_ITEM_INSPECTED',tid,'USER_IMPORT_REVIEW',
                [item.field_type] if item.field_type else [],{'import_item_id':item_id})
            conflict=s.get(ProfileFactRow,item.conflict_fact_id) if item.conflict_fact_id else None
            if conflict and (conflict.user_id!=user or conflict.traveler_id!=tid or conflict.status!='ACTIVE'):conflict=None
            return {'import_item_id':item_id,'value':self._item_value(item),'conflict_fact_id':item.conflict_fact_id,
                'existing_value':json.loads(decrypt_secret(conflict.value_ciphertext)) if conflict else None}

    def assign_import_traveler(self,user,job_id,item_id,body):
        from go_hotel.services.personal_travel_vault import SENSITIVE_FIELDS,now
        with mutation_session() as s:
            job=s.get(ProfileImportJobRow,job_id);item=s.get(ProfileImportItemRow,item_id)
            if not job or job.user_id!=user or not item or item.import_job_id!=job_id or item.user_id!=user:
                raise ValueError('PROFILE_IMPORT_ITEM_NOT_FOUND')
            if item.entity_type!='PROFILE_FACT':raise ValueError('PROFILE_ASSIGNMENT_FIELD_ONLY')
            if item.status=='COMMITTED' or job.status=='COMMITTED':raise ValueError('PROFILE_IMPORT_ITEM_FINALIZED')
            if (job.metadata_json or {}).get('source_disconnected'):raise ValueError('PROFILE_SOURCE_DISCONNECTED')
            confirmed_revision(item,body)
            tr=owned_traveler(s,user,body.get('traveler_id'),edit=True)
            if (item.sensitive or item.field_type in SENSITIVE_FIELDS) and not permission(s,user,tr,'SENSITIVE_DATA'):
                raise ValueError('TRAVELER_SENSITIVE_PERMISSION_REQUIRED')
            item.resolution_traveler_id=tr.traveler_id;item.conflict_fact_id=None;item.review_action=None
            item.status='NEEDS_REVIEW';item.updated_at=now()
            self._audit(s,user,user,'CONSUMER','PROFILE_IMPORT_TRAVELER_ASSIGNED',tr.traveler_id,
                'USER_IMPORT_REVIEW',[item.field_type],{'import_item_id':item_id})
            return {'import_item_id':item_id,'traveler_id':tr.traveler_id,'status':'NEEDS_REVIEW'}
