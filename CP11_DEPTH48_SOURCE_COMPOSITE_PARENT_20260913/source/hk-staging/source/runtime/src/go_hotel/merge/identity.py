from __future__ import annotations
import re
from datetime import datetime, timezone
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import RoomExternalIdentityRow

_STOP={"room","hotel","the","with","and","non","smoking","smoke","禁烟","客房"}
def _norm(value:str)->str:
    words=re.findall(r"[a-z0-9]+",(value or "").lower().replace("kingbed","king bed"))
    return "-".join(w for w in words if w not in _STOP)

class RoomIdentityService:
    def map(self, connector_id:str, external_room_id:str, canonical_room_id:str, confidence_bps:int=10000, method:str="CONTRACTED_MAPPING"):
        now=datetime.now(timezone.utc)
        with SessionLocal.begin() as s:
            row=s.scalar(select(RoomExternalIdentityRow).where(RoomExternalIdentityRow.connector_id==connector_id,RoomExternalIdentityRow.external_room_id==external_room_id))
            if row:
                row.canonical_room_id=canonical_room_id; row.match_confidence_bps=confidence_bps; row.match_method=method; row.updated_at=now
            else:
                s.add(RoomExternalIdentityRow(connector_id=connector_id,external_room_id=external_room_id,canonical_room_id=canonical_room_id,match_confidence_bps=confidence_bps,match_method=method,status="ACTIVE",created_at=now,updated_at=now))

    def resolve(self, hotel_id:str, connector_id:str, external_room_id:str)->tuple[str,int,str]:
        with SessionLocal() as s:
            row=s.scalar(select(RoomExternalIdentityRow).where(RoomExternalIdentityRow.connector_id==connector_id,RoomExternalIdentityRow.external_room_id==external_room_id,RoomExternalIdentityRow.status=="ACTIVE"))
            if row: return row.canonical_room_id,row.match_confidence_bps,row.match_method
        # Conservative heuristic fallback. It creates a deterministic comparison bucket only;
        # it does not persist a contracted identity mapping.
        token=_norm(external_room_id)
        return f"heur:{hotel_id}:{token or external_room_id.lower()}",8500,"HEURISTIC_TOKEN"

room_identity_service=RoomIdentityService()
