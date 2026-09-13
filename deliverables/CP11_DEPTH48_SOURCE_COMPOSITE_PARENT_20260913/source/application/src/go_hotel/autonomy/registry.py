from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Dict, Iterable, Mapping, Tuple

from .types import (
    CellDefinition,
    CollaborationMode,
    ContractDefinition,
    EventDefinition,
    Environment,
    ProductionReality,
    QualificationKey,
    QualificationRecord,
    RiskClass,
)


INDEPENDENT_QA_CELL_ID = "C13"


class GovernanceViolation(RuntimeError):
    pass


class DomainOwnershipRegistry:
    def __init__(self, cells: Iterable[CellDefinition]):
        self._cells: Dict[str, CellDefinition] = {}
        self._domain_owner: Dict[str, str] = {}
        for cell in cells:
            if cell.cell_id in self._cells:
                raise GovernanceViolation(f"DUPLICATE_CELL_ID:{cell.cell_id}")
            if cell.domain in self._domain_owner:
                raise GovernanceViolation(f"MULTIPLE_FINAL_OWNERS:{cell.domain}")
            self._cells[cell.cell_id] = cell
            self._domain_owner[cell.domain] = cell.cell_id

    @property
    def cells(self) -> Mapping[str, CellDefinition]:
        return dict(self._cells)

    def cell(self, cell_id: str) -> CellDefinition:
        try:
            return self._cells[cell_id]
        except KeyError as exc:
            raise GovernanceViolation(f"UNKNOWN_CELL:{cell_id}") from exc

    def owner_for(self, domain: str) -> CellDefinition:
        try:
            return self.cell(self._domain_owner[domain])
        except KeyError as exc:
            raise GovernanceViolation(f"UNKNOWN_DOMAIN:{domain}") from exc

    def assert_truth_write(self, *, actor_cell: str, target_domain: str) -> None:
        owner = self.owner_for(target_domain)
        if owner.cell_id != actor_cell:
            raise GovernanceViolation(
                f"CROSS_DOMAIN_TRUTH_MUTATION_DENIED:{actor_cell}->{target_domain};owner={owner.cell_id}"
            )

    def assert_collaboration(
        self,
        *,
        actor_cell: str,
        target_domain: str,
        mode: CollaborationMode,
    ) -> None:
        self.cell(actor_cell)
        self.owner_for(target_domain)
        if mode not in (CollaborationMode.CONTRACT, CollaborationMode.EVENT):
            raise GovernanceViolation("CROSS_DOMAIN_REQUIRES_CONTRACT_OR_EVENT")

    def production_accountability_gaps(self) -> Tuple[str, ...]:
        return tuple(
            sorted(cell.cell_id for cell in self._cells.values() if not cell.accountability_bound)
        )


class ContractEventRegistry:
    def __init__(
        self,
        *,
        cells: DomainOwnershipRegistry,
        contracts: Iterable[ContractDefinition] = (),
        events: Iterable[EventDefinition] = (),
    ):
        self._cells = cells
        self._contracts: Dict[str, ContractDefinition] = {}
        self._events: Dict[str, EventDefinition] = {}
        for contract in contracts:
            self.register_contract(contract)
        for event in events:
            self.register_event(event)

    def register_contract(self, contract: ContractDefinition) -> None:
        self._cells.cell(contract.producer_cell)
        for consumer in contract.consumer_cells:
            self._cells.cell(consumer)
        if contract.contract_id in self._contracts:
            raise GovernanceViolation(f"DUPLICATE_CONTRACT:{contract.contract_id}")
        self._contracts[contract.contract_id] = contract

    def register_event(self, event: EventDefinition) -> None:
        self._cells.cell(event.producer_cell)
        for consumer in event.allowed_consumers:
            self._cells.cell(consumer)
        if event.event_type in self._events:
            raise GovernanceViolation(f"DUPLICATE_EVENT:{event.event_type}")
        self._events[event.event_type] = event

    @property
    def contracts(self) -> Mapping[str, ContractDefinition]:
        return dict(self._contracts)

    @property
    def events(self) -> Mapping[str, EventDefinition]:
        return dict(self._events)


