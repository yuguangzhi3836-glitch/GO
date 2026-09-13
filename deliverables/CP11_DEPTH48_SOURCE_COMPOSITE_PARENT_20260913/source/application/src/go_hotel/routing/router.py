from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from sqlalchemy import select
from go_hotel.core.config import settings
from go_hotel.connectors.registry import registry
from go_hotel.connectors.resilience import ResilientConnector
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import SupplierConnectorOnboardingRow, RoutingDecisionRow
from go_hotel.domain.models import new_id, Offer
from go_hotel.routing.models import RouteCandidate, RoutingDecision
from go_hotel.routing.sla import sla_service


def now(): return datetime.now(timezone.utc)

def rollout_bucket(request_key:str, connector_id:str) -> int:
    raw=sha256(f"{request_key}:{connector_id}".encode()).digest()
    return int.from_bytes(raw[:4],"big") % 100 + 1

class TrafficRouter:
    def _active(self, request_key:str) -> list[dict]:
        known={m.connector_id for m in registry.list()}
        with SessionLocal() as s:
            rows=s.scalars(select(SupplierConnectorOnboardingRow).where(SupplierConnectorOnboardingRow.status=="ACTIVE",SupplierConnectorOnboardingRow.rollout_percent>0)).all()
            active=[]
            for r in rows:
                if r.connector_id not in known: continue
                if rollout_bucket(request_key,r.connector_id) <= r.rollout_percent:
                    active.append({"connector_id":r.connector_id,"supplier_id":r.supplier_id,"rollout_percent":r.rollout_percent})
        # V5.0 production truth: Mock connectors may support local/test compatibility only.
        # Production must fail closed when no certified/active supplier connector is available.
        if not active and "conn_mock_hotel" in known and settings.app_env.lower() not in {"prod","production"}:
            active=[{"connector_id":"conn_mock_hotel","supplier_id":"sup_mock","rollout_percent":100}]
        return active

    async def search(self, *, request_key:str, city_code:str, check_in:str, check_out:str, currency:str) -> tuple[list[RouteCandidate], RoutingDecision]:
        eligible=self._active(request_key)
        async def call(item):
            cid=item["connector_id"]
            try:
                offers=await ResilientConnector(registry.get(cid)).search(city_code,check_in,check_out,currency)
                return item,offers,None
            except Exception as exc:
                return item,[],str(exc)
        results=await asyncio.gather(*(call(i) for i in eligible))
        candidates=[]; failed=[]
        for item,offers,error in results:
            if error: failed.append(item["connector_id"]); continue
            sla=sla_service.get(item["connector_id"])
            if sla.health_status=="UNHEALTHY":
                failed.append(item["connector_id"]); continue
            for offer in offers:
                candidates.append(RouteCandidate(item["connector_id"],offer,item["supplier_id"],bool(offer.official_direct),item["rollout_percent"],sla,0))
        candidates.sort(key=lambda c:c.ranking_key(),reverse=True)
        selected=candidates[0].connector_id if candidates else None
        decision=RoutingDecision(new_id("route"),"SEARCH",candidates[0].offer.hotel_id if candidates else None,selected,[c.connector_id for c in candidates],self._reason_codes(candidates),[c.connector_id for c in candidates[1:]]+failed,request_key)
        self._save(decision,candidates)
        return candidates,decision

    def plan_for_offers(self, *, request_key:str, operation:str, candidates:list[RouteCandidate]) -> RoutingDecision:
        candidates=sorted(candidates,key=lambda c:c.ranking_key(),reverse=True)
        d=RoutingDecision(new_id("route"),operation,candidates[0].offer.hotel_id if candidates else None,candidates[0].connector_id if candidates else None,[c.connector_id for c in candidates],self._reason_codes(candidates),[c.connector_id for c in candidates[1:]],request_key)
        self._save(d,candidates); return d

    @staticmethod
    def _reason_codes(candidates:list[RouteCandidate])->list[str]:
        if not candidates: return ["NO_ELIGIBLE_CONNECTOR"]
        top=candidates[0]
        out=[]
        if top.official_authorized: out.append("OFFICIAL_AUTHORIZATION_PRIORITY")
        out += ["SLA_RELIABILITY", "USER_NET_VALUE", "FARE_FLEXIBILITY", "TOTAL_COST"]
        return out

    def _save(self,d:RoutingDecision,candidates:list[RouteCandidate]):
        with SessionLocal.begin() as s:
            s.add(RoutingDecisionRow(decision_id=d.decision_id,operation=d.operation,hotel_id=d.hotel_id,request_key=d.request_key,selected_connector_id=d.selected_connector_id,candidate_connector_ids=d.candidate_connector_ids,fallback_connector_ids=d.fallback_connector_ids,reason_codes=d.reason_codes,candidate_snapshot=[{"connector_id":c.connector_id,"official_authorized":c.official_authorized,"sla":c.sla.as_dict(),"total_amount_minor":c.offer.total_amount_minor} for c in candidates],created_at=now()))

traffic_router=TrafficRouter()
