from __future__ import annotations
from datetime import datetime, timezone, timedelta
import hashlib, os, secrets, uuid
from urllib.parse import urlencode
from sqlalchemy import select, func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import (
 HotelPartnerPropertyRow,HotelPartnerChangeRequestRow,HotelPartnerRoomTypeRow,
 HotelPartnerSellableProductRow,HotelPartnerRatePlanRow,HotelPartnerFacilityDefinitionRow,
 HotelPartnerFacilityAssignmentRow,HotelPartnerPolicyRow,HotelPartnerAriOverrideRow,
 HotelPartnerOperationalInboxRow,HotelPartnerGoOfferAuthorityRow,HotelPartnerAuditEventRow,
 HotelRegistrationDirectRow,HotelCanonicalProfileRow,HotelAutoPageVersionRow)

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
    def one_click_import(self,supplier_id,actor,pid,b):
        provider=str(b.get('provider') or '').upper();method=str(b.get('method') or '').upper()
        if provider not in self.IMPORT_PROVIDERS:raise ValueError('UNSUPPORTED_OTA_PROVIDER')
        if method not in self.IMPORT_PROVIDERS[provider]['methods']:raise ValueError('UNSUPPORTED_IMPORT_METHOD')
        self._reject_credentials(b)
        if method=='OFFICIAL_AUTHORIZATION' and not b.get('authorization_code'):
            authorization_base=os.getenv(self.IMPORT_PROVIDERS[provider]['authorization_env'])
            if not authorization_base:return {'status':'AUTHORIZATION_UNAVAILABLE','provider':provider,'login_surface':'PROVIDER_HOSTED','credentials_received_by_go':False,'fallback':'DATA_EXPORT'}
            state=secrets.token_urlsafe(32)
            with SessionLocal() as s:
                prop=self._property(s,pid,supplier_id);ops=dict(prop.operations_json or {});ops['ota_authorization']={'provider':provider,'state_hash':hashlib.sha256(state.encode()).hexdigest(),'requested_by':actor};prop.operations_json=ops;prop.updated_at=now();s.commit()
            query=urlencode({'state':state,'property_id':pid})
            return {'status':'AUTHORIZATION_REQUIRED','provider':provider,'authorization_url':authorization_base+('&' if '?' in authorization_base else '?')+query,'login_surface':'PROVIDER_HOSTED','credentials_received_by_go':False,'fallback':'DATA_EXPORT'}
        if method=='OFFICIAL_AUTHORIZATION':
            with SessionLocal() as s:
                prop=self._property(s,pid,supplier_id);intent=(prop.operations_json or {}).get('ota_authorization') or {}
                if intent.get('provider')!=provider or hashlib.sha256(str(b.get('authorization_state') or '').encode()).hexdigest()!=intent.get('state_hash'):raise ValueError('SUPPLIER_PROVIDER_STATE_INVALID')
        package=b.get('hotel_package')
        if not isinstance(package,dict):raise ValueError('HOTEL_DATA_PACKAGE_REQUIRED')
        hotel=package.get('hotel') or {};rooms=package.get('room_types') or []
        media=package.get('media') or []
        if media:
            rights=b.get('media_rights') or {}
            if rights.get('status') not in {'HOTEL_SUBMITTED','DISTRIBUTION_LICENSE'} or not rights.get('evidence_reference'):
                raise ValueError('MEDIA_RIGHTS_EVIDENCE_REQUIRED')
        patch={k:hotel[k] for k in ('name_zh','name_en','property_type','group_name','brand_name','address','contacts','legal','poi') if k in hotel}
        if media:patch['operations']={'import_provider':provider,'media_candidates':media,'media_rights':b['media_rights']}
        if patch:self.patch_property(supplier_id,actor,pid,patch)
        created=[]
        for room in rooms:
            if not isinstance(room,dict):raise ValueError('INVALID_ROOM_TYPE')
            created.append(self.create_room_type(supplier_id,actor,pid,room))
        with SessionLocal() as s:
            self._property(s,pid,supplier_id);self._audit(s,pid,'HOTEL_LIBRARY_IMPORTED','PROPERTY',pid,{'provider':provider,'method':method,'room_count':len(created),'media_count':len(media)},actor);s.commit()
        return {'status':'IMPORTED','property_id':pid,'provider':provider,'method':method,'room_types_created':len(created),'media_candidates':len(media),'publication_state':'DRAFT'}
    def create_property(self,supplier_id,actor,b):
        t=now(); r=HotelPartnerPropertyRow(property_id=ident('prop'),supplier_id=supplier_id,name_zh=b['name_zh'],name_en=b.get('name_en'),property_type=b['property_type'],group_name=b.get('group_name'),brand_name=b.get('brand_name'),address_json=b.get('address',{}),latitude=b.get('latitude'),longitude=b.get('longitude'),contacts_json=b.get('contacts',{}),legal_json=b.get('legal',{}),operations_json=b.get('operations',{}),poi_json=b.get('poi',[]),publication_state='DRAFT',version=1,created_at=t,updated_at=t)
        with SessionLocal() as s:s.add(r);self._audit(s,r.property_id,'PROPERTY_CREATED','PROPERTY',r.property_id,{},actor);s.commit();return out(r)
    def properties(self,supplier_id):
        with SessionLocal() as s:return [out(x) for x in s.scalars(select(HotelPartnerPropertyRow).where(HotelPartnerPropertyRow.supplier_id==supplier_id)).all()]
    def patch_property(self,supplier_id,actor,pid,b):
        risk=set(b)&self.HIGH_RISK
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
        with SessionLocal() as s:
            self._property(s,pid,supplier_id);t=now();r=HotelPartnerRoomTypeRow(room_type_id=ident('room'),property_id=pid,name_zh=b['name_zh'],name_en=b.get('name_en'),sale_unit=b.get('sale_unit','WHOLE_ROOM'),physical_room_count=b['physical_room_count'],occupancy_json=occ,bed_configurations_json=b.get('bed_configurations',[]),attributes_json=b.get('attributes',{}),media_json=b.get('media',[]),state='ACTIVE',created_at=t,updated_at=t)
            s.add(r);self._audit(s,pid,'ROOM_TYPE_CREATED','ROOM_TYPE',r.room_type_id,{},actor);s.commit();return out(r)
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
