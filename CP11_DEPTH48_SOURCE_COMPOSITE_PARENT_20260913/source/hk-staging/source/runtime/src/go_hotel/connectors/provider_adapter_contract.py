from __future__ import annotations

from dataclasses import dataclass
from typing import Any


REQUIRED_OPERATIONS = (
    "availability",
    "quote",
    "book",
    "query",
    "cancel",
)

REQUIRED_MAPPING_SECTIONS = (
    "property",
    "room",
    "rate_plan",
    "availability",
    "quote",
    "booking",
    "cancellation",
)

ALLOWED_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
ALLOWED_AUTH_METHODS = {
    "BEARER",
    "API_KEY_HEADER",
    "BASIC",
    "HMAC",
    "OAUTH2_CLIENT_CREDENTIALS",
    "MTLS",
    "CUSTOM_CONTRACTED",
}


class ProviderContractError(ValueError):
    pass


def _required(value: Any, code: str) -> Any:
    if value in (None, "", [], {}):
        raise ProviderContractError(code)
    return value


def _require_https(value: str, code: str) -> str:
    if not isinstance(value, str) or not value.startswith("https://"):
        raise ProviderContractError(code)
    return value


def _require_placeholder_free_secret_fields(payload: dict[str, Any]) -> None:
    forbidden = {
        "password", "secret", "token", "api_key", "private_key",
        "client_secret", "bearer_token", "webhook_secret",
    }
    stack: list[Any] = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                if key.lower() in forbidden and value not in (None, ""):
                    raise ProviderContractError("INLINE_SECRET_FORBIDDEN")
                stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)


def _validate_operation(name: str, operation: dict[str, Any]) -> None:
    if not isinstance(operation, dict):
        raise ProviderContractError(f"{name.upper()}_OPERATION_REQUIRED")
    method = str(_required(operation.get("method"), f"{name.upper()}_METHOD_REQUIRED")).upper()
    if method not in ALLOWED_HTTP_METHODS:
        raise ProviderContractError(f"{name.upper()}_METHOD_UNSUPPORTED")
    path = str(_required(operation.get("path"), f"{name.upper()}_PATH_REQUIRED"))
    if not path.startswith("/"):
        raise ProviderContractError(f"{name.upper()}_PATH_MUST_BE_RELATIVE")
    _required(operation.get("request_mapping"), f"{name.upper()}_REQUEST_MAPPING_REQUIRED")
    _required(operation.get("response_mapping"), f"{name.upper()}_RESPONSE_MAPPING_REQUIRED")


