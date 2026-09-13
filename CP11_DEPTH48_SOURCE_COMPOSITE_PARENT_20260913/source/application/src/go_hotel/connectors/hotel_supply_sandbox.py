from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class HotelSupplyOperationResult:
    operation: str
    ok: bool
    supplier_reference: str | None = None
    payload: dict[str, Any] | None = None


class HotelSupplySandboxExecutor:
    """Fail-closed runtime boundary with deployment-only executor injection."""

    def __init__(self) -> None:
        self._delegate: Any | None = None

    @property
    def configured(self) -> bool:
        return self._delegate is not None and bool(getattr(self._delegate, "configured", False))

    def install(self, delegate: Any) -> None:
        if delegate is None or not bool(getattr(delegate, "configured", False)):
            raise ValueError("CONFIGURED_HOTEL_SUPPLY_EXECUTOR_REQUIRED")
        self._delegate = delegate

    def clear(self) -> None:
        self._delegate = None

    def execute_suite(self, *, supplier_name: str, endpoint: str, credential_reference: str,
                      test_hotel_reference: str, mapping: dict[str, Any],
                      idempotency_key: str) -> list[HotelSupplyOperationResult]:
        if not self.configured:
            raise ValueError("HOTEL_SUPPLY_SANDBOX_EXECUTOR_NOT_CONFIGURED")
        return self._delegate.execute_suite(
            supplier_name=supplier_name,
            endpoint=endpoint,
            credential_reference=credential_reference,
            test_hotel_reference=test_hotel_reference,
            mapping=mapping,
            idempotency_key=idempotency_key,
        )


hotel_supply_sandbox_executor = HotelSupplySandboxExecutor()


def result_dict(result: HotelSupplyOperationResult) -> dict[str, Any]:
    return asdict(result)
