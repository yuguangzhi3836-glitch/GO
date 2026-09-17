from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json

import pytest

from go_hotel.connectors.external_sandbox_runtime import ContractDrivenHotelSupplyExecutor


NOW = datetime(2026, 9, 17, 6, 30, tzinfo=timezone.utc)


def contract(auth_method: str = "BEARER", max_attempts: int = 2) -> dict:
    operation = {
        "method": "POST",
        "path": "/v1/op",
        "request_mapping": {"hotel": "hotel"},
        "response_mapping": {"id": "supplier_reference"},
    }
    return {
        "provider": {"provider_code": "SIGNED_PROVIDER", "supplier_legal_name": "Signed Supplier Ltd", "environment": "SANDBOX"},
        "contract_source": {
            "authority": "SIGNED_SUPPLIER_DOCUMENTATION",
            "documentation_reference": "contract://signed/42",
            "documentation_version": "42",
            "documentation_hash": "sha256:" + "a" * 64,
        },
        "transport": {
            "base_url": "https://sandbox.supplier.test",
            "auth": {"method": auth_method, "credential_reference": "vault://supplier/auth"},
            "ip_allowlist_reference": "change://allowlist/42",
        },
        "operations": {name: dict(operation) for name in ("availability", "quote", "book", "query", "cancel")},
        "canonical_mapping": {name: {"source": "signed"} for name in ("property", "room", "rate_plan", "availability", "quote", "booking", "cancellation")},
        "webhook": {
            "callback_path": "/callbacks/supplier",
            "signature": {
                "scheme": "HMAC_SHA256",
                "signature_header": "X-Signature",
                "secret_reference": "vault://supplier/webhook",
                "timestamp_header": "X-Timestamp",
                "replay_tolerance_seconds": 300,
            },
        },
        "error_mapping": {"supplier_to_go": {"429": "RATE_LIMITED"}, "unknown_error_policy": "FAIL_CLOSED"},
        "limits": {
            "requests_per_second": 100000,
            "max_concurrency": 1,
            "connect_timeout_ms": 1000,
            "read_timeout_ms": 1000,
            "max_attempts": max_attempts,
            "retryable_go_errors": ["RATE_LIMITED"],
        },
        "attestation": {
            "contract_reference": "contract://signed/42",
            "sandbox_account_reference": "supplier-account://sandbox/42",
            "test_property_reference": "supplier-property://test/42",
            "authorized_scope": ["availability", "quote", "book", "query", "cancel"],
            "evidence_references": ["evidence://supplier-contract/42"],
            "prepared_by": "supplier-integration-owner",
            "prepared_at": "2026-09-17T00:00:00Z",
            "external_transport_verified": False,
        },
    }


class Resolver:
    def resolve(self, reference: str) -> dict[str, str]:
        return {"token": "secret-token", "signing_key": "secret-key"}


class Transport:
    def __init__(self, responses=None):
        self.responses = list(responses or [(200, {"Content-Type": "application/json"}, b'{"supplier_reference":"S-42"}')])
        self.calls = []

    def request(self, method, url, *, headers, body, timeout_seconds):
        self.calls.append((method, url, headers, body, timeout_seconds))
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


class Evidence:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.attempts = []

    def seal_attempt(self, **attempt):
        self.attempts.append(attempt)
        if self.fail:
            return ""
        return f"evidence://raw/{attempt['operation']}/{attempt['attempt']}"


class Replay:
    def __init__(self):
        self.keys = set()

    def claim(self, replay_key: str, *, expires_at: datetime) -> bool:
        if replay_key in self.keys:
            return False
        self.keys.add(replay_key)
        return True


class Materializer:
    def materialize(self, **context):
        assert context["scheme"] == "HMAC"
        assert context["resolved_secret"]["signing_key"] == "secret-key"
        return {"Authorization": "HMAC signed-request", "X-Body-SHA256": hashlib.sha256(context["body"]).hexdigest()}


def executor(*, auth_method="BEARER", transport=None, evidence=None, replay=None, materializer=None):
    return ContractDrivenHotelSupplyExecutor(
        contract=contract(auth_method),
        resolver=Resolver(),
        transport=transport or Transport(),
        evidence_sink=evidence or Evidence(),
        replay_store=replay or Replay(),
        auth_materializer=materializer,
        clock=lambda: NOW,
    )


def execute_one(runtime):
    return runtime._execute_operation(
        "BOOK",
        endpoint="https://sandbox.supplier.test",
        credential_reference="vault://supplier/auth",
        payload={"hotel": "H-1", "amount": "100.00"},
        idempotency_key="idem-1",
    )


