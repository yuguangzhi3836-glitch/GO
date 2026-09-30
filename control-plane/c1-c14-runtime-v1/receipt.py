"""Unsigned runtime receipt payloads.

Workers may construct/verify receipt payloads but never receive signing-key access.
External Command Center authority may sign the canonical bytes later.
"""
from __future__ import annotations
import hashlib,json
from typing import Any

def canonical_receipt(snapshot: dict[str,Any], *, runtime_version: str, head_sha: str) -> dict[str,Any]:
    core={
      "runtime_version":runtime_version,
      "head_sha":head_sha,
      "task_counts":snapshot["task_counts"],
      "open_escalations":snapshot["open_escalations"],
      "evidence_chain_valid":snapshot["evidence_chain_valid"],
      "agent_status":{a["c_id"]:a["status"] for a in snapshot["agents"]},
    }
    raw=json.dumps(core,sort_keys=True,separators=(",",":"))
    return {**core,"payload_sha256":hashlib.sha256(raw.encode()).hexdigest(),"signature":None,"signer":None}

def verify_unsigned_receipt(receipt: dict[str,Any]) -> bool:
    core={k:receipt[k] for k in ("runtime_version","head_sha","task_counts","open_escalations","evidence_chain_valid","agent_status")}
    raw=json.dumps(core,sort_keys=True,separators=(",",":"))
    return receipt.get("payload_sha256")==hashlib.sha256(raw.encode()).hexdigest()
