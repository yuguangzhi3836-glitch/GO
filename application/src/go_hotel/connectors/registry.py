from __future__ import annotations
from go_hotel.connectors.base import HotelConnector
from go_hotel.connectors.mock_hotel import connector as mock_connector

class ConnectorRegistry:
    def __init__(self): self._items: dict[str, HotelConnector] = {}
    def register(self, connector: HotelConnector): self._items[connector.metadata.connector_id] = connector; return connector
    def get(self, connector_id: str) -> HotelConnector:
        if connector_id not in self._items: raise KeyError(f"Unknown connector {connector_id}")
        return self._items[connector_id]
    def default(self) -> HotelConnector: return self.get("conn_mock_hotel")
    def list(self): return [c.metadata for c in self._items.values()]

registry=ConnectorRegistry(); registry.register(mock_connector)
