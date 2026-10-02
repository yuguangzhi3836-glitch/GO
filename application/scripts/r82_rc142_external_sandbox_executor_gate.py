#!/usr/bin/env python3
from pathlib import Path
import json
import sys
import tempfile
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from go_hotel.connectors.hotel_supply_sandbox import hotel_supply_sandbox_executor
from go_hotel.connectors.external_sandbox_runtime import ContractDrivenHotelSupplyExecutor
from go_hotel.connectors.supplier_runtime_controls import metadata, SQLMutationJournal


class Resolver:
    def resolve(self, ref):
        return {"token": "sandbox-token", "webhook_secret": "hook"}


class Transport:
    def __init__(self):
        self.calls = []

    def request(self, method, url, *, headers, body, timeout_seconds):
        self.calls.append((method, url, headers.get("Idempotency-Key"), body))
        response = {"status": "ok", "supplier_reference": "ref-" + url.rsplit("/", 1)[-1]}
        return 200, {"Content-Type": "application/json"}, json.dumps(response, separators=(",", ":")).encode()


class Evidence:
    def __init__(self):
        self.attempts = []

    def seal_attempt(self, **attempt):
        self.attempts.append(attempt)
        return f"evidence://raw/{attempt['operation']}/{attempt['attempt']}"


class Replay:
    def __init__(self):
        self.claims = set()

    def claim(self, replay_key, *, expires_at):
        if replay_key in self.claims:
            return False
        self.claims.add(replay_key)
        return True


def op(path):
    return {"method": "POST", "path": path, "request_mapping": {"x": "x"}, "response_mapping": {"x": "x"}, "response_validation": {"required_fields": {"status": "string", "supplier_reference": "string"}, "success_equals": {"status": "ok"}, "reference_field": "supplier_reference"}}


contract = {
    "provider": {"provider_code": "TEST", "supplier_legal_name": "Test Supplier", "environment": "SANDBOX"},
    "contract_source": {
        "authority": "SIGNED_SUPPLIER_DOCUMENTATION",
        "documentation_reference": "contract://test",
        "documentation_version": "1",
        "documentation_hash": "a" * 64,
    },
    "transport": {
        "base_url": "https://sandbox.example.com",
        "auth": {"method": "BEARER", "credential_reference": "vault://test"},
        "ip_allowlist_reference": "allow://test",
    },
    "operations": {key: op("/" + key) for key in ("availability", "quote", "book", "query", "cancel")},
    "canonical_mapping": {
        key: {"field": "field"}
        for key in ("property", "room", "rate_plan", "availability", "quote", "booking", "cancellation")
    },
    "webhook": {
        "callback_path": "/hook",
        "event_mapping": {"x": "x"},
        "signature": {
            "scheme": "HMAC_SHA256",
            "signature_header": "X-Sig",
            "timestamp_header": "X-Time",
            "replay_tolerance_seconds": 300,
            "secret_reference": "vault://hook",
        },
    },
    "error_mapping": {"supplier_to_go": {"429": "SUPPLIER_RATE_LIMITED"}, "unknown_error_policy": "FAIL_CLOSED"},
    "limits": {
        "requests_per_second": 1000,
        "max_concurrency": 2,
        "connect_timeout_ms": 1000,
        "read_timeout_ms": 1000,
        "max_attempts": 2,
        "retryable_go_errors": ["SUPPLIER_RATE_LIMITED"],
    },
    "attestation": {
        "contract_reference": "contract://test",
        "sandbox_account_reference": "acct://test",
        "test_property_reference": "hotel://test",
        "authorized_scope": ["HOTEL"],
        "evidence_references": ["evidence://test"],
        "prepared_by": "gate",
        "prepared_at": "2026-08-24T00:00:00+00:00",
        "external_transport_verified": False,
    },
}
checks = {}
try:
    hotel_supply_sandbox_executor.execute_suite(
        supplier_name="x",
        endpoint="https://x",
        credential_reference="vault://x",
        test_hotel_reference="x",
        mapping={},
        idempotency_key="x",
    )
    checks["default_fail_closed"] = False
except ValueError as exc:
    checks["default_fail_closed"] = str(exc) == "HOTEL_SUPPLY_SANDBOX_EXECUTOR_NOT_CONFIGURED"

transport = Transport()
evidence = Evidence()
temp = tempfile.TemporaryDirectory()
engine = create_engine("sqlite:///" + str(Path(temp.name) / "controls.db"))
metadata.create_all(engine)
executor = ContractDrivenHotelSupplyExecutor(
    contract=contract,
    resolver=Resolver(),
    transport=transport,
    evidence_sink=evidence,
    replay_store=Replay(),
    mutation_journal=SQLMutationJournal(engine, scope="gate/test"),
)
hotel_supply_sandbox_executor.install(executor)
results = hotel_supply_sandbox_executor.execute_suite(
    supplier_name="Test Supplier",
    endpoint="https://sandbox.example.com",
    credential_reference="vault://test",
    test_hotel_reference="hotel://test",
    mapping={"supplier_property_id": "p", "go_hotel_id": "g", "rooms": [{"x": 1}]},
    idempotency_key="idem",
)
by_operation = {item.operation: item.ok for item in results}
checks.update(
    {
        "executor_injection_controlled": hotel_supply_sandbox_executor.configured,
        "availability_quote_book_query_cancel": all(
            by_operation.get(name) for name in ("AVAILABILITY", "QUOTE", "BOOK", "QUERY", "CANCEL")
        ),
        "supplier_idempotency_not_fabricated": by_operation.get("BOOK_IDEMPOTENCY") is False,
        "external_webhook_not_fabricated": by_operation.get("SIGNED_WEBHOOK") is False,
        "error_mapping_fail_closed": by_operation.get("ERROR_MAPPING") is True,
        "reconciliation_not_fabricated": by_operation.get("RECONCILIATION") is False,
        "raw_attempt_evidence": len(executor.audits) == 5
        and len(evidence.attempts) == 5
        and all(item.evidence_reference.startswith("evidence://raw/") for item in executor.audits),
    }
)
hotel_supply_sandbox_executor.clear()
engine.dispose()
temp.cleanup()
for key, value in checks.items():
    print(f'{key}={"PASS" if value else "FAIL"}')
if not all(checks.values()):
    raise SystemExit(1)
print("R8.2_RC14_2_EXTERNAL_SANDBOX_EXECUTOR_GATE: PASS")
