from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import OfferDriftStateRow, OfferDriftEventRow
from go_hotel.domain.models import Offer, new_id

def _hash(data:dict)->str:
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()

class DriftService:
    def observe(self, offer:Offer, canonical_room_id:str)->list[str]:
        now=datetime.now(timezone.utc)
        payload={
            "total_amount_minor":offer.total_amount_minor,
            "currency":offer.currency,
            "fare_rule_id":offer.fare_rule_id,
            "meal_plan":getattr(offer,"meal_plan","ROOM_ONLY"),
            "refundable":getattr(offer,"refundable",True),
            "cancellation_deadline":getattr(offer,"cancellation_deadline",None),
            "inventory_units":getattr(offer,"inventory_units",None),
        }
        fp=_hash(payload); key=f"{offer.connector_id}:{offer.hotel_id}:{canonical_room_id}:{offer.rate_plan_id}:{offer.check_in}:{offer.check_out}:{offer.currency}"
        changes=[]
        with SessionLocal.begin() as s:
            state=s.get(OfferDriftStateRow,key)
            if state and state.fingerprint!=fp:
                before=state.snapshot or {}
                for field in payload:
                    if before.get(field)!=payload.get(field): changes.append(field)
                s.add(OfferDriftEventRow(drift_id=new_id("drift"),drift_key=key,connector_id=offer.connector_id,hotel_id=offer.hotel_id,canonical_room_id=canonical_room_id,changed_fields=changes,before_snapshot=before,after_snapshot=payload,detected_at=now,status="OPEN"))
                state.fingerprint=fp; state.snapshot=payload; state.updated_at=now
            elif state is None:
                s.add(OfferDriftStateRow(drift_key=key,connector_id=offer.connector_id,hotel_id=offer.hotel_id,canonical_room_id=canonical_room_id,fingerprint=fp,snapshot=payload,updated_at=now))
        return changes

drift_service=DriftService()
