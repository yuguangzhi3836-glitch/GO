"""Installation eligibility gate for C1-C14 Runtime."""
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

def installation_eligibility(x:GateInput)->dict:
 blockers=[]
 if x.postgres_acceptance!="PASS": blockers.append("POSTGRES_ACCEPTANCE_NOT_PASS")
 if x.c13_verdict!="PASS": blockers.append("C13_NOT_PASS")
 if x.c14_verdict!="PASS": blockers.append("C14_NOT_PASS")
 if not x.evidence_chain_valid: blockers.append("EVIDENCE_CHAIN_INVALID")
 if not x.sha256_manifest_present: blockers.append("SHA256_MANIFEST_MISSING")
 if not x.human_command_center_authorization: blockers.append("HUMAN_AUTHORIZATION_MISSING")
 return {"eligible":not blockers,"blockers":blockers}
