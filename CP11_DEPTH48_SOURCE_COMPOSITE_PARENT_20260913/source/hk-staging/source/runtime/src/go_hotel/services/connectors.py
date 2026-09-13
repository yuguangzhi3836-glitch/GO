from __future__ import annotations
from go_hotel.connectors.registry import registry
from go_hotel.connectors.resilience import ResilientConnector
from go_hotel.connectors.certification import harness
from go_hotel.repositories.sql import repo

class ConnectorService:
    def wrapped(self, connector_id: str | None=None):
        c=registry.get(connector_id) if connector_id else registry.default()
        return ResilientConnector(c)
    async def certify(self, connector_id: str):
        report=await harness.certify(self.wrapped(connector_id)); repo.save_connector_certification(report.as_dict()); return report.as_dict()
    async def health(self):
        result=[]
        for meta in registry.list():
            c=self.wrapped(meta.connector_id)
            try: status=await c.health(); ok=True
            except Exception as exc: status={"error":str(exc)}; ok=False
            repo.save_connector_health(meta.connector_id, ok, status)
            result.append({"connector_id":meta.connector_id,"healthy":ok,"detail":status})
        return result
connector_service=ConnectorService()
