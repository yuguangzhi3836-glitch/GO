from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from go_hotel.connectors.provider_adapter_contract import validate_provider_adapter_contract


@dataclass(frozen=True)
class PreparedProviderRequest:
    operation: str
    method: str
    url: str
    headers_template: dict[str, str]
    request_mapping: dict[str, Any]
    response_mapping: dict[str, Any]


class NamedProviderAdapterTemplate:
    """Contract-driven adapter template for a named hotel supplier.

    This class deliberately does not infer any Tongcheng, Agoda or other provider schema.
    Once the signed sandbox documentation is received, the provider template is completed,
    validated and can then be implemented/executed by deployment-controlled transport.
    """

    def __init__(self, contract: dict[str, Any]):
        self.contract = validate_provider_adapter_contract(contract)

    @property
    def provider_code(self) -> str:
        return self.contract["provider"]["provider_code"]

    def prepare(self, operation: str) -> PreparedProviderRequest:
        op = (self.contract.get("operations") or {}).get(operation)
        if not op:
            raise ValueError("PROVIDER_OPERATION_NOT_CONFIGURED")
        base = self.contract["transport"]["base_url"].rstrip("/")
        path = op["path"]
        return PreparedProviderRequest(
            operation=operation,
            method=op["method"].upper(),
            url=base + path,
            headers_template=dict(op.get("headers_template") or {}),
            request_mapping=dict(op["request_mapping"]),
            response_mapping=dict(op["response_mapping"]),
        )

    def webhook_contract(self) -> dict[str, Any]:
        return dict(self.contract["webhook"])

    def error_contract(self) -> dict[str, Any]:
        return dict(self.contract["error_mapping"])

    def limit_contract(self) -> dict[str, Any]:
        return dict(self.contract["limits"])

    def attestation_contract(self) -> dict[str, Any]:
        return dict(self.contract["attestation"])
