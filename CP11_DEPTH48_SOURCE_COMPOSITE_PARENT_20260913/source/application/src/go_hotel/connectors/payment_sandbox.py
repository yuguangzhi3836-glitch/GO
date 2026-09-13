from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PaymentLinkResult:
    external_operation_id: str
    payment_url: str
    expires_at: str
    evidence_reference: str


class PaymentSandboxExecutor:
    """Command Center-owned PSP sandbox boundary. Default is fail-closed.

    Hong Kong may configure an approved artifact; it may not implement a delegate.
    """
    def __init__(self) -> None:
        self._delegate: Any | None = None

    @property
    def configured(self) -> bool:
        return self._delegate is not None and bool(getattr(self._delegate, "configured", False))

    def install(self, delegate: Any) -> None:
        if delegate is None or not bool(getattr(delegate, "configured", False)):
            raise ValueError("CONFIGURED_PAYMENT_SANDBOX_EXECUTOR_REQUIRED")
        self._delegate = delegate

    def clear(self) -> None:
        self._delegate = None

    def create_payment_link(self, **kwargs) -> PaymentLinkResult:
        if not self.configured:
            raise ValueError("EXTERNAL_PAYMENT_SANDBOX_EXECUTOR_NOT_CONFIGURED")
        return self._delegate.create_payment_link(**kwargs)

    def certification_probe(self, **kwargs) -> dict[str, Any]:
        """Run approved PSP sandbox certification probes.

        A real provider implementation must be developed and reviewed in Command
        Center against the selected official contract. Configuration alone and
        the isolated money simulator cannot certify a PSP integration. An approved
        delegate must explicitly implement this contract.
        """
        if not self.configured:
            raise ValueError("EXTERNAL_PAYMENT_SANDBOX_EXECUTOR_NOT_CONFIGURED")
        probe = getattr(self._delegate, "certification_probe", None)
        if probe is None:
            raise ValueError("PAYMENT_SANDBOX_CERTIFICATION_PROBE_NOT_IMPLEMENTED")
        result = probe(**kwargs)
        if not isinstance(result, dict):
            raise ValueError("INVALID_PAYMENT_SANDBOX_CERTIFICATION_RESULT")
        return result


payment_sandbox_executor = PaymentSandboxExecutor()
