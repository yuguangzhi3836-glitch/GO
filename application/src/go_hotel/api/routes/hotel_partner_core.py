from fastapi import APIRouter,Depends,HTTPException,Header
from pydantic import BaseModel
from go_hotel.security.deps import supplier_principal
from go_hotel.security.service import Principal
from go_hotel.services.hotel_partner_core import hotel_partner_core_service as svc
router=APIRouter(prefix='/v1/supplier',tags=['hotel-partner-self-operating-core'])
def call(fn,*args):
    try:return {'data':fn(*args)}
    except ValueError as e:
        code=str(e)
        if code in {'PROPERTY_NOT_FOUND','ROOM_TYPE_NOT_FOUND','INBOX_ITEM_NOT_FOUND'}:status=404
        elif code in {'IDEMPOTENCY_PAYLOAD_MISMATCH','IMPORT_ALREADY_IN_PROGRESS','SUPPLIER_PROVIDER_STATE_ALREADY_USED'}:status=409
        elif code in {'SUPPLIER_PROVIDER_VERIFIER_UNAVAILABLE','AUTHORIZATION_UNAVAILABLE'}:status=503
        else:status=422
        raise HTTPException(status,detail=code)
class Payload(BaseModel):model_config={'extra':'allow'}
@router.post('/properties',status_code=201)
def create_property(b:Payload,p:Principal=Depends(supplier_principal)):return call(svc.create_property,p.supplier_id,p.user_id,b.model_dump(exclude_none=True))
@router.get('/properties')
def properties(p:Principal=Depends(supplier_principal)):return {'data':svc.properties(p.supplier_id)}
@router.get('/one-click-import/providers')
def one_click_import_providers(p:Principal=Depends(supplier_principal)):return {'data':svc.import_providers()}
@router.post('/properties/{property_id}/one-click-import')
def one_click_import(property_id:str,b:Payload,idempotency_key:str|None=Header(None,alias='Idempotency-Key'),p:Principal=Depends(supplier_principal)):return call(svc.one_click_import,p.supplier_id,p.user_id,property_id,b.model_dump(exclude_none=True),idempotency_key)
@router.patch('/properties/{property_id}')
def patch_property(property_id:str,b:Payload,p:Principal=Depends(supplier_principal)):return call(svc.patch_property,p.supplier_id,p.user_id,property_id,b.model_dump(exclude_none=True))
@router.get('/properties/{property_id}/command-center')
def command_center(property_id:str,p:Principal=Depends(supplier_principal)):return call(svc.command_center,p.supplier_id,property_id)
@router.get('/properties/{property_id}/product-graph')
def product_graph(property_id:str,p:Principal=Depends(supplier_principal)):return call(svc.graph,p.supplier_id,property_id)
@router.get('/properties/{property_id}/operating-snapshot')
def operating_snapshot(property_id:str,p:Principal=Depends(supplier_principal)):return call(svc.operating_snapshot,p.supplier_id,property_id)
@router.get('/hotel-webpage')
def hotel_webpage(p:Principal=Depends(supplier_principal)):return call(svc.webpage_workspace,p.supplier_id)
@router.post('/properties/{property_id}/room-types',status_code=201)
def room_type(property_id:str,b:Payload,p:Principal=Depends(supplier_principal)):return call(svc.create_room_type,p.supplier_id,p.user_id,property_id,b.model_dump(exclude_none=True))
@router.post('/properties/{property_id}/sellable-products',status_code=201)
def product(property_id:str,b:Payload,p:Principal=Depends(supplier_principal)):return call(svc.create_product,p.supplier_id,p.user_id,property_id,b.model_dump(exclude_none=True))
@router.post('/properties/{property_id}/rate-plans',status_code=201)
def rate(property_id:str,b:Payload,p:Principal=Depends(supplier_principal)):return call(svc.create_rate_plan,p.supplier_id,p.user_id,property_id,b.model_dump(exclude_none=True))
@router.put('/properties/{property_id}/facilities')
def facility(property_id:str,b:Payload,p:Principal=Depends(supplier_principal)):return call(svc.upsert_facility,p.supplier_id,p.user_id,property_id,b.model_dump(exclude_none=True))
@router.put('/properties/{property_id}/policies')
def policy(property_id:str,b:Payload,p:Principal=Depends(supplier_principal)):return call(svc.upsert_policy,p.supplier_id,p.user_id,property_id,b.model_dump(exclude_none=True))
@router.put('/properties/{property_id}/ari/date-override')
def ari(property_id:str,b:Payload,p:Principal=Depends(supplier_principal)):return call(svc.upsert_ari,p.supplier_id,p.user_id,property_id,b.model_dump(exclude_none=True))
@router.post('/properties/{property_id}/operational-inbox',status_code=201)
def inbox_create(property_id:str,b:Payload,p:Principal=Depends(supplier_principal)):return call(svc.create_inbox,p.supplier_id,p.user_id,property_id,b.model_dump(exclude_none=True))
@router.post('/operational-inbox/{item_id}/transition')
def inbox_transition(item_id:str,b:Payload,p:Principal=Depends(supplier_principal)):return call(svc.transition_inbox,p.supplier_id,p.user_id,item_id,b.model_dump(exclude_none=True))
@router.put('/properties/{property_id}/go-offer-authority')
def offer_authority(property_id:str,b:Payload,p:Principal=Depends(supplier_principal)):return call(svc.upsert_offer_authority,p.supplier_id,p.user_id,property_id,b.model_dump(exclude_none=True))
