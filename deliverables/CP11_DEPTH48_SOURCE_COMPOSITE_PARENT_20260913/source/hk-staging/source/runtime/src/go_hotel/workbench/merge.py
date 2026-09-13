from __future__ import annotations
import hashlib
from .definitions import C09_PROTECTED_ASSETS, WORKSPACE_BY_ID
from .types import CandidateManifest, GateRecord, GateStatus, MergeDecision

REQUIRED_GATES = (
    "CROSS_CELL_CONTRACT_VALIDATION",
    "AUTHORITY_CONSTITUTION_GATE",
    "C14_LEGAL_EXPOSURE_REVIEW",
    "C13_INDEPENDENT_QA",
)

class MergeController:
    def _path_allowed(self, manifest: CandidateManifest) -> tuple[bool, str]:
        ws = WORKSPACE_BY_ID.get(manifest.builder_cell)
        if ws is None:
            return False, "UNKNOWN_BUILDER_CELL"
        if manifest.builder_cell == "C13":
            return False, "C13_MUST_NOT_BUILD_FEATURE_CANDIDATE"
        for path in manifest.changed_paths:
            if ws.forbidden(path):
                return False, f"FORBIDDEN_PATH:{path}"
            if not ws.owns(path):
                return False, f"PATH_NOT_OWNED:{path}"
            if manifest.builder_cell != "C09" and any(path == p or path.startswith(p.rstrip('/') + '/') for p in C09_PROTECTED_ASSETS):
                return False, f"C09_CONSTITUTIONAL_ASSET_PROTECTED:{path}"
        return True, "PATH_SCOPE_VALID"

    def validate_candidate_isolation(self, manifests: tuple[CandidateManifest, ...]) -> tuple[bool, str]:
        branches = [m.branch for m in manifests]
        worktrees = [m.worktree for m in manifests]
        if len(branches) != len(set(branches)):
            return False, "BRANCH_COLLISION"
        if len(worktrees) != len(set(worktrees)):
            return False, "WORKTREE_COLLISION"
        path_owners = {}
        for m in manifests:
            ok, reason = self._path_allowed(m)
            if not ok:
                return False, f"{m.candidate_id}:{reason}"
            for path in m.changed_paths:
                previous = path_owners.get(path)
                if previous and previous != m.builder_cell:
                    return False, f"PATH_COLLISION:{path}:{previous}:{m.builder_cell}"
                path_owners[path] = m.builder_cell
        return True, "ISOLATED"

    def authorize_merge(self, manifest: CandidateManifest, gates: tuple[GateRecord, ...]) -> MergeDecision:
        ok, reason = self._path_allowed(manifest)
        if not ok:
            return MergeDecision(False, "SCOPE_BLOCK", reason, manifest.candidate_id)
        gate_map = {g.gate: g for g in gates}
        for gate in REQUIRED_GATES:
            rec = gate_map.get(gate)
            if rec is None:
                return MergeDecision(False, "GATE_MISSING", gate, manifest.candidate_id)
            if rec.status is not GateStatus.PASS:
                return MergeDecision(False, "GATE_NOT_PASS", f"{gate}:{rec.status.value}", manifest.candidate_id)
        if gate_map["C13_INDEPENDENT_QA"].reviewer_cell != "C13":
            return MergeDecision(False, "QA_NOT_INDEPENDENT", "C13 required", manifest.candidate_id)
        if gate_map["C14_LEGAL_EXPOSURE_REVIEW"].reviewer_cell != "C14":
            return MergeDecision(False, "LEGAL_REVIEWER_INVALID", "C14 required", manifest.candidate_id)
        if manifest.builder_cell in {"C13", "C14"} and any(
            p.startswith(("src/go_hotel/hotel/","src/go_hotel/flight/","src/go_hotel/rail/","src/go_hotel/mobility/","src/go_hotel/attractions/","src/go_hotel/journey/","src/go_hotel/payments/","src/go_hotel/judgment/"))
            for p in manifest.changed_paths
        ):
            return MergeDecision(False, "CONTROL_CELL_BUSINESS_MUTATION", manifest.builder_cell, manifest.candidate_id)
        digest = hashlib.sha256((manifest.candidate_id + manifest.source_sha256 + "|" + "|".join(sorted(manifest.changed_paths))).encode()).hexdigest()[:16]
        return MergeDecision(True, "MERGE_ALLOW", "all mandatory gates passed", manifest.candidate_id, f"PARENT-CANDIDATE-{digest}")
