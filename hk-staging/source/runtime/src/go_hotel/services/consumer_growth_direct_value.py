from __future__ import annotations
from datetime import datetime,timezone,timedelta
import hashlib,json,secrets
from sqlalchemy import select,func
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import DirectValueOfferRow,MarketBenchmarkQuoteRow,SupplierChannelEconomicsRow,DirectValueRecommendationRow,ConsumerGrowthEventRow,ConsumerGrowthAttributionRow,ConsumerTripInvitationRow,ConsumerTripMemberRow,TravelerClaimRow,TripImportIntentRow,HotelPartnerPropertyRow,GoJourneyRow,ConsumerProfileRow,TravelerProfileRow
from go_hotel.domain.models import new_id

def now():return datetime.now(timezone.utc)
def sha(v):return hashlib.sha256((v if isinstance(v,str) else json.dumps(v,sort_keys=True,default=str,separators=(',',':'))).encode()).hexdigest()
def dt(v):
    if not v:return None
    if isinstance(v,datetime):return v
    return datetime.fromisoformat(str(v).replace('Z','+00:00'))
def clamp(v,a,b):return max(a,min(b,int(v)))
def aware(v):
    if not v:return v
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)

def comparable_fp(b):
    return sha({k:(b.get(k) or '') for k in ['check_in','check_out','room_type_key','occupancy_key','meal_plan_key','cancellation_key','tax_fee_key','eligibility_key','currency']})

