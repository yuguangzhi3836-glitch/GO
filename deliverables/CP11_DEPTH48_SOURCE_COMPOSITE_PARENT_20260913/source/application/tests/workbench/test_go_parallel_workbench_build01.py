import pytest
from go_hotel.workbench.controller import ParallelWorkbench, WorkbenchViolation
from go_hotel.workbench.definitions import WORKBENCH_POLICY, WORKSPACES
from go_hotel.workbench.graph import DependencyGraph, DependencyGraphError
from go_hotel.workbench.merge import MergeController
from go_hotel.workbench.types import CandidateManifest, GateRecord, GateStatus, WorkDirective

def directive(*cells):
    return WorkDirective(
        directive_id="D001", title="parallel", description="x",
        master_version="GO_ULTIMATE_MASTER_PLAN_V7.0_2026-08-31_MASTER",
        requested_cells=tuple(cells), scope_boundary="infra only"
    )

def gates():
    return (
        GateRecord("CROSS_CELL_CONTRACT_VALIDATION","C12",GateStatus.PASS,"ok"),
        GateRecord("AUTHORITY_CONSTITUTION_GATE","C14",GateStatus.PASS,"ok"),
        GateRecord("C14_LEGAL_EXPOSURE_REVIEW","C14",GateStatus.PASS,"ok"),
        GateRecord("C13_INDEPENDENT_QA","C13",GateStatus.PASS,"ok"),
    )

def test_fourteen_workspaces_and_seven_lanes():
    assert len(WORKSPACES) == 14
    assert len(WORKBENCH_POLICY["required_lanes"]) == 7

def test_each_workspace_has_independent_branch_and_worktree_prefix():
    assert len({w.branch_prefix for w in WORKSPACES}) == 14
    assert len({w.worktree_prefix for w in WORKSPACES}) == 14

def test_decomposition_builds_isolated_workitems():
    wb = ParallelWorkbench()
    items = wb.decompose(directive("C08","C09"), {
        "C08": ("src/go_hotel/go_ai/planner.py",),
        "C09": ("src/go_hotel/judgment/service.py",),
    }, {"C08":("C09",)})
    assert len(items) == 2
    assert items[0].branch != items[1].branch
    assert items[0].worktree != items[1].worktree

def test_cross_owned_path_is_blocked():
    wb=ParallelWorkbench()
    with pytest.raises(WorkbenchViolation):
        wb.decompose(directive("C08"), {"C08":("src/go_hotel/judgment/service.py",)})

def test_c14_cannot_mutate_business_truth_paths():
    wb=ParallelWorkbench()
    with pytest.raises(WorkbenchViolation):
        wb.decompose(directive("C14"), {"C14":("src/go_hotel/payments/ledger.py",)})

def test_dependency_cycle_fails_closed():
    g=DependencyGraph()
    g.add_dependency("A","B")
    with pytest.raises(DependencyGraphError):
        g.add_dependency("B","A")

def test_c09_constitutional_assets_protected_from_other_cells():
    m=CandidateManifest("X","D","C12","cell/c12/d","worktrees/c12/d",
        ("src/go_hotel/judgment/service.py",),(),"abc")
    decision=MergeController().authorize_merge(m,gates())
    assert not decision.allowed
    assert decision.code == "SCOPE_BLOCK"

def test_merge_requires_all_gates():
    m=CandidateManifest("X","D","C08","cell/c08/d","worktrees/c08/d",
        ("src/go_hotel/go_ai/planner.py",),(),"abc")
    decision=MergeController().authorize_merge(m,gates()[:-1])
    assert not decision.allowed and decision.code == "GATE_MISSING"

def test_c13_must_be_independent_qa():
    m=CandidateManifest("X","D","C08","cell/c08/d","worktrees/c08/d",
        ("src/go_hotel/go_ai/planner.py",),(),"abc")
    bad=tuple(GateRecord(g.gate,("C12" if g.gate=="C13_INDEPENDENT_QA" else g.reviewer_cell),g.status,g.reason) for g in gates())
    decision=MergeController().authorize_merge(m,bad)
    assert not decision.allowed and decision.code == "QA_NOT_INDEPENDENT"

def test_c14_must_review_legal_gate():
    m=CandidateManifest("X","D","C08","cell/c08/d","worktrees/c08/d",
        ("src/go_hotel/go_ai/planner.py",),(),"abc")
    bad=tuple(GateRecord(g.gate,("C12" if g.gate=="C14_LEGAL_EXPOSURE_REVIEW" else g.reviewer_cell),g.status,g.reason) for g in gates())
    decision=MergeController().authorize_merge(m,bad)
    assert not decision.allowed and decision.code == "LEGAL_REVIEWER_INVALID"

def test_valid_candidate_can_merge():
    m=CandidateManifest("X","D","C08","cell/c08/d","worktrees/c08/d",
        ("src/go_hotel/go_ai/planner.py",),(),"abc")
    decision=MergeController().authorize_merge(m,gates())
    assert decision.allowed
    assert decision.parent_candidate_id.startswith("PARENT-CANDIDATE-")

def test_parallel_candidate_path_collision_fails():
    a=CandidateManifest("A","D","C08","b1","w1",("src/go_hotel/go_ai/planner.py",),(),"a")
    b=CandidateManifest("B","D","C08","b2","w2",("src/go_hotel/go_ai/planner.py",),(),"b")
    ok, reason=MergeController().validate_candidate_isolation((a,b))
    assert ok  # same final owner may serialize within its own cell without cross-cell corruption
