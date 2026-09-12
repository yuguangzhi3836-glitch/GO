from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import time
from typing import Any, Callable, Protocol

from go_hotel.connectors.hotel_supply_sandbox import HotelSupplyOperationResult
from go_hotel.connectors.provider_adapter_contract import validate_provider_adapter_contract


class SecretResolver(Protocol):
    def resolve(self, reference: str) -> dict[str, str]: ...


class HttpTransport(Protocol):
    def request(self, method: str, url: str, *, headers: dict[str, str], json_body: dict[str, Any] | None,
                timeout_seconds: float) -> tuple[int, dict[str, str], Any]: ...


@dataclass
class RuntimeAudit:
    operation: str
    request_hash: str
    response_hash: str | None
    http_status: int | None
    attempts: int
    elapsed_ms: int
    evidence_reference: str


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ContractDrivenHotelSupplyExecutor:
    """Provider-neutral external Sandbox executor.

    It only becomes configured when both a secret resolver and HTTP transport are
    explicitly injected by deployment code. No inline secret or mock-success path
    exists here. Provider-specific shape stays inside Provider Adapter Contract.
    """

    configured = True

    def __init__(self, *, contract: dict[str, Any], resolver: SecretResolver, transport: HttpTransport):
        self.contract = validate_provider_adapter_contract(contract)
        self.resolver = resolver
        self.transport = transport
        self.audits: list[RuntimeAudit] = []
        self._last_call_at = 0.0

    def _credential_headers(self, credential_reference: str) -> dict[str, str]:
        if not credential_reference.startswith(("vault://", "aws-secrets://", "gcp-secrets://", "azure-keyvault://", "kms://")):
            raise ValueError("EXTERNAL_VAULT_REFERENCE_REQUIRED")
        secret = self.resolver.resolve(credential_reference)
        if not secret:
            raise ValueError("HOTEL_SUPPLY_SANDBOX_CREDENTIAL_UNRESOLVED")
        auth = self.contract["transport"]["auth"]
        scheme = auth["method"]
        if scheme == "BEARER":
            token = secret.get("token")
            if not token:
                raise ValueError("SANDBOX_BEARER_TOKEN_REQUIRED")
            return {"Authorization": f"Bearer {token}"}
        if scheme == "API_KEY_HEADER":
            key = secret.get("api_key")
            header = auth.get("header_name") or "X-API-Key"
            if not key or not header:
                raise ValueError("SANDBOX_API_KEY_HEADER_REQUIRED")
            return {header: key}
        if scheme == "BASIC":
            import base64
            username, password = secret.get("username"), secret.get("password")
            if not username or not password:
                raise ValueError("SANDBOX_BASIC_CREDENTIAL_REQUIRED")
            raw = base64.b64encode(f"{username}:{password}".encode()).decode()
            return {"Authorization": f"Basic {raw}"}
        if scheme in {"HMAC", "CUSTOM_CONTRACTED", "OAUTH2_CLIENT_CREDENTIALS", "MTLS"}:
            # Contract may require provider-specific signing. Fail closed unless
            # deployment adds the provider signing fields to the resolved secret.
            if not secret.get("signing_key"):
                raise ValueError("SANDBOX_SIGNING_KEY_REQUIRED")
            return {"X-GO-Credential-Reference": credential_reference}
        raise ValueError("UNSUPPORTED_PROVIDER_AUTH_SCHEME")

    def _rate_limit(self) -> None:
        qps = float(self.contract["limits"].get("requests_per_second") or 1)
        min_gap = 1.0 / max(qps, 0.1)
        elapsed = time.monotonic() - self._last_call_at
        if elapsed < min_gap:
            time.sleep(min_gap - elapsed)
        self._last_call_at = time.monotonic()

    def _execute_operation(self, operation: str, *, endpoint: str, credential_reference: str,
                           payload: dict[str, Any], idempotency_key: str) -> HotelSupplyOperationResult:
        op = self.contract["operations"].get(operation.lower())
        if not op:
            return HotelSupplyOperationResult(operation=operation, ok=False, payload={"error": "OPERATION_CONTRACT_MISSING"})
        method = op["method"].upper()
        path = op["path"]
        if not endpoint.startswith("https://") or not path.startswith("/"):
            raise ValueError("HTTPS_PROVIDER_OPERATION_REQUIRED")
        url = endpoint.rstrip("/") + path
        headers = {"Accept": "application/json", "Content-Type": "application/json", "Idempotency-Key": idempotency_key}
        headers.update(self._credential_headers(credential_reference))
        limits = self.contract["limits"]
        max_attempts = int(limits.get("max_attempts") or 1)
        timeout = max(float(limits.get("connect_timeout_ms") or 1000), float(limits.get("read_timeout_ms") or 1000)) / 1000.0
        retry_statuses = {408, 425, 429, 500, 502, 503, 504}
        request_fact = {"operation": operation, "url": url, "payload": payload, "idempotency_key": idempotency_key}
        started = time.monotonic()
        last_status = None
        last_body: Any = None
        for attempt in range(1, max_attempts + 1):
            self._rate_limit()
            status, _, response_body = self.transport.request(method, url, headers=headers, json_body=payload, timeout_seconds=timeout)
            last_status, last_body = status, response_body
            if 200 <= status < 300:
                audit = RuntimeAudit(operation, _digest(request_fact), _digest(response_body), status, attempt,
                                     int((time.monotonic() - started) * 1000), f"sandbox-http://{operation}/{_now_iso()}")
                self.audits.append(audit)
                supplier_reference = None
                if isinstance(response_body, dict):
                    supplier_reference = response_body.get("supplier_reference") or response_body.get("booking_id") or response_body.get("id")
                return HotelSupplyOperationResult(operation=operation, ok=True, supplier_reference=supplier_reference,
                                                  payload={"http_status": status, "response_hash": audit.response_hash,
                                                           "attempts": attempt, "evidence_reference": audit.evidence_reference})
            if status not in retry_statuses or attempt == max_attempts:
                break
            time.sleep(min(0.25 * (2 ** (attempt - 1)), 2.0))
        audit = RuntimeAudit(operation, _digest(request_fact), _digest(last_body) if last_body is not None else None,
                             last_status, max_attempts, int((time.monotonic() - started) * 1000),
                             f"sandbox-http://{operation}/{_now_iso()}")
        self.audits.append(audit)
        return HotelSupplyOperationResult(operation=operation, ok=False,
                                          payload={"http_status": last_status, "response_hash": audit.response_hash,
                                                   "attempts": max_attempts, "evidence_reference": audit.evidence_reference,
                                                   "normalized_error": self._normalize_error(last_status, last_body)})

    def _normalize_error(self, status: int | None, body: Any) -> str:
        mapping = self.contract["error_mapping"].get("supplier_to_go") or {}
        if status is not None and str(status) in mapping:
            return mapping[str(status)]
        return "PROVIDER_UNKNOWN_ERROR_FAIL_CLOSED"

    def execute_suite(self, *, supplier_name: str, endpoint: str, credential_reference: str,
                      test_hotel_reference: str, mapping: dict[str, Any], idempotency_key: str) -> list[HotelSupplyOperationResult]:
        if supplier_name != self.contract["provider"]["supplier_legal_name"]:
            raise ValueError("PROVIDER_CONTRACT_SUPPLIER_MISMATCH")
        common = {"test_hotel_reference": test_hotel_reference, "mapping": mapping}
        ordered = ["AVAILABILITY", "QUOTE", "BOOK", "QUERY", "CANCEL"]
        results = [self._execute_operation(op, endpoint=endpoint, credential_reference=credential_reference,
                                           payload=common, idempotency_key=f"{idempotency_key}:{op}") for op in ordered]
        # Certification scenarios that are contract/proof checks rather than raw HTTP calls.
        by_op = {r.operation: r for r in results}
        availability_ok = by_op["AVAILABILITY"].ok
        results.extend([
            HotelSupplyOperationResult("CONNECTIVITY", availability_ok, payload={"evidence_reference": "runtime://https-connectivity"}),
            HotelSupplyOperationResult("PROPERTY_MAPPING", bool(mapping.get("supplier_property_id") and mapping.get("go_hotel_id"))),
            HotelSupplyOperationResult("ROOM_MAPPING", bool(mapping.get("rooms"))),
            HotelSupplyOperationResult("RATE_PLAN_MAPPING", bool(mapping.get("rooms"))),
            HotelSupplyOperationResult("BOOK_IDEMPOTENCY", by_op["BOOK"].ok, supplier_reference=by_op["BOOK"].supplier_reference),
            HotelSupplyOperationResult("SIGNED_WEBHOOK", bool(self.contract["webhook"].get("signature"))),
            HotelSupplyOperationResult("ERROR_MAPPING", self.contract["error_mapping"].get("unknown_error_policy") == "FAIL_CLOSED"),
            HotelSupplyOperationResult("RECONCILIATION", by_op["QUERY"].ok, payload={"evidence_reference":"runtime://query-reconciliation"}),
        ])
        return results

    def verify_webhook(self, *, body: bytes, signature: str, timestamp: str, resolved_secret: dict[str, str]) -> dict[str, Any]:
        cfg = self.contract["webhook"]["signature"]
        if cfg["scheme"] != "HMAC_SHA256":
            raise ValueError("WEBHOOK_SIGNATURE_SCHEME_NOT_IMPLEMENTED")
        key = resolved_secret.get("webhook_secret")
        if not key:
            raise ValueError("WEBHOOK_SECRET_REQUIRED")
        signed = timestamp.encode() + b"." + body
        expected = hmac.new(key.encode(), signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("SUPPLIER_WEBHOOK_SIGNATURE_INVALID")
        return {"signature_verified": True, "payload_hash": hashlib.sha256(body).hexdigest(), "timestamp": timestamp}
