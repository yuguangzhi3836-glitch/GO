from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol
from go_hotel.domain.models import Offer, Prebook

@dataclass(frozen=True)
class ConnectorCapabilities:
    search: bool = True
    prebook: bool = True
    book: bool = True
    status: bool = True
    cancel: bool = True
    change: bool = False
    refund: bool = False
    webhooks: bool = False
    idempotent_book: bool = True
    hard_inventory_hold: bool = False
    provider_price_lock: bool = True

@dataclass(frozen=True)
class ConnectorMetadata:
    connector_id: str
    display_name: str
    version: str
    capabilities: ConnectorCapabilities = field(default_factory=ConnectorCapabilities)

class HotelConnector(Protocol):
    metadata: ConnectorMetadata
    async def search(self, city_code: str, check_in: str, check_out: str, currency: str) -> list[Offer]: ...
    async def prebook(self, offer: Offer) -> Prebook: ...
    async def book(self, order_id: str, prebook: Prebook, idempotency_key: str | None = None) -> str: ...
    async def status(self, confirmation_no: str) -> str: ...
    async def cancel(self, confirmation_no: str) -> str: ...
    async def change(self, confirmation_no: str, new_check_in: str, new_check_out: str, idempotency_key: str | None = None) -> str: ...
    async def health(self) -> dict[str, Any]: ...
