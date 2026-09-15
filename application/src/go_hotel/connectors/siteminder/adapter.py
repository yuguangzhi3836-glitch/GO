from __future__ import annotations
from typing import Callable
from go_hotel.connectors.base import ConnectorMetadata, ConnectorCapabilities
from go_hotel.connectors.http_base import HttpConnectorBase
from go_hotel.connectors.mapping import get_path, MappingError
from go_hotel.connectors.siteminder.config import SiteMinderConfig
from go_hotel.connectors.siteminder.normalizer import SiteMinderCanonicalNormalizer
from go_hotel.domain.models import Offer, Prebook, new_id

class SiteMinderChannelsPlusConnector(HttpConnectorBase):
    """GO adapter boundary for SiteMinder booking-channel connectivity.

    SiteMinder publicly describes Channels Plus as supporting property search, availability,
    pricing, static content and media for booking channels, while SiteConnect supports rates,
    availability/restrictions and reservation management. Exact partner endpoint paths and
    private payload fields are therefore injected from the contracted sandbox specification,
    not guessed in source code.
    """
    metadata=ConnectorMetadata(
        connector_id="conn_siteminder_channels_plus", display_name="SiteMinder Channels Plus",
        version="1.0-sprint1g", capabilities=ConnectorCapabilities(search=True,prebook=True,book=True,status=True,cancel=True,webhooks=False,idempotent_book=True)
    )
    def __init__(self, cfg: SiteMinderConfig, identity_resolver: Callable[[str],str|None]):
        super().__init__(cfg.base_url, api_key=None, timeout_seconds=cfg.timeout_seconds)
        self.cfg=cfg; self.identity_resolver=identity_resolver
        self.normalizer=SiteMinderCanonicalNormalizer(self.metadata.connector_id,cfg.offer_mapping,identity_resolver)

    def headers(self) -> dict[str,str]:
        h=super().headers(); h["Authorization"]=f"Bearer {self.cfg.bearer_token}"; return h

    async def search(self, city_code:str, check_in:str, check_out:str, currency:str) -> list[Offer]:
        payload=await self.request("POST",self.cfg.endpoints.search_path,json={"city_code":city_code,"check_in":check_in,"check_out":check_out,"currency":currency})
        return self.normalizer.normalize_search(payload)

    async def prebook(self, offer:Offer) -> Prebook:
        payload=await self.request("POST",self.cfg.endpoints.prebook_path,json={"offer_id":offer.offer_id,"hotel_id":offer.hotel_id,"amount_minor":offer.total_amount_minor,"currency":offer.currency})
        m=self.cfg.prebook_mapping
        amount=int(get_path(payload,m.amount_minor,offer.total_amount_minor)) if m.amount_minor else offer.total_amount_minor
        currency=str(get_path(payload,m.currency,offer.currency)) if m.currency else offer.currency
        return Prebook(prebook_id=new_id("pb"),offer_id=offer.offer_id,total_amount_minor=amount,currency=currency)

    async def book(self, order_id:str, prebook:Prebook, idempotency_key:str|None=None) -> str:
        payload=await self.request("POST",self.cfg.endpoints.book_path,json={"order_id":order_id,"prebook_id":prebook.prebook_id},idempotency_key=idempotency_key)
        conf=get_path(payload,self.cfg.booking_mapping.confirmation_no)
        if not conf: raise MappingError("supplier confirmation number missing")
        return str(conf)

    async def status(self, confirmation_no:str) -> str:
        payload=await self.request("GET",self.cfg.endpoints.status_path,params={"confirmation_no":confirmation_no})
        path=self.cfg.booking_mapping.status
        raw=str(get_path(payload,path,"PENDING")) if path else "PENDING"
        normalized=raw.upper()
        if normalized in {"CONFIRMED","CANCELLED","PENDING","NOT_FOUND"}: return normalized
        return "PENDING"

    async def cancel(self, confirmation_no:str) -> str:
        payload=await self.request("POST",self.cfg.endpoints.cancel_path,json={"confirmation_no":confirmation_no})
        path=self.cfg.booking_mapping.status
        raw=str(get_path(payload,path,"CANCELLED")) if path else "CANCELLED"
        return "CANCELLED" if raw.upper() in {"CANCELLED","SUCCESS","OK"} else raw.upper()

    async def health(self):
        return {"status":"CONFIGURED","connector_id":self.metadata.connector_id,"base_url":self.base_url,"sandbox_ready":True}