def test_exact_raw_request_and_response_are_sealed_before_success_is_accepted():
    evidence = Evidence()
    transport = Transport()
    runtime = executor(transport=transport, evidence=evidence)
    result = execute_one(runtime)

    assert result.ok is True
    assert result.supplier_reference == "S-42"
    assert transport.calls[0][3] == b'{"amount":"100.00","hotel":"H-1"}'
    assert evidence.attempts[0]["request_body"] == transport.calls[0][3]
    assert evidence.attempts[0]["response_body"] == b'{"supplier_reference":"S-42"}'
    assert runtime.audits[0].request_hash == hashlib.sha256(transport.calls[0][3]).hexdigest()
    assert result.payload["evidence_reference"] == "evidence://raw/BOOK/1"


def test_evidence_failure_prevents_accepting_supplier_success():
    with pytest.raises(ValueError, match="SUPPLIER_RAW_EVIDENCE_PERSISTENCE_REQUIRED"):
        execute_one(executor(evidence=Evidence(fail=True)))


def test_each_retry_attempt_is_independently_sealed():
    evidence = Evidence()
    transport = Transport(
        [
            (429, {}, b'{"error":"slow_down"}'),
            (200, {}, b'{"supplier_reference":"S-43"}'),
        ]
    )
    result = execute_one(executor(transport=transport, evidence=evidence))
    assert result.ok is True
    assert result.payload["attempts"] == 2
    assert [item["response_status"] for item in evidence.attempts] == [429, 200]


def test_complex_auth_fails_closed_without_materializer():
    with pytest.raises(ValueError, match="SANDBOX_AUTH_MATERIALIZER_REQUIRED"):
        execute_one(executor(auth_method="HMAC"))


def test_complex_auth_uses_deployment_materializer_and_never_sends_reference_as_auth():
    transport = Transport()
    execute_one(executor(auth_method="HMAC", transport=transport, materializer=Materializer()))
    headers = transport.calls[0][2]
    assert headers["Authorization"] == "HMAC signed-request"
    assert "X-GO-Credential-Reference" not in headers
    assert "secret-key" not in json.dumps(headers)


def signed(timestamp: str, body: bytes) -> str:
    return hmac.new(b"webhook-key", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def test_webhook_signature_timestamp_and_atomic_replay_claim_are_all_required():
    replay = Replay()
    runtime = executor(replay=replay)
    body = b'{"event":"booking.updated"}'
    timestamp = str(int(NOW.timestamp()))
    signature = signed(timestamp, body)

    proof = runtime.verify_webhook(
        body=body,
        signature=signature,
        timestamp=timestamp,
        resolved_secret={"webhook_secret": "webhook-key"},
    )
    assert proof["signature_verified"] is True
    assert proof["replay_claimed"] is True

    with pytest.raises(ValueError, match="SUPPLIER_WEBHOOK_REPLAYED"):
        runtime.verify_webhook(
            body=body,
            signature=signature,
            timestamp=timestamp,
            resolved_secret={"webhook_secret": "webhook-key"},
        )


@pytest.mark.parametrize("offset", [-301, 301])
def test_webhook_rejects_stale_and_future_timestamps(offset):
    runtime = executor()
    body = b"{}"
    timestamp = str(int((NOW + timedelta(seconds=offset)).timestamp()))
    with pytest.raises(ValueError, match="SUPPLIER_WEBHOOK_TIMESTAMP_OUTSIDE_TOLERANCE"):
        runtime.verify_webhook(
            body=body,
            signature=signed(timestamp, body),
            timestamp=timestamp,
            resolved_secret={"webhook_secret": "webhook-key"},
        )


def test_signed_webhook_suite_result_does_not_claim_external_observation():
    runtime = executor()
    results = runtime.execute_suite(
        supplier_name="Signed Supplier Ltd",
        endpoint="https://sandbox.supplier.test",
        credential_reference="vault://supplier/auth",
        test_hotel_reference="H-1",
        mapping={"supplier_property_id": "P-1", "go_hotel_id": "G-1", "rooms": ["R-1"]},
        idempotency_key="suite-1",
    )
    webhook = next(item for item in results if item.operation == "SIGNED_WEBHOOK")
    assert webhook.ok is True
    assert webhook.payload == {"externally_observed": False, "status": "CONTRACT_READY_NOT_OBSERVED"}

