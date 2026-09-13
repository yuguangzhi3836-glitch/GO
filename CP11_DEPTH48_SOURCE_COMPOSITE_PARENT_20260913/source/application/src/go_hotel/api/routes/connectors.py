from fastapi import APIRouter
from go_hotel.connectors.registry import registry
from go_hotel.services.connectors import connector_service
from go_hotel.services.reconciliation import reconciliation_service
router=APIRouter(prefix="/internal/v1/connectors",tags=["internal-connectors"])
@router.get("")
def list_connectors(): return {"data":[{"connector_id":m.connector_id,"display_name":m.display_name,"version":m.version,"capabilities":m.capabilities.__dict__} for m in registry.list()]}
@router.post("/{connector_id}/certify")
async def certify(connector_id:str): return {"data":await connector_service.certify(connector_id)}
@router.get("/health/all")
async def health_all(): return {"data":await connector_service.health()}
@router.post("/reconciliation/run-once")
async def reconcile(limit:int=100): return {"data":await reconciliation_service.run_once(limit)}
