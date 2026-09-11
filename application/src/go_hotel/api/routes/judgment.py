from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from go_hotel.judgment.service import judgment_service

router=APIRouter()
class ReevaluateRequest(BaseModel):
    extra_features: dict = Field(default_factory=dict)

@router.post('/internal/v1/judgments/{hotel_id}/reevaluate')
def reevaluate(hotel_id:str,body:ReevaluateRequest=ReevaluateRequest()):
    return {'data':judgment_service.reevaluate(hotel_id,body.extra_features)}

@router.post('/internal/v1/judgment-hooks/{hook_id}/process')
def process_hook(hook_id:str): return {'data':judgment_service.process_hook(hook_id)}

@router.post('/internal/v1/judgment-hooks/process-pending')
def process_pending(limit:int=Query(default=100,ge=1,le=1000)): return {'data':judgment_service.process_pending(limit)}

@router.get('/internal/v1/judgments/{judgment_id}')
def get_judgment(judgment_id:str): return {'data':judgment_service.get_judgment(judgment_id)}

@router.get('/v1/hotels/{hotel_id}/judgment')
def public_judgment(hotel_id:str): return {'data':judgment_service.public_view(hotel_id)}
