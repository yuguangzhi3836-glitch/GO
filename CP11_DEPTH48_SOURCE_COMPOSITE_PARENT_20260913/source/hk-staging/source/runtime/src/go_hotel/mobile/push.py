from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import uuid
import httpx
from sqlalchemy import select
from go_hotel.core.config import settings
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import ConsumerNotificationRow, ConsumerDeviceRow, MobilePushReceiptRow
from go_hotel.security.mfa import unseal

UTC = timezone.utc

def now():
    return datetime.now(UTC)

def rid():
    return f"prc_{uuid.uuid4().hex}"

@dataclass
class PushResult:
    ok: bool
    provider_message_id: str | None = None
    error: str | None = None

@dataclass
class ReceiptResult:
    status: str  # DELIVERED | FAILED | PENDING
    error_code: str | None = None
    error_detail: str | None = None

class MockPushProvider:
    name = "MOCK"
    def send(self, token, title, body, deep_link):
        return PushResult(True, f"mock_{uuid.uuid4().hex}")
    def receipts(self, ids: list[str]):
        return {x: ReceiptResult("DELIVERED") for x in ids}

class ExpoPushProvider:
    name = "EXPO"
    def send(self, token, title, body, deep_link):
        payload = {"to": token, "title": title, "body": body, "data": {"deep_link": deep_link} if deep_link else {}}
        try:
            r = httpx.post(settings.expo_push_url, json=payload, timeout=8.0)
            if r.status_code >= 300:
                return PushResult(False, error=f"HTTP_{r.status_code}")
            d = r.json().get("data") or {}
            if d.get("status") == "error":
                return PushResult(False, error=d.get("details", {}).get("error") or d.get("message") or "EXPO_PUSH_ERROR")
            return PushResult(True, d.get("id"))
        except Exception as e:
            return PushResult(False, error=f"EXPO_PUSH_EXCEPTION:{type(e).__name__}")

    def receipts(self, ids: list[str]):
        if not ids:
            return {}
        url = settings.expo_push_url.replace("/send", "/getReceipts")
        try:
            r = httpx.post(url, json={"ids": ids}, timeout=10.0)
            if r.status_code >= 300:
                return {x: ReceiptResult("PENDING", error_detail=f"HTTP_{r.status_code}") for x in ids}
            data = r.json().get("data") or {}
            out = {}
            for mid in ids:
                item = data.get(mid)
                if not item:
                    out[mid] = ReceiptResult("PENDING")
                elif item.get("status") == "ok":
                    out[mid] = ReceiptResult("DELIVERED")
                else:
                    details = item.get("details") or {}
                    out[mid] = ReceiptResult("FAILED", details.get("error"), item.get("message"))
            return out
        except Exception as e:
            return {x: ReceiptResult("PENDING", error_detail=f"EXPO_RECEIPT_EXCEPTION:{type(e).__name__}") for x in ids}

def provider_for():
    return ExpoPushProvider() if settings.mobile_push_mode.lower() == "expo" else MockPushProvider()

class ConsumerPushWorker:
    """Submits inbox notifications to active devices and persists one receipt per device attempt."""
    def run_once(self):
        processed = 0
        provider = provider_for()
        with SessionLocal() as s:
            notifications = s.scalars(
                select(ConsumerNotificationRow)
                .where(ConsumerNotificationRow.delivery_status == "PENDING")
                .order_by(ConsumerNotificationRow.created_at)
                .limit(settings.mobile_push_batch_size)
            ).all()
            for n in notifications:
                devices = s.scalars(
                    select(ConsumerDeviceRow).where(
                        ConsumerDeviceRow.user_id == n.user_id,
                        ConsumerDeviceRow.status == "ACTIVE",
                        ConsumerDeviceRow.notifications_enabled == True,
                    )
                ).all()
                attempted = 0
                success = 0
                for d in devices:
                    if not d.push_token_ciphertext:
                        continue
                    attempted += 1
                    result = provider.send(unseal(d.push_token_ciphertext), n.title, n.body, n.deep_link)
                    receipt = MobilePushReceiptRow(
                        receipt_id=rid(), notification_id=n.notification_id, device_id=d.device_id,
                        provider=provider.name, provider_message_id=result.provider_message_id,
                        status="SUBMITTED" if result.ok else "FAILED",
                        error_code=None if result.ok else result.error,
                        error_detail=None if result.ok else result.error,
                        attempt_count=1, submitted_at=now(), checked_at=None, delivered_at=None,
                    )
                    s.add(receipt)
                    if result.ok:
                        success += 1
                n.delivery_status = "SENT" if success else ("INBOX_ONLY" if attempted == 0 else "FAILED")
                processed += 1
            s.commit()
        return processed

class PushReceiptWorker:
    """Resolves provider receipts and revokes dead push tokens without deleting the in-app inbox."""
    DEAD_TOKEN_ERRORS = {"DeviceNotRegistered", "DEVICE_NOT_REGISTERED", "InvalidCredentials"}

    def run_once(self):
        provider = provider_for()
        cutoff = now() - timedelta(seconds=settings.mobile_push_receipt_min_age_seconds)
        with SessionLocal() as s:
            rows = s.scalars(
                select(MobilePushReceiptRow)
                .where(
                    MobilePushReceiptRow.status == "SUBMITTED",
                    MobilePushReceiptRow.provider_message_id.is_not(None),
                    MobilePushReceiptRow.submitted_at <= cutoff,
                )
                .order_by(MobilePushReceiptRow.submitted_at)
                .limit(settings.mobile_push_receipt_batch_size)
            ).all()
            ids = [x.provider_message_id for x in rows if x.provider_message_id]
            if not ids:
                return 0
            results = provider.receipts(ids)
            changed = 0
            for row in rows:
                result = results.get(row.provider_message_id)
                if not result or result.status == "PENDING":
                    row.checked_at = now()
                    row.attempt_count += 1
                    continue
                row.checked_at = now()
                row.status = result.status
                row.error_code = result.error_code
                row.error_detail = result.error_detail
                if result.status == "DELIVERED":
                    row.delivered_at = now()
                elif result.error_code in self.DEAD_TOKEN_ERRORS:
                    device = s.get(ConsumerDeviceRow, row.device_id)
                    if device:
                        device.status = "REVOKED"
                        device.notifications_enabled = False
                        device.updated_at = now()
                changed += 1
            s.commit()
            return changed

    def status(self, notification_id: str):
        with SessionLocal() as s:
            rows = s.scalars(select(MobilePushReceiptRow).where(MobilePushReceiptRow.notification_id == notification_id)).all()
            return [{
                "receipt_id": x.receipt_id,
                "device_id": x.device_id,
                "provider": x.provider,
                "provider_message_id": x.provider_message_id,
                "status": x.status,
                "error_code": x.error_code,
                "attempt_count": x.attempt_count,
                "submitted_at": x.submitted_at.isoformat(),
                "checked_at": x.checked_at.isoformat() if x.checked_at else None,
                "delivered_at": x.delivered_at.isoformat() if x.delivered_at else None,
            } for x in rows]

push_worker = ConsumerPushWorker()
push_receipt_worker = PushReceiptWorker()
