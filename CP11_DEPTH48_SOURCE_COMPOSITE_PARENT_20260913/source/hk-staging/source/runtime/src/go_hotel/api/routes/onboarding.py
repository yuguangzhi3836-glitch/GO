from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Header, HTTPException, Depends
from pydantic import BaseModel, Field
from go_hotel.services.onboarding import onboarding_service
from go_hotel.security.deps import require_permission
from go_hotel.security.service import Principal, approval_service, audit_service

router=APIRouter(prefix="/internal/v1/supplier-connectors",tags=["supplier-connector-onboarding"])

class CreateOnboarding(BaseModel):
    supplier_id:str; connector_id:str; environment:str="SANDBOX"
class CredentialsBody(BaseModel): credential_reference:str; purpose:str="PROVIDER_AUTH"
class MappingBody(BaseModel):
    external_hotel_id:str; proposed_hotel_id:str|None=None; external_name:str|None=None; external_address:str|None=None; confidence_bps:int=Field(default=0,ge=0,le=10000); match_method:str="MANUAL"
class MappingReviewBody(BaseModel): decision:str; note:str|None=None
class RolloutBody(BaseModel): percent:int=Field(ge=0,le=100)
class SuspendBody(BaseModel): reason:str

def actor(x_actor_id:str|None): return x_actor_id or "system"
def call(fn,*args,**kwargs):
    try: return {"data":fn(*args,**kwargs)}
    except KeyError as e: raise HTTPException(404,detail=str(e))
    except ValueError as e: raise HTTPException(422,detail=str(e))

@router.post("")
def create(body:CreateOnboarding): return call(onboarding_service.create,body.supplier_id,body.connector_id,body.environment)
@router.get("")
def list_all(): return {"data":onboarding_service.list()}
@router.get("/{onboarding_id}")
def get_one(onboarding_id:str): return call(onboarding_service._row,onboarding_id)
@router.put("/{onboarding_id}/credentials")
def credentials(onboarding_id:str,body:CredentialsBody,x_actor_id:str|None=Header(default=None)): return call(onboarding_service.store_credential_reference,onboarding_id,body.credential_reference,actor(x_actor_id),body.purpose)
@router.get("/{onboarding_id}/credentials")
def credential_metadata(onboarding_id:str): return {"data":onboarding_service.credential_metadata(onboarding_id)}
@router.post("/{onboarding_id}/property-mappings")
def propose_mapping(onboarding_id:str,body:MappingBody): return call(onboarding_service.propose_mapping,onboarding_id,**body.model_dump())
@router.get("/{onboarding_id}/property-mappings")
def list_mappings(onboarding_id:str): return {"data":onboarding_service.mappings(onboarding_id)}
@router.post("/property-mappings/{mapping_id}/review")
def review_mapping(mapping_id:str,body:MappingReviewBody,x_actor_id:str|None=Header(default=None)): return call(onboarding_service.review_mapping,mapping_id,body.decision,actor(x_actor_id),body.note)
@router.post("/{onboarding_id}/certify")
async def certify(onboarding_id:str,x_actor_id:str|None=Header(default=None)):
    try: return {"data":await onboarding_service.certify(onboarding_id,actor(x_actor_id))}
    except KeyError as e: raise HTTPException(404,detail=str(e))
    except (ValueError,KeyError) as e: raise HTTPException(422,detail=str(e))
@router.post("/{onboarding_id}/activation-request")
def request_activation(onboarding_id:str,x_actor_id:str|None=Header(default=None)): return call(onboarding_service.request_activation,onboarding_id,actor(x_actor_id))
@router.post("/{onboarding_id}/activate")
def activate(onboarding_id:str,body:RolloutBody|None=None,x_approval_id:str|None=Header(default=None,alias='X-Approval-ID'),p:Principal=Depends(require_permission('admin:connector'))):
    if not x_approval_id: raise HTTPException(403,detail='SECOND_APPROVAL_REQUIRED')
    try: approval_service.consume(p,x_approval_id,'CONNECTOR_ACTIVATION',onboarding_id)
    except PermissionError as e: raise HTTPException(403,detail=str(e))
    result=onboarding_service.activate(onboarding_id,p.user_id,body.percent if body else None); audit_service.append(p,'CONNECTOR_ACTIVATED','SUPPLIER_CONNECTOR',onboarding_id,after=result,approval_id=x_approval_id); return {'data':result}
@router.put("/{onboarding_id}/rollout")
def rollout(onboarding_id:str,body:RolloutBody,x_actor_id:str|None=Header(default=None)): return call(onboarding_service.set_rollout,onboarding_id,actor(x_actor_id),body.percent)
@router.post("/{onboarding_id}/suspend")
def suspend(onboarding_id:str,body:SuspendBody,x_approval_id:str|None=Header(default=None,alias='X-Approval-ID'),p:Principal=Depends(require_permission('admin:connector'))):
    if not x_approval_id: raise HTTPException(403,detail='SECOND_APPROVAL_REQUIRED')
    try: approval_service.consume(p,x_approval_id,'CONNECTOR_SUSPENSION',onboarding_id)
    except PermissionError as e: raise HTTPException(403,detail=str(e))
    result=onboarding_service.suspend(onboarding_id,p.user_id,body.reason); audit_service.append(p,'CONNECTOR_SUSPENDED','SUPPLIER_CONNECTOR',onboarding_id,after=result,approval_id=x_approval_id); return {'data':result}
