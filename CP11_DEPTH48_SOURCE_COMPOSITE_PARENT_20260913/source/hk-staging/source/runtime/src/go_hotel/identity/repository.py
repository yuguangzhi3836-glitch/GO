from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.orm import Session
from go_hotel.db.models import HotelExternalIdentityRow

class HotelIdentityRepository:
    def __init__(self, session: Session): self.session = session

    def resolve(self, connector_id: str, external_hotel_id: str) -> str | None:
        row = self.session.execute(
            select(HotelExternalIdentityRow).where(
                HotelExternalIdentityRow.connector_id == connector_id,
                HotelExternalIdentityRow.external_hotel_id == external_hotel_id,
                HotelExternalIdentityRow.status == "ACTIVE",
            )
        ).scalar_one_or_none()
        return row.hotel_id if row else None

    def upsert(self, connector_id: str, external_hotel_id: str, hotel_id: str, *, confidence: int = 10000, method: str = "CONTRACTED_MAPPING") -> None:
        row = self.session.execute(
            select(HotelExternalIdentityRow).where(
                HotelExternalIdentityRow.connector_id == connector_id,
                HotelExternalIdentityRow.external_hotel_id == external_hotel_id,
            )
        ).scalar_one_or_none()
        if row is None:
            row = HotelExternalIdentityRow(
                connector_id=connector_id, external_hotel_id=external_hotel_id, hotel_id=hotel_id,
                match_confidence_bps=confidence, match_method=method, status="ACTIVE"
            )
            self.session.add(row)
        else:
            row.hotel_id=hotel_id; row.match_confidence_bps=confidence; row.match_method=method; row.status="ACTIVE"
