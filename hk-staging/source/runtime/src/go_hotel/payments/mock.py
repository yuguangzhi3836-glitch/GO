from __future__ import annotations
import asyncio
from hashlib import sha256
from go_hotel.domain.models import Payment, PaymentStatus

class MockPaymentProvider:
    """Provider simulator for authorize -> capture/void semantics with idempotency."""
    def __init__(self):
        self.authorize_calls = 0
        self.capture_calls = 0
        self.void_calls = 0
        self.refund_calls = 0
        self.delay_seconds = 0.0
        self._authorizations: dict[str, Payment] = {}
        self._tokens: dict[str, str] = {}
        self._capture_results: dict[str, Payment] = {}
        self._void_results: dict[str, Payment] = {}
        self._refund_results: dict[str, Payment] = {}

    def reset(self) -> None:
        self.authorize_calls = self.capture_calls = self.void_calls = self.refund_calls = 0
        self.delay_seconds = 0.0
        self._authorizations.clear(); self._tokens.clear(); self._capture_results.clear(); self._void_results.clear(); self._refund_results.clear()

    async def authorize(self, order_id: str, amount_minor: int, currency: str, token: str, idempotency_key: str) -> Payment:
        if idempotency_key in self._authorizations:
            return self._authorizations[idempotency_key]
        self.authorize_calls += 1
        if self.delay_seconds: await asyncio.sleep(self.delay_seconds)
        pid = "pay_" + sha256(idempotency_key.encode()).hexdigest()[:16]
        status = PaymentStatus.FAILED if token == "pm_decline" else PaymentStatus.AUTHORIZED
        p = Payment(pid, order_id, amount_minor, currency, status)
        self._authorizations[idempotency_key] = p
        self._tokens[pid] = token
        return p

    async def capture(self, payment_id: str, idempotency_key: str) -> Payment:
        if idempotency_key in self._capture_results:
            return self._capture_results[idempotency_key]
        self.capture_calls += 1
        if self.delay_seconds: await asyncio.sleep(self.delay_seconds)
        auth = next((p for p in self._authorizations.values() if p.payment_id == payment_id), None)
        if auth is None:
            return Payment(payment_id, "unknown", 0, "XXX", PaymentStatus.FAILED)
        token = self._tokens.get(payment_id)
        status = PaymentStatus.FAILED if token == "pm_capture_fail" else PaymentStatus.CAPTURED
        p = Payment(auth.payment_id, auth.order_id, auth.amount_minor, auth.currency, status)
        self._capture_results[idempotency_key] = p
        return p

    async def void(self, payment_id: str, idempotency_key: str) -> Payment:
        if idempotency_key in self._void_results:
            return self._void_results[idempotency_key]
        self.void_calls += 1
        auth = next((p for p in self._authorizations.values() if p.payment_id == payment_id), None)
        if auth is None:
            p = Payment(payment_id, "unknown", 0, "XXX", PaymentStatus.FAILED)
        else:
            p = Payment(auth.payment_id, auth.order_id, auth.amount_minor, auth.currency, PaymentStatus.VOIDED)
        self._void_results[idempotency_key] = p
        return p


    async def refund(self, payment_id: str, amount_minor: int, idempotency_key: str) -> Payment:
        if idempotency_key in self._refund_results:
            return self._refund_results[idempotency_key]
        self.refund_calls += 1
        captured = next((p for p in self._capture_results.values() if p.payment_id == payment_id and p.status == PaymentStatus.CAPTURED), None)
        if captured is None or amount_minor < 0 or amount_minor > captured.amount_minor:
            p = Payment(payment_id, captured.order_id if captured else "unknown", amount_minor, captured.currency if captured else "XXX", PaymentStatus.FAILED)
        else:
            p = Payment(payment_id, captured.order_id, amount_minor, captured.currency, PaymentStatus.REFUNDED)
        self._refund_results[idempotency_key] = p
        return p

    async def status(self, payment_id: str) -> PaymentStatus:
        for p in self._capture_results.values():
            if p.payment_id == payment_id: return p.status
        for p in self._void_results.values():
            if p.payment_id == payment_id: return p.status
        for p in self._authorizations.values():
            if p.payment_id == payment_id: return p.status
        return PaymentStatus.FAILED

payment_provider = MockPaymentProvider()
