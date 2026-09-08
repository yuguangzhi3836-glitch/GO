"""Seven-chain code-side acceptance matrix for autonomous directory adapters.

This evaluator separates code completeness from runtime/full-directory truth. A chain
cannot be marked READY merely because an adapter class exists. Official-source
contract readiness, adapter topology, deterministic property identity, resumable
cursor behavior, host fail-closed behavior and complete-directory proof are all
separate gates.
"""
from __future__ import annotations

from .chain_hotel_registry import ChainCode
from .chain_official_source_contracts import DirectoryReadiness, contract_for

CHAIN_ORDER=(
    ChainCode.HYATT,
    ChainCode.MARRIOTT,
    ChainCode.SHANGRI_LA,
    ChainCode.HILTON,
    ChainCode.IHG,
    ChainCode.H_WORLD,
    ChainCode.ATOUR,
)

EXPECTED_TOPOLOGY={
    ChainCode.HYATT:"DEDICATED_SNAPSHOT_CURSOR",
    ChainCode.MARRIOTT:"HIERARCHICAL_OFFICIAL_DIRECTORY",
    ChainCode.SHANGRI_LA:"FLAT_OFFICIAL_DIRECTORY",
    ChainCode.HILTON:"HIERARCHICAL_OFFICIAL_DIRECTORY",
    ChainCode.IHG:"HIERARCHICAL_OFFICIAL_DIRECTORY",
    ChainCode.H_WORLD:"OFFICIAL_INVENTORY_CONTRACT_REQUIRED",
    ChainCode.ATOUR:"OFFICIAL_INVENTORY_CONTRACT_REQUIRED",
}


def evaluate_chain(record:dict)->dict:
    try: chain=ChainCode(str(record.get("chain") or ""))
    except Exception:return {"status":"HOLD","reason":"CHAIN_CODE_INVALID","checks":{}}
    contract=contract_for(chain);checks={}
    checks["official_contract_present"]=bool(contract.directory_url and contract.property_identity_strategy)
    checks["official_https"]=str(contract.directory_url).startswith("https://")
    checks["adapter_topology"]=(record.get("adapter_topology")==EXPECTED_TOPOLOGY[chain])
    checks["deterministic_property_identity"]=(record.get("property_identity_strategy")==contract.property_identity_strategy and record.get("property_identity_collision_count")==0)
    checks["official_host_fail_closed"]=record.get("official_host_fail_closed") is True
    checks["snapshot_or_cursor_resume"]=record.get("snapshot_or_cursor_resume") is True
    checks["snapshot_drift_fail_closed"]=record.get("snapshot_drift_fail_closed") is True
    checks["duplicate_seed_count_zero"]=record.get("duplicate_seed_count")==0
    checks["directory_nonempty"]=isinstance(record.get("property_count"),int) and record.get("property_count")>0
    if contract.readiness==DirectoryReadiness.VERIFIED_FULL_DIRECTORY:
        checks["full_directory_contract_verified"]=record.get("full_directory_contract_verified") is True
    elif contract.readiness==DirectoryReadiness.VERIFIED_DIRECTORY_ENTRYPOINT:
        checks["full_directory_contract_verified"]=record.get("full_directory_contract_verified") is True and record.get("entrypoint_only") is not True
    else:
        checks["full_directory_contract_verified"]=False
    checks["runtime_enumeration_evidence"]=record.get("runtime_enumeration_evidence") is True
    passed=all(checks.values())
    return {"chain":chain.value,"status":"PASS" if passed else "HOLD","checks":checks,"contract_readiness":contract.readiness.value}


def evaluate_seven_chain_matrix(records:list[dict])->dict:
    by_chain={str(x.get("chain") or ""):x for x in records}
    results=[]
    for chain in CHAIN_ORDER:
        record=by_chain.get(chain.value,{"chain":chain.value})
        results.append(evaluate_chain(record))
    passed=all(x["status"]=="PASS" for x in results)
    return {
        "status":"PASS" if passed else "HOLD",
        "chain_count":7,
        "pass_count":sum(1 for x in results if x["status"]=="PASS"),
        "hold_count":sum(1 for x in results if x["status"]!="PASS"),
        "chains":results,
    }
