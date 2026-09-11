from __future__ import annotations

from dataclasses import replace
from datetime import datetime,timezone
from typing import Any

from .contracts import OfferRequest,ReserveRequest
from .real_core import GoTransactionCore as _GoTransactionCore,_digest,_jsonable,_parse_ref

IGNORED_QUOTE_FIELDS={'external_live','data_mode'}

def _stable(value:Any)->Any:
    value=_jsonable(value)
    if isinstance(value,dict):
        return {k:_stable(v) for k,v in sorted(value.items()) if k not in IGNORED_QUOTE_FIELDS}
    if isinstance(value,list):return [_stable(v) for v in value]
    if isinstance(value,str) and 'T' in value:
        try:
            dt=datetime.fromisoformat(value.replace('Z','+00:00'))
            if dt.tzinfo is not None:dt=dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt.isoformat()
        except ValueError:pass
    return value

class GoTransactionCore(_GoTransactionCore):
    """Canonical semantic quote identity over native GO services."""

    def _offer(self,vertical,raw,search):
        offer=super()._offer(vertical,raw,search)
        qh=_digest({'vertical':vertical,'raw_offer':_stable(raw),'search':_stable(search)})
        return replace(offer,quote_hash=qh,inventory_version=qh)

    async def _assert_quote(self,ctx,req:ReserveRequest):
        vertical,raw_id=_parse_ref(req.offer_id);search=dict(req.search)
        if vertical=='HOTEL':
            from go_hotel.repositories.sql import repo
            raw=repo.get_offer(raw_id)
            if not raw:raise ValueError('OFFER_NOT_FOUND')
            current=self._offer(vertical,raw,search)
        elif vertical=='FLIGHT':
            from go_hotel.flight.service import flight_service
            current=self._offer(vertical,flight_service.get_offer(raw_id),search)
        elif vertical=='RAIL':
            from go_hotel.rail.service import rail_service
            current=self._offer(vertical,rail_service.get_offer(raw_id),search)
        else:
            current=next((o for o in await self.find_offers(ctx,OfferRequest(vertical,search)) if o.offer_id==req.offer_id),None)
            if current is None:raise ValueError('OFFER_NOT_FOUND')
        if current.quote_hash!=req.quote_hash:raise ValueError('OFFER_CHANGED_RECONFIRM_REQUIRED')
        if not current.machine_bookable:raise ValueError('OFFER_NOT_MACHINE_BOOKABLE')
        return vertical,raw_id,current
