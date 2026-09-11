from __future__ import annotations
from .types import CellWorkspace

MASTER_VERSION = "GO_ULTIMATE_MASTER_PLAN_V7.0_2026-08-31_MASTER"
WORKBENCH_BUILD = "GO_PARALLEL_WORKBENCH_BUILD01"

# C09 constitutional assets are protected from mutation by every other Cell.
C09_PROTECTED_ASSETS = (
    "governance/recommendation/",
    "docs/GO_RECOMMENDATION_CONSTITUTION_1_0.md",
    "src/go_hotel/judgment/",
)

def _ws(cell_id, name, domain, owned, forbidden=(), control_only=False):
    return CellWorkspace(
        cell_id=cell_id,
        name=name,
        domain=domain,
        branch_prefix=f"cell/{cell_id.lower()}",
        worktree_prefix=f"worktrees/{cell_id.lower()}",
        owned_paths=tuple(owned),
        forbidden_paths=tuple(forbidden),
        control_only=control_only,
    )

BUSINESS_TRUTH_PATHS = (
    "src/go_hotel/hotel/", "src/go_hotel/flight/", "src/go_hotel/rail/",
    "src/go_hotel/mobility/", "src/go_hotel/attractions/",
    "src/go_hotel/journey/", "src/go_hotel/payments/", "src/go_hotel/judgment/",
)

WORKSPACES = (
    _ws("C01","Hotel AI Operations Cell","HOTEL",("src/go_hotel/hotel/","src/go_hotel/services/","src/go_hotel/connectors/hotel/","tests/hotel/"),forbidden=("src/go_hotel/services/onboarding.py",)),
    _ws("C02","Flight AI Operations Cell","FLIGHT",("src/go_hotel/flight/","src/go_hotel/connectors/flight/","tests/flight/")),
    _ws("C03","Rail AI Operations Cell","RAIL",("src/go_hotel/rail/","src/go_hotel/connectors/rail/","tests/rail/")),
    _ws("C04","Rental AI Operations Cell","RENTAL",("src/go_hotel/mobility/rental/","tests/mobility/rental/")),
    _ws("C05","Ride AI Operations Cell","RIDE",("src/go_hotel/mobility/ride/","tests/mobility/ride/")),
    _ws("C06","Attraction AI Operations Cell","ATTRACTION",("src/go_hotel/attractions/","tests/attractions/")),
    _ws("C07","Traveler Intelligence Cell","TRAVELER_INTELLIGENCE",("src/go_hotel/travel_intelligence/","src/go_hotel/identity/","tests/travel_intelligence/")),
    _ws("C08","GO AI Planning & Execution Cell","GO_AI_PLAN",("src/go_hotel/go_ai/","src/go_hotel/routing/","tests/go_ai/")),
    _ws("C09","GO Judgment & Trust Cell","GO_JUDGMENT",("src/go_hotel/judgment/","governance/recommendation/","tests/judgment/")),
    _ws("C10","Unified Trips Cell","UNIFIED_TRIPS",("src/go_hotel/journey/","tests/journey/")),
    _ws("C11","Transaction & Finance Cell","TRANSACTION_FINANCE",("src/go_hotel/payments/","src/go_hotel/compensation/","tests/payments/")),
    _ws("C12","Platform / Security / Model Gateway Cell","PLATFORM_SECURITY_MODEL_GATEWAY",("src/go_hotel/core/","src/go_hotel/security/","src/go_hotel/observability/","src/go_hotel/autonomy/","src/go_hotel/workbench/","src/go_hotel/services/onboarding.py","src/go_hotel/api/routes/onboarding.py","governance/autonomy/","governance/workbench/","tests/autonomy/","tests/workbench/","script/")),
    _ws("C13","Independent QA & Release Cell","INDEPENDENT_QA_RELEASE",("tests/","deploy/","gate_runtime/","evidence/","release/"),forbidden=("src/go_hotel/",),control_only=True),
    _ws("C14","AI Constitutional, Legal & Regulatory Control Cell","AI_CONSTITUTIONAL_LEGAL_REGULATORY_CONTROL",("src/go_hotel/autonomy/","governance/legal/","governance/autonomy/","tests/autonomy/"),forbidden=BUSINESS_TRUTH_PATHS,control_only=True),
)

WORKSPACE_BY_ID = {w.cell_id: w for w in WORKSPACES}

WORKBENCH_POLICY = {
    "master_version": MASTER_VERSION,
    "build": WORKBENCH_BUILD,
    "cell_count": 14,
    "required_lanes": (
        "MASTER_CONTROL_BOARD",
        "CELL_WORKSPACES",
        "DEPENDENCY_GRAPH",
        "CONTRACT_EVENT_REGISTRY",
        "AUTHORITY_C14_LEGAL_QUEUE",
        "INDEPENDENT_QA_LANE",
        "PARENT_MERGE_RELEASE_LANE",
    ),
    "workflow": (
        "MASTER_DIRECTIVE",
        "WORK_DECOMPOSITION",
        "CELL_ASSIGNMENT",
        "PARALLEL_CANDIDATE_BUILD",
        "CROSS_CELL_CONTRACT_VALIDATION",
        "AUTHORITY_CONSTITUTION_GATE",
        "C14_LEGAL_EXPOSURE_REVIEW",
        "C13_INDEPENDENT_QA",
        "MERGE_CONTROLLER",
        "DEPLOYABLE_PARENT_CANDIDATE",
    ),
    "rules": {
        "independent_worktree_branch_manifest": True,
        "shared_parent_direct_write": False,
        "cross_domain_truth_mutation": False,
        "cross_domain_collaboration_modes": ("CONTRACT","EVENT"),
        "c09_recommendation_constitution_protected": True,
        "c13_builder_forbidden": True,
        "c14_business_truth_mutation_forbidden": True,
    },
}
