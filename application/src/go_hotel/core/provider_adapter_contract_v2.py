from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from go_hotel.connectors.provider_adapter_contract import (
    ProviderContractError,
    contains_placeholders,
)

ALLOWED_VERTICALS = {"HOTEL", "FLIGHT", "RAIL", "RENTAL", "RIDE", "ATTRACTION"}
ALLOWED_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
ALLOWED_AUTH_METHODS = {
    "BEARER", "API_KEY_HEADER", "BASIC", "HMAC",
    "OAUTH2_CLIENT_CREDENTIALS", "MTLS", "CUSTOM_CONTRACTED",
}
VAULT_PREFIXES = ("vault://", "aws-secrets://", "gcp-secrets://", "azure-keyvault://", "kms://")

VERTICAL_PROFILES: dict[str, dict[str, tuple[str, ...]]] = {
    "HOTEL": {
        "operations": ("search", "quote", "book", "query", "cancel"),
        "canonical": ("property", "room", "rate_plan", "availability", "price", "booking", "cancellation"),
    },
    "FLIGHT": {
        "operations": ("search", "prebook", "book", "query", "change", "cancel", "refund"),
        "canonical": ("offer", "segment", "fare", "baggage", "order", "ticket", "change", "refund"),
    },
    "RAIL": {
        "operations": ("search", "prebook", "book", "query", "change", "cancel", "refund"),
        "canonical": ("service", "segment", "fare", "inventory", "order", "change", "refund"),
    },
    "RENTAL": {
        "operations": ("search", "quote", "book", "query", "modify", "cancel", "refund"),
        "canonical": ("vehicle", "rate", "insurance", "deposit", "pickup_return", "order", "refund"),
    },
    "RIDE": {
        "operations": ("search", "quote", "book", "query", "modify", "cancel", "refund"),
        "canonical": ("vehicle", "route", "driver_fleet", "price", "order", "fulfillment", "refund"),
    },
    "ATTRACTION": {
        "operations": ("search", "prebook", "book", "query", "change", "cancel", "refund", "redeem"),
        "canonical": ("product", "session", "availability", "price", "voucher", "order", "refund", "redemption"),
    },
}


def _required(value: Any, code: str) -> Any:
    if value in (None, "", [], {}):
        raise ProviderContractError(code)
    return value


def _no_inline_secrets(payload: Any) -> None:
    forbidden = {"password", "secret", "token", "api_key", "private_key", "client_secret", "bearer_token", "webhook_secret"}
    stack = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                if key.lower() in forbidden and value not in (None, ""):
                    raise ProviderContractError("INLINE_SECRET_FORBIDDEN")
                stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)


