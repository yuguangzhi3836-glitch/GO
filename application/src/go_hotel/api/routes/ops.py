from fastapi import APIRouter
from go_hotel.services.outbox import outbox_publisher
from go_hotel.services.recovery import recovery_worker

router = APIRouter(prefix="/internal/v1/ops", tags=["internal"])

@router.post("/outbox/run-once")
def outbox_once(limit: int = 100):
    return {"data": outbox_publisher.run_once(limit)}

@router.post("/saga-recovery/run-once")
async def saga_recovery_once(limit: int = 100):
    return {"data": await recovery_worker.run_once(limit)}