class ConsumerGrowthDirectValueService:
    def _property(self,s,supplier_id,hotel_id):
        p=s.get(HotelPartnerPropertyRow,hotel_id)
        if not p or p.supplier_id!=supplier_id:raise ValueError('SUPPLIER_HOTEL_NOT_FOUND')
        return p
    def upsert_offer(self,supplier_id,hotel_id,b):
        cash=clamp(b.get('cash_discount_bps',0),0,10000)
        breakfast=(b.get('breakfast_option') or 'NONE').upper()
        if breakfast not in {'NONE','SINGLE','DOUBLE','CHOICE'}:raise ValueError('INVALID_BREAKFAST_OPTION')
        if cash>500: health='PRICE_WAR_RISK'
        elif 100<=cash<=350: health='HEALTHY_CASH_VALUE_BAND'
        elif cash>0: health='CASH_VALUE_OUTSIDE_TARGET_BAND'
        else: health='NO_CASH_DISCOUNT'
        if not (b.get('upgrade_priority') or b.get('late_checkout_priority') or cash>0 or breakfast!='NONE' or b.get('benefits')):raise ValueError('OFFICIAL_DIRECT_VALUE_REQUIRED')
        with SessionLocal() as s:
            self._property(s,supplier_id,hotel_id)
            r=s.scalar(select(DirectValueOfferRow).where(DirectValueOfferRow.supplier_id==supplier_id,DirectValueOfferRow.hotel_id==hotel_id,DirectValueOfferRow.status=='ACTIVE').order_by(DirectValueOfferRow.updated_at.desc()))
            t=now();vals=dict(cash_discount_bps=cash,upgrade_priority=bool(b.get('upgrade_priority')),late_checkout_priority=bool(b.get('late_checkout_priority')),late_checkout_time=b.get('late_checkout_time'),breakfast_option=breakfast,benefits_json=b.get('benefits') or [],supplier_incremental_cost_minor=max(0,int(b.get('supplier_incremental_cost_minor',0))),consumer_perceived_value_minor=max(0,int(b.get('consumer_perceived_value_minor',0))),currency=(b.get('currency') or 'CNY').upper(),starts_at=dt(b.get('starts_at')),ends_at=dt(b.get('ends_at')),authorization_reference=b.get('authorization_reference') or 'SUPPLIER_CONSOLE',updated_at=t)
            if r:
                for k,v in vals.items():setattr(r,k,v)
            else:r=DirectValueOfferRow(direct_value_offer_id=new_id('dvo'),supplier_id=supplier_id,hotel_id=hotel_id,status='ACTIVE',created_at=t,**vals);s.add(r)
            s.commit();return self.offer_out(r)|{'cash_value_health':health,'recommendation_pool_unchanged':True,'three_percent_is_anchor_not_requirement':True}
    def offer_out(self,r):
        return {'direct_value_offer_id':r.direct_value_offer_id,'supplier_id':r.supplier_id,'hotel_id':r.hotel_id,'status':r.status,'cash_discount_bps':r.cash_discount_bps,'upgrade_priority':r.upgrade_priority,'late_checkout_priority':r.late_checkout_priority,'late_checkout_time':r.late_checkout_time,'breakfast_option':r.breakfast_option,'benefits':r.benefits_json,'supplier_incremental_cost_minor':r.supplier_incremental_cost_minor,'consumer_perceived_value_minor':r.consumer_perceived_value_minor,'currency':r.currency,'starts_at':r.starts_at.isoformat() if r.starts_at else None,'ends_at':r.ends_at.isoformat() if r.ends_at else None,'authorization_reference':r.authorization_reference}
    def add_benchmark(self,b):
        if not b.get('authorized_for_consumer',True):raise ValueError('UNAUTHORIZED_BENCHMARK_NOT_ELIGIBLE')
        t=now();fp=comparable_fp(b)
        with SessionLocal() as s:
            r=MarketBenchmarkQuoteRow(benchmark_quote_id=new_id('mbq'),hotel_id=b['hotel_id'],source_provider=b['source_provider'],source_type=b.get('source_type','AUTHORIZED_THIRD_PARTY'),check_in=b['check_in'],check_out=b['check_out'],room_type_key=b['room_type_key'],occupancy_key=b['occupancy_key'],meal_plan_key=b['meal_plan_key'],cancellation_key=b['cancellation_key'],tax_fee_key=b['tax_fee_key'],eligibility_key=b.get('eligibility_key','PUBLIC'),total_amount_minor=int(b['total_amount_minor']),currency=b.get('currency','CNY').upper(),comparable_fingerprint=fp,authorized_for_consumer=True,captured_at=dt(b.get('captured_at')) or t,expires_at=dt(b.get('expires_at')),evidence_json=b.get('evidence') or {});s.add(r);s.commit();return {'benchmark_quote_id':r.benchmark_quote_id,'comparable_fingerprint':fp,'recommendation_pool_unchanged':True}
    def _latest_offer(self,s,hotel_id):
        t=now();return s.scalar(select(DirectValueOfferRow).where(DirectValueOfferRow.hotel_id==hotel_id,DirectValueOfferRow.status=='ACTIVE',((DirectValueOfferRow.starts_at==None)|(DirectValueOfferRow.starts_at<=t)),((DirectValueOfferRow.ends_at==None)|(DirectValueOfferRow.ends_at>=t))).order_by(DirectValueOfferRow.updated_at.desc()))
    def value_layers(self,hotel_id,query=None):
        query=query or {}
        with SessionLocal() as s:
            offer=self._latest_offer(s,hotel_id)
            q=select(MarketBenchmarkQuoteRow).where(MarketBenchmarkQuoteRow.hotel_id==hotel_id,MarketBenchmarkQuoteRow.authorized_for_consumer==True)
            fp=comparable_fp(query) if all(query.get(k) for k in ['check_in','check_out','room_type_key','occupancy_key','meal_plan_key','cancellation_key','tax_fee_key','currency']) else None
            if fp:q=q.where(MarketBenchmarkQuoteRow.comparable_fingerprint==fp)
            benchmarks=s.scalars(q.order_by(MarketBenchmarkQuoteRow.captured_at.desc()).limit(8)).all()
            market=[{'benchmark_quote_id':x.benchmark_quote_id,'provider':x.source_provider,'total_amount_minor':x.total_amount_minor,'currency':x.currency,'captured_at':x.captured_at.isoformat(),'comparable':bool(fp and x.comparable_fingerprint==fp) if fp else True} for x in benchmarks]
            best=min((x.total_amount_minor for x in benchmarks),default=None)
            direct_rate=int(query.get('direct_rate_minor') or 0) or None
            cash_adv=None
            if direct_rate and best and best>0:cash_adv=round((best-direct_rate)*10000/best)
            benefits=[]
            if offer:
                if offer.upgrade_priority:benefits.append({'type':'UPGRADE_PRIORITY_WHEN_AVAILABLE','priority':1})
                if offer.late_checkout_priority:benefits.append({'type':'LATE_CHECKOUT_PRIORITY_WHEN_AVAILABLE','priority':2,'time':offer.late_checkout_time})
                if offer.cash_discount_bps:benefits.append({'type':'CASH_PRICE_ADVANTAGE','priority':3,'target_bps':offer.cash_discount_bps})
                if offer.breakfast_option!='NONE':benefits.append({'type':'BREAKFAST','priority':4,'option':offer.breakfast_option})
                benefits+=offer.benefits_json or []
            return {'hotel_id':hotel_id,'go_recommendation':{'separate_pool':True,'commercial_value_can_buy_recommendation':False},'official_direct_value':None if not offer else self.offer_out(offer)|{'benefits_priority':benefits,'three_percent_cash_anchor_bps':300,'cash_discount_not_mandatory':True,'price_war_not_encouraged':True},'market_price_benchmark':{'role':'MARKET_REFERENCE_AND_FALLBACK_NOT_STRATEGIC_CENTER','quotes':market,'best_public_comparable_minor':best},'comparison':{'comparable_rate_gate':bool(fp),'direct_cash_advantage_bps':cash_adv},'direct_first':True}
    def simulate_economics(self,supplier_id,hotel_id,b):
        direct=max(0,int(b['direct_rate_minor']));market=int(b.get('market_rate_minor') or direct);ota=clamp(b.get('ota_channel_cost_bps',1500),0,10000);go=clamp(b.get('go_direct_cost_bps',300),0,10000);cash=clamp(b.get('cash_discount_bps',0),0,10000);inc=max(0,int(b.get('supplier_incremental_cost_minor',0)));shared=max(0,int(b.get('consumer_value_shared_minor',0)))
        ota_net=market*(10000-ota)//10000;go_net=direct*(10000-go)//10000-inc;uplift=go_net-ota_net
        reasons=[]
        if 100<=cash<=350:reasons.append('HEALTHY_CASH_VALUE_BAND')
        if cash>500:reasons.append('PRICE_WAR_RISK_REVIEW')
        if uplift>0:reasons.append('SUPPLIER_EARNS_MORE_AFTER_VALUE_SHARE')
        if shared==0 and cash==0 and inc==0:reasons.append('CONSUMER_VALUE_SIGNAL_WEAK')
        with SessionLocal() as s:
            self._property(s,supplier_id,hotel_id);offer=self._latest_offer(s,hotel_id)
            r=SupplierChannelEconomicsRow(channel_economics_id=new_id('sce'),supplier_id=supplier_id,hotel_id=hotel_id,direct_value_offer_id=offer.direct_value_offer_id if offer else None,direct_rate_minor=direct,market_rate_minor=market,ota_channel_cost_bps=ota,go_direct_cost_bps=go,cash_discount_bps=cash,consumer_value_shared_minor=shared,supplier_incremental_cost_minor=inc,ota_net_revenue_minor=ota_net,go_net_revenue_minor=go_net,net_revenue_uplift_minor=uplift,currency=b.get('currency','CNY').upper(),assumptions_json=b.get('assumptions') or {},created_at=now());s.add(r)
            perceived=max(shared,offer.consumer_perceived_value_minor if offer else 0);cost=max(inc,offer.supplier_incremental_cost_minor if offer else 0);eff=perceived*10000//cost if cost else (100000 if perceived else 0)
            typ='KEEP_VALUE_MIX' if uplift>=0 and perceived>0 else 'ADD_LOW_COST_HIGH_PERCEIVED_VALUE' if uplift>=0 else 'REDUCE_SUPPLIER_COST_OR_CASH_DISCOUNT'
            rec=DirectValueRecommendationRow(direct_value_recommendation_id=new_id('dvr'),supplier_id=supplier_id,hotel_id=hotel_id,direct_value_offer_id=offer.direct_value_offer_id if offer else None,recommendation_type=typ,proposed_cash_discount_bps=min(300,cash or 300),proposed_benefits_json=['UPGRADE_PRIORITY_WHEN_AVAILABLE','LATE_CHECKOUT_PRIORITY_WHEN_AVAILABLE'],consumer_perceived_value_minor=perceived,supplier_incremental_cost_minor=cost,value_efficiency_bps=eff,reason_codes_json=reasons,recommendation_pool_unchanged=True,created_at=now());s.add(rec);s.commit()
            return {'channel_economics_id':r.channel_economics_id,'ota_net_revenue_minor':ota_net,'go_net_revenue_minor':go_net,'net_revenue_uplift_minor':uplift,'consumer_value_shared_minor':shared,'supplier_incremental_cost_minor':inc,'recommendation':{'type':typ,'reason_codes':reasons,'value_efficiency_bps':eff},'recommendation_pool_unchanged':True,'principle':'SUPPLIER_KEEPS_MAJORITY_SHARE_SMALL_PART_WITH_CONSUMER'}
    def supplier_economics(self,supplier_id,hotel_id,limit=20):
        with SessionLocal() as s:
            self._property(s,supplier_id,hotel_id);rows=s.scalars(select(SupplierChannelEconomicsRow).where(SupplierChannelEconomicsRow.supplier_id==supplier_id,SupplierChannelEconomicsRow.hotel_id==hotel_id).order_by(SupplierChannelEconomicsRow.created_at.desc()).limit(limit)).all()
            return [{'channel_economics_id':x.channel_economics_id,'direct_rate_minor':x.direct_rate_minor,'market_rate_minor':x.market_rate_minor,'ota_channel_cost_bps':x.ota_channel_cost_bps,'go_direct_cost_bps':x.go_direct_cost_bps,'consumer_value_shared_minor':x.consumer_value_shared_minor,'supplier_incremental_cost_minor':x.supplier_incremental_cost_minor,'ota_net_revenue_minor':x.ota_net_revenue_minor,'go_net_revenue_minor':x.go_net_revenue_minor,'net_revenue_uplift_minor':x.net_revenue_uplift_minor,'created_at':x.created_at.isoformat()} for x in rows]
    def record_event(self,user_id,event_type,**kw):
        allowed={'USER_REGISTERED','USER_ACTIVATED','PROFILE_CREATED','TRAVELER_ADDED','TRAVELER_INVITED','TRAVELER_CLAIMED','TRIP_CREATED','TRIP_SHARED','TRIP_JOINED','AI_PLAN_SHARED','OFFER_SHARED','DIRECT_ORDER_COMPLETED','DIRECT_VALUE_SHARED','STAFF_ACTIVATED','SUPPLIER_TRAFFIC_REGISTERED','TRIP_IMPORT_RECEIVED'}
        if event_type not in allowed:raise ValueError('INVALID_GROWTH_EVENT_TYPE')
        t=now()
        with SessionLocal() as s:
            e=ConsumerGrowthEventRow(growth_event_id=new_id('cge'),user_id=user_id,event_type=event_type,source_surface=kw.get('source_surface'),object_type=kw.get('object_type'),object_id=kw.get('object_id'),referrer_user_id=kw.get('referrer_user_id'),journey_id=kw.get('journey_id'),supplier_id=kw.get('supplier_id'),metadata_json=kw.get('metadata') or {},occurred_at=t);s.add(e)
            if user_id:
                a=s.scalar(select(ConsumerGrowthAttributionRow).where(ConsumerGrowthAttributionRow.user_id==user_id))
                if not a:
                    a=ConsumerGrowthAttributionRow(growth_attribution_id=new_id('cga'),user_id=user_id,acquisition_source=kw.get('acquisition_source') or kw.get('source_surface'),registration_trigger=kw.get('registration_trigger'),activation_trigger=None,referrer_user_id=kw.get('referrer_user_id'),supplier_id=kw.get('supplier_id'),first_seen_at=t,registered_at=t if event_type=='USER_REGISTERED' else None,activated_at=None,updated_at=t);s.add(a)
                if event_type=='USER_REGISTERED' and not a.registered_at:a.registered_at=t;a.registration_trigger=a.registration_trigger or kw.get('registration_trigger') or kw.get('source_surface')
                if event_type in {'PROFILE_CREATED','TRIP_CREATED','TRIP_JOINED','TRAVELER_CLAIMED','DIRECT_ORDER_COMPLETED','STAFF_ACTIVATED','USER_ACTIVATED'} and not a.activated_at:a.activated_at=t;a.activation_trigger=event_type
                a.updated_at=t
            s.commit();return {'growth_event_id':e.growth_event_id,'event_type':event_type,'occurred_at':t.isoformat()}
    def create_trip_invite(self,user_id,journey_id,b):
        token=secrets.token_urlsafe(24);t=now();exp=t+timedelta(days=max(1,min(30,int(b.get('expires_in_days',7)))))
        with SessionLocal() as s:
            j=s.get(GoJourneyRow,journey_id)
            if not j or j.account_id!=user_id:raise ValueError('JOURNEY_NOT_FOUND')
            r=ConsumerTripInvitationRow(invitation_id=new_id('cti'),journey_id=journey_id,inviter_user_id=user_id,invite_token_hash=sha(token),invitee_hint_hash=sha((b.get('invitee_hint') or '').strip().lower()) if b.get('invitee_hint') else None,status='ACTIVE',joined_user_id=None,expires_at=exp,created_at=t,joined_at=None);s.add(r);s.commit()
        self.record_event(user_id,'TRIP_SHARED',source_surface='GO_TRIPS',object_type='JOURNEY',object_id=journey_id,journey_id=journey_id)
        return {'invitation_id':r.invitation_id,'invite_token':token,'deep_link':f'go://trips/invite/{token}','expires_at':exp.isoformat()}
    def join_trip(self,user_id,token):
        th=sha(token);t=now()
        with SessionLocal() as s:
            r=s.scalar(select(ConsumerTripInvitationRow).where(ConsumerTripInvitationRow.invite_token_hash==th))
            if not r or r.status!='ACTIVE' or aware(r.expires_at)<=t:raise ValueError('TRIP_INVITATION_NOT_AVAILABLE')
            if r.inviter_user_id==user_id:raise ValueError('INVITER_CANNOT_JOIN_OWN_INVITE')
            r.status='JOINED';r.joined_user_id=user_id;r.joined_at=t
            member=s.scalar(select(ConsumerTripMemberRow).where(ConsumerTripMemberRow.journey_id==r.journey_id,ConsumerTripMemberRow.user_id==user_id))
            if not member:
                member=ConsumerTripMemberRow(trip_member_id=new_id('ctm'),journey_id=r.journey_id,user_id=user_id,role='MEMBER',status='ACTIVE',source_invitation_id=r.invitation_id,joined_at=t);s.add(member)
            s.commit();jid=r.journey_id;ref=r.inviter_user_id
        self.record_event(user_id,'TRIP_JOINED',source_surface='TRIP_INVITE',object_type='JOURNEY',object_id=jid,journey_id=jid,referrer_user_id=ref,acquisition_source='TRIP_INVITE',registration_trigger='TRIP_INVITE')
        return {'journey_id':jid,'joined':True,'collaboration_scope':'SHARED_TRIP_VIEW','source_owner_user_id':ref}
    def create_claim(self,user_id,traveler_id,target_email):
        token=secrets.token_urlsafe(24);t=now();email_hash=sha(target_email.strip().lower())
        with SessionLocal() as s:
            tr=s.get(TravelerProfileRow,traveler_id)
            if not tr or tr.user_id!=user_id:raise ValueError('TRAVELER_NOT_FOUND')
            if tr.relationship_type=='CHILD':raise ValueError('MINOR_TRAVELER_USES_GUARDIAN_MODEL')
            r=TravelerClaimRow(traveler_claim_id=new_id('tcl'),traveler_id=traveler_id,owner_user_id=user_id,target_email_hash=email_hash,claim_token_hash=sha(token),status='PENDING',claimed_user_id=None,created_at=t,expires_at=t+timedelta(days=7),claimed_at=None);s.add(r);s.commit()
        self.record_event(user_id,'TRAVELER_INVITED',source_surface='PERSONAL_VAULT',object_type='TRAVELER',object_id=traveler_id)
        return {'traveler_claim_id':r.traveler_claim_id,'claim_token':token,'deep_link':f'go://profile/claim/{token}','expires_at':r.expires_at.isoformat()}
    def accept_claim(self,user_id,token):
        th=sha(token);t=now()
        with SessionLocal() as s:
            r=s.scalar(select(TravelerClaimRow).where(TravelerClaimRow.claim_token_hash==th))
            if not r or r.status!='PENDING' or aware(r.expires_at)<=t:raise ValueError('TRAVELER_CLAIM_NOT_AVAILABLE')
            cp=s.get(ConsumerProfileRow,user_id)
            if not cp or sha(cp.email.strip().lower())!=r.target_email_hash:raise ValueError('TRAVELER_CLAIM_IDENTITY_MISMATCH')
            tr=s.get(TravelerProfileRow,r.traveler_id)
            if not tr or tr.relationship_type=='CHILD':raise ValueError('MINOR_TRAVELER_USES_GUARDIAN_MODEL')
            r.status='CLAIMED';r.claimed_user_id=user_id;r.claimed_at=t;s.commit();owner=r.owner_user_id;trav=r.traveler_id
        self.record_event(user_id,'TRAVELER_CLAIMED',source_surface='TRAVELER_CLAIM',object_type='TRAVELER',object_id=trav,referrer_user_id=owner,acquisition_source='TRAVELER_CLAIM',registration_trigger='TRAVELER_CLAIM')
        return {'traveler_claim_id':r.traveler_claim_id,'traveler_id':trav,'claimed':True,'data_transfer':'NO_AUTOMATIC_SENSITIVE_FACT_TRANSFER','next_step':'EXPLICIT_PERMISSION_AND_IDENTITY_RESOLUTION'}
    def create_trip_import_intent(self,user_id,b):
        src=(b.get('source_type') or 'SHARE_TO_GO').upper()
        if src not in {'SHARE_TO_GO','SCREENSHOT','PDF','FILE','EMAIL','TEXT','OFFICIAL_API'}:raise ValueError('INVALID_TRIP_IMPORT_SOURCE')
        ch=b.get('content_hash') or sha({'source':src,'provider':b.get('source_provider'),'ref':b.get('source_reference')})
        t=now()
        with SessionLocal() as s:
            old=s.scalar(select(TripImportIntentRow).where(TripImportIntentRow.user_id==user_id,TripImportIntentRow.content_hash==ch).order_by(TripImportIntentRow.created_at.desc()))
            if old:return {'trip_import_intent_id':old.trip_import_intent_id,'status':old.status,'idempotent_replay':True}
            r=TripImportIntentRow(trip_import_intent_id=new_id('tii'),user_id=user_id,source_type=src,source_provider=b.get('source_provider'),source_reference=b.get('source_reference'),content_hash=ch,status='RECEIVED',detected_verticals_json=b.get('detected_verticals') or [],created_journey_id=None,created_at=t,updated_at=t);s.add(r);s.commit()
        self.record_event(user_id,'TRIP_IMPORT_RECEIVED',source_surface=src,object_type='TRIP_IMPORT_INTENT',object_id=r.trip_import_intent_id)
        return {'trip_import_intent_id':r.trip_import_intent_id,'status':'RECEIVED','trigger_required':True,'supported_triggers':['SHARE_TO_GO','SCREENSHOT','PDF','FILE','EMAIL','TEXT','OFFICIAL_API'],'no_background_ota_account_scraping':True}
    def growth_metrics(self,days=30):
        since=now()-timedelta(days=max(1,min(365,days)))
        with SessionLocal() as s:
            events=s.scalars(select(ConsumerGrowthEventRow).where(ConsumerGrowthEventRow.occurred_at>=since)).all();attrs=s.scalars(select(ConsumerGrowthAttributionRow).where(ConsumerGrowthAttributionRow.first_seen_at>=since)).all()
            activated={x.user_id for x in attrs if x.activated_at and aware(x.activated_at)>=since};organic={x.user_id for x in attrs if x.activated_at and aware(x.activated_at)>=since and (x.acquisition_source or '') not in {'PAID_AD','PAID_SEARCH'}}
            generated={e.user_id for e in events if e.event_type in {'TRIP_JOINED','TRAVELER_CLAIMED'} and e.user_id}
            base={e.user_id for e in events if e.user_id and e.event_type in {'PROFILE_CREATED','TRIP_CREATED','DIRECT_ORDER_COMPLETED','STAFF_ACTIVATED'}}
            return {'days':days,'matu':len(activated),'organic_activated_user_ratio':round(len(organic)/len(activated),4) if activated else 0.0,'consumer_cellular_k':round(len(generated)/len(base),4) if base else 0.0,'events':len(events),'activated_users':len(activated),'generated_activated_users':len(generated),'definition':'Consumer Cellular K = naturally generated activated users / activated source users'}
    def admin_overview(self):
        with SessionLocal() as s:
            offers=s.scalars(select(DirectValueOfferRow).where(DirectValueOfferRow.status=='ACTIVE')).all();bench=s.scalar(select(func.count()).select_from(MarketBenchmarkQuoteRow)) or 0;econ=s.scalars(select(SupplierChannelEconomicsRow).order_by(SupplierChannelEconomicsRow.created_at.desc()).limit(100)).all()
            return {'active_direct_value_offers':len(offers),'upgrade_priority_offers':sum(1 for x in offers if x.upgrade_priority),'late_checkout_priority_offers':sum(1 for x in offers if x.late_checkout_priority),'cash_value_offers':sum(1 for x in offers if x.cash_discount_bps>0),'breakfast_offers':sum(1 for x in offers if x.breakfast_option!='NONE'),'benchmark_quotes':bench,'latest_net_revenue_uplift_minor':sum((x.net_revenue_uplift_minor or 0) for x in econ),'growth':self.growth_metrics(30),'recommendation_pool_unchanged':True}
consumer_growth_direct_value_service=ConsumerGrowthDirectValueService()
