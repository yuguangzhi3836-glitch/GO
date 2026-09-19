from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, re, unicodedata, uuid
from sqlalchemy import select, func
from go_hotel.services import catalog_scope
from go_hotel.autonomy.durable import transaction
from go_hotel.db.session import SessionLocal
from go_hotel.services.media_harvester import media_harvester_service
from go_hotel.services.hotel_catalog_quality import quality
from go_hotel.db.models import (
    HotelContentSourceSnapshotRow, HotelCanonicalProfileRow, HotelContactPointRow,
    HotelAutoPageVersionRow, HotelRegistrationDirectRow, HotelAutoPageEventRow,
)

ALLOWED_RIGHTS={'AUTHORIZED','HOTEL_SUBMITTED','PUBLIC_BUSINESS_FACT','DISTRIBUTION_LICENSE'}
SOURCE_PRIORITY={
    'HOTEL_OFFICIAL_SUBMISSION':100,'OFFICIAL_WEBSITE':95,'GROUP_OFFICIAL':94,'CRS_PMS':90,
    'CONTENT_PROVIDER':80,'AUTHORIZED_DISTRIBUTOR':70,'OTA_DISTRIBUTION':68,'OTA_DISCOVERY':46,'PUBLIC_SOURCE':45,
}
PAGE_FIELDS=['name','name_zh','name_en','brand','group','address','latitude','longitude','description','facilities','media','rooms','policies','poi','website','media_candidates','catalog_manifest','direct_submission']