class AutonomyQualificationRegistry:
    def __init__(self, *, cells: DomainOwnershipRegistry):
        self._cells = cells
        self._records: Dict[QualificationKey, QualificationRecord] = {}

    def qualify(self, record: QualificationRecord) -> QualificationRecord:
        cell = self._cells.cell(record.key.cell_id)
        if record.validator_cell != INDEPENDENT_QA_CELL_ID:
            raise GovernanceViolation("INDEPENDENT_VALIDATION_REQUIRED")
        if record.validator_cell == record.key.cell_id:
            raise GovernanceViolation("SELF_CERTIFICATION_PROHIBITED")
        if record.key.capability not in cell.capabilities:
            raise GovernanceViolation(
                f"CAPABILITY_NOT_OWNED:{record.key.cell_id}:{record.key.capability}"
            )
        if record.key.capability in cell.forbidden_capabilities:
            raise GovernanceViolation("FORBIDDEN_CAPABILITY")
        if record.key.risk_class is RiskClass.R4:
            raise GovernanceViolation("R4_PROHIBITED")
        if record.key.risk_class is RiskClass.R3 and record.reality is ProductionReality.AUTONOMOUS_QUALIFIED:
            raise GovernanceViolation("R3_NOT_DOMAIN_AUTONOMOUS")
        if not record.evidence.complete_for(record.key.risk_class, record.key.environment):
            raise GovernanceViolation("QUALIFICATION_EVIDENCE_INCOMPLETE")
        if record.key.environment is Environment.PRODUCTION and not cell.accountability_bound:
            raise GovernanceViolation("LEGAL_ACCOUNTABILITY_NOT_BOUND")
        if not isinstance(record.key.risk_class, RiskClass) or not isinstance(record.key.environment, Environment):
            raise GovernanceViolation("TYPED_QUALIFICATION_SCOPE_REQUIRED")
        if not isinstance(record.reality, ProductionReality):
            raise GovernanceViolation("TYPED_PRODUCTION_REALITY_REQUIRED")
        if record.releaser_cell in {None, record.validator_cell, record.key.cell_id}:
            raise GovernanceViolation("INDEPENDENT_RELEASE_REQUIRED")
        self._cells.cell(record.releaser_cell)
        if not record.policy_version or not record.evidence.evidence_refs:
            raise GovernanceViolation("QUALIFICATION_POLICY_AND_EVIDENCE_REQUIRED")
        dates = (record.valid_from, record.valid_until)
        if any(d is not None for d in dates):
            if any(not isinstance(d, datetime) or d.tzinfo is None or d.utcoffset() is None for d in dates):
                raise GovernanceViolation("QUALIFICATION_AWARE_VALIDITY_WINDOW_REQUIRED")
            if record.valid_from >= record.valid_until:
                raise GovernanceViolation("QUALIFICATION_VALIDITY_WINDOW_INVALID")
        current = self._records.get(record.key)
        if current and current.reality in {ProductionReality.RESTRICTED, ProductionReality.SUSPENDED}:
            if (not record.valid_from or (current.valid_from is not None and record.valid_from <= current.valid_from)
                    or record.evidence.evidence_refs == current.evidence.evidence_refs):
                raise GovernanceViolation("FRESH_INDEPENDENT_REQUALIFICATION_REQUIRED")
        self._records[record.key] = record
        return record

    def get(self, key: QualificationKey) -> QualificationRecord | None:
        return self._records.get(key)

    def current_denial(self, key: QualificationKey, *, at: datetime, policy_version: str) -> str | None:
        record = self.get(key)
        if record is None:
            return "AUTONOMY_QUALIFICATION_MISSING"
        if record.reality is not ProductionReality.AUTONOMOUS_QUALIFIED:
            return "AUTONOMY_NOT_CURRENTLY_QUALIFIED"
        if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
            return "AUTONOMY_AWARE_EXECUTION_TIME_REQUIRED"
        if record.valid_from is None or record.valid_until is None:
            return "AUTONOMY_QUALIFICATION_VALIDITY_REQUIRED"
        if at < record.valid_from:
            return "AUTONOMY_QUALIFICATION_NOT_YET_VALID"
        if at >= record.valid_until:
            return "AUTONOMY_QUALIFICATION_EXPIRED"
        if record.policy_version != policy_version:
            return "AUTONOMY_QUALIFICATION_POLICY_CHANGED"
        return None

    def revoke(self, key: QualificationKey, *, reason: str) -> QualificationRecord:
        current = self._records.get(key)
        if current is None:
            raise GovernanceViolation("QUALIFICATION_NOT_FOUND")
        downgraded = replace(
            current,
            reality=ProductionReality.RESTRICTED,
            metadata={**dict(current.metadata), "revocation_reason": reason},
        )
        self._records[key] = downgraded
        return downgraded

    def suspend(self, key: QualificationKey, *, reason: str) -> QualificationRecord:
        current = self._records.get(key)
        if current is None:
            raise GovernanceViolation("QUALIFICATION_NOT_FOUND")
        suspended = replace(
            current,
            reality=ProductionReality.SUSPENDED,
            metadata={**dict(current.metadata), "suspension_reason": reason},
        )
        self._records[key] = suspended
        return suspended
