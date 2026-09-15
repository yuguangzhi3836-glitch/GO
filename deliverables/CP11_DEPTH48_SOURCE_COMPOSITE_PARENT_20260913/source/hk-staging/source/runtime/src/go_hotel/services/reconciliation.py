from __future__ import annotations
from go_hotel.connectors.registry import registry
from go_hotel.connectors.resilience import ResilientConnector
from go_hotel.repositories.sql import repo
from go_hotel.domain.models import Event, new_id

class ReconciliationService:
    """Detects drift between GO ledger projection and supplier system; never overwrites silently."""
    async def run_once(self, limit: int=100):
        candidates=repo.orders_for_reconciliation(limit); checked=mismatch=errors=0
        for item in candidates:
            checked += 1
            try:
                c=ResilientConnector(registry.default())
                external=await c.status(item["supplier_confirmation_no"])
                local=item["status"]
                compatible=(local=="CONFIRMED" and external=="CONFIRMED") or (local=="FAILED" and external=="NOT_FOUND")
                repo.record_reconciliation(item["order_id"], c.metadata.connector_id, local, external, "MATCH" if compatible else "MISMATCH")
                if not compatible:
                    mismatch += 1
                    repo.append_event(Event(new_id("evt"),"RECONCILIATION_MISMATCH_DETECTED","HOTEL_ORDER",item["order_id"],{"local_status":local,"external_status":external,"connector_id":c.metadata.connector_id}))
            except Exception as exc:
                errors += 1; repo.record_reconciliation(item["order_id"], registry.default().metadata.connector_id, item["status"], None, "ERROR", str(exc))
        return {"checked":checked,"mismatches":mismatch,"errors":errors}
reconciliation_service=ReconciliationService()
