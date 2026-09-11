from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"ANCHOR_MISMATCH:{path}:{count}:{old[:80]}")
    path.write_text(text.replace(old, new, 1))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--source', required=True, type=Path)
    a = p.parse_args()
    root = a.source

    base = root / 'src/go_hotel/connectors/base.py'
    replace_once(base,
        '    hard_inventory_hold: bool = False\n    provider_price_lock: bool = True',
        '    hard_inventory_hold: bool = False\n    hard_hold_release: bool = False\n    idempotent_hard_hold_release: bool = False\n    provider_price_lock: bool = True')
    replace_once(base,
        '    async def cancel(self, confirmation_no: str) -> str: ...\n    async def change(',
        '    async def cancel(self, confirmation_no: str) -> str: ...\n    async def release_prebook_hold(self, prebook_id: str, idempotency_key: str) -> str: ...\n    async def lookup_prebook_hold(self, prebook_id: str, idempotency_key: str) -> str: ...\n    async def change(')

    mock = root / 'src/go_hotel/connectors/mock_hotel.py'
    replace_once(mock,
        'metadata = ConnectorMetadata(connector_id=connector_id, display_name="GO Mock Hotel", version="1.0", capabilities=ConnectorCapabilities(webhooks=True))',
        'metadata = ConnectorMetadata(connector_id=connector_id, display_name="GO Mock Hotel", version="1.0", capabilities=ConnectorCapabilities(webhooks=True, hard_inventory_hold=True, hard_hold_release=True, idempotent_hard_hold_release=True))')
    replace_once(mock,
        '        self._prebooks: dict[str, Prebook] = {}\n        self.prebook_price_delta_minor = 0',
        '        self._prebooks: dict[str, Prebook] = {}\n        self._hard_hold_releases: dict[str, str] = {}\n        self.release_hold_calls = 0\n        self.ambiguous_release_hold = False\n        self.prebook_price_delta_minor = 0')
    replace_once(mock,
        '        self._rejected_bookings.clear(); self._prebooks.clear()\n        self.book_calls = 0;',
        '        self._rejected_bookings.clear(); self._prebooks.clear(); self._hard_hold_releases.clear(); self.release_hold_calls=0; self.ambiguous_release_hold=False\n        self.book_calls = 0;')
    replace_once(mock,
        '    async def status(self, confirmation_no: str) -> str: return "CANCELLED" if confirmation_no in self._cancelled else "CONFIRMED" if confirmation_no in self._known_confirmations else "NOT_FOUND"',
        '''    async def release_prebook_hold(self, prebook_id: str, idempotency_key: str) -> str:\n        if idempotency_key in self._hard_hold_releases:\n            old = self._hard_hold_releases[idempotency_key]\n            if old != prebook_id: raise ValueError("SUPPLIER_HARD_HOLD_RELEASE_KEY_CONFLICT")\n            return "RELEASED"\n        self.release_hold_calls += 1\n        if self.ambiguous_release_hold:\n            raise TimeoutError("SUPPLIER_HARD_HOLD_RELEASE_UNKNOWN")\n        self._hard_hold_releases[idempotency_key] = prebook_id\n        return "RELEASED"\n\n    async def lookup_prebook_hold(self, prebook_id: str, idempotency_key: str) -> str:\n        return "RELEASED" if self._hard_hold_releases.get(idempotency_key) == prebook_id else "UNKNOWN"\n\n    async def status(self, confirmation_no: str) -> str: return "CANCELLED" if confirmation_no in self._cancelled else "CONFIRMED" if confirmation_no in self._known_confirmations else "NOT_FOUND"''')

    expiry = root / 'src/go_hotel/services/vertical_reservation_expiry.py'
    replace_once(expiry,
        '    RailOrderRow, AttractionOrderRow,\n)',
        '    RailOrderRow, AttractionOrderRow, MobilityRideOrderRow, MobilityRentalOrderRow,\n)')
    replace_once(expiry,
        "MODELS = {'RAIL': RailOrderRow, 'ATTRACTION': AttractionOrderRow}",
        "MODELS = {'RAIL': RailOrderRow, 'ATTRACTION': AttractionOrderRow, 'RIDE': MobilityRideOrderRow, 'RENTAL': MobilityRentalOrderRow}")
    replace_once(expiry,
        "        from go_hotel.db.models import VerticalCapacityClaimRow as Claim\n        claims = list(s.scalars(select(Claim).where(Claim.vertical == vertical,\n            Claim.order_id == order_id, Claim.state == 'ALLOCATED')))\n        quantity = len(order.passengers or []) if vertical == 'RAIL' else order.quantity\n        if len(claims) != 1 or claims[0].slot != 'ORIGINAL' or claims[0].quantity != quantity:\n            finish_in(s, row, 'REVIEW', 'CAPACITY_CLAIM_REQUIRES_RECONCILIATION')\n            return 'REVIEW'\n        from go_hotel.services.vertical_capacity import release_all_in\n        from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence\n        from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle\n        release_all_in(s, vertical, order_id)\n        order.status = 'CANCELLED'",
        "        from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence\n        from go_hotel.services.vertical_lifecycle_projection import project_vertical_lifecycle\n        capacity_released = False\n        if vertical in {'RAIL', 'ATTRACTION'}:\n            from go_hotel.db.models import VerticalCapacityClaimRow as Claim\n            claims = list(s.scalars(select(Claim).where(Claim.vertical == vertical,\n                Claim.order_id == order_id, Claim.state == 'ALLOCATED')))\n            quantity = len(order.passengers or []) if vertical == 'RAIL' else order.quantity\n            if len(claims) != 1 or claims[0].slot != 'ORIGINAL' or claims[0].quantity != quantity:\n                finish_in(s, row, 'REVIEW', 'CAPACITY_CLAIM_REQUIRES_RECONCILIATION')\n                return 'REVIEW'\n            from go_hotel.services.vertical_capacity import release_all_in\n            release_all_in(s, vertical, order_id)\n            capacity_released = True\n        elif getattr(order, 'supplier_reference', None):\n            finish_in(s, row, 'REVIEW', 'MOBILITY_SUPPLIER_REFERENCE_REQUIRES_RECONCILIATION')\n            return 'REVIEW'\n        order.status = 'CANCELLED'")
    replace_once(expiry,
        "facts = {'unpaid': True, 'capacity_released': True, 'payment_deadline_ms': row.expires_ms,",
        "facts = {'unpaid': True, 'capacity_released': capacity_released, 'payment_deadline_ms': row.expires_ms,")

    ride = root / 'src/go_hotel/mobility/ride/service.py'
    replace_once(ride,
        '            s.add(o); s.flush()\n            append_vertical_evidence(s, "RIDE", o.order_id, "ORDER_CREATED", o.status,',
        '            s.add(o); s.flush()\n            from go_hotel.services.vertical_reservation_expiry import issue_in\n            issue_in(s, "RIDE", o)\n            append_vertical_evidence(s, "RIDE", o.order_id, "ORDER_CREATED", o.status,')
    replace_once(ride,
        '                "supplier_reference": o.supplier_reference if o.status in {"CONFIRMED","IN_PROGRESS"} else None, "external_live": False}',
        '                "supplier_reference": o.supplier_reference if o.status in {"CONFIRMED","IN_PROGRESS"} else None,\n                **__import__("go_hotel.services.vertical_reservation_expiry", fromlist=["projection"]).projection("RIDE", o), "external_live": False}')

    rental = root / 'src/go_hotel/mobility/rental/service.py'
    replace_once(rental,
        '            s.add(o); s.flush()\n            append_vertical_evidence(s, "RENTAL", o.order_id, "ORDER_CREATED", o.status, {',
        '            s.add(o); s.flush()\n            from go_hotel.services.vertical_reservation_expiry import issue_in\n            issue_in(s, "RENTAL", o)\n            append_vertical_evidence(s, "RENTAL", o.order_id, "ORDER_CREATED", o.status, {')
    replace_once(rental,
        '                "supplier_reference": o.supplier_reference if o.status in {"CONFIRMED","IN_PROGRESS"} else None, "external_live": False}',
        '                "supplier_reference": o.supplier_reference if o.status in {"CONFIRMED","IN_PROGRESS"} else None,\n                **__import__("go_hotel.services.vertical_reservation_expiry", fromlist=["projection"]).projection("RENTAL", o), "external_live": False}')

    bridge = root / 'src/go_hotel/services/vertical_transaction_bridge.py'
    replace_once(bridge,
        "    def checkout_contract(self, vertical:str, order_id:str, account_id:str, source_id:str, evidence_reference:str, payment_method_id:str|None=None):\n        if _prod(): raise ValueError('EXTERNAL_PAYMENT_EXECUTOR_REQUIRED')",
        "    def checkout_contract(self, vertical:str, order_id:str, account_id:str, source_id:str, evidence_reference:str, payment_method_id:str|None=None):\n        if _prod(): raise ValueError('EXTERNAL_PAYMENT_EXECUTOR_REQUIRED')\n        if vertical in {'RIDE','RENTAL'}:\n            from go_hotel.services.vertical_reservation_expiry import guard_checkout_payment\n            guard_checkout_payment(vertical, order_id, account_id)")
    replace_once(bridge,
        "        if i is None:\n            i=omnichannel_payment_service.create_intent({'business_type':BTYPE[vertical],'business_id':order_id,'channel_priority':['LOCAL_MARKET']},f'{vertical.lower()}-checkout:{order_id}',account_id)\n        if i['state']=='UNKNOWN_EXTERNAL_STATE'",
        "        if i is None:\n            i=omnichannel_payment_service.create_intent({'business_type':BTYPE[vertical],'business_id':order_id,'channel_priority':['LOCAL_MARKET']},f'{vertical.lower()}-checkout:{order_id}',account_id)\n        if vertical in {'RIDE','RENTAL'}:\n            from go_hotel.services.vertical_reservation_expiry import payment_started\n            payment_started(vertical, order_id, account_id)\n        if i['state']=='UNKNOWN_EXTERNAL_STATE'")

    # Add native payment helpers after payment_started_in so the order lock and deadline
    # state serialize checkout against expiry, with a second post-intent barrier.
    replace_once(expiry,
        "def cancelled_in(s, vertical, order):",
        '''def guard_checkout_payment(vertical, order_id, account_id):\n    if vertical not in {'RIDE','RENTAL'}: return\n    with transaction(SessionLocal) as s:\n        order = s.get(MODELS[vertical], order_id, with_for_update=True)\n        if not order or order.account_id != account_id: raise ValueError('MOBILITY_ORDER_NOT_FOUND')\n        if order.status != 'PAYMENT_PENDING': raise ValueError('MOBILITY_ORDER_NOT_PAYABLE')\n        guard_payment_in(s, vertical, order)\n\n\ndef payment_started(vertical, order_id, account_id):\n    if vertical not in {'RIDE','RENTAL'}: return\n    with transaction(SessionLocal) as s:\n        order = s.get(MODELS[vertical], order_id, with_for_update=True)\n        if not order or order.account_id != account_id: raise ValueError('MOBILITY_ORDER_NOT_FOUND')\n        if order.status != 'PAYMENT_PENDING': raise ValueError('MOBILITY_ORDER_NOT_PAYABLE')\n        row = checked_in(s, vertical, order)\n        if not row: raise ValueError('PAYMENT_DEADLINE_ROOT_REQUIRED')\n        if row.state in {'CANCELLED','EXPIRED','REVIEW'}: raise ValueError('RESERVATION_' + row.state + '_NOT_PAYABLE')\n        if not payment_in(s, vertical, order_id): raise ValueError('PAYMENT_DEADLINE_ROOT_REQUIRED')\n        if row.state == 'OPEN': finish_in(s, row, 'PAYMENT_STARTED', 'PAYMENT_INTENT_COMMITTED')\n\n\ndef cancelled_in(s, vertical, order):''')

    lifecycle = root / 'src/go_hotel/agent_gateway/lifecycle_core.py'
    replace_once(lifecycle,
        "            if pb.inventory_held: raise ValueError(\"HOTEL_HARD_HOLD_RELEASE_REQUIRES_CONNECTOR_RELEASE\")\n                o.status = \"CANCELLED\";",
        "            if pb.inventory_held:\n                    from go_hotel.services.hotel_hard_hold_release import release_locked\n                    return await release_locked(s, o, pb, account, oid)\n                o.status = \"CANCELLED\";")
    replace_once(lifecycle,
        "            elif vertical in {\"HOTEL\", \"FLIGHT\"}:\n                state = await self._expire_prebook_deadline(account, vertical, oid)\n            else:\n                raise ValueError(\"AGENT_EXPIRE_NATIVE_DEADLINE_REQUIRED:\" + vertical)",
        "            elif vertical in {\"HOTEL\", \"FLIGHT\"}:\n                state = await self._expire_prebook_deadline(account, vertical, oid)\n            elif vertical in {\"RIDE\", \"RENTAL\"}:\n                from go_hotel.services.vertical_reservation_expiry import expire_one\n                state = expire_one(vertical, oid)\n            else:\n                raise ValueError(\"AGENT_EXPIRE_NATIVE_DEADLINE_REQUIRED:\" + vertical)")

    hotel_release = root / 'src/go_hotel/services/hotel_hard_hold_release.py'
    hotel_release.write_text('''from __future__ import annotations\n\nfrom go_hotel.connectors.registry import registry\nfrom go_hotel.domain.models import Event, new_id, now_utc\nfrom go_hotel.repositories.sql import repo\n\n\nasync def release_locked(session, order_row, prebook_row, account_id: str, order_id: str):\n    \"\"\"Release a connector-native hard prebook hold before local cancellation.\n\n    Caller owns the native hotel order row lock. The connector must advertise an\n    idempotent hard-hold release contract. An ambiguous result is reconciled by\n    connector lookup; UNKNOWN never becomes a local cancellation.\n    \"\"\"\n    offer = repo.get_offer(prebook_row.offer_id)\n    if not offer or not offer.connector_id: raise ValueError('HOTEL_HARD_HOLD_CONNECTOR_REQUIRED')\n    connector = registry.get(offer.connector_id)\n    caps = connector.metadata.capabilities\n    if not (caps.hard_inventory_hold and caps.hard_hold_release and caps.idempotent_hard_hold_release):\n        raise ValueError('HOTEL_HARD_HOLD_CONNECTOR_RELEASE_NOT_CERTIFIED')\n    key = 'agent-hard-hold-release:' + order_id\n    try:\n        result = await connector.release_prebook_hold(prebook_row.prebook_id, key)\n    except TimeoutError:\n        result = await connector.lookup_prebook_hold(prebook_row.prebook_id, key)\n    if result != 'RELEASED':\n        raise ValueError('HOTEL_HARD_HOLD_RELEASE_RECONCILIATION_REQUIRED')\n    order_row.status = 'CANCELLED'; order_row.version += 1; order_row.updated_at = now_utc()\n    repo._append_event_and_outbox(session, Event(new_id('evt'), 'UNPAID_ORDER_CANCELLED', 'HOTEL_ORDER', order_id,\n        {'account_id': account_id, 'inventory_held': True, 'hold_type': prebook_row.hold_type,\n         'connector_id': offer.connector_id, 'connector_hold_release': 'RELEASED', 'release': 'AGENT'}))\n    session.flush()\n    return {'order_id': order_id, 'status': 'CANCELLED', 'connector_hold_release': 'RELEASED',\n            'connector_id': offer.connector_id, 'prebook_id': prebook_row.prebook_id}\n''')

    print('DEPTH39_NATIVE_CLOSURE_APPLIED=PASS')


if __name__ == '__main__':
    main()
