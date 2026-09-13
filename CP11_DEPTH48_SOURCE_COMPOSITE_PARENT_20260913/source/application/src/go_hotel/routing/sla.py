from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import ConnectorSlaWindowRow
from go_hotel.routing.models import ConnectorSlaScore

def now(): return datetime.now(timezone.utc)

def _weighted(success:int, latency_score:int, cancel:int, inventory:int, price:int) -> int:
    # 45/20/15/10/10. Score is routing reliability only, never GO Judgment.
    return round(success*.45 + latency_score*.20 + cancel*.15 + inventory*.10 + price*.10)

def _latency_score(p95_ms:int) -> int:
    if p95_ms <= 500: return 10000
    if p95_ms <= 1000: return 9000
    if p95_ms <= 2000: return 7500
    if p95_ms <= 4000: return 5500
    if p95_ms <= 8000: return 3000
    return 1000

class ConnectorSlaService:
    def get(self, connector_id:str) -> ConnectorSlaScore:
        with SessionLocal() as s:
            r=s.get(ConnectorSlaWindowRow, connector_id)
            if not r: return ConnectorSlaScore(connector_id=connector_id)
            return ConnectorSlaScore(
                connector_id=connector_id,
                success_rate_bps=r.success_rate_bps,
                confirmation_latency_ms_p95=r.confirmation_latency_ms_p95,
                cancel_success_rate_bps=r.cancel_success_rate_bps,
                inventory_accuracy_bps=r.inventory_accuracy_bps,
                price_consistency_bps=r.price_consistency_bps,
                composite_score_bps=r.composite_score_bps,
                sample_size=r.sample_size,
                health_status=r.health_status,
            )

    def upsert_snapshot(self, connector_id:str, *, success_rate_bps:int, confirmation_latency_ms_p95:int,
                        cancel_success_rate_bps:int, inventory_accuracy_bps:int, price_consistency_bps:int,
                        sample_size:int=0) -> dict:
        for n in (success_rate_bps,cancel_success_rate_bps,inventory_accuracy_bps,price_consistency_bps):
            if n < 0 or n > 10000: raise ValueError("INVALID_SLA_BPS")
        comp=_weighted(success_rate_bps,_latency_score(confirmation_latency_ms_p95),cancel_success_rate_bps,inventory_accuracy_bps,price_consistency_bps)
        health="HEALTHY" if comp>=8500 else "DEGRADED" if comp>=6500 else "UNHEALTHY"
        with SessionLocal.begin() as s:
            r=s.get(ConnectorSlaWindowRow,connector_id)
            if not r:
                r=ConnectorSlaWindowRow(connector_id=connector_id,success_rate_bps=success_rate_bps,confirmation_latency_ms_p95=confirmation_latency_ms_p95,cancel_success_rate_bps=cancel_success_rate_bps,inventory_accuracy_bps=inventory_accuracy_bps,price_consistency_bps=price_consistency_bps,composite_score_bps=comp,sample_size=sample_size,health_status=health,updated_at=now()); s.add(r)
            else:
                r.success_rate_bps=success_rate_bps; r.confirmation_latency_ms_p95=confirmation_latency_ms_p95; r.cancel_success_rate_bps=cancel_success_rate_bps; r.inventory_accuracy_bps=inventory_accuracy_bps; r.price_consistency_bps=price_consistency_bps; r.composite_score_bps=comp; r.sample_size=sample_size; r.health_status=health; r.updated_at=now()
        return self.get(connector_id).as_dict()

sla_service=ConnectorSlaService()
