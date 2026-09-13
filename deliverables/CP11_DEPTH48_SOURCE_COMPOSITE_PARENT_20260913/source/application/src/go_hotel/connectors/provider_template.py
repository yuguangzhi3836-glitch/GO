from __future__ import annotations
"""Copy this file when implementing a contracted supplier API.

Replace mappings only from that supplier's current signed API specification. Never infer
provider fields from another supplier and never expose raw supplier payloads to GO domains.
"""
from go_hotel.connectors.base import ConnectorMetadata, ConnectorCapabilities
from go_hotel.connectors.http_base import HttpConnectorBase
from go_hotel.domain.models import Offer, Prebook

class ProviderConnectorTemplate(HttpConnectorBase):
    metadata=ConnectorMetadata(
        connector_id="conn_replace_me",
        display_name="Replace Me",
        version="0.1",
        capabilities=ConnectorCapabilities(webhooks=False),
    )
    async def search(self, city_code:str, check_in:str, check_out:str, currency:str) -> list[Offer]:
        raise NotImplementedError("Map provider search response to canonical Offer")
    async def prebook(self, offer:Offer) -> Prebook:
        raise NotImplementedError("Map provider prebook response")
    async def book(self, order_id:str, prebook:Prebook, idempotency_key:str|None=None) -> str:
        raise NotImplementedError("Return supplier confirmation number")
    async def status(self, confirmation_no:str) -> str:
        raise NotImplementedError("Normalize supplier status")
    async def cancel(self, confirmation_no:str) -> str:
        raise NotImplementedError("Normalize supplier cancellation result")
