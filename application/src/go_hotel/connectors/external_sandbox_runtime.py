from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> tuple[int, dict[str, str], bytes]: ...


class ProviderAuthMaterializer(Protocol):
    def materialize(
        self,
        *,
        scheme: str,
        auth_contract: dict[str, Any],
        resolved_secret: dict[str, str],
        method: str,
        url: str,
        body: bytes,
        idempotency_key: str,
    ) -> dict[str, str]: ...


class RawEvidenceSink(Protocol):
    def seal_attempt(
        self,
        *,
        operation: str,
        attempt: int,
        method: str,
        url: str,
        request_body: bytes,
        response_status: int | None,
        response_headers: dict[str, str],
        response_body: bytes,
        transport_error: str | None,
    ) -> str: ...


class WebhookReplayStore(Protocol):
    def claim(self, replay_key: str, *, expires_at: datetime) -> bool: ...


@dataclass(frozen=True)
class RuntimeAudit:
    operation: str
    request_hash: str
    response_hash: str
    http_status: int | None
    attempt: int
    elapsed_ms: int
    evidence_reference: str


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _parse_timestamp(value: str) -> datetime:
    try:
        if value.lstrip("-").isdigit():
            parsed = datetime.fromtimestamp(int(value), tz=timezone.utc)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("SUPPLIER_WEBHOOK_TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None:
        raise ValueError("SUPPLIER_WEBHOOK_TIMESTAMP_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc)


class ContractDrivenHotelSupplyExecutor:
    """Provider-neutral runtime that fails closed until deployment controls exist."""

    configured = True
    _VAULT_PREFIXES = ("vault://", "aws-secrets://", "gcp-secrets://", "azure-keyvault://", "kms://")
    _COMPLEX_AUTH = {"HMAC", "CUSTOM_CONTRACTED", "OAUTH2_CLIENT_CREDENTIALS", "MTLS"}
    _RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}

    def __init__(
        self,
        *,
        contract: dict[str, Any],
        resolver: SecretResolver,
        transport: HttpTransport,
        evidence_sink: RawEvidenceSink,
        replay_store: WebhookReplayStore,
        auth_materializer: ProviderAuthMaterializer | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.contract = validate_provider_adapter_contract(contract)
        self.resolver = resolver
        self.transport = transport
        self.evidence_sink = evidence_sink
        self.replay_store = replay_store
        self.auth_materializer = auth_materializer
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.audits: list[RuntimeAudit] = []
        self._last_call_at = 0.0

    def _resolved_secret(self, credential_reference: str) -> dict[str, str]:
        if not credential_reference.startswith(self._VAULT_PREFIXES):
            raise ValueError("EXTERNAL_VAULT_REFERENCE_REQUIRED")
        secret = self.resolver.resolve(credential_reference)
        if not secret:
            raise ValueError("HOTEL_SUPPLY_SANDBOX_CREDENTIAL_UNRESOLVED")
        return secret

    def _credential_headers(
        self,
        credential_reference: str,
        *,
        method: str,
        url: str,
        body: bytes,
        idempotency_key: str,
    ) -> dict[str, str]:
        secret = self._resolved_secret(credential_reference)
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
            username, password = secret.get("username"), secret.get("password")
            if not username or not password:
                raise ValueError("SANDBOX_BASIC_CREDENTIAL_REQUIRED")
            raw = base64.b64encode(f"{username}:{password}".encode()).decode()
            return {"Authorization": f"Basic {raw}"}
        if scheme in self._COMPLEX_AUTH:
            if self.auth_materializer is None:
                raise ValueError("SANDBOX_AUTH_MATERIALIZER_REQUIRED")
            headers = self.auth_materializer.materialize(
                scheme=scheme,
                auth_contract=auth,
                resolved_secret=secret,
                method=method,
                url=url,
                body=body,
                idempotency_key=idempotency_key,
            )
            if not headers or not all(isinstance(k, str) and isinstance(v, str) and k and v for k, v in headers.items()):
                raise ValueError("SANDBOX_AUTH_MATERIALIZATION_FAILED")
            if set(headers) == {"X-GO-Credential-Reference"}:
                raise ValueError("SANDBOX_AUTH_MATERIALIZATION_FAILED")
            return headers
        raise ValueError("UNSUPPORTED_PROVIDER_AUTH_SCHEME")

    def _rate_limit(self) -> None:
        qps = float(self.contract["limits"].get("requests_per_second") or 1)
        min_gap = 1.0 / max(qps, 0.1)
        elapsed = time.monotonic() - self._last_call_at
        if elapsed < min_gap:
            time.sleep(min_gap - elapsed)
        self._last_call_at = time.monotonic()

    def _seal_attempt(
        self,
        *,
        operation: str,
        attempt: int,
        method: str,
        url: str,
        request_body: bytes,
        response_status: int | None,
        response_headers: dict[str, str],
        response_body: bytes,
        transport_error: str | None,
        started: float,
    ) -> RuntimeAudit:
        reference = self.evidence_sink.seal_attempt(
            operation=operation,
            attempt=attempt,
            method=method,
            url=url,
            request_body=request_body,
            response_status=response_status,
            response_headers=response_headers,
            response_body=response_body,
            transport_error=transport_error,
        )
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError("SUPPLIER_RAW_EVIDENCE_PERSISTENCE_REQUIRED")
        audit = RuntimeAudit(
            operation=operation,
            request_hash=_sha256_bytes(request_body),
            response_hash=_sha256_bytes(response_body),
            http_status=response_status,
            attempt=attempt,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            evidence_reference=reference,
        )
        self.audits.append(audit)
        return audit

    def _execute_operation(
        self,
        operation: str,
        *,
        endpoint: str,
        credential_reference: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> HotelSupplyOperationResult:
        op = self.contract["operations"].get(operation.lower())
        if not op:
            return HotelSupplyOperationResult(operation=operation, ok=False, payload={"error": "OPERATION_CONTRACT_MISSING"})
        method = op["method"].upper()
        path = op["path"]
        if not endpoint.startswith("https://") or not path.startswith("/"):
            raise ValueError("HTTPS_PROVIDER_OPERATION_REQUIRED")
        url = endpoint.rstrip("/") + path
        request_body = _canonical_json(payload)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        }
        headers.update(
            self._credential_headers(
                credential_reference,
                method=method,
                url=url,
                body=request_body,
                idempotency_key=idempotency_key,
            )
        )
        limits = self.contract["limits"]
        max_attempts = int(limits.get("max_attempts") or 1)
        timeout = max(
            float(limits.get("connect_timeout_ms") or 1000),
            float(limits.get("read_timeout_ms") or 1000),
        ) / 1000.0
        started = time.monotonic()
        last_status: int | None = None
        last_body = b""
        last_audit: RuntimeAudit | None = None
        for attempt in range(1, max_attempts + 1):
            self._rate_limit()
            try:
                status, response_headers, response_body = self.transport.request(
                    method,
                    url,
                    headers=headers,
                    body=request_body,
                    timeout_seconds=timeout,
                )
            except Exception as exc:
                last_status, last_body = None, b""
                last_audit = self._seal_attempt(
                    operation=operation,
                    attempt=attempt,
                    method=method,
                    url=url,
                    request_body=request_body,
                    response_status=None,
                    response_headers={},
                    response_body=b"",
                    transport_error=type(exc).__name__,
                    started=started,
                )
                # The transport may have sent a mutating request before losing
                # the response. Without provider-attested idempotency semantics,
                # retrying could duplicate the side effect.
                break
            if not isinstance(response_body, bytes):
                raise TypeError("SUPPLIER_TRANSPORT_RAW_BYTES_REQUIRED")
            last_status, last_body = status, response_body
            last_audit = self._seal_attempt(
                operation=operation,
                attempt=attempt,
                method=method,
                url=url,
                request_body=request_body,
                response_status=status,
                response_headers=response_headers,
                response_body=response_body,
                transport_error=None,
                started=started,
            )
            parsed: Any
            try:
                parsed = json.loads(response_body.decode("utf-8")) if response_body else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                parsed = None
            if 200 <= status < 300:
                if parsed is None and response_body:
                    raise ValueError("SUPPLIER_RESPONSE_JSON_INVALID")
                supplier_reference = None
                if isinstance(parsed, dict):
                    supplier_reference = parsed.get("supplier_reference") or parsed.get("booking_id") or parsed.get("id")
                return HotelSupplyOperationResult(
                    operation=operation,
                    ok=True,
                    supplier_reference=supplier_reference,
                    payload={
                        "http_status": status,
                        "response_hash": last_audit.response_hash,
                        "attempts": attempt,
                        "evidence_reference": last_audit.evidence_reference,
                    },
                )
            if status not in self._RETRY_STATUSES or attempt == max_attempts:
                break
            time.sleep(min(0.25 * (2 ** (attempt - 1)), 2.0))
        assert last_audit is not None
        try:
            error_body = json.loads(last_body.decode("utf-8")) if last_body else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            error_body = None
        return HotelSupplyOperationResult(
            operation=operation,
            ok=False,
            payload={
                "http_status": last_status,
                "response_hash": last_audit.response_hash,
                "attempts": last_audit.attempt,
                "evidence_reference": last_audit.evidence_reference,
                "normalized_error": self._normalize_error(last_status, error_body),
            },
        )

    def _normalize_error(self, status: int | None, body: Any) -> str:
        mapping = self.contract["error_mapping"].get("supplier_to_go") or {}
        if status is not None and str(status) in mapping:
            return mapping[str(status)]
        return "PROVIDER_UNKNOWN_ERROR_FAIL_CLOSED"

    def execute_suite(
        self,
        *,
        supplier_name: str,
        endpoint: str,
        credential_reference: str,
        test_hotel_reference: str,
        mapping: dict[str, Any],
        idempotency_key: str,
    ) -> list[HotelSupplyOperationResult]:
        if supplier_name != self.contract["provider"]["supplier_legal_name"]:
            raise ValueError("PROVIDER_CONTRACT_SUPPLIER_MISMATCH")
        common = {"test_hotel_reference": test_hotel_reference, "mapping": mapping}
        ordered = ["AVAILABILITY", "QUOTE", "BOOK", "QUERY", "CANCEL"]
        results = [
            self._execute_operation(
                op,
                endpoint=endpoint,
                credential_reference=credential_reference,
                payload=common,
                idempotency_key=f"{idempotency_key}:{op}",
            )
            for op in ordered
        ]
        by_op = {r.operation: r for r in results}
        availability_ok = by_op["AVAILABILITY"].ok
        results.extend(
            [
                HotelSupplyOperationResult("CONNECTIVITY", availability_ok, payload={"evidence_reference": "runtime://https-connectivity"}),
                HotelSupplyOperationResult("PROPERTY_MAPPING", bool(mapping.get("supplier_property_id") and mapping.get("go_hotel_id"))),
                HotelSupplyOperationResult("ROOM_MAPPING", bool(mapping.get("rooms"))),
                HotelSupplyOperationResult("RATE_PLAN_MAPPING", bool(mapping.get("rooms"))),
                HotelSupplyOperationResult("BOOK_IDEMPOTENCY", by_op["BOOK"].ok, supplier_reference=by_op["BOOK"].supplier_reference),
                HotelSupplyOperationResult(
                    "SIGNED_WEBHOOK",
                    bool(self.contract["webhook"].get("signature")),
                    payload={"externally_observed": False, "status": "CONTRACT_READY_NOT_OBSERVED"},
                ),
                HotelSupplyOperationResult("ERROR_MAPPING", self.contract["error_mapping"].get("unknown_error_policy") == "FAIL_CLOSED"),
                HotelSupplyOperationResult("RECONCILIATION", by_op["QUERY"].ok, payload={"evidence_reference": "runtime://query-reconciliation"}),
            ]
        )
        return results

    def verify_webhook(
        self,
        *,
        body: bytes,
        signature: str,
        timestamp: str,
        resolved_secret: dict[str, str],
    ) -> dict[str, Any]:
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
        observed_at = _parse_timestamp(timestamp)
        now = self.clock().astimezone(timezone.utc)
        tolerance = int(cfg.get("replay_tolerance_seconds") or 0)
        if tolerance <= 0:
            raise ValueError("WEBHOOK_REPLAY_TOLERANCE_REQUIRED")
        # A half-open validity window aligns verifier acceptance with stores
        # that delete a claim at expires_at.
        if abs((now - observed_at).total_seconds()) >= tolerance:
            raise ValueError("SUPPLIER_WEBHOOK_TIMESTAMP_OUTSIDE_TOLERANCE")
        replay_key = _sha256_bytes(signed + b"." + signature.encode())
        # Keep the atomic claim for the full remaining validity window, including
        # callbacks whose signed timestamp is slightly in the future.
        if not self.replay_store.claim(replay_key, expires_at=observed_at + timedelta(seconds=tolerance)):
            raise ValueError("SUPPLIER_WEBHOOK_REPLAYED")
        return {
            "signature_verified": True,
            "replay_claimed": True,
            "payload_hash": _sha256_bytes(body),
            "timestamp": timestamp,
            "replay_key": replay_key,
        }
