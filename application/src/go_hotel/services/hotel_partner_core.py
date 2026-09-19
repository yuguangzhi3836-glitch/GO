from __future__ import annotations
from datetime import datetime, timezone, timedelta
import hashlib, hmac, json, os, secrets, uuid
from urllib.parse import urlencode
from sqlalchemy import select, func, update
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
 HotelPartnerPropertyRow,HotelPartnerChangeRequestRow,HotelPartnerRoomTypeRow,
 HotelPartnerSellableProductRow,HotelPartnerRatePlanRow,HotelPartnerFacilityDefinitionRow,
 HotelPartnerFacilityAssignmentRow,HotelPartnerPolicyRow,HotelPartnerAriOverrideRow,
 HotelPartnerOperationalInboxRow,HotelPartnerGoOfferAuthorityRow,HotelPartnerAuditEventRow,
 HotelRegistrationDirectRow,HotelCanonicalProfileRow,HotelAutoPageVersionRow,
 HotelPartnerImportAuthorizationRow,HotelPartnerImportJobRow)
from go_hotel.security.external_navigation import validate_external_navigation_url

def now(): return datetime.now(timezone.utc)
def ident(prefix): return f'{prefix}_{uuid.uuid4().hex}'
def out(row):
    if row is None:return None
    return {c.name:(getattr(row,c.name).isoformat() if isinstance(getattr(row,c.name),datetime) else getattr(row,c.name)) for c in row.__table__.columns}

