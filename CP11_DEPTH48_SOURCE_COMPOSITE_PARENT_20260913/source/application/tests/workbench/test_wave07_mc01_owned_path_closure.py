import json
from pathlib import Path

import pytest

from go_hotel.workbench.controller import ParallelWorkbench, WorkbenchViolation
from go_hotel.workbench.definitions import WORKSPACE_BY_ID
from go_hotel.workbench.merge import MergeController
from go_hotel.workbench.types import CandidateManifest, GateRecord, GateStatus, WorkDirective

SERVICE = 'src/go_hotel/services/onboarding.py'
ROUTE = 'src/go_hotel/api/routes/onboarding.py'
CORE = 'src/go_hotel/core/provider_onboarding_governance_v1.py'
TEST = 'tests/workbench/test_wave07_provider_onboarding_governance_v1.py'


def _directive(cell):
    return WorkDirective(
        directive_id='W07MC01', title='owned path closure', description='exact carve-out only',
        master_version='GO_ULTIMATE_MASTER_PLAN_V7.0_2026-08-31_MASTER',
        requested_cells=(cell,), scope_boundary='P1-MC-01 ownership only',
    )


def _gates():
    return (
        GateRecord('CROSS_CELL_CONTRACT_VALIDATION','C12',GateStatus.PASS,'post-closure impact check'),
        GateRecord('AUTHORITY_CONSTITUTION_GATE','C14',GateStatus.PASS,'unchanged prior gate'),
        GateRecord('C14_LEGAL_EXPOSURE_REVIEW','C14',GateStatus.PASS,'unchanged prior gate'),
        GateRecord('C13_INDEPENDENT_QA','C13',GateStatus.PASS,'post-closure C13'),
    )


def test_exact_onboarding_integration_is_c12_owned_without_services_directory_transfer():
    c01=WORKSPACE_BY_ID['C01']
    c12=WORKSPACE_BY_ID['C12']
    assert c01.owns(SERVICE)  # legacy broad prefix still exists
    assert c01.forbidden(SERVICE)  # exact carve-out removes write authority
    assert c12.owns(SERVICE)
    assert c12.owns(ROUTE)
    assert not c12.owns('src/go_hotel/services/hotel_content.py')


def test_c01_cannot_build_carved_out_onboarding_service():
    with pytest.raises(WorkbenchViolation, match='FORBIDDEN_PATH:C01'):
        ParallelWorkbench().decompose(_directive('C01'), {'C01': (SERVICE,)})


def test_c12_can_build_only_the_wave07_integration_paths():
    item=ParallelWorkbench().decompose(_directive('C12'), {'C12': (SERVICE, ROUTE, CORE, TEST)})[0]
    assert item.cell_id == 'C12'
    assert item.change_scope == (SERVICE, ROUTE, CORE, TEST)


def test_ownership_contract_matches_machine_registry():
    data=json.loads(Path('governance/workbench/WAVE07_ONBOARDING_INTEGRATION_OWNERSHIP_CONTRACT_20260831.json').read_text())
    assert data['collaboration_mode']=='CONTRACT'
    assert data['exact_path_assignment'][SERVICE]=='C12'
    assert data['exact_path_assignment'][ROUTE]=='C12'
    assert 'does not grant C12 HOTEL or any six-Vertical business Truth authority' in data['truth_boundary'][0]


def test_wave07_candidate_scope_is_merge_controller_owned_path_valid():
    manifest=CandidateManifest(
        'WAVE07-P1-CLOSURE','W07','C12','cell/c12/wave07','worktrees/c12/wave07',
        (SERVICE,ROUTE,CORE,TEST),('go.provider-adapter-contract.v2',),'closure-source-sha'
    )
    decision=MergeController().authorize_merge(manifest,_gates())
    assert decision.allowed, (decision.code,decision.reason)
    assert decision.code=='MERGE_ALLOW'
