"""Preflight only. Inputs must come from verified, exact-candidate evidence.

This helper neither authenticates caller claims nor installs anything. Formal
Command Center admission remains the authority boundary. Missing topology facts
fail closed; raw PASS_SCOPED labels must not be promoted into installation PASS.
"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class GateInput:
 postgres_acceptance:str
 c13_verdict:str
 c14_verdict:str
 evidence_chain_valid:bool
 sha256_manifest_present:bool
 human_command_center_authorization:bool
 topology_review_passed:bool=False
 topology_validation_passed:bool=False
 topology_approved_and_proven:bool=False
 topology_binding_verified:bool=False

def installation_eligibility(x:GateInput)->dict:
 blockers=[]
 if not all(v is True for v in (x.topology_review_passed, x.topology_validation_passed, x.topology_approved_and_proven, x.topology_binding_verified)):
  blockers.append("TOPOLOGY_CHANGE_REQUIRED")
 if x.postgres_acceptance!="PASS": blockers.append("POSTGRES_ACCEPTANCE_NOT_PASS")
 if x.c13_verdict!="PASS": blockers.append("C13_NOT_PASS")
 if x.c14_verdict!="PASS": blockers.append("C14_NOT_PASS")
 if x.evidence_chain_valid is not True: blockers.append("EVIDENCE_CHAIN_INVALID")
 if x.sha256_manifest_present is not True: blockers.append("SHA256_MANIFEST_MISSING")
 if x.human_command_center_authorization is not True: blockers.append("HUMAN_AUTHORIZATION_MISSING")
 return {"eligible":not blockers,"blockers":blockers,"authorizes_any_action":False}