class HotelPartnerCoreService:
    HIGH_RISK={'LEGAL','ADDRESS','BRAND','QUALIFICATION'}
    FOUR_STATE={'YES','NO','UNKNOWN','NOT_APPLICABLE'}
    IMPORT_PROVIDERS={
        'CTRIP':{'label':'携程','methods':['OFFICIAL_AUTHORIZATION','DATA_EXPORT','FILE_UPLOAD'],'authorization_env':'GO_CTRIP_SUPPLIER_AUTHORIZATION_URL'},
        'MEITUAN':{'label':'美团','methods':['OFFICIAL_AUTHORIZATION','DATA_EXPORT','FILE_UPLOAD'],'authorization_env':'GO_MEITUAN_SUPPLIER_AUTHORIZATION_URL'},
        'FLIGGY':{'label':'飞猪','methods':['OFFICIAL_AUTHORIZATION','DATA_EXPORT','FILE_UPLOAD'],'authorization_env':'GO_FLIGGY_SUPPLIER_AUTHORIZATION_URL'},
        'BOOKING':{'label':'Booking.com','methods':['OFFICIAL_AUTHORIZATION','DATA_EXPORT','FILE_UPLOAD'],'authorization_env':'GO_BOOKING_SUPPLIER_AUTHORIZATION_URL'},
        'OTHER_OTA':{'label':'其他 OTA','methods':['OFFICIAL_AUTHORIZATION','DATA_EXPORT','FILE_UPLOAD'],'authorization_env':'GO_OTHER_OTA_SUPPLIER_AUTHORIZATION_URL'},
    }
    FORBIDDEN_CREDENTIAL_KEYS={'password','passwd','otp','captcha','cookie','cookies','session','session_id','access_token','refresh_token'}
    IMPORT_HOTEL_FIELDS={'name_zh','name_en','property_type','group_name','brand_name','address','contacts','legal','poi'}
    def _property(self,s,pid,supplier_id):
        r=s.get(HotelPartnerPropertyRow,pid)
        if not r or r.supplier_id!=supplier_id: raise ValueError('PROPERTY_NOT_FOUND')
        return r
    def _audit(self,s,pid,event,typ,aid,payload,actor):
        s.add(HotelPartnerAuditEventRow(audit_event_id=ident('hpa'),property_id=pid,event_type=event,aggregate_type=typ,aggregate_id=aid,payload_json=payload,actor_id=actor,created_at=now()))
    def import_providers(self):
        providers={key:{'label':value['label'],'methods':value['methods'],'official_authorization_available':bool(os.getenv(value['authorization_env']))} for key,value in self.IMPORT_PROVIDERS.items()}
        return {'providers':providers,'credential_policy':'PROVIDER_HOSTED_LOGIN_ONLY','fallback':'DATA_EXPORT_OR_FILE_UPLOAD'}
    def _reject_credentials(self,value):
        if isinstance(value,dict):
            for key,item in value.items():
                if str(key).lower() in self.FORBIDDEN_CREDENTIAL_KEYS:raise ValueError('OTA_CREDENTIALS_NOT_ACCEPTED')
                self._reject_credentials(item)
        elif isinstance(value,list):
            for item in value:self._reject_credentials(item)
    def _request_hash(self,b):
        safe={k:v for k,v in b.items() if k not in {'authorization_code','authorization_state'}}
        return hashlib.sha256(json.dumps(safe,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    def _select_import_package(self,package,selection):
        """Select whole hotel fields before validation or writes; omitted means legacy full import.

        Selection never grants ownership or publication authority. Room and media
        collections are opt-in as a whole when an explicit selection is supplied.
        """
        if selection is None:return package
        if not isinstance(selection,list) or not selection:raise ValueError('IMPORT_SELECTION_REQUIRED')
        allowed={f'hotel.{field}' for field in self.IMPORT_HOTEL_FIELDS}|{'room_types','media'}
        if any(not isinstance(field,str) or field not in allowed for field in selection):raise ValueError('INVALID_IMPORT_SELECTION')
        if not isinstance(package,dict):raise ValueError('HOTEL_DATA_PACKAGE_REQUIRED')
        selected={}
        for field in selection:
            if field.startswith('hotel.'):
                name=field.split('.',1)[1];hotel=package.get('hotel')
                if not isinstance(hotel,dict) or name not in hotel:raise ValueError('IMPORT_SELECTED_FIELD_MISSING')
                selected.setdefault('hotel',{})[name]=hotel[name]
            else:
                if field not in package:raise ValueError('IMPORT_SELECTED_FIELD_MISSING')
                selected[field]=package[field]
        return selected
    def _validate_media_rights(self,media,rights):
        if not media:return
        if rights.get('status') not in {'HOTEL_SUBMITTED','DISTRIBUTION_LICENSE'}:raise ValueError('MEDIA_RIGHTS_EVIDENCE_REQUIRED')
        if not all(str(rights.get(k) or '').strip() for k in ('rights_holder','evidence_reference')):raise ValueError('MEDIA_RIGHTS_EVIDENCE_REQUIRED')
        scopes=set(rights.get('usage_scope') or [])
        if 'DISTRIBUTE_ON_GO' not in scopes:raise ValueError('MEDIA_DISTRIBUTION_SCOPE_REQUIRED')
        if rights.get('expires_at'):
            try:expires=datetime.fromisoformat(str(rights['expires_at']).replace('Z','+00:00'))
            except (TypeError,ValueError):raise ValueError('MEDIA_RIGHTS_EXPIRY_INVALID')
            if expires.tzinfo is None:expires=expires.replace(tzinfo=timezone.utc)
            if expires<=now():raise ValueError('MEDIA_RIGHTS_EXPIRED')
        if not rights.get('applies_to_all_assets'):
            declared=set(rights.get('asset_references') or [])
            actual={str(x.get('source_reference') or x.get('url') or '') for x in media if isinstance(x,dict)}
            if not actual or '' in actual or not actual.issubset(declared):raise ValueError('MEDIA_ASSET_RIGHTS_INCOMPLETE')
    def _normalize_package(self,package):
        if not isinstance(package,dict):raise ValueError('HOTEL_DATA_PACKAGE_REQUIRED')
        hotel=package.get('hotel') or {};rooms=package.get('room_types') or [];media=package.get('media') or []
        if not isinstance(hotel,dict) or not isinstance(rooms,list) or not isinstance(media,list):raise ValueError('HOTEL_DATA_PACKAGE_INVALID')
        if len(rooms)>500 or len(media)>2000:raise ValueError('HOTEL_DATA_PACKAGE_LIMIT')
        allowed=self.IMPORT_HOTEL_FIELDS
        patch={k:hotel[k] for k in allowed if k in hotel}
        normalized=[]
        for raw in rooms:
            if not isinstance(raw,dict):raise ValueError('INVALID_ROOM_TYPE')
            room={k:raw[k] for k in ('name_zh','name_en','sale_unit','physical_room_count','occupancy','bed_configurations','attributes') if k in raw}
            if not str(room.get('name_zh') or '').strip() or not isinstance(room.get('physical_room_count'),int) or room['physical_room_count']<0:raise ValueError('INVALID_ROOM_TYPE')
            occ=room.get('occupancy')
            if not isinstance(occ,dict):raise ValueError('INVALID_OCCUPANCY_CONSTRAINT')
            m=int(occ.get('max_occupancy',0));a=int(occ.get('max_adults',0));c=int(occ.get('max_children',0))
            if min(m,a,c)<0 or m==0 or a>m or c>m or a+c<m:raise ValueError('INVALID_OCCUPANCY_CONSTRAINT')
            normalized.append(room)
        for asset in media:
            if not isinstance(asset,dict) or not str(asset.get('source_reference') or asset.get('url') or '').strip():raise ValueError('INVALID_MEDIA_ASSET')
            if asset.get('url'):
                try:validate_external_navigation_url(asset['url'])
                except ValueError as exc:raise ValueError('INVALID_MEDIA_ASSET') from exc
        return patch,normalized,media
    def _verify_provider_authorization(self,provider,b):
        """Verify the result produced by GO's server-side provider adapter.

        The browser authorization code is never treated as proof by itself.  The
        adapter exchanges it with the provider and signs the minimal result; no
        provider token or account credential is persisted in the hotel library.
        """
        proof=b.get('authorization_proof') or {};signature=str(b.get('authorization_signature') or '')
        secret=os.getenv(f'GO_{provider}_SUPPLIER_CALLBACK_SECRET')
        if not secret:raise ValueError('SUPPLIER_PROVIDER_VERIFIER_UNAVAILABLE')
        required=('provider_account_subject','authorization_evidence_reference','state')
        if not isinstance(proof,dict) or not all(str(proof.get(k) or '').strip() for k in required):raise ValueError('SUPPLIER_PROVIDER_AUTHORIZATION_UNVERIFIED')
        if proof.get('state')!=b.get('authorization_state'):raise ValueError('SUPPLIER_PROVIDER_STATE_INVALID')
        raw=json.dumps(proof,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
        expected=hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(expected,signature):raise ValueError('SUPPLIER_PROVIDER_AUTHORIZATION_UNVERIFIED')
        return {'provider_account_subject_hash':hashlib.sha256(str(proof['provider_account_subject']).encode()).hexdigest(),'authorization_evidence_reference':proof['authorization_evidence_reference']}
    def one_click_import(self,supplier_id,actor,pid,b,idempotency_key=None):
        provider=str(b.get('provider') or '').upper();method=str(b.get('method') or '').upper()
        if provider not in self.IMPORT_PROVIDERS:raise ValueError('UNSUPPORTED_OTA_PROVIDER')
        if method not in self.IMPORT_PROVIDERS[provider]['methods']:raise ValueError('UNSUPPORTED_IMPORT_METHOD')
        self._reject_credentials(b)
        if method=='OFFICIAL_AUTHORIZATION' and not b.get('authorization_code'):
            authorization_base=os.getenv(self.IMPORT_PROVIDERS[provider]['authorization_env'])
            if not authorization_base:return {'status':'AUTHORIZATION_UNAVAILABLE','provider':provider,'login_surface':'PROVIDER_HOSTED','credentials_received_by_go':False,'fallback':'DATA_EXPORT'}
            try:authorization_base=validate_external_navigation_url(authorization_base,reject_sensitive_query=False)
            except ValueError as exc:raise ValueError('SUPPLIER_PROVIDER_AUTHORIZATION_URL_INVALID') from exc
            state=secrets.token_urlsafe(32)
            with SessionLocal() as s:
                self._property(s,pid,supplier_id);t=now();s.add(HotelPartnerImportAuthorizationRow(authorization_id=ident('hpia'),property_id=pid,supplier_id=supplier_id,provider=provider,state_hash=hashlib.sha256(state.encode()).hexdigest(),status='PENDING',requested_by=actor,created_at=t,expires_at=t+timedelta(minutes=10),consumed_at=None));s.commit()
            query=urlencode({'state':state,'property_id':pid})
            return {'status':'AUTHORIZATION_REQUIRED','provider':provider,'authorization_url':authorization_base+('&' if '?' in authorization_base else '?')+query,'login_surface':'PROVIDER_HOSTED','credentials_received_by_go':False,'fallback':'DATA_EXPORT'}
        authorization_evidence=self._verify_provider_authorization(provider,b) if method=='OFFICIAL_AUTHORIZATION' else None
        package=self._select_import_package(b.get('hotel_package'),b.get('selected_fields'))
        patch,rooms,media=self._normalize_package(package)
        self._validate_media_rights(media,b.get('media_rights') or {})
        request_hash=self._request_hash(b);key=str(idempotency_key or b.get('idempotency_key') or request_hash)
        if not key or len(key)>160:raise ValueError('INVALID_IDEMPOTENCY_KEY')
        with SessionLocal() as s:
            prop=self._property(s,pid,supplier_id)
            existing=s.scalar(select(HotelPartnerImportJobRow).where(HotelPartnerImportJobRow.supplier_id==supplier_id,HotelPartnerImportJobRow.property_id==pid,HotelPartnerImportJobRow.idempotency_key==key))
            if existing:
                if existing.request_hash!=request_hash:raise ValueError('IDEMPOTENCY_PAYLOAD_MISMATCH')
                if existing.status=='COMPLETED':return dict(existing.result_json)|{'idempotent_replay':True,'import_job_id':existing.import_job_id}
                raise ValueError('IMPORT_ALREADY_IN_PROGRESS')
            authorization=None
            if method=='OFFICIAL_AUTHORIZATION':
                state_hash=hashlib.sha256(str(b.get('authorization_state') or '').encode()).hexdigest()
                authorization=s.scalar(select(HotelPartnerImportAuthorizationRow).where(HotelPartnerImportAuthorizationRow.property_id==pid,HotelPartnerImportAuthorizationRow.supplier_id==supplier_id,HotelPartnerImportAuthorizationRow.provider==provider,HotelPartnerImportAuthorizationRow.state_hash==state_hash))
                if not authorization or authorization.status!='PENDING':raise ValueError('SUPPLIER_PROVIDER_STATE_INVALID')
                if not hmac.compare_digest(authorization.state_hash,state_hash):raise ValueError('SUPPLIER_PROVIDER_STATE_INVALID')
                expires=authorization.expires_at if authorization.expires_at.tzinfo else authorization.expires_at.replace(tzinfo=timezone.utc)
                if expires<=now():authorization.status='EXPIRED';s.commit();raise ValueError('SUPPLIER_PROVIDER_STATE_EXPIRED')
                consumed=s.execute(update(HotelPartnerImportAuthorizationRow).where(HotelPartnerImportAuthorizationRow.authorization_id==authorization.authorization_id,HotelPartnerImportAuthorizationRow.status=='PENDING').values(status='CONSUMED',consumed_at=now())).rowcount
                if consumed!=1:raise ValueError('SUPPLIER_PROVIDER_STATE_ALREADY_USED')
            t=now();job=HotelPartnerImportJobRow(import_job_id=ident('hpij'),property_id=pid,supplier_id=supplier_id,provider=provider,method=method,idempotency_key=key,request_hash=request_hash,status='PROCESSING',result_json={},error_code=None,created_by=actor,created_at=t,completed_at=None);s.add(job)
            mapping={'name_zh':'name_zh','name_en':'name_en','property_type':'property_type','group_name':'group_name','brand_name':'brand_name','address':'address_json','contacts':'contacts_json','legal':'legal_json','poi':'poi_json'}
            for k,v in patch.items():setattr(prop,mapping[k],v)
            source={'provider':provider,'method':method,'source_kind':'OTA_IMPORT','import_job_id':job.import_job_id,'imported_at':t.isoformat()}
            ops=dict(prop.operations_json or {});sources=dict(ops.get('import_field_sources') or {})
            for field in patch:sources[f'hotel.{field}']=dict(source)
            if rooms:sources['room_types']=dict(source)
            if media:sources['media']=dict(source)
            ops['import_field_sources']=sources
            if media:
                ops['import_provider']=provider;ops['media_candidates']=media;ops['media_rights']=b['media_rights']
            prop.operations_json=ops
            prop.version+=1;prop.updated_at=t
            for room in rooms:
                r=HotelPartnerRoomTypeRow(room_type_id=ident('room'),property_id=pid,name_zh=room['name_zh'],name_en=room.get('name_en'),sale_unit=room.get('sale_unit','WHOLE_ROOM'),physical_room_count=room['physical_room_count'],occupancy_json=room['occupancy'],bed_configurations_json=room.get('bed_configurations',[]),attributes_json=room.get('attributes',{}),media_json=[],state='ACTIVE',created_at=t,updated_at=t);s.add(r)
            result={'status':'IMPORTED','property_id':pid,'provider':provider,'method':method,'source_kind':'OTA_IMPORT','room_types_created':len(rooms),'media_candidates':len(media),'publication_state':prop.publication_state,'mapping':{'hotel_fields':sorted(patch),'room_types':len(rooms),'ignored_unknown_fields':True}}
            job.status='COMPLETED';job.result_json=result;job.completed_at=t
            audit_payload={'provider':provider,'method':method,'room_count':len(rooms),'media_count':len(media),'request_hash':request_hash}
            if authorization_evidence:audit_payload|=authorization_evidence
            self._audit(s,pid,'HOTEL_LIBRARY_IMPORTED','IMPORT_JOB',job.import_job_id,audit_payload,actor);s.commit()
            return result|{'import_job_id':job.import_job_id,'idempotent_replay':False}
    def create_property(self,supplier_id,actor,b):
        operations=b.get('operations') or {}
        if not isinstance(operations,dict):raise ValueError('PROPERTY_OPERATIONS_INVALID')
        operation_media=operations.get('media_candidates') or operations.get('media') or []
        self._validate_media_rights(operation_media,operations.get('media_rights') or b.get('media_rights') or {})
        t=now(); r=HotelPartnerPropertyRow(property_id=ident('prop'),supplier_id=supplier_id,name_zh=b['name_zh'],name_en=b.get('name_en'),property_type=b['property_type'],group_name=b.get('group_name'),brand_name=b.get('brand_name'),address_json=b.get('address',{}),latitude=b.get('latitude'),longitude=b.get('longitude'),contacts_json=b.get('contacts',{}),legal_json=b.get('legal',{}),operations_json=b.get('operations',{}),poi_json=b.get('poi',[]),publication_state='DRAFT',version=1,created_at=t,updated_at=t)
        with SessionLocal() as s:s.add(r);self._audit(s,r.property_id,'PROPERTY_CREATED','PROPERTY',r.property_id,{},actor);s.commit();return out(r)
    def properties(self,supplier_id):
        with SessionLocal() as s:return [out(x) for x in s.scalars(select(HotelPartnerPropertyRow).where(HotelPartnerPropertyRow.supplier_id==supplier_id)).all()]
    def patch_property(self,supplier_id,actor,pid,b):
        risk=set(b)&self.HIGH_RISK
        operations=b.get('operations') or {}
        if not isinstance(operations,dict):raise ValueError('PROPERTY_OPERATIONS_INVALID')
        operation_media=operations.get('media_candidates') or operations.get('media') or []
        if operation_media:self._validate_media_rights(operation_media,operations.get('media_rights') or b.get('media_rights') or {})
        with SessionLocal() as s:
            r=self._property(s,pid,supplier_id)
            if risk:
                cr=HotelPartnerChangeRequestRow(change_request_id=ident('hcr'),property_id=pid,field_group=sorted(risk)[0],proposed_value_json=b,evidence_json=b.get('evidence',[]),state='SUBMITTED',requested_by=actor,created_at=now())
                s.add(cr);self._audit(s,pid,'HIGH_RISK_CHANGE_SUBMITTED','CHANGE_REQUEST',cr.change_request_id,{'field_groups':sorted(risk)},actor);s.commit();return {'mode':'CHANGE_REQUEST','change_request':out(cr)}
            mapping={'name_zh':'name_zh','name_en':'name_en','property_type':'property_type','group_name':'group_name','brand_name':'brand_name','address':'address_json','contacts':'contacts_json','legal':'legal_json','operations':'operations_json','poi':'poi_json'}
            for k,v in b.items():
                if k in mapping:setattr(r,mapping[k],v)
            r.version+=1;r.updated_at=now();self._audit(s,pid,'LOW_RISK_PROPERTY_UPDATED','PROPERTY',pid,{'fields':list(b)},actor);s.commit();return {'mode':'IMMEDIATE','property':out(r)}
    def create_room_type(self,supplier_id,actor,pid,b):
        occ=b['occupancy'];m=int(occ.get('max_occupancy',0));a=int(occ.get('max_adults',0));c=int(occ.get('max_children',0))
        if min(m,a,c)<0 or m==0 or a>m or c>m or a+c<m: raise ValueError('INVALID_OCCUPANCY_CONSTRAINT')
        self._validate_media_rights(b.get('media') or [],b.get('media_rights') or {})
        with SessionLocal() as s:
            self._property(s,pid,supplier_id);t=now();r=HotelPartnerRoomTypeRow(room_type_id=ident('room'),property_id=pid,name_zh=b['name_zh'],name_en=b.get('name_en'),sale_unit=b.get('sale_unit','WHOLE_ROOM'),physical_room_count=b['physical_room_count'],occupancy_json=occ,bed_configurations_json=b.get('bed_configurations',[]),attributes_json=b.get('attributes',{}),media_json=b.get('media',[]),state='ACTIVE',created_at=t,updated_at=t)
            rights=b.get('media_rights') or {}
            rights_audit={'media_count':len(b.get('media') or []),'rights_status':rights.get('status'),
                'rights_evidence_hash':hashlib.sha256(str(rights.get('evidence_reference') or '').encode()).hexdigest() if rights else None}
            s.add(r);self._audit(s,pid,'ROOM_TYPE_CREATED','ROOM_TYPE',r.room_type_id,rights_audit,actor);s.commit();return out(r)
    def create_product(self,supplier_id,actor,pid,b):
        with SessionLocal() as s:
            self._property(s,pid,supplier_id);rt=s.get(HotelPartnerRoomTypeRow,b['room_type_id'])
            if not rt or rt.property_id!=pid:raise ValueError('ROOM_TYPE_NOT_FOUND')
            r=HotelPartnerSellableProductRow(sellable_product_id=ident('product'),property_id=pid,room_type_id=rt.room_type_id,name=b['name'],occupancy_offer_json=b.get('occupancy_offer',{}),state='ACTIVE');s.add(r);self._audit(s,pid,'SELLABLE_PRODUCT_CREATED','SELLABLE_PRODUCT',r.sellable_product_id,{},actor);s.commit();return out(r)
    def create_rate_plan(self,supplier_id,actor,pid,b):
        with SessionLocal() as s:
            self._property(s,pid,supplier_id);p=s.get(HotelPartnerSellableProductRow,b['sellable_product_id'])
            if not p or p.property_id!=pid:raise ValueError('SELLABLE_PRODUCT_NOT_FOUND')
            tiers=b.get('cancellation_tiers',[])
            if any('before_arrival_hours' not in x or 'charge_percent' not in x for x in tiers):raise ValueError('INVALID_CANCELLATION_TIERS')
            t=now();r=HotelPartnerRatePlanRow(rate_plan_id=ident('rate'),property_id=pid,sellable_product_id=p.sellable_product_id,name=b['name'],payment_type=b['payment_type'],meal_plan_json=b.get('meal_plan',{}),cancellation_tiers_json=tiers,restrictions_json=b.get('restrictions',{}),default_ari_json=b.get('default_ari',{}),state='ACTIVE',created_at=t,updated_at=t);s.add(r);self._audit(s,pid,'RATE_PLAN_CREATED','RATE_PLAN',r.rate_plan_id,{},actor);s.commit();return out(r)
    def upsert_facility(self,supplier_id,actor,pid,b):
        if b['status'] not in self.FOUR_STATE:raise ValueError('INVALID_FACILITY_STATUS')
        with SessionLocal() as s:
            self._property(s,pid,supplier_id);d=s.scalar(select(HotelPartnerFacilityDefinitionRow).where(HotelPartnerFacilityDefinitionRow.code==b['code']))
            if not d:d=HotelPartnerFacilityDefinitionRow(facility_definition_id=ident('fac'),code=b['code'],category=b['category'],name_zh=b['name_zh'],name_en=b.get('name_en'),attribute_schema_json=b.get('attribute_schema',{}));s.add(d);s.flush()
            rid=b.get('room_type_id');q=select(HotelPartnerFacilityAssignmentRow).where(HotelPartnerFacilityAssignmentRow.property_id==pid,HotelPartnerFacilityAssignmentRow.facility_definition_id==d.facility_definition_id)
            q=q.where(HotelPartnerFacilityAssignmentRow.room_type_id==rid) if rid else q.where(HotelPartnerFacilityAssignmentRow.room_type_id.is_(None));r=s.scalar(q)
            if not r:r=HotelPartnerFacilityAssignmentRow(facility_assignment_id=ident('fassign'),property_id=pid,room_type_id=rid,facility_definition_id=d.facility_definition_id,status=b['status'],inherited=b.get('inherited',False),attributes_json=b.get('attributes',{}),evidence_json=b.get('evidence',[]),updated_at=now());s.add(r)
            else:r.status=b['status'];r.inherited=b.get('inherited',False);r.attributes_json=b.get('attributes',{});r.evidence_json=b.get('evidence',[]);r.updated_at=now()
            self._audit(s,pid,'FACILITY_ASSIGNED','FACILITY_ASSIGNMENT',r.facility_assignment_id,{'status':r.status},actor);s.commit();return out(r)
    def upsert_policy(self,supplier_id,actor,pid,b):
        with SessionLocal() as s:
            self._property(s,pid,supplier_id);r=s.scalar(select(HotelPartnerPolicyRow).where(HotelPartnerPolicyRow.property_id==pid,HotelPartnerPolicyRow.policy_type==b['policy_type'],HotelPartnerPolicyRow.state=='ACTIVE'))
            if not r:r=HotelPartnerPolicyRow(policy_id=ident('policy'),property_id=pid,policy_type=b['policy_type'],rule_json=b['rule'],effective_from=b.get('effective_from'),effective_to=b.get('effective_to'),state='ACTIVE',version=1,updated_at=now());s.add(r)
            else:r.rule_json=b['rule'];r.effective_from=b.get('effective_from');r.effective_to=b.get('effective_to');r.version+=1;r.updated_at=now()
            self._audit(s,pid,'MACHINE_POLICY_UPDATED','POLICY',r.policy_id,{'version':r.version},actor);s.commit();return out(r)
    def upsert_ari(self,supplier_id,actor,pid,b):
        if b['sell_status'] not in {'OPEN','CLOSED'} or b['inventory_mode'] not in {'FREE_SALE','ALLOTMENT'}:raise ValueError('INVALID_ARI_MODE')
        if b['inventory_mode']=='ALLOTMENT' and b.get('remaining_rooms') is None:raise ValueError('ALLOTMENT_REQUIRES_REMAINING_ROOMS')
        if b['inventory_mode']=='FREE_SALE' and b.get('remaining_rooms') is not None:raise ValueError('FREE_SALE_MUST_NOT_SET_REMAINING_ROOMS')
        if b['exhaustion_policy'] not in {'STOP_SELL','ON_REQUEST','REQUEST_TO_BOOK'}:raise ValueError('INVALID_EXHAUSTION_POLICY')
        with SessionLocal() as s:
            self._property(s,pid,supplier_id);rate=s.get(HotelPartnerRatePlanRow,b['rate_plan_id']);room=s.get(HotelPartnerRoomTypeRow,b['room_type_id'])
            if not rate or not room or rate.property_id!=pid or room.property_id!=pid:raise ValueError('ROOM_OR_RATE_NOT_FOUND')
            r=s.scalar(select(HotelPartnerAriOverrideRow).where(HotelPartnerAriOverrideRow.rate_plan_id==rate.rate_plan_id,HotelPartnerAriOverrideRow.stay_date==b['stay_date']))
            values=dict(property_id=pid,room_type_id=room.room_type_id,rate_plan_id=rate.rate_plan_id,stay_date=b['stay_date'],sell_status=b['sell_status'],inventory_mode=b['inventory_mode'],remaining_rooms=b.get('remaining_rooms'),exhaustion_policy=b['exhaustion_policy'],inventory_sharing=b.get('inventory_sharing','INDEPENDENT'),price_json=b['price'],restrictions_json=b.get('restrictions',{}),override_fields_json=b.get('override_fields',[]),evidence_json=b.get('evidence',[]),updated_by=actor,updated_at=now())
            if not r:r=HotelPartnerAriOverrideRow(ari_override_id=ident('ari'),**values);s.add(r)
            else:
                for k,v in values.items():setattr(r,k,v)
            self._audit(s,pid,'DATE_ARI_OVERRIDDEN','ARI_OVERRIDE',r.ari_override_id,{'stay_date':r.stay_date,'impact_preview':b.get('impact_preview',{})},actor);s.commit();return out(r)
    def create_inbox(self,supplier_id,actor,pid,b):
        with SessionLocal() as s:
            self._property(s,pid,supplier_id);t=now();due=t+timedelta(minutes=b.get('sla_minutes',60));r=HotelPartnerOperationalInboxRow(inbox_item_id=ident('inbox'),property_id=pid,item_type=b['item_type'],priority=b.get('priority','MEDIUM'),sla_due_at=due,owner_id=b.get('owner_id'),state='OPEN',subject=b['subject'],payload_json=b.get('payload',{}),evidence_json=b.get('evidence',[]),created_at=t,updated_at=t);s.add(r);self._audit(s,pid,'INBOX_ITEM_CREATED','INBOX_ITEM',r.inbox_item_id,{},actor);s.commit();return out(r)
    def transition_inbox(self,supplier_id,actor,item_id,b):
        allowed={'OPEN':{'ACKNOWLEDGED','IN_PROGRESS'},'ACKNOWLEDGED':{'IN_PROGRESS','RESOLVED'},'IN_PROGRESS':{'RESOLVED','BLOCKED'},'BLOCKED':{'IN_PROGRESS','RESOLVED'}}
        with SessionLocal() as s:
            r=s.get(HotelPartnerOperationalInboxRow,item_id)
            if not r:self._notfound()
            self._property(s,r.property_id,supplier_id)
            if b['state'] not in allowed.get(r.state,set()):raise ValueError('INVALID_INBOX_TRANSITION')
            r.state=b['state'];r.owner_id=b.get('owner_id',r.owner_id);r.evidence_json=list(r.evidence_json or [])+b.get('evidence',[]);r.updated_at=now();self._audit(s,r.property_id,'INBOX_STATE_CHANGED','INBOX_ITEM',r.inbox_item_id,{'state':r.state},actor);s.commit();return out(r)
    def _notfound(self):raise ValueError('INBOX_ITEM_NOT_FOUND')
    def upsert_offer_authority(self,supplier_id,actor,pid,b):
        if b['requirement_type'] not in {'ROOM_ONLY','MEETING_OR_EVENT'} or b['quote_mode'] not in {'MANUAL_QUOTE','SYSTEM_GENERATED'}:raise ValueError('INVALID_GO_OFFER_AUTHORITY')
        if b['quote_mode']=='SYSTEM_GENERATED' and (not b.get('authorized_inventory') or not b.get('authorized_rules') or not b.get('price_floor')):raise ValueError('SYSTEM_GENERATED_REQUIRES_DEDICATED_AUTHORIZED_SUPPLY')
        if b.get('source_scope','GO_OFFER_DEDICATED')!='GO_OFFER_DEDICATED':raise ValueError('GO_OFFER_ORDINARY_SUPPLY_FORBIDDEN')
        with SessionLocal() as s:
            self._property(s,pid,supplier_id);r=s.scalar(select(HotelPartnerGoOfferAuthorityRow).where(HotelPartnerGoOfferAuthorityRow.property_id==pid,HotelPartnerGoOfferAuthorityRow.requirement_type==b['requirement_type']))
            v=dict(quote_mode=b['quote_mode'],authorized_inventory_json=b.get('authorized_inventory',{}),authorized_rules_json=b.get('authorized_rules',{}),packages_json=b.get('packages',[]),price_floor_json=b.get('price_floor',{}),validity_json=b.get('validity',{}),conditions_json=b.get('conditions',{}),source_scope='GO_OFFER_DEDICATED',state=b.get('state','ACTIVE'),updated_at=now())
            if not r:r=HotelPartnerGoOfferAuthorityRow(go_offer_authority_id=ident('gooa'),property_id=pid,requirement_type=b['requirement_type'],**v);s.add(r)
            else:
                for k,x in v.items():setattr(r,k,x)
            self._audit(s,pid,'GO_OFFER_AUTHORITY_UPDATED','GO_OFFER_AUTHORITY',r.go_offer_authority_id,{'quote_mode':r.quote_mode,'recommendation_eligibility_changed':False},actor);s.commit();return out(r)
    def graph(self,supplier_id,pid):
        with SessionLocal() as s:
            p=self._property(s,pid,supplier_id)
            rooms=s.scalars(select(HotelPartnerRoomTypeRow).where(HotelPartnerRoomTypeRow.property_id==pid)).all();products=s.scalars(select(HotelPartnerSellableProductRow).where(HotelPartnerSellableProductRow.property_id==pid)).all();rates=s.scalars(select(HotelPartnerRatePlanRow).where(HotelPartnerRatePlanRow.property_id==pid)).all();assignments=s.scalars(select(HotelPartnerFacilityAssignmentRow).where(HotelPartnerFacilityAssignmentRow.property_id==pid)).all();policies=s.scalars(select(HotelPartnerPolicyRow).where(HotelPartnerPolicyRow.property_id==pid,HotelPartnerPolicyRow.state=='ACTIVE')).all()
            facilities=[]
            for a in assignments:
                d=s.get(HotelPartnerFacilityDefinitionRow,a.facility_definition_id)
                facilities.append({'房型编号':a.room_type_id,'分类':getattr(d,'category',None),'设施':getattr(d,'name_zh',None) or getattr(d,'code',None),'状态':a.status,'继承酒店默认':bool(a.inherited),'详情':a.attributes_json or {}})
            return {'property':out(p),'room_types':[out(x) for x in rooms],'sellable_products':[out(x) for x in products],'rate_plans':[out(x) for x in rates],'facilities':facilities,'policies':[out(x) for x in policies]}
    def operating_snapshot(self,supplier_id,pid):
        with SessionLocal() as s:
            self._property(s,pid,supplier_id)
            def rows(model):return [out(x) for x in s.scalars(select(model).where(model.property_id==pid)).all()]
            return {'product_graph':self.graph(supplier_id,pid),'facility_assignments':rows(HotelPartnerFacilityAssignmentRow),'policies':rows(HotelPartnerPolicyRow),'ari_date_overrides':rows(HotelPartnerAriOverrideRow),'operational_inbox':rows(HotelPartnerOperationalInboxRow),'go_offer_authorities':rows(HotelPartnerGoOfferAuthorityRow),'change_requests':rows(HotelPartnerChangeRequestRow)}
    def webpage_workspace(self,supplier_id):
        with SessionLocal() as s:
            prop=s.scalar(select(HotelPartnerPropertyRow).where(HotelPartnerPropertyRow.supplier_id==supplier_id).order_by(HotelPartnerPropertyRow.updated_at.desc()))
            reg=s.scalar(select(HotelRegistrationDirectRow).where(HotelRegistrationDirectRow.supplier_id==supplier_id).order_by(HotelRegistrationDirectRow.created_at.desc()))
            if not reg:
                return {'mapped':False,'property':out(prop),'message':'酒店网页尚未与 Canonical Hotel 绑定；酒店资料仍可继续维护。','publication_state':'NOT_MAPPED','page':None}
            profile=s.get(HotelCanonicalProfileRow,reg.hotel_id)
            latest=s.scalar(select(HotelAutoPageVersionRow).where(HotelAutoPageVersionRow.hotel_id==reg.hotel_id).order_by(HotelAutoPageVersionRow.version.desc())) if profile else None
            return {'mapped':bool(profile),'property':out(prop),'registration':out(reg),'hotel_id':reg.hotel_id,'profile':out(profile),'publication_state':profile.page_state if profile else 'NOT_MAPPED','go_direct_state':profile.go_direct_state if profile else 'NOT_REGISTERED','page':(latest.page_json if latest else None),'page_version':(latest.version if latest else None),'page_hash':(latest.page_hash if latest else None),'supplier_can_edit_facts':True,'supplier_can_bypass_rights_gate':False}

    def command_center(self,supplier_id,pid):
        with SessionLocal() as s:
            p=self._property(s,pid,supplier_id);open_items=s.scalars(select(HotelPartnerOperationalInboxRow).where(HotelPartnerOperationalInboxRow.property_id==pid,HotelPartnerOperationalInboxRow.state!='RESOLVED').order_by(HotelPartnerOperationalInboxRow.priority,HotelPartnerOperationalInboxRow.sla_due_at).limit(8)).all()
            rooms=s.scalar(select(func.count()).select_from(HotelPartnerRoomTypeRow).where(HotelPartnerRoomTypeRow.property_id==pid)) or 0;policies=s.scalar(select(func.count()).select_from(HotelPartnerPolicyRow).where(HotelPartnerPolicyRow.property_id==pid)) or 0;facilities=s.scalar(select(func.count()).select_from(HotelPartnerFacilityAssignmentRow).where(HotelPartnerFacilityAssignmentRow.property_id==pid,HotelPartnerFacilityAssignmentRow.status!='UNKNOWN')) or 0
            readiness=min(100,int(bool(p.address_json))*15+int(bool(p.contacts_json))*10+int(bool(p.legal_json))*15+min(25,rooms*10)+min(15,policies*3)+min(20,facilities*2))
            return {'property_id':pid,'readiness_score':readiness,'actions':[{'insight':x.subject,'reason':x.item_type,'recommended_action':'OPEN_INBOX_ITEM','expected_impact':'REDUCE_OPERATIONAL_RISK','approval_required':True,'inbox_item':out(x)} for x in open_items],'guardrails':{'ai_may_recommend':True,'ai_may_mutate_supplier_price_inventory_rule':False,'recommendation_value_separated':True}}

hotel_partner_core_service=HotelPartnerCoreService()
