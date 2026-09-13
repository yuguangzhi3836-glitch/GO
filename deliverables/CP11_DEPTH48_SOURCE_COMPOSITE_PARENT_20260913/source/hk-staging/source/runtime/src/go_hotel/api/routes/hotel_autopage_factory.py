from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from go_hotel.security.deps import admin_principal,supplier_principal
from go_hotel.security.service import Principal
from go_hotel.services.hotel_autopage_factory import hotel_autopage_factory_service as svc
from go_hotel.services.media_harvester import media_harvester_service as media_svc
from go_hotel.services.hotel_infrastructure_p0 import hotel_infrastructure_p0_service as infra_p0

router=APIRouter(tags=['go-hotel-autopage-factory'])
class Payload(BaseModel):model_config={'extra':'allow'}
def call(fn,*a):
    try:return {'data':fn(*a)}
    except ValueError as e:raise HTTPException(409,detail=str(e))

def call_kw(fn,**kw):
    try:return {'data':fn(**kw)}
    except ValueError as e:raise HTTPException(409,detail=str(e))


@router.get('/internal/v1/hotel-autopage/factory/overview')
def factory_overview(limit:int=200,p:Principal=Depends(admin_principal)):
    return call(svc.factory_overview,limit)

@router.get('/internal/v1/hotel-autopage/factory/hotels/{hotel_id}')
def factory_detail(hotel_id:str,p:Principal=Depends(admin_principal)):
    return call(svc.factory_detail,hotel_id)

@router.post('/internal/v1/hotel-autopage/factory/hotels/{hotel_id}/publication')
def factory_publication(hotel_id:str,b:Payload,p:Principal=Depends(admin_principal)):
    d=b.model_dump(exclude_none=True)
    return call(svc.set_publication,hotel_id,d.get('action'),p.user_id)

@router.post('/internal/v1/hotel-autopage/sources/ingest')
def ingest(b:Payload,p:Principal=Depends(admin_principal)):return call(svc.ingest,b.model_dump(exclude_none=True),p.user_id)
@router.post('/internal/v1/hotel-autopage/hotels/{hotel_id}/compose')
def compose(hotel_id:str,p:Principal=Depends(admin_principal)):return call(svc.compose,hotel_id,p.user_id)
@router.get('/internal/v1/hotel-autopage/hotels/{hotel_id}/contacts')
def contacts(hotel_id:str,p:Principal=Depends(admin_principal)):return call(svc.contact_graph,hotel_id)
@router.post('/internal/v1/hotel-autopage/go-direct-registrations/{registration_direct_id}/decision')
def registration_decision(registration_direct_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.decide_registration_direct,registration_direct_id,p.user_id,b.model_dump(exclude_none=True))
@router.post('/internal/v1/hotel-autopage/contacts/{contact_id}/suppress')
def suppress(contact_id:str,b:Payload,p:Principal=Depends(admin_principal)):return call(svc.suppress_contact,contact_id,p.user_id,b.model_dump(exclude_none=True).get('reason','OPT_OUT'))
@router.get('/v1/hotel-pages/{slug}')
def page(slug:str):return call(svc.public_page,slug)
@router.post('/v1/supplier/hotels/{hotel_id}/go-direct-registration')
def register_go_direct(hotel_id:str,b:Payload,p:Principal=Depends(supplier_principal)):return call(svc.register_for_go_direct,hotel_id,p.supplier_id,p.user_id,b.model_dump(exclude_none=True))

@router.post('/internal/v1/hotel-autopage/media/harvest')
def media_harvest(b:Payload,p:Principal=Depends(admin_principal)):
    d=b.model_dump(exclude_none=True)
    return call_kw(media_svc.harvest,**d)

@router.post('/internal/v1/hotel-autopage/media/harvest-batch')
def media_harvest_batch(b:Payload,p:Principal=Depends(admin_principal)):
    d=b.model_dump(exclude_none=True)
    return call(media_svc.harvest_batch,d.get('candidates',[]),bool(d.get('allow_private',False)))

@router.post('/internal/v1/hotel-autopage/media/{asset_id}/rights')
def media_rights(asset_id:str,b:Payload,p:Principal=Depends(admin_principal)):
    d=b.model_dump(exclude_none=True)
    return call_kw(media_svc.decide_rights,asset_id=asset_id,rights_state=d.get('rights_state'),actor=p.user_id,rights_owner=d.get('rights_owner'),evidence_reference=d.get('evidence_reference'),expires_at=d.get('expires_at'),rights_scope=d.get('rights_scope'),rights_regions=d.get('rights_regions'),rights_basis=d.get('rights_basis'),provider=d.get('provider'),contract_id=d.get('contract_id'),cache_allowed=d.get('cache_allowed'),modification_allowed=d.get('modification_allowed'))

@router.get('/internal/v1/hotel-autopage/media/assets')
def media_assets(hotel_id:str|None=None,room_type_id:str|None=None,publishable_only:bool=False,p:Principal=Depends(admin_principal)):
    return {'data':media_svc.list_assets(hotel_id=hotel_id,room_type_id=room_type_id,publishable_only=publishable_only)}

@router.get('/internal/v1/hotel-autopage/media/{asset_id}/content')
def media_admin_content(asset_id:str,p:Principal=Depends(admin_principal)):
    try:
        rec=media_svc.get(asset_id); path=media_svc.content_path(asset_id,require_publishable=False)
        return FileResponse(path,media_type=rec['mime_type'],filename=path.name)
    except ValueError as e:raise HTTPException(404,detail=str(e))