def validate_provider_adapter_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Validate a provider adapter contract without inventing supplier schemas.

    All supplier-specific paths, mappings, headers, webhook signing semantics and error
    codes must come from current signed supplier documentation. This validator only
    checks that the integration template is complete enough to be executed later.
    """
    if not isinstance(contract, dict):
        raise ProviderContractError("PROVIDER_ADAPTER_CONTRACT_REQUIRED")
    _require_placeholder_free_secret_fields(contract)

    provider = contract.get("provider") or {}
    _required(provider.get("provider_code"), "PROVIDER_CODE_REQUIRED")
    _required(provider.get("supplier_legal_name"), "SUPPLIER_LEGAL_NAME_REQUIRED")
    if provider.get("environment") != "SANDBOX":
        raise ProviderContractError("SANDBOX_ENVIRONMENT_REQUIRED")

    source = contract.get("contract_source") or {}
    if source.get("authority") != "SIGNED_SUPPLIER_DOCUMENTATION":
        raise ProviderContractError("SIGNED_SUPPLIER_DOCUMENTATION_REQUIRED")
    _required(source.get("documentation_reference"), "DOCUMENTATION_REFERENCE_REQUIRED")
    _required(source.get("documentation_version"), "DOCUMENTATION_VERSION_REQUIRED")
    _required(source.get("documentation_hash"), "DOCUMENTATION_HASH_REQUIRED")

    transport = contract.get("transport") or {}
    _require_https(str(_required(transport.get("base_url"), "SANDBOX_BASE_URL_REQUIRED")), "HTTPS_SANDBOX_BASE_URL_REQUIRED")
    auth = transport.get("auth") or {}
    method = str(_required(auth.get("method"), "AUTH_METHOD_REQUIRED")).upper()
    if method not in ALLOWED_AUTH_METHODS:
        raise ProviderContractError("AUTH_METHOD_UNSUPPORTED")
    secret_ref = str(_required(auth.get("credential_reference"), "CREDENTIAL_REFERENCE_REQUIRED"))
    if not secret_ref.startswith(("vault://", "aws-secrets://", "gcp-secrets://", "azure-keyvault://", "kms://")):
        raise ProviderContractError("EXTERNAL_VAULT_REFERENCE_REQUIRED")
    _required(transport.get("ip_allowlist_reference"), "IP_ALLOWLIST_REFERENCE_REQUIRED")

    operations = contract.get("operations") or {}
    for op in REQUIRED_OPERATIONS:
        _validate_operation(op, operations.get(op) or {})

    mapping = contract.get("canonical_mapping") or {}
    for section in REQUIRED_MAPPING_SECTIONS:
        _required(mapping.get(section), f"{section.upper()}_CANONICAL_MAPPING_REQUIRED")

    webhook = contract.get("webhook") or {}
    _required(webhook.get("callback_path"), "WEBHOOK_CALLBACK_PATH_REQUIRED")
    signing = webhook.get("signature") or {}
    _required(signing.get("scheme"), "WEBHOOK_SIGNATURE_SCHEME_REQUIRED")
    _required(signing.get("signature_header"), "WEBHOOK_SIGNATURE_HEADER_REQUIRED")
    _required(signing.get("secret_reference"), "WEBHOOK_SECRET_REFERENCE_REQUIRED")
    if not str(signing["secret_reference"]).startswith(("vault://", "aws-secrets://", "gcp-secrets://", "azure-keyvault://", "kms://")):
        raise ProviderContractError("WEBHOOK_SECRET_VAULT_REFERENCE_REQUIRED")
    _required(signing.get("timestamp_header"), "WEBHOOK_TIMESTAMP_HEADER_REQUIRED")
    tolerance = int(_required(signing.get("replay_tolerance_seconds"), "WEBHOOK_REPLAY_TOLERANCE_REQUIRED"))
    if tolerance <= 0 or tolerance > 900:
        raise ProviderContractError("WEBHOOK_REPLAY_TOLERANCE_INVALID")

    errors = contract.get("error_mapping") or {}
    _required(errors.get("supplier_to_go"), "ERROR_MAPPING_REQUIRED")
    _required(errors.get("unknown_error_policy"), "UNKNOWN_ERROR_POLICY_REQUIRED")
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
    for key in (
        "contract_reference", "sandbox_account_reference", "test_property_reference",
        "authorized_scope", "evidence_references", "prepared_by", "prepared_at",
    ):
        _required(attestation.get(key), f"ATTESTATION_{key.upper()}_REQUIRED")
    if attestation.get("external_transport_verified") is not False:
        raise ProviderContractError("EXTERNAL_TRANSPORT_MUST_START_UNVERIFIED")

    if contains_placeholders(contract):
        raise ProviderContractError("PROVIDER_CONTRACT_PLACEHOLDERS_REMAIN")

    normalized = dict(contract)
    normalized["schema"] = "go.hotel-supply-provider-adapter-contract.v1"
    normalized["external_transport_verified"] = False
    normalized["production_live"] = False
    normalized["payment_scope"] = "OUT_OF_SCOPE"
    return normalized


def contains_placeholders(value: Any) -> bool:
    if isinstance(value, dict):
        return any(contains_placeholders(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_placeholders(v) for v in value)
    return isinstance(value, str) and value.startswith("__") and value.endswith("__")


@dataclass(frozen=True)
class ProviderAdapterReadiness:
    provider_code: str
    supplier_legal_name: str
    contract_complete: bool
    external_transport_verified: bool
    production_live: bool
    payment_scope: str
