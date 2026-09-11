from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol

@dataclass(frozen=True)
class RecoveryAdapterCapabilities:
    revalidate: bool = True
    mutate: bool = True
    poll: bool = True
    webhooks: bool = True
    supplier_idempotency: bool = True
    query_by_idempotency_key: bool = True

@dataclass(frozen=True)
class RecoveryAdapterMetadata:
    adapter_key: str
    vertical: str
    version: str = '1.0'
    capabilities: RecoveryAdapterCapabilities = field(default_factory=RecoveryAdapterCapabilities)

@dataclass(frozen=True)
class RecoveryRevalidation:
    status: str
    delta_minor: int
    currency: str
    quote_id: str
    rule_version: str
    evidence: dict[str,Any]=field(default_factory=dict)

@dataclass(frozen=True)
class RecoveryMutationResult:
    status: str  # CONFIRMED | ACCEPTED | UNKNOWN | FAILED
    external_operation_id: str | None = None
    supplier_confirmation_id: str | None = None
    evidence: dict[str,Any]=field(default_factory=dict)

@dataclass(frozen=True)
class RecoveryObservation:
    status: str  # CONFIRMED | NOT_APPLIED | PENDING | FAILED | UNKNOWN
    supplier_confirmation_id: str | None = None
    external_event_id: str | None = None
    evidence: dict[str,Any]=field(default_factory=dict)

class RecoverySupplierAdapter(Protocol):
    metadata: RecoveryAdapterMetadata
    def revalidate(self, *, order_id:str, quote_id:str, rule_version:str, expected_delta_minor:int, currency:str, facts:dict[str,Any]) -> RecoveryRevalidation: ...
    def mutate(self, *, order_id:str, command_type:str, idempotency_key:str, quote_id:str, rule_version:str, authorized_delta_minor:int, currency:str, facts:dict[str,Any]) -> RecoveryMutationResult: ...
    def poll(self, *, external_operation_id:str|None, idempotency_key:str, order_id:str, facts:dict[str,Any]) -> RecoveryObservation: ...
    def parse_webhook(self, payload:dict[str,Any]) -> RecoveryObservation: ...
