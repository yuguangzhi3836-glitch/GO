from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,Field
from go_hotel.security.deps import consumer_principal
from go_hotel.security.service import Principal
from go_hotel.journey.service import journey_service
router=APIRouter(tags=["sprint3e-unified-go-trips"])
class Item(BaseModel):
 vertical:str;order_id:str;title:str|None=None;subtitle:str|None=None;location:str|None=None;starts_at:str|None=None;ends_at:str|None=None;sort_key:str|None=None;facts:dict=Field(default_factory=dict)
class Create(BaseModel):
 title:str;destination_summary:str|None=None;starts_at:str|None=None;ends_at:str|None=None;items:list[Item]=Field(default_factory=list)
def call(fn,*args):
 try:return {"data":fn(*args)}
 except ValueError as e: raise HTTPException(404 if "NOT_FOUND" in str(e) else 409,detail=str(e))
@router.post("/v1/trips/journeys")
def create(b:Create,p:Principal=Depends(consumer_principal)): return call(journey_service.create,p.user_id,b.model_dump())
@router.get("/v1/trips/journeys")
def list_journeys(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0),q:str|None=Query(None,max_length=100),p:Principal=Depends(consumer_principal)): return {"data":journey_service.list_page(p.user_id,limit,offset,q)}
@router.get("/v1/trips/journeys/{journey_id}")
def get_journey(journey_id:str,p:Principal=Depends(consumer_principal)): return call(journey_service.get,p.user_id,journey_id)
@router.post("/v1/trips/journeys/{journey_id}/items")
def attach(journey_id:str,b:Item,p:Principal=Depends(consumer_principal)): return call(journey_service.attach,p.user_id,journey_id,b.model_dump())
