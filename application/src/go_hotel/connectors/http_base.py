from __future__ import annotations
import httpx
from typing import Any
from go_hotel.connectors.base import ConnectorMetadata

class HttpConnectorBase:
    """Provider-neutral HTTP base. Concrete providers own payload mapping and auth.

    No provider-specific contract is invented here; real connector implementations must be
    built against the supplier's signed API documentation and certified through Sprint 1F.
    """
    metadata: ConnectorMetadata
    def __init__(self, base_url: str, api_key: str | None = None, timeout_seconds: float = 4.0):
        self.base_url=base_url.rstrip('/'); self.api_key=api_key; self.timeout_seconds=timeout_seconds

    def headers(self) -> dict[str,str]:
        h={"Accept":"application/json","User-Agent":"GO-Hotel-Connector/1.0"}
        if self.api_key: h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def request(self, method: str, path: str, *, json: dict | None=None, params: dict | None=None, idempotency_key: str | None=None) -> dict[str, Any]:
        headers=self.headers()
        if idempotency_key: headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            r=await client.request(method, f"{self.base_url}/{path.lstrip('/')}", json=json, params=params, headers=headers)
            r.raise_for_status()
            return r.json()

    async def health(self):
        return {"status":"CONFIGURED","connector_id":self.metadata.connector_id,"base_url":self.base_url}
