from __future__ import annotations
from dataclasses import dataclass
from typing import Awaitable, Callable, Any

@dataclass(frozen=True)
class FailoverPolicy:
    operation: str
    allow_cross_connector_failover: bool
    reason: str

POLICIES={
    "SEARCH": FailoverPolicy("SEARCH",True,"Read-only; safe to retry/fail over."),
    "AVAILABILITY": FailoverPolicy("AVAILABILITY",True,"Read-only; safe to retry/fail over."),
    "PREBOOK": FailoverPolicy("PREBOOK",True,"No committed booking yet; failover allowed after definitive failure."),
    "BOOK": FailoverPolicy("BOOK",False,"Cross-connector retry can double-book after an ambiguous external success. Reconcile first."),
    "CANCEL": FailoverPolicy("CANCEL",False,"Cancellation must stay on the connector that owns the booking."),
    "REFUND": FailoverPolicy("REFUND",False,"Refund must stay on the original payment/booking rail."),
}

class FailoverBlocked(RuntimeError): pass

async def execute_safe_failover(operation:str, connector_ids:list[str], call:Callable[[str],Awaitable[Any]]):
    policy=POLICIES.get(operation,FailoverPolicy(operation,False,"Unknown mutation; fail closed."))
    errors=[]
    for idx,cid in enumerate(connector_ids):
        try: return await call(cid),cid
        except Exception as exc:
            errors.append((cid,str(exc)))
            if idx < len(connector_ids)-1 and not policy.allow_cross_connector_failover:
                raise FailoverBlocked(f"{operation}_FAILOVER_BLOCKED_RECONCILIATION_REQUIRED:{errors}") from exc
    raise RuntimeError(f"{operation}_ALL_CONNECTORS_FAILED:{errors}")
