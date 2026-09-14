"""Read-only rental refund diagnosis. Findings never repair money or order state."""
from collections import Counter
from types import SimpleNamespace
from sqlalchemy import select
from go_hotel.db.models import (MobilityRentalOrderRow as Order, MobilityRefundRow as Refund,
    OmnichannelMoneyMovementRow as Movement)
from go_hotel.db.session import SessionLocal
from go_hotel.mobility.rental.changes import adjustment_ids
from go_hotel.services import mobility_refund_consent as consent
from go_hotel.services.vertical_refund_recovery import _confirmed_money_in


def inspect_refund(account, order_id, refund_id):
    with SessionLocal() as session, session.no_autoflush:
        order = session.get(Order, order_id)
        refund = session.get(Refund, refund_id)
        if (not order or order.account_id != account or not refund
                or refund.order_id != order_id or refund.vertical != 'RENTAL'):
            raise ValueError('RENTAL_REFUND_NOT_FOUND')
        findings, ids, plan_proven, money_confirmed = [], [], False, False
        try:
            records = consent.records(session, order, 'RENTAL')
            if not records:
                findings.append('FROZEN_CONSENT_UNAVAILABLE')
            else:
                consent.existing(session, order, refund, None, 'RENTAL')
                plan_proven = True
        except ValueError as error:
            findings.append(str(error))
        plan = refund.settlement_plan_json
        valid_plan = (isinstance(plan, list) and bool(plan) and all(
            isinstance(item, dict) and all(key in item for key in ('payment_intent_id', 'capture_id', 'amount_minor', 'key'))
            and type(item['amount_minor']) is int and item['amount_minor'] > 0
            and all(isinstance(item[key], str) and item[key] for key in ('payment_intent_id', 'capture_id', 'key'))
            for item in plan))
        if not valid_plan:
            findings.append('FROZEN_PLAN_UNAVAILABLE_OR_INVALID')
            plan_proven = False
        elif plan_proven:
            receipts = []
            for item in plan:
                matches = list(session.scalars(select(Movement).where(
                    Movement.root_payment_intent_id == item['payment_intent_id'],
                    Movement.idempotency_key == item['key'])))
                if len(matches) != 1:
                    findings.append('FROZEN_PLAN_RECEIPT_MISSING_OR_AMBIGUOUS')
                else:
                    receipts.extend(matches)
            expected = Counter((item['payment_intent_id'], item['capture_id'], item['amount_minor'], item['key']) for item in plan)
            observed = Counter((row.root_payment_intent_id, row.parent_movement_id, row.amount_minor, row.idempotency_key) for row in receipts)
            if len(receipts) == len(plan) and expected == observed:
                try:
                    ids = _confirmed_money_in(session, SimpleNamespace(vertical='RENTAL', order_id=order_id,
                        account_id=account, adjustment_ids_json=adjustment_ids(session, order_id),
                        quote_json={'currency': refund.currency, 'refund_amount_minor': refund.refund_amount_minor}),
                        {'money_movement_ids': [row.money_movement_id for row in receipts]})
                    money_confirmed = True
                except ValueError as error:
                    findings.append(str(error))
            else:
                findings.append('REFUND_RECEIPT_PLAN_MISMATCH')
        if refund.status == 'REFUND_COMPLETED' and order.status != 'REFUNDED':
            findings.append('COMPLETED_REFUND_ORDER_STATE_MISMATCH')
        if refund.status == 'REFUND_PENDING' and order.status != 'REFUND_PENDING':
            findings.append('PENDING_REFUND_ORDER_STATE_MISMATCH')
        if not plan_proven:
            status, next_action = 'UNPROVEN_HISTORICAL', 'OBTAIN_FROZEN_PLAN_AND_CONSENT_EVIDENCE'
        elif refund.status == 'REFUND_COMPLETED' and order.status == 'REFUNDED' and money_confirmed and not findings:
            status, next_action = 'MATCHED_COMPLETED', 'NONE'
        elif refund.status == 'REFUND_PENDING' and order.status == 'REFUND_PENDING' and money_confirmed and not findings:
            status, next_action = 'MONEY_CONFIRMED_ORDER_PENDING', 'REVIEW_EXISTING_REFUND_COMPLETION_PATH'
        elif refund.status == 'REFUND_PENDING' and order.status == 'REFUND_PENDING' and not money_confirmed:
            status, next_action = 'PENDING_MONEY', 'RECONCILE_FROZEN_PLAN_RECEIPTS'
        else:
            status, next_action = 'CONTRADICTION', 'REVIEW_ORDER_AND_REFUND_STATE_AGAINST_LEDGER'
        return {'order_id': order_id, 'refund_id': refund_id, 'status': status,
            'order_status': order.status, 'refund_status': refund.status,
            'plan_proven': plan_proven, 'money_confirmed': money_confirmed,
            'confirmed_movement_ids': ids, 'findings': sorted(set(findings)),
            'next_action': next_action, 'read_only': True, 'automatic_repair': False}
