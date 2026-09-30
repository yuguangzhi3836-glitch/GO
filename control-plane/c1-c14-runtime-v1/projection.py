"""Read-only Command Center projection for Runtime state."""
from __future__ import annotations
from runtime import Runtime

def command_center_projection(rt: Runtime) -> dict:
    snap=rt.snapshot()
    unhealthy=[a["c_id"] for a in snap["agents"] if a["status"]=="STALE"]
    return {
      "runtime":"C1-C14",
      "health":"DEGRADED" if unhealthy or snap["open_escalations"] else "HEALTHY",
      "stale_domains":unhealthy,
      "task_counts":snap["task_counts"],
      "open_escalations":snap["open_escalations"],
      "evidence_chain_valid":snap["evidence_chain_valid"],
      "domains":[{"c_id":a["c_id"],"status":a["status"],"heartbeat_at":a["heartbeat_at"]} for a in snap["agents"]]
    }
