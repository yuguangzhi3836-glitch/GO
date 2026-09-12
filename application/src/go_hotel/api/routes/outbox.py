from fastapi import APIRouter
from go_hotel.services.outbox import outbox_publisher
router = APIRouter(prefix="/internal/v1/outbox", tags=["internal"])
@router.post("/drain")
def drain_outbox(limit: int = 100):
    result = outbox_publisher.run_once(limit)
    return {"data": {"published": result["published"], **result}}
