from __future__ import annotations
from go_hotel.repositories.sql import repo
from go_hotel.services.booking import booking_service

class SagaRecoveryWorker:
    async def run_once(self, limit: int = 100) -> dict:
        ops = repo.recoverable_operations(limit)
        recovered = failed = 0
        for op in ops:
            try:
                if op["operation_type"] == "SUPPLIER_BOOK":
                    await booking_service.recover_confirmation(op)
                elif op["operation_type"] == "PAYMENT_CAPTURE_AFTER_BOOK":
                    await booking_service.recover_capture(op)
                elif op["operation_type"] == "PAYMENT_AUTHORIZE":
                    await booking_service.recover_authorization(op)
                else:
                    continue
                recovered += 1
            except Exception as exc:
                repo.mark_reconcile_required(op["operation_id"], str(exc)); failed += 1
        return {"scanned": len(ops), "recovered": recovered, "failed": failed}

recovery_worker = SagaRecoveryWorker()