@router.get('/v1/hotel-media/{asset_id}')
def media_public_content(asset_id:str):
    try:
        rec=media_svc.get(asset_id); path=media_svc.content_path(asset_id,require_publishable=True)
        return FileResponse(path,media_type=rec['mime_type'],headers={'Cache-Control':'public, max-age=31536000, immutable','ETag':rec['sha256'],'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'"})
    except ValueError as e:raise HTTPException(404,detail=str(e))

# Slice 1 — GO Hotel Discovery & AutoPage Production Engine: discovery + immutable source snapshots.
from go_hotel.services.hotel_discovery_orchestrator import hotel_discovery_orchestrator_service as discovery_svc

@router.post('/internal/v1/hotel-discovery/seeds')
def discovery_register_seed(b:Payload,p:Principal=Depends(admin_principal)):
    return call(discovery_svc.register_seed,b.model_dump(exclude_none=True),p.user_id)

@router.get('/internal/v1/hotel-discovery/seeds')
def discovery_list_seeds(limit:int=100,p:Principal=Depends(admin_principal)):
    return {'data':discovery_svc.list_seeds(limit)}

@router.post('/internal/v1/hotel-discovery/jobs/{job_id}/run')
def discovery_run(job_id:str,b:Payload,p:Principal=Depends(admin_principal)):
    d=b.model_dump(exclude_none=True)
    return call_kw(discovery_svc.run_job,job_id=job_id,actor=p.user_id,max_retries=int(d.get('max_retries',2)))

@router.post('/internal/v1/hotel-discovery/jobs/{job_id}/retry')
def discovery_retry(job_id:str,b:Payload,p:Principal=Depends(admin_principal)):
    d=b.model_dump(exclude_none=True)
    return call_kw(discovery_svc.retry_job,job_id=job_id,actor=p.user_id,max_retries=int(d.get('max_retries',2)))

@router.get('/internal/v1/hotel-discovery/jobs/{job_id}')
def discovery_status(job_id:str,p:Principal=Depends(admin_principal)):
    return call(discovery_svc.job_status,job_id)

@router.get('/internal/v1/hotel-discovery/jobs/{job_id}/snapshots')
def discovery_snapshots(job_id:str,p:Principal=Depends(admin_principal)):
    return call(discovery_svc.job_snapshots,job_id)

@router.post('/internal/v1/hotel-discovery/batches/run')
def discovery_batch(b:Payload,p:Principal=Depends(admin_principal)):
    d=b.model_dump(exclude_none=True)
    return call_kw(discovery_svc.run_batch,seeds=d.get('seeds',[]),actor=p.user_id,max_retries=int(d.get('max_retries',2)))

# RC17.9 — National Hotel Digital Infrastructure Console / one-click regional build.
from go_hotel.services.regional_hotel_build import regional_hotel_build_service as regional_build_svc

@router.post('/internal/v1/hotel-infrastructure/build-runs')
def regional_build_start(b:Payload,p:Principal=Depends(admin_principal)):
    d=b.model_dump(exclude_none=True)
    return call_kw(regional_build_svc.start,mode=d.get('mode'),actor=p.user_id,country=d.get('country','CN'),province=d.get('province'),city=d.get('city'),tier=d.get('tier'),target_name=d.get('target_name'))

@router.get('/internal/v1/hotel-infrastructure/build-runs')
def regional_build_status(run_id:str|None=None,p:Principal=Depends(admin_principal)):
    return {'data':regional_build_svc.status(run_id)}

@router.get('/internal/v1/hotel-infrastructure/exceptions')
def regional_build_exceptions(limit:int=200,p:Principal=Depends(admin_principal)):
    return {'data':regional_build_svc.exceptions(limit)}

@router.post('/internal/v1/hotel-infrastructure/build-runs/{run_id}/retry')
def regional_build_retry(run_id:str,p:Principal=Depends(admin_principal)):
    return call_kw(regional_build_svc.retry_failures,run_id=run_id,actor=p.user_id)


@router.get('/internal/v1/hotel-infrastructure/clean-slate/harbin/preview')
def harbin_clean_slate_preview(p:Principal=Depends(admin_principal)):
    return {'data':infra_p0.reset_preview()}

@router.post('/internal/v1/hotel-infrastructure/clean-slate/harbin/execute')
def harbin_clean_slate_execute(b:Payload,p:Principal=Depends(admin_principal)):
    d=b.model_dump(exclude_none=True)
    return call_kw(infra_p0.reset_execute,confirmation=d.get('confirmation',''),actor=p.user_id)

@router.post('/internal/v1/hotel-infrastructure/golden-build/aoluguya')
def aoluguya_golden_build(p:Principal=Depends(admin_principal)):
    return call_kw(regional_build_svc.start,mode='REGION',actor=p.user_id,country='CN',province='黑龙江省',city='哈尔滨市',tier=5,target_name='敖麓谷雅')

@router.get('/internal/v1/hotel-infrastructure/hotels/{hotel_id}/completeness-gate')
def hotel_completeness_gate(hotel_id:str,tier:int=5,p:Principal=Depends(admin_principal)):
    return call_kw(infra_p0.completeness_gate,hotel_id=hotel_id,tier=tier)

@router.post('/internal/v1/hotel-infrastructure/hotels/{hotel_id}/travel-graph-project')
def hotel_travel_graph_project(hotel_id:str,p:Principal=Depends(admin_principal)):
    return call(infra_p0.project_to_travel_graph,hotel_id)

@router.post('/internal/v1/hotel-infrastructure/build-runs/{run_id}/advance-after-acceptance')
def regional_build_advance_after_acceptance(run_id:str,b:Payload,p:Principal=Depends(admin_principal)):
    d=b.model_dump(exclude_none=True)
    return call_kw(regional_build_svc.advance_after_acceptance,run_id=run_id,actor=p.user_id,confirmation=d.get('confirmation',''))
