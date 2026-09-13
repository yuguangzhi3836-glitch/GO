from __future__ import annotations
from dataclasses import dataclass, asdict
from go_hotel.domain.models import Offer

@dataclass
class Check:
    name: str; passed: bool; detail: str=""
@dataclass
class CertificationReport:
    connector_id: str; passed: bool; checks: list[Check]
    def as_dict(self): return {"connector_id":self.connector_id,"passed":self.passed,"checks":[asdict(c) for c in self.checks]}

class ConnectorCertificationHarness:
    async def certify(self, connector, *, city_code="TYO", check_in="2026-09-01", check_out="2026-09-02", currency="CNY") -> CertificationReport:
        checks=[]
        async def check(name, coro, validate=lambda x: True):
            try:
                value=await coro; ok=bool(validate(value)); checks.append(Check(name,ok,"ok" if ok else f"invalid result: {value!r}")); return value
            except Exception as exc: checks.append(Check(name,False,f"{type(exc).__name__}: {exc}")); return None
        health=await check("health", connector.health(), lambda x:isinstance(x,dict))
        offers=await check("search", connector.search(city_code,check_in,check_out,currency), lambda x:isinstance(x,list))
        offer=offers[0] if offers else None
        if offer is None:
            checks.extend([Check("canonical_offer",False,"no offer"),Check("prebook",False,"blocked"),Check("book_idempotency",False,"blocked"),Check("status",False,"blocked")])
        else:
            checks.append(Check("canonical_offer", isinstance(offer,Offer) and offer.total_amount_minor>0 and len(offer.currency)==3, "canonical model"))
            pb=await check("prebook",connector.prebook(offer),lambda x:x.offer_id==offer.offer_id and x.total_amount_minor==offer.total_amount_minor)
            if pb:
                k="certification-idempotency-key"; c1=await check("book",connector.book("ord_cert",pb,idempotency_key=k),lambda x:bool(x)); c2=await check("book_idempotency",connector.book("ord_cert",pb,idempotency_key=k),lambda x:bool(x))
                checks[-1].passed = checks[-1].passed and c1==c2; checks[-1].detail = "same confirmation" if c1==c2 else "confirmation mismatch"
                if c1: await check("status",connector.status(c1),lambda x:x in {"CONFIRMED","CANCELLED","NOT_FOUND","PENDING"})
        return CertificationReport(connector.metadata.connector_id, all(c.passed for c in checks), checks)

harness=ConnectorCertificationHarness()
