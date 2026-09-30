"""Runtime watchdog for unattended 24x7 operation."""
from __future__ import annotations
import time
from runtime import C_IDS, Runtime

class Watchdog:
    def __init__(self, rt: Runtime, *, stale_after_s: int = 120):
        self.rt=rt; self.stale_after_s=stale_after_s

    def inspect(self, *, now: float | None=None) -> dict:
        now=time.time() if now is None else now
        snap=self.rt.snapshot()
        stale=[]
        for a in snap["agents"]:
            hb=a["heartbeat_at"]
            if hb is None:
                continue
            if now-hb > self.stale_after_s:
                stale.append(a["c_id"])
        recovered=self.rt.recover_stale(now=now)
        for c_id in stale:
            self.rt.escalate(
                c_id,"AGENT_HEARTBEAT_STALE",severity="HIGH",
                details={"stale_after_s":self.stale_after_s},requires_human=False
            )
        return {"stale_domains":stale,"recovery":recovered,"evidence_chain_valid":snap["evidence_chain_valid"]}
