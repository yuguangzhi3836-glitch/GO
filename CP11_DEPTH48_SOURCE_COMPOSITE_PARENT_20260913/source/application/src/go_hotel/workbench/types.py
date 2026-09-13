from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Tuple


class WorkStatus(str, Enum):
    PLANNED = "PLANNED"
    ASSIGNED = "ASSIGNED"
    BUILDING = "BUILDING"
    CANDIDATE_READY = "CANDIDATE_READY"
    CONTRACT_VALIDATED = "CONTRACT_VALIDATED"
    AUTHORITY_PASSED = "AUTHORITY_PASSED"
    LEGAL_PASSED = "LEGAL_PASSED"
    QA_PASSED = "QA_PASSED"
    MERGE_READY = "MERGE_READY"
    MERGED = "MERGED"
    BLOCKED = "BLOCKED"


class GateStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    PASS = "PASS"
    HOLD = "HOLD"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class CellWorkspace:
    cell_id: str
    name: str
    domain: str
    branch_prefix: str
    worktree_prefix: str
    owned_paths: Tuple[str, ...]
    forbidden_paths: Tuple[str, ...] = ()
    control_only: bool = False

    def owns(self, path: str) -> bool:
        return any(path == p or path.startswith(p.rstrip("/") + "/") for p in self.owned_paths)

    def forbidden(self, path: str) -> bool:
        return any(path == p or path.startswith(p.rstrip("/") + "/") for p in self.forbidden_paths)


@dataclass(frozen=True)
class WorkDirective:
    directive_id: str
    title: str
    description: str
    master_version: str
    requested_cells: Tuple[str, ...]
    scope_boundary: str
    acceptance_criteria: Tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkItem:
    work_item_id: str
    directive_id: str
    cell_id: str
    branch: str
    worktree: str
    change_scope: Tuple[str, ...]
    contract_dependencies: Tuple[str, ...] = ()
    status: WorkStatus = WorkStatus.ASSIGNED


@dataclass(frozen=True)
class CandidateManifest:
    candidate_id: str
    directive_id: str
    builder_cell: str
    branch: str
    worktree: str
    changed_paths: Tuple[str, ...]
    contract_versions: Tuple[str, ...]
    source_sha256: str
    evidence_refs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class GateRecord:
    gate: str
    reviewer_cell: str
    status: GateStatus
    reason: str
    evidence_refs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class MergeDecision:
    allowed: bool
    code: str
    reason: str
    candidate_id: str
    parent_candidate_id: str | None = None
