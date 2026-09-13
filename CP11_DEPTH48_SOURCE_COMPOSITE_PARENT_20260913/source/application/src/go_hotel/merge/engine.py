from __future__ import annotations
import hashlib, json
from collections import defaultdict
from datetime import datetime, timezone
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OfferMergeDecisionRow
from go_hotel.domain.models import Offer, new_id
from go_hotel.merge.identity import room_identity_service
from go_hotel.merge.models import MergeCandidate, MergeDecision, NormalizedPolicy
from go_hotel.merge.drift import drift_service
from go_hotel.routing.sla import sla_service

def _fp(x:dict)->str: return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()

def _policy(o:Offer)->NormalizedPolicy:
    refundable=bool(getattr(o,"refundable",True))
    deadline=getattr(o,"cancellation_deadline",None)
    data={"refundable":refundable,"deadline":deadline,"fare_rule_id":o.fare_rule_id}
    return NormalizedPolicy(refundable,deadline,o.fare_rule_id,_fp(data))

def _source_rank(o:Offer)->tuple:
    sla=sla_service.get(o.connector_id)
    # Official authorization, reliability, flexibility, total cost. No GO Score / recommendation fields.
    return (1 if o.official_direct else 0,sla.composite_score_bps,1 if getattr(o,"refundable",True) else 0,-o.total_amount_minor)

class OfferMergeEngine:
    def merge(self, offers:list[Offer])->tuple[list[Offer],list[MergeDecision]]:
        buckets=defaultdict(list)
        for o in offers:
            room_id,confidence,_=room_identity_service.resolve(o.hotel_id,o.connector_id,o.room_type_id)
            c=MergeCandidate(o,room_id,confidence,_policy(o))
            drift_service.observe(o,room_id)
            # Different meal plans and materially different policies remain separate comparable offers.
            key=(o.hotel_id,room_id,o.check_in,o.check_out,o.currency,getattr(o,"meal_plan","ROOM_ONLY"),c.policy.fingerprint)
            buckets[key].append(c)
        selected=[]; decisions=[]
        for key,cands in buckets.items():
            cands.sort(key=lambda c:_source_rank(c.offer),reverse=True)
            top=cands[0]; conflicts=[]
            amounts={c.offer.total_amount_minor for c in cands}
            if len(amounts)>1:
                hi=max(amounts); lo=min(amounts)
                conflicts.append({"type":"PRICE_CONFLICT","min_minor":lo,"max_minor":hi,"spread_minor":hi-lo})
            inventories={getattr(c.offer,"inventory_units",None) for c in cands if getattr(c.offer,"inventory_units",None) is not None}
            if len(inventories)>1: conflicts.append({"type":"INVENTORY_CONFLICT","values":sorted(inventories)})
            d=MergeDecision(new_id("merge"),top.offer.hotel_id,top.canonical_room_id,top.offer.offer_id,top.offer.connector_id,[c.offer.offer_id for c in cands[1:]], ["OFFICIAL_AUTHORIZATION","SLA_RELIABILITY","FARE_FLEXIBILITY","TOTAL_COST"], conflicts)
            self._save(d,cands)
            selected.append(top.offer); decisions.append(d)
        # One chosen source for each equivalent rate/policy bucket; consumers can still compare materially different policies.
        selected.sort(key=lambda o:(o.hotel_id,o.total_amount_minor))
        return selected,decisions

    def _save(self,d:MergeDecision,cands:list[MergeCandidate]):
        now=datetime.now(timezone.utc)
        with SessionLocal.begin() as s:
            s.add(OfferMergeDecisionRow(decision_id=d.decision_id,hotel_id=d.hotel_id,canonical_room_id=d.canonical_room_id,selected_offer_id=d.selected_offer_id,selected_connector_id=d.selected_connector_id,alternate_offer_ids=d.alternate_offer_ids,reason_codes=d.reason_codes,conflicts=d.conflicts,candidate_snapshot=[{"offer_id":c.offer.offer_id,"connector_id":c.offer.connector_id,"total_amount_minor":c.offer.total_amount_minor,"policy_fingerprint":c.policy.fingerprint,"room_confidence_bps":c.room_confidence_bps} for c in cands],created_at=now))

offer_merge_engine=OfferMergeEngine()
