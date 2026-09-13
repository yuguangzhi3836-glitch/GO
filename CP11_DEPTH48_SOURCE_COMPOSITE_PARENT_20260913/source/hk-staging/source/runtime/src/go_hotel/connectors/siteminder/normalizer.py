from __future__ import annotations
from datetime import datetime, timezone, timedelta
from go_hotel.connectors.mapping import CanonicalOfferMapping, get_path, MappingError
from go_hotel.domain.models import Offer, new_id

class SiteMinderCanonicalNormalizer:
    """Normalizes contracted SiteMinder payloads without hard-coding private API fields."""
    def __init__(self, connector_id: str, mapping: CanonicalOfferMapping, identity_resolver):
        self.connector_id=connector_id; self.mapping=mapping; self.identity_resolver=identity_resolver

    def normalize_search(self, payload: dict) -> list[Offer]:
        items=get_path(payload,self.mapping.offers_path,[])
        if not isinstance(items,list): raise MappingError("offers_path must resolve to list")
        offers=[]
        for raw in items:
            ext_property=str(get_path(raw,self.mapping.external_property_id,""))
            hotel_id=self.identity_resolver(ext_property)
            if not hotel_id:
                continue  # unmapped properties are never silently exposed as new GO hotels
            amount=int(get_path(raw,self.mapping.amount_minor,0) or 0)
            currency=str(get_path(raw,self.mapping.currency,""))
            if amount <= 0 or len(currency) != 3: continue
            expires=datetime.now(timezone.utc)+timedelta(minutes=10)
            offers.append(Offer(
                offer_id=new_id("off"), hotel_id=hotel_id,
                room_type_id=f"ext:{get_path(raw,self.mapping.external_room_id,'unknown')}",
                rate_plan_id=f"ext:{get_path(raw,self.mapping.external_rate_id,'unknown')}",
                total_amount_minor=amount, currency=currency.upper(),
                check_in=str(get_path(raw,self.mapping.check_in,"")), check_out=str(get_path(raw,self.mapping.check_out,"")),
                official_direct=True,
                fare_rule_id=str(get_path(raw,self.mapping.fare_rule_id,"fr_supplier_snapshot")) if self.mapping.fare_rule_id else "fr_supplier_snapshot",
                expires_at=expires,
            ))
        return offers