def now(): return datetime.now(timezone.utc)
def utc(value): return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
def ident(prefix): return f'{prefix}_{uuid.uuid4().hex}'
def dump(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def sha(v): return hashlib.sha256(dump(v).encode()).hexdigest()
def out(row):
    if row is None:return None
    return {c.name:(getattr(row,c.name).isoformat() if isinstance(getattr(row,c.name),datetime) else getattr(row,c.name)) for c in row.__table__.columns}

def _norm_text(s):
    s=unicodedata.normalize('NFKC',str(s or '')).strip().lower()
    return re.sub(r'[^0-9a-z\u4e00-\u9fff]+','',s)

def _slug(s):
    base=unicodedata.normalize('NFKC',str(s or 'hotel')).strip().lower()
    base=re.sub(r'[^0-9a-z\u4e00-\u9fff]+','-',base).strip('-') or 'hotel'
    return base[:140]

def _contact_norm(channel,value):
    v=str(value or '').strip()
    return v.lower() if channel=='EMAIL' else re.sub(r'[^0-9+]','',v)

class HotelAutoPageFactoryService:
    def _event(self,s,hotel_id,event,evidence,actor):
        s.add(HotelAutoPageEventRow(hotel_auto_page_event_id=ident('hape'),hotel_id=hotel_id,event_type=event,evidence_json=evidence,actor=actor,created_at=now()))

    def _match_profile(self,s,b):
        def locked(hotel_id):
            return s.scalar(select(HotelCanonicalProfileRow).where(HotelCanonicalProfileRow.hotel_id==hotel_id).with_for_update())
        explicit=b.get('canonical_hotel_id')
        if explicit:
            r=locked(explicit)
            if not r: raise ValueError('EXPLICIT_CANONICAL_HOTEL_NOT_FOUND')
            return r
        # Stable provider identity is stronger than mutable hotel content. Reuse an existing
        # Canonical Hotel whenever the same source identity is observed with a new snapshot.
        if b.get('source_key') and b.get('external_hotel_id'):
            snap=s.scalar(select(HotelContentSourceSnapshotRow).where(
                HotelContentSourceSnapshotRow.source_key==b['source_key'],
                HotelContentSourceSnapshotRow.external_hotel_id==b['external_hotel_id'],
                HotelContentSourceSnapshotRow.canonical_hotel_id.is_not(None),
            ).order_by(HotelContentSourceSnapshotRow.observed_at.desc()))
            if snap:
                r=locked(snap.canonical_hotel_id)
                if r:return r
        p=b.get('payload') or {}
        name=_norm_text(p.get('name') or p.get('name_zh') or p.get('name_en'))
        addr=_norm_text((p.get('address') or {}).get('formatted') if isinstance(p.get('address'),dict) else p.get('address'))
        if not name:return None
        matches=[]
        for r in s.scalars(select(HotelCanonicalProfileRow)).all():
            c=r.canonical_json or {}
            rn=_norm_text(c.get('name') or c.get('name_zh') or c.get('name_en'))
            ra=_norm_text((c.get('address') or {}).get('formatted') if isinstance(c.get('address'),dict) else c.get('address'))
            if rn==name and addr and ra and ra==addr:
                matches.append(r);continue
            if rn==name and p.get('latitude') is not None and p.get('longitude') is not None and c.get('latitude') is not None and c.get('longitude') is not None:
                try:
                    # Approximate proximity gate (~250m) prevents duplicate Canonical hotels when address formatting differs.
                    if abs(float(p['latitude'])-float(c['latitude'])) <= 0.0025 and abs(float(p['longitude'])-float(c['longitude'])) <= 0.0035:
                        matches.append(r)
                except Exception:
                    pass
        if len(matches)>1: raise ValueError('CANONICAL_IDENTITY_AMBIGUOUS')
        return locked(matches[0].hotel_id) if matches else None

    def _ingest_locks(self,s,b):
        # Serialize provider identity and same-name identity decisions, including
        # the no-row-yet case. Transaction-scoped locks release on rollback too.
        # SQLite's transaction() reserves the writer before any matching reads.
        if s.bind.dialect.name=='postgresql':
            payload=b['payload']
            names=['source:'+str(b['source_key'])+':'+str(b['external_hotel_id']),
                   'name:'+_norm_text(payload.get('name') or payload.get('name_zh') or payload.get('name_en'))]
            if b.get('canonical_hotel_id'): names.append('canonical:'+b['canonical_hotel_id'])
            keys=sorted({int.from_bytes(hashlib.sha256(('go.hotel.catalog:'+n).encode()).digest()[:8],'big',signed=True) for n in names})
            for key in keys:s.execute(select(func.pg_advisory_xact_lock(key)))

    def catalog_quality(self,profile):
        return quality(profile.canonical_json,profile.field_provenance_json,
            media_harvester_service.list_assets(hotel_id=profile.hotel_id),hotel_id=profile.hotel_id,
            verify_asset=media_harvester_service.content_path)

    def _catalog_media(self,hotel_id,catalog):
        if isinstance(catalog,dict) and 'direct_submission' in catalog:
            from go_hotel.services.hotel_direct_submission_publication import direct_media
            try:return direct_media(catalog,hotel_id)
            except (ValueError,KeyError,TypeError,OSError):
                return {'hero':[],'gallery':[],'rooms':{},'dining':[],'facility':[],'meeting':[],'poi':[]}
        expected={(x.get('role'),x.get('room_type_id'),x.get('source_url'))
            for x in (catalog or {}).get('media_candidates',[]) if isinstance(x,dict)}
        allowed=set()
        for asset in media_harvester_service.list_assets(hotel_id=hotel_id,publishable_only=True):
            if asset.get('source_type') not in {'OFFICIAL_WEBSITE','GROUP_OFFICIAL','HOTEL_OFFICIAL_SUBMISSION'}:continue
            if (asset.get('role'),asset.get('room_type_id'),asset.get('source_url')) not in expected:continue
            try:media_harvester_service.content_path(asset['asset_id'])
            except (ValueError,OSError):continue
            allowed.add(asset['asset_id'])
        return media_harvester_service.page_media(hotel_id,asset_ids=allowed)

    def _paused(self,s,hotel_id):
        last=s.scalar(select(HotelAutoPageEventRow).where(HotelAutoPageEventRow.hotel_id==hotel_id,
            HotelAutoPageEventRow.event_type.in_(['AUTO_PAGE_UNPUBLISHED','AUTO_PAGE_MANUAL_PUBLISHED']))
            .order_by(HotelAutoPageEventRow.created_at.desc(),HotelAutoPageEventRow.hotel_auto_page_event_id.desc()))
        return bool(last and last.event_type=='AUTO_PAGE_UNPUBLISHED')

    def _unique_slug(self,s,name,hotel_id):
        base=_slug(name)
        slug=base; i=2
        while (x:=s.scalar(select(HotelCanonicalProfileRow).where(HotelCanonicalProfileRow.slug==slug))) and x.hotel_id!=hotel_id:
            slug=f'{base}-{i}';i+=1
        return slug

    def _extract_contacts(self,payload):
        contacts=[]
        raw=payload.get('contacts') or []
        if isinstance(raw,dict):
            raw=[{'contact_type':k.upper(),'channel':'EMAIL' if '@' in str(v) else 'PHONE','value':v} for k,v in raw.items()]
        for x in raw:
            if not isinstance(x,dict) or not x.get('value'):continue
            ch=str(x.get('channel') or ('EMAIL' if '@' in str(x['value']) else 'PHONE')).upper()
            contacts.append({
                'contact_type':str(x.get('contact_type') or 'GENERAL').upper(),'channel':ch,'value':str(x['value']).strip(),
                'is_public_business_contact':bool(x.get('is_public_business_contact',False)),
                'jurisdiction':x.get('jurisdiction'),'marketing_eligibility':x.get('marketing_eligibility'),
            })
        for key,typ,ch in [('email','GENERAL','EMAIL'),('phone','GENERAL','PHONE'),('reservations_email','RESERVATIONS','EMAIL'),('sales_email','SALES','EMAIL'),('reservations_phone','RESERVATIONS','PHONE'),('sales_phone','SALES','PHONE')]:
            if payload.get(key):contacts.append({'contact_type':typ,'channel':ch,'value':str(payload[key]).strip(),'is_public_business_contact':True,'jurisdiction':payload.get('country_code')})
        return contacts

    def _upsert_contacts(self,s,hotel_id,snap,b):
        for c in self._extract_contacts(b.get('payload') or {}):
            n=_contact_norm(c['channel'],c['value'])
            if not n:continue
            r=s.scalar(select(HotelContactPointRow).where(HotelContactPointRow.hotel_id==hotel_id,HotelContactPointRow.channel==c['channel'],HotelContactPointRow.normalized_value==n))
            eligibility=c.get('marketing_eligibility') or ('ELIGIBLE_FOR_POLICY_CHECK' if c['is_public_business_contact'] else 'REVIEW_REQUIRED')
            vals=dict(contact_type=c['contact_type'],value=c['value'],source_url=b.get('source_url'),source_type=b['source_type'],is_public_business_contact=c['is_public_business_contact'],jurisdiction=c.get('jurisdiction'),confidence_bps=int(b.get('confidence_bps',5000)),marketing_eligibility=eligibility,updated_at=now())
            if r:
                for k,v in vals.items():setattr(r,k,v)
            else:
                s.add(HotelContactPointRow(hotel_contact_point_id=ident('hcp'),hotel_id=hotel_id,channel=c['channel'],normalized_value=n,do_not_contact=False,verified_at=None,created_at=now(),**vals))

    def _merge(self,s,profile):
        snaps=s.scalars(select(HotelContentSourceSnapshotRow).where(HotelContentSourceSnapshotRow.canonical_hotel_id==profile.hotel_id)).all()
        # Old versions of the same source are historical evidence, not current
        # competing facts. In particular, removed rooms must not reappear.
        latest={}
        for snap in sorted(snaps,key=lambda x:(utc(x.observed_at).timestamp(),utc(x.created_at).timestamp(),x.content_source_snapshot_id)):
            latest[(snap.source_key,snap.external_hotel_id)]=snap
        current=list(latest.values())
        chosen={}; provenance={}
        for snap in current:
            rank=SOURCE_PRIORITY.get(snap.source_type,10)
            payload=snap.payload_json or {}
            for field in PAGE_FIELDS:
                val=payload.get(field)
                if val in (None,'',[],{}):continue
                score=(rank,int(snap.confidence_bps),utc(snap.observed_at).timestamp())
                if field not in chosen or score>chosen[field][0]:
                    chosen[field]=(score,val)
                    provenance[field]={'snapshot_id':snap.content_source_snapshot_id,'source_key':snap.source_key,'source_type':snap.source_type,'source_url':snap.source_url,'rights_status':snap.rights_status,'confidence_bps':snap.confidence_bps,'observed_at':utc(snap.observed_at).isoformat()}
        # Preserve field-level conflict evidence instead of silently hiding disagreeing sources.
        for field in PAGE_FIELDS:
            vals=[]
            for snap in current:
                val=(snap.payload_json or {}).get(field)
                if val in (None,'',[],{}):continue
                marker=dump(val)
                if marker not in [x['marker'] for x in vals]:
                    vals.append({'marker':marker,'value':val,'snapshot_id':snap.content_source_snapshot_id,'source_key':snap.source_key})
            if len(vals)>1 and field in provenance:
                provenance[field]['conflict_state']='REVIEW_REQUIRED'
                provenance[field]['conflict_candidates']=[{'value':x['value'],'snapshot_id':x['snapshot_id'],'source_key':x['source_key']} for x in vals]
        canonical={k:v[1] for k,v in chosen.items()}
        canonical.setdefault('name',canonical.get('name_zh') or canonical.get('name_en'))
        profile.canonical_json=canonical;profile.field_provenance_json=provenance
        profile.source_snapshot_ids_json=[x.content_source_snapshot_id for x in snaps]
        weights={'name':1500,'address':1500,'media':1200,'facilities':1000,'description':900,'rooms':1200,'policies':700,'website':500,'latitude':250,'longitude':250,'poi':500,'brand':250,'group':250}
        got=0
        for f,w in weights.items():
            if canonical.get(f) not in (None,'',[],{}):got+=w
        profile.completeness_bps=min(10000,got)
        profile.version+=1;profile.updated_at=now()
        return canonical,provenance

    def _page_json(self,s,profile):
        c=profile.canonical_json or {}
        contacts=s.scalars(select(HotelContactPointRow).where(HotelContactPointRow.hotel_id==profile.hotel_id)).all()
        public_contacts=[{'type':x.contact_type,'channel':x.channel,'value':x.value} for x in contacts if x.is_public_business_contact and not x.do_not_contact]
        go_direct_verified=profile.go_direct_state in {'GO_DIRECT_VERIFIED','GO_DIRECT_LIVE'}
        publishable_media=self._catalog_media(profile.hotel_id,c)
        return {
            'hotel_id':profile.hotel_id,'slug':profile.slug,'page_owner':'GO','page_kind':'GO_PREBUILT_HOTEL_PAGE',
            'go_direct_state':profile.go_direct_state,'hotel_registration_required_for_page':False,
            'identity':{'name':c.get('name'),'name_zh':c.get('name_zh'),'name_en':c.get('name_en'),'brand':c.get('brand'),'group':c.get('group')},
            'hero':{'media':publishable_media.get('hero',[]),'description':c.get('description')},
            'media':publishable_media,
            'location':{'address':c.get('address'),'latitude':c.get('latitude'),'longitude':c.get('longitude'),'poi':c.get('poi',[])},
            'hotel_facts':{'facilities':c.get('facilities',[]),'rooms':c.get('rooms',[]),'policies':c.get('policies',[])},
            'contact':{'website':c.get('website'),'public_business_contacts':public_contacts},
            'trust':{
                'completeness_bps':profile.completeness_bps,
                'source_provenance_available':True,
                'media_rights_gate_enforced':True,
                'raw_external_media_never_published_without_rights':True,
                'go_direct_verified':go_direct_verified,
                'display_disclaimer':'酒店主体已完成GO直连身份核验；酒店提交资料与GO多源事实均保留来源和版本证据。' if go_direct_verified else 'GO整理公开及授权资料；酒店注册并完成身份核验后可校对或补充官方资料。',
            },
            'transaction':{'route':'UNRESOLVED_UNTIL_SUPPLY_QUERY','official_direct':False},
        }

    def _publish_version(self,s,profile,actor):
        report=self.catalog_quality(profile)
        paused=self._paused(s,profile.hotel_id)
        state='PUBLISHED' if report['passed'] and not paused else 'DRAFT'
        page=self._page_json(s,profile)
        # Kept in the immutable version for re-validating the last good page.
        # These keys are removed by every page projection returned to a client.
        page['_catalog_evidence']={'catalog':profile.canonical_json,'provenance':profile.field_provenance_json}
        h=sha({'page':page,'publication_state':state})
        latest=s.scalar(select(HotelAutoPageVersionRow).where(HotelAutoPageVersionRow.hotel_id==profile.hotel_id).order_by(HotelAutoPageVersionRow.version.desc()))
        prior=s.scalar(select(HotelAutoPageVersionRow).where(HotelAutoPageVersionRow.hotel_id==profile.hotel_id,
            HotelAutoPageVersionRow.publication_state=='PUBLISHED').order_by(HotelAutoPageVersionRow.version.desc()))
        profile.page_state='PUBLISHED' if not paused and (state=='PUBLISHED' or prior is not None) else 'DRAFT'
        if latest and latest.page_hash==h:return latest
        version=(latest.version+1) if latest else 1
        row=HotelAutoPageVersionRow(hotel_auto_page_version_id=ident('hapv'),hotel_id=profile.hotel_id,slug=profile.slug,version=version,page_json=page,page_hash=h,source_snapshot_ids_json=profile.source_snapshot_ids_json,go_direct_state=profile.go_direct_state,publication_state=state,created_at=now())
        s.add(row);self._event(s,profile.hotel_id,'AUTO_PAGE_PUBLISHED' if state=='PUBLISHED' else 'AUTO_PAGE_CANDIDATE_COMPOSED',{'page_version':version,'page_hash':h,'go_direct_state':profile.go_direct_state,'page_state':state,'catalog_quality':report},actor)
        return row

    def ingest(self,b,actor='SYSTEM',*,require_publishable=False,preserve_current_facts=False):
        if b.get('rights_status') not in ALLOWED_RIGHTS:raise ValueError('CONTENT_RIGHTS_NOT_ALLOWED')
        if b.get('source_type') not in SOURCE_PRIORITY:raise ValueError('UNSUPPORTED_CONTENT_SOURCE_TYPE')
        if not b.get('source_key') or not b.get('external_hotel_id') or not isinstance(b.get('payload'),dict):raise ValueError('INVALID_CONTENT_SOURCE_PAYLOAD')
        ph=sha(b['payload']); t=now()
        with transaction(SessionLocal) as s:
            catalog_scope.scope_lock(s)
            self._ingest_locks(s,b)
            known=set(s.scalars(select(HotelContentSourceSnapshotRow.canonical_hotel_id).where(
                HotelContentSourceSnapshotRow.source_key==b['source_key'],
                HotelContentSourceSnapshotRow.external_hotel_id==b['external_hotel_id'],
                HotelContentSourceSnapshotRow.canonical_hotel_id.is_not(None))).all())
            if len(known)>1 or known and b.get('canonical_hotel_id') and b['canonical_hotel_id'] not in known:
                raise ValueError('SOURCE_CANONICAL_IDENTITY_CONFLICT')
            existing=s.scalar(select(HotelContentSourceSnapshotRow).where(HotelContentSourceSnapshotRow.source_key==b['source_key'],HotelContentSourceSnapshotRow.external_hotel_id==b['external_hotel_id'],HotelContentSourceSnapshotRow.payload_hash==ph))
            if existing:
                catalog_scope.require_hotel(s,existing.canonical_hotel_id)
                p=s.get(HotelCanonicalProfileRow,existing.canonical_hotel_id) if existing.canonical_hotel_id else None
                return {'idempotent':True,'snapshot':out(existing),'profile':out(p),'page':self.public_page_by_hotel(existing.canonical_hotel_id) if p else None,'catalog_quality':self.catalog_quality(p) if p else None}
            p=self._match_profile(s,b)
            catalog_scope.require_hotel(s,p.hotel_id if p else None)
            if not p:
                hid=b.get('canonical_hotel_id') or ident('hotel');name=b['payload'].get('name') or b['payload'].get('name_zh') or b['payload'].get('name_en') or b['external_hotel_id']
                p=HotelCanonicalProfileRow(hotel_id=hid,slug=self._unique_slug(s,name,hid),canonical_json={},field_provenance_json={},source_snapshot_ids_json=[],completeness_bps=0,go_direct_state='NOT_REGISTERED',page_state='DRAFT',version=0,created_at=t,updated_at=t);s.add(p);s.flush()
            snap=HotelContentSourceSnapshotRow(content_source_snapshot_id=ident('hcss'),source_key=b['source_key'],source_type=b['source_type'],external_hotel_id=b['external_hotel_id'],source_url=b.get('source_url'),rights_status=b['rights_status'],confidence_bps=int(b.get('confidence_bps',5000)),payload_json=b['payload'],payload_hash=ph,canonical_hotel_id=p.hotel_id,observed_at=b.get('observed_at') or t,created_at=t)
            prior_facts={k:v for k,v in (p.canonical_json or {}).items() if k!='direct_submission'}
            s.add(snap);s.flush();self._upsert_contacts(s,p.hotel_id,snap,b);self._merge(s,p)
            if preserve_current_facts and sha(prior_facts)!=sha({k:v for k,v in (p.canonical_json or {}).items() if k!='direct_submission'}):
                raise ValueError('DIRECT_PUBLICATION_CANONICAL_FACTS_CHANGED')
            if require_publishable and (self._paused(s,p.hotel_id) or not self.catalog_quality(p)['passed']):
                raise ValueError('HOTEL_CATALOG_QUALITY_HOLD')
            page=self._publish_version(s,p,actor);self._event(s,p.hotel_id,'SOURCE_INGESTED',{'snapshot_id':snap.content_source_snapshot_id,'source_key':b['source_key'],'source_type':b['source_type'],'rights_status':b['rights_status']},actor);s.flush()
            return {'idempotent':False,'snapshot':out(snap),'profile':out(p),'page_version':out(page),'catalog_quality':self.catalog_quality(p)}

    def compose(self,hotel_id,actor='SYSTEM'):
        with transaction(SessionLocal) as s:
            catalog_scope.scope_lock(s)
            p=s.scalar(select(HotelCanonicalProfileRow).where(HotelCanonicalProfileRow.hotel_id==hotel_id).with_for_update())
            catalog_scope.require_hotel(s,p.hotel_id if p else None)
            if not p:raise ValueError('HOTEL_PROFILE_NOT_FOUND')
            self._merge(s,p);v=self._publish_version(s,p,actor);s.flush();return {'profile':out(p),'page_version':out(v),'catalog_quality':self.catalog_quality(p)}

    def public_page(self,slug):
        with SessionLocal() as s:
            p=s.scalar(select(HotelCanonicalProfileRow).where(HotelCanonicalProfileRow.slug==slug))
            catalog_scope.require_hotel(s,p.hotel_id if p else None)
            if not p:raise ValueError('HOTEL_PAGE_NOT_FOUND')
            if p.page_state!='PUBLISHED':raise ValueError('HOTEL_PAGE_NOT_PUBLISHED')
            v=s.scalar(select(HotelAutoPageVersionRow).where(HotelAutoPageVersionRow.hotel_id==p.hotel_id,HotelAutoPageVersionRow.publication_state=='PUBLISHED').order_by(HotelAutoPageVersionRow.version.desc()))
            if not v:raise ValueError('HOTEL_PAGE_NOT_PUBLISHED')
            page=dict(v.page_json or {})
            evidence=page.pop('_catalog_evidence',{})
            report=quality(evidence.get('catalog'),evidence.get('provenance'),
                media_harvester_service.list_assets(hotel_id=p.hotel_id),hotel_id=p.hotel_id,
                verify_asset=media_harvester_service.content_path)
            if not report['passed']:raise ValueError('HOTEL_PAGE_QUALITY_HOLD')
            current_media=self._catalog_media(p.hotel_id,evidence.get('catalog'))
            page['media']=current_media
            page['hero']=dict(page.get('hero') or {})
            page['hero']['media']=current_media.get('hero',[])
            page['trust']=dict(page.get('trust') or {})
            page['trust']['media_rights_gate_enforced']=True
            page['trust']['media_projection_mode']='DYNAMIC_RIGHTS_GATED_CACHE'
            return page

    def public_page_by_hotel(self,hotel_id):
        with SessionLocal() as s:
            p=s.get(HotelCanonicalProfileRow,hotel_id)
            catalog_scope.require_hotel(s,p.hotel_id if p else None)
            if not p:return None
            v=s.scalar(select(HotelAutoPageVersionRow).where(HotelAutoPageVersionRow.hotel_id==hotel_id).order_by(HotelAutoPageVersionRow.version.desc()))
            if not v:return None
            page=dict(v.page_json or {})
            evidence=page.pop('_catalog_evidence',{})
            if 'direct_submission' in (evidence.get('catalog') or {}):
                report=quality(evidence.get('catalog'),evidence.get('provenance'),[],hotel_id=hotel_id,verify_asset=None)
                if not report['passed']:raise ValueError('HOTEL_PAGE_QUALITY_HOLD')
            current_media=self._catalog_media(hotel_id,evidence.get('catalog'))
            page['media']=current_media
            page['hero']=dict(page.get('hero') or {})
            page['hero']['media']=current_media.get('hero',[])
            page['trust']=dict(page.get('trust') or {})
            page['trust']['media_rights_gate_enforced']=True
            page['trust']['media_projection_mode']='DYNAMIC_RIGHTS_GATED_CACHE'
            return page

    def contact_graph(self,hotel_id):
        with SessionLocal() as s:
            p=s.get(HotelCanonicalProfileRow,hotel_id)
            catalog_scope.require_hotel(s,p.hotel_id if p else None)
            if not p:raise ValueError('HOTEL_PROFILE_NOT_FOUND')
            cs=s.scalars(select(HotelContactPointRow).where(HotelContactPointRow.hotel_id==hotel_id)).all()
            return {'hotel_id':hotel_id,'go_direct_state':p.go_direct_state,'contacts':[out(x) for x in cs],
                    'outreach_readiness':{'email_candidates':sum(1 for x in cs if x.channel=='EMAIL' and not x.do_not_contact and x.marketing_eligibility=='ELIGIBLE_FOR_POLICY_CHECK'),'phone_candidates':sum(1 for x in cs if x.channel=='PHONE' and not x.do_not_contact),'automatic_send_allowed':False,'reason':'JURISDICTION_POLICY_GATE_REQUIRED'}}

    def register_for_go_direct(self,hotel_id,supplier_id,actor,b):
        with transaction(SessionLocal) as s:
            catalog_scope.scope_lock(s)
            p=s.get(HotelCanonicalProfileRow,hotel_id)
            catalog_scope.require_hotel(s,p.hotel_id if p else None)
            if not p:raise ValueError('HOTEL_PROFILE_NOT_FOUND')
            if p.go_direct_state in {'GO_DIRECT_VERIFIED','GO_DIRECT_LIVE'}:raise ValueError('HOTEL_ALREADY_GO_DIRECT_VERIFIED')
            existing=s.scalar(select(HotelRegistrationDirectRow).where(HotelRegistrationDirectRow.hotel_id==hotel_id,HotelRegistrationDirectRow.supplier_id==supplier_id,HotelRegistrationDirectRow.state=='SUBMITTED'))
            if existing:return out(existing)
            r=HotelRegistrationDirectRow(hotel_registration_direct_id=ident('hregdir'),hotel_id=hotel_id,supplier_id=supplier_id,state='SUBMITTED',evidence_json=b.get('evidence',[]),official_supplement_json=b.get('official_supplement',{}),requested_by=actor,reviewed_by=None,created_at=now(),reviewed_at=None)
            s.add(r);p.go_direct_state='REGISTRATION_PENDING';p.updated_at=now();self._event(s,hotel_id,'HOTEL_REGISTRATION_SUBMITTED',{'registration_direct_id':r.hotel_registration_direct_id,'supplier_id':supplier_id},actor);self._publish_version(s,p,actor);s.commit();return out(r)

    def decide_registration_direct(self,registration_direct_id,actor,b):
        with transaction(SessionLocal) as s:
            catalog_scope.scope_lock(s)
            r=s.get(HotelRegistrationDirectRow,registration_direct_id)
            if not r or r.state!='SUBMITTED':raise ValueError('REGISTRATION_NOT_REVIEWABLE')
            catalog_scope.require_hotel(s,r.hotel_id)
            if b.get('decision') not in {'APPROVE','REJECT'}:raise ValueError('INVALID_REGISTRATION_DECISION')
            p=s.get(HotelCanonicalProfileRow,r.hotel_id);r.reviewed_by=actor;r.reviewed_at=now()
            if b['decision']=='REJECT':
                r.state='REJECTED';p.go_go_direct_state='NOT_REGISTERED';self._event(s,p.hotel_id,'HOTEL_REGISTRATION_REJECTED',{'registration_direct_id':registration_direct_id,'reason':b.get('reason')},actor)
            else:
                r.state='APPROVED';p.go_direct_state='GO_DIRECT_VERIFIED'
                supplement=r.official_supplement_json or {}
                if supplement:
                    sb={'source_key':f'hotel-official:{r.supplier_id}','source_type':'HOTEL_OFFICIAL_SUBMISSION','external_hotel_id':p.hotel_id,'source_url':None,'rights_status':'HOTEL_SUBMITTED','confidence_bps':10000,'payload':supplement,'canonical_hotel_id':p.hotel_id}
                    snap=HotelContentSourceSnapshotRow(content_source_snapshot_id=ident('hcss'),source_key=sb['source_key'],source_type='HOTEL_OFFICIAL_SUBMISSION',external_hotel_id=p.hotel_id,source_url=None,rights_status='HOTEL_SUBMITTED',confidence_bps=10000,payload_json=supplement,payload_hash=sha(supplement),canonical_hotel_id=p.hotel_id,observed_at=now(),created_at=now());s.add(snap);s.flush();self._upsert_contacts(s,p.hotel_id,snap,sb)
                self._merge(s,p);self._event(s,p.hotel_id,'HOTEL_GO_DIRECT_VERIFIED',{'registration_direct_id':registration_direct_id,'supplier_id':r.supplier_id},actor)
            self._publish_version(s,p,actor);s.commit();return {'registration_direct':out(r),'profile':out(p)}


    def _latest_registration(self,s,hotel_id):
        return s.scalar(select(HotelRegistrationDirectRow).where(HotelRegistrationDirectRow.hotel_id==hotel_id).order_by(HotelRegistrationDirectRow.created_at.desc()))

    def _factory_flags(self,s,profile):
        snapshots=s.scalars(select(HotelContentSourceSnapshotRow).where(HotelContentSourceSnapshotRow.canonical_hotel_id==profile.hotel_id)).all()
        contacts=s.scalars(select(HotelContactPointRow).where(HotelContactPointRow.hotel_id==profile.hotel_id)).all()
        latest=s.scalar(select(HotelAutoPageVersionRow).where(HotelAutoPageVersionRow.hotel_id==profile.hotel_id).order_by(HotelAutoPageVersionRow.version.desc()))
        registration=self._latest_registration(s,profile.hotel_id)
        assets=media_harvester_service.list_assets(hotel_id=profile.hotel_id)
        pending_media=[x for x in assets if not x.get('publishable')]
        c=profile.canonical_json or {}
        rooms=c.get('rooms') if isinstance(c.get('rooms'),list) else []
        events=s.scalars(select(HotelAutoPageEventRow).where(HotelAutoPageEventRow.hotel_id==profile.hotel_id).order_by(HotelAutoPageEventRow.created_at.desc())).all()
        latest_job=None; running=False; failed=0
        for ev in events:
            evidence=ev.evidence_json or {}
            if not latest_job and evidence.get('job_id'): latest_job=evidence.get('job_id')
            if ev.event_type=='DISCOVERY_JOB_STARTED' and latest_job and evidence.get('job_id')==latest_job: running=True
            if ev.event_type=='DISCOVERY_JOB_FINISHED' and evidence.get('job_id')==latest_job:
                running=False; failed=int(evidence.get('failure_count') or 0)
                break
        flags={
            'NEEDS_ENRICHMENT':not self.catalog_quality(profile)['passed'],
            'COLLECTING':running,
            'WAIT_MERGE':bool(snapshots) and latest is None,
            'WAIT_MEDIA_REVIEW':bool(pending_media),
            'WAIT_PUBLISH':profile.page_state!='PUBLISHED' and bool(c.get('name') and c.get('address')),
            'PUBLISHED':profile.page_state=='PUBLISHED',
            'WAIT_CLAIM':profile.page_state=='PUBLISHED' and profile.go_direct_state=='NOT_REGISTERED',
            'CLAIMED':bool(registration) and registration.state in {'SUBMITTED','APPROVED'},
            'GO_DIRECT':profile.go_direct_state in {'GO_DIRECT_VERIFIED','GO_DIRECT_LIVE'},
        }
        if flags['COLLECTING']: primary='COLLECTING'
        elif flags['NEEDS_ENRICHMENT']: primary='NEEDS_ENRICHMENT'
        elif flags['WAIT_MEDIA_REVIEW']: primary='WAIT_MEDIA_REVIEW'
        elif flags['WAIT_MERGE']: primary='WAIT_MERGE'
        elif flags['WAIT_PUBLISH']: primary='WAIT_PUBLISH'
        elif flags['GO_DIRECT']: primary='GO_DIRECT'
        elif flags['CLAIMED']: primary='CLAIMED'
        elif flags['WAIT_CLAIM']: primary='WAIT_CLAIM'
        elif flags['PUBLISHED']: primary='PUBLISHED'
        else: primary='WAIT_BUILD'
        return {
            'primary_stage':primary,'stage_flags':flags,'source_count':len(snapshots),'contact_count':len(contacts),
            'room_count':len(rooms),'image_count':len(assets),'rights_pending_count':len(pending_media),
            'latest_page_version':latest.version if latest else None,'latest_page_created_at':latest.created_at.isoformat() if latest else None,
            'latest_discovery_job_id':latest_job,'discovery_failure_count':failed,
            'last_source_observed_at':max((x.observed_at for x in snapshots),default=None).isoformat() if snapshots else None,
            'registration_state':registration.state if registration else None,
            'catalog_quality':self.catalog_quality(profile),
        }

    def factory_overview(self,limit=200):
        limit=max(1,min(int(limit or 200),1000))
        with SessionLocal() as s:
            active=catalog_scope.state(s)
            visible=HotelCanonicalProfileRow.hotel_id.in_(active['protected_ids']) if active else True
            profiles=s.scalars(select(HotelCanonicalProfileRow).where(visible).order_by(HotelCanonicalProfileRow.updated_at.desc()).limit(limit)).all()
            items=[]
            counters={k:0 for k in ['WAIT_BUILD','COLLECTING','WAIT_MERGE','WAIT_MEDIA_REVIEW','WAIT_PUBLISH','PUBLISHED','WAIT_CLAIM','CLAIMED','GO_DIRECT','NEEDS_ENRICHMENT']}
            for p in profiles:
                f=self._factory_flags(s,p)
                for key,val in f['stage_flags'].items():
                    if val: counters[key]+=1
                c=p.canonical_json or {}
                items.append({
                    'hotel_id':p.hotel_id,'slug':p.slug,'name':c.get('name') or c.get('name_zh') or c.get('name_en') or '未命名酒店',
                    'address':c.get('address'),'completeness_bps':p.completeness_bps,'page_state':p.page_state,'go_direct_state':p.go_direct_state,
                    **f,
                })
            # Discovery seeds which have not created a canonical hotel yet remain visible as WAIT_BUILD.
            created=s.scalars(select(HotelAutoPageEventRow).where(HotelAutoPageEventRow.event_type=='DISCOVERY_JOB_CREATED',catalog_scope.event_filter(s)).order_by(HotelAutoPageEventRow.created_at.desc()).limit(limit)).all()
            created=catalog_scope.visible_events(s,created)
            known_jobs={x.get('latest_discovery_job_id') for x in items if x.get('latest_discovery_job_id')}
            seed_queue=[]
            for e in created:
                ev=e.evidence_json or {}; jid=ev.get('job_id')
                if not jid or jid in known_jobs: continue
                seed=ev.get('seed') or {}
                seed_queue.append({'job_id':jid,'name':seed.get('name') or '待采集酒店','address':seed.get('address'),'created_at':e.created_at.isoformat(),'primary_stage':'WAIT_BUILD'})
            counters['WAIT_BUILD']=len(seed_queue)
            total_hotels=int(s.scalar(select(func.count()).select_from(HotelCanonicalProfileRow).where(visible)) or 0)
            published_pages=int(s.scalar(select(func.count()).select_from(HotelCanonicalProfileRow).where(visible).where(HotelCanonicalProfileRow.page_state=='PUBLISHED')) or 0)
            draft_pages=int(s.scalar(select(func.count()).select_from(HotelCanonicalProfileRow).where(visible).where(HotelCanonicalProfileRow.page_state=='DRAFT')) or 0)
            return {'counts':counters,'items':items,'seed_queue':seed_queue[:limit],
                    'total_hotels':total_hotels,'total_pages':published_pages+draft_pages,
                    'published_pages':published_pages,'draft_pages':draft_pages}

    def factory_detail(self,hotel_id):
        with SessionLocal() as s:
            p=s.get(HotelCanonicalProfileRow,hotel_id)
            catalog_scope.require_hotel(s,p.hotel_id if p else None)
            if not p: raise ValueError('HOTEL_PROFILE_NOT_FOUND')
            f=self._factory_flags(s,p)
            snapshots=s.scalars(select(HotelContentSourceSnapshotRow).where(HotelContentSourceSnapshotRow.canonical_hotel_id==hotel_id).order_by(HotelContentSourceSnapshotRow.observed_at.desc())).all()
            contacts=s.scalars(select(HotelContactPointRow).where(HotelContactPointRow.hotel_id==hotel_id).order_by(HotelContactPointRow.updated_at.desc())).all()
            events=s.scalars(select(HotelAutoPageEventRow).where(HotelAutoPageEventRow.hotel_id==hotel_id).order_by(HotelAutoPageEventRow.created_at.desc()).limit(80)).all()
            assets=media_harvester_service.list_assets(hotel_id=hotel_id)
            c=p.canonical_json or {}; anomalies=[]
            if not c.get('name'): anomalies.append({'code':'NAME_MISSING','label':'酒店名称待完善'})
            if not c.get('address'): anomalies.append({'code':'ADDRESS_MISSING','label':'酒店地址待完善'})
            if f['rights_pending_count']: anomalies.append({'code':'MEDIA_RIGHTS_PENDING','label':f"{f['rights_pending_count']} 张图片待 Rights 审核"})
            if f['discovery_failure_count']: anomalies.append({'code':'DISCOVERY_FAILURE','label':f"最近采集有 {f['discovery_failure_count']} 个来源失败"})
            for code in f['catalog_quality']['reasons']:anomalies.append({'code':code,'label':code})
            rights_summary={}
            for a in assets:
                key=a.get('rights_state') or 'RIGHTS_UNKNOWN';rights_summary[key]=rights_summary.get(key,0)+1
            return {
                'profile':out(p),'display':{'name':c.get('name') or c.get('name_zh') or c.get('name_en'),'address':c.get('address'),'website':c.get('website'),'facilities':c.get('facilities') or [],'rooms':c.get('rooms') or [],'policies':c.get('policies') or []},
                'factory':f,'contacts':[out(x) for x in contacts],
                'sources':[{'snapshot_id':x.content_source_snapshot_id,'source_key':x.source_key,'source_type':x.source_type,'source_url':x.source_url,'rights_status':x.rights_status,'confidence_bps':x.confidence_bps,'observed_at':x.observed_at.isoformat(),'payload_hash':x.payload_hash} for x in snapshots],
                'media':{'count':len(assets),'publishable_count':sum(1 for x in assets if x.get('publishable')),'rights_pending_count':f['rights_pending_count'],'rights_summary':rights_summary},
                'anomalies':anomalies,
                'timeline':[{'event_type':x.event_type,'created_at':x.created_at.isoformat(),'actor':x.actor,'evidence':x.evidence_json} for x in events],
                'preview_url':f"/v1/hotel-pages/{p.slug}" if p.page_state=='PUBLISHED' else None,
            }

    def set_publication(self,hotel_id,action,actor='SYSTEM'):
        action=str(action or '').upper()
        if action not in {'PUBLISH','UNPUBLISH'}: raise ValueError('INVALID_PUBLICATION_ACTION')
        with transaction(SessionLocal) as s:
            catalog_scope.scope_lock(s)
            p=s.scalar(select(HotelCanonicalProfileRow).where(HotelCanonicalProfileRow.hotel_id==hotel_id).with_for_update())
            catalog_scope.require_hotel(s,p.hotel_id if p else None)
            if not p: raise ValueError('HOTEL_PROFILE_NOT_FOUND')
            if action=='PUBLISH':
                c=p.canonical_json or {}
                if not c.get('name') or not c.get('address'): raise ValueError('HOTEL_PAGE_REQUIRED_FACTS_MISSING')
                if not self.catalog_quality(p)['passed']: raise ValueError('HOTEL_CATALOG_QUALITY_HOLD')
                p.page_state='PUBLISHED';p.updated_at=now();self._event(s,hotel_id,'AUTO_PAGE_MANUAL_PUBLISHED',{'slug':p.slug},actor)
            else:
                p.page_state='DRAFT';p.updated_at=now();self._event(s,hotel_id,'AUTO_PAGE_UNPUBLISHED',{'slug':p.slug},actor)
            s.flush();v=self._publish_version(s,p,actor);s.flush();return {'profile':out(p),'page_version':out(v)}

    def suppress_contact(self,contact_id,actor,reason='OPT_OUT'):
        with transaction(SessionLocal) as s:
            catalog_scope.scope_lock(s)
            r=s.get(HotelContactPointRow,contact_id)
            if not r:raise ValueError('CONTACT_NOT_FOUND')
            catalog_scope.require_hotel(s,r.hotel_id)
            r.do_not_contact=True;r.marketing_eligibility='SUPPRESSED';r.updated_at=now();self._event(s,r.hotel_id,'CONTACT_SUPPRESSED',{'contact_id':contact_id,'reason':reason},actor);s.commit();return out(r)

hotel_autopage_factory_service=HotelAutoPageFactoryService()
