from __future__ import annotations

from .contracts import OfferRequest,ReserveRequest
from .real_core import GoTransactionCore as _GoTransactionCore,_parse_ref


class GoTransactionCore(_GoTransactionCore):
    """Corrected canonical core facade for DEPTH37.

    Some native read projections intentionally omit non-transaction metadata that
    search projections include. Quote verification normalizes that difference
    before hashing; material price/inventory/terms fields remain fail-closed.
    """

    async def _assert_quote(self,ctx,req:ReserveRequest):
        vertical,raw_id=_parse_ref(req.offer_id);search=dict(req.search)
        if vertical=="HOTEL":
            from go_hotel.repositories.sql import repo
            raw=repo.get_offer(raw_id)
            if not raw:raise ValueError("OFFER_NOT_FOUND")
            current=self._offer(vertical,raw,search)
        elif vertical=="FLIGHT":
            from go_hotel.flight.service import flight_service
            current=self._offer(vertical,flight_service.get_offer(raw_id),search)
        elif vertical=="RAIL":
            from go_hotel.rail.service import rail_service
            raw=rail_service.get_offer(raw_id)
            raw.setdefault("external_live",False)
            current=self._offer(vertical,raw,search)
        else:
            current=next((o for o in await self.find_offers(ctx,OfferRequest(vertical,search)) if o.offer_id==req.offer_id),None)
            if current is None:raise ValueError("OFFER_NOT_FOUND")
        if current.quote_hash!=req.quote_hash:raise ValueError("OFFER_CHANGED_RECONFIRM_REQUIRED")
        if not current.machine_bookable:raise ValueError("OFFER_NOT_MACHINE_BOOKABLE")
        return vertical,raw_id,current