def validate_provider_adapter_contract_v2(contract: dict[str, Any]) -> dict[str, Any]:
    """Validate a vertical-neutral provider adapter readiness contract.

    This validator proves schema/readiness only. It never invents supplier endpoints,
    credentials, field mappings, webhook semantics, or LIVE status. All provider-specific
    values must originate from signed/current supplier documentation and remain sandbox-only
    until separate external transport certification exists.
    """
    if not isinstance(contract, dict):
        raise ProviderContractError("PROVIDER_ADAPTER_CONTRACT_REQUIRED")
    _no_inline_secrets(contract)

    vertical = str(_required(contract.get("vertical"), "VERTICAL_REQUIRED")).upper()
    if vertical not in ALLOWED_VERTICALS:
        raise ProviderContractError("VERTICAL_UNSUPPORTED")
    profile = VERTICAL_PROFILES[vertical]

    provider = contract.get("provider") or {}
    _required(provider.get("provider_code"), "PROVIDER_CODE_REQUIRED")
    _required(provider.get("supplier_legal_name"), "SUPPLIER_LEGAL_NAME_REQUIRED")
    if provider.get("environment") != "SANDBOX":
        raise ProviderContractError("SANDBOX_ENVIRONMENT_REQUIRED")

    source = contract.get("contract_source") or {}
    if source.get("authority") != "SIGNED_SUPPLIER_DOCUMENTATION":
        raise ProviderContractError("SIGNED_SUPPLIER_DOCUMENTATION_REQUIRED")
    for key in ("documentation_reference", "documentation_version", "documentation_hash"):
        _required(source.get(key), f"{key.upper()}_REQUIRED")

    transport = contract.get("transport") or {}
    base_url = str(_required(transport.get("base_url"), "SANDBOX_BASE_URL_REQUIRED"))
    if not base_url.startswith("https://"):
        raise ProviderContractError("HTTPS_SANDBOX_BASE_URL_REQUIRED")
    auth = transport.get("auth") or {}
    method = str(_required(auth.get("method"), "AUTH_METHOD_REQUIRED")).upper()
    if method not in ALLOWED_AUTH_METHODS:
        raise ProviderContractError("AUTH_METHOD_UNSUPPORTED")
    cred = str(_required(auth.get("credential_reference"), "CREDENTIAL_REFERENCE_REQUIRED"))
    if not cred.startswith(VAULT_PREFIXES):
        raise ProviderContractError("EXTERNAL_VAULT_REFERENCE_REQUIRED")

    operations = contract.get("operations") or {}
    for name in profile["operations"]:
        op = operations.get(name) or {}
        method = str(_required(op.get("method"), f"{name.upper()}_METHOD_REQUIRED")).upper()
        if method not in ALLOWED_HTTP_METHODS:
            raise ProviderContractError(f"{name.upper()}_METHOD_UNSUPPORTED")
        path = str(_required(op.get("path"), f"{name.upper()}_PATH_REQUIRED"))
        if not path.startswith("/"):
            raise ProviderContractError(f"{name.upper()}_PATH_MUST_BE_RELATIVE")
        _required(op.get("request_mapping"), f"{name.upper()}_REQUEST_MAPPING_REQUIRED")
        _required(op.get("response_mapping"), f"{name.upper()}_RESPONSE_MAPPING_REQUIRED")

    canonical = contract.get("canonical_mapping") or {}
    for section in profile["canonical"]:
        _required(canonical.get(section), f"{section.upper()}_CANONICAL_MAPPING_REQUIRED")

    webhook = contract.get("webhook") or {}
    _required(webhook.get("callback_path"), "WEBHOOK_CALLBACK_PATH_REQUIRED")
    signature = webhook.get("signature") or {}
    for key in ("scheme", "signature_header", "timestamp_header", "secret_reference", "replay_tolerance_seconds"):
        _required(signature.get(key), f"WEBHOOK_{key.upper()}_REQUIRED")
    if not str(signature["secret_reference"]).startswith(VAULT_PREFIXES):
        raise ProviderContractError("WEBHOOK_SECRET_VAULT_REFERENCE_REQUIRED")
    tolerance = int(signature["replay_tolerance_seconds"])
    if tolerance <= 0 or tolerance > 900:
        raise ProviderContractError("WEBHOOK_REPLAY_TOLERANCE_INVALID")

    errors = contract.get("error_mapping") or {}
    _required(errors.get("supplier_to_go"), "ERROR_MAPPING_REQUIRED")
    if errors.get("unknown_error_policy") != "FAIL_CLOSED":
        raise ProviderContractError("UNKNOWN_ERROR_MUST_FAIL_CLOSED")

    limits = contract.get("limits") or {}
    for key in ("requests_per_second", "max_concurrency", "connect_timeout_ms", "read_timeout_ms", "max_attempts"):
        value = int(_required(limits.get(key), f"{key.upper()}_REQUIRED"))
        if value <= 0:
            raise ProviderContractError(f"{key.upper()}_INVALID")
    if int(limits["max_attempts"]) > 5:
        raise ProviderContractError("MAX_ATTEMPTS_TOO_HIGH")
    _required(limits.get("retryable_go_errors"), "RETRYABLE_GO_ERRORS_REQUIRED")

    attestation = contract.get("attestation") or {}
    for key in ("contract_reference", "sandbox_account_reference", "test_entity_reference", "authorized_scope", "evidence_references", "prepared_by", "prepared_at"):
        _required(attestation.get(key), f"ATTESTATION_{key.upper()}_REQUIRED")
    if attestation.get("external_transport_verified") is not False:
        raise ProviderContractError("EXTERNAL_TRANSPORT_MUST_START_UNVERIFIED")

    if contains_placeholders(contract):
        raise ProviderContractError("PROVIDER_CONTRACT_PLACEHOLDERS_REMAIN")

    normalized = dict(contract)
    normalized["schema"] = "go.provider-adapter-contract.v2"
    normalized["vertical"] = vertical
    normalized["external_transport_verified"] = False
    normalized["production_live"] = False
    normalized["credential_state"] = "REFERENCE_ONLY_NO_INLINE_SECRET"
    normalized["readiness_state"] = "PROVIDER_CONTRACT_READY_NOT_EXTERNALLY_VERIFIED"
    return normalized


@dataclass(frozen=True)
class ProviderAdapterProfileV2:
    vertical: str
    required_operations: tuple[str, ...]
    canonical_sections: tuple[str, ...]
