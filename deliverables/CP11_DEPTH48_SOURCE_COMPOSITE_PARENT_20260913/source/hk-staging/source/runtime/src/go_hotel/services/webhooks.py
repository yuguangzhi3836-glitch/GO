from __future__ import annotations
import hashlib
import hmac
from go_hotel.core.config import settings
from go_hotel.repositories.sql import repo

class WebhookService:
    def signature(self, raw_body: bytes) -> str:
        return hmac.new(settings.webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()

    def verify(self, raw_body: bytes, supplied: str | None) -> bool:
        if not supplied: return False
        expected = self.signature(raw_body)
        return hmac.compare_digest(expected, supplied)

    def ingest_and_process(self, connector_id: str, payload: dict, raw_body: bytes, signature: str | None) -> tuple[dict, bool]:
        valid = self.verify(raw_body, signature)
        row, created = repo.ingest_webhook(
            connector_id=connector_id,
            external_event_id=str(payload.get("external_event_id") or ""),
            aggregate_id=str(payload.get("order_id") or ""),
            event_type=str(payload.get("event_type") or ""),
            sequence=payload.get("sequence"),
            payload=payload,
            signature_valid=valid,
        )
        if valid and created:
            row = repo.process_webhook(row["webhook_id"])
        return row, created

webhook_service = WebhookService()
