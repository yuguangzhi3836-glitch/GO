"""Read-only cross-vertical order facts, scoped by durable supplier identity.

This projection never mutates ownership, orders or money. The payment root,
frozen fact binding and source decision must agree before a non-hotel order
is visible to a supplier. The root payment ledger is explicitly scoped; it
is not a statement about bank settlement or unrelated adjustment payments.
"""
from sqlalchemy import select, union_all, literal, func
from go_hotel.db.session import SessionLocal
from go_hotel.db import models as m

ORDERS = {'HOTEL': m.OrderRow, 'FLIGHT': m.FlightOrderRow,
          'RAIL': m.RailOrderRow, 'RIDE': m.MobilityRideOrderRow,
          'RENTAL': m.MobilityRentalOrderRow, 'ATTRACTION': m.AttractionOrderRow}
REFUNDS = {'HOTEL': m.RefundRow, 'FLIGHT': m.FlightRefundRow,
           'RAIL': m.RailRefundRow, 'RIDE': m.MobilityRefundRow,
           'RENTAL': m.MobilityRefundRow, 'ATTRACTION': m.AttractionRefundRow}
F, R, I, D = (m.PaymentOrderFactBindingRow, m.PaymentOrderRootRow,
              m.OmnichannelPaymentIntentRow, m.VerticalSourceDecisionRow)


def supplier_query(vertical, supplier_id):
    model = ORDERS[vertical]
    if vertical == 'HOTEL':
        return select(model).where(model.supplier_id == supplier_id)
    return (select(model).join(R, (R.business_id == model.order_id) &
            (R.business_type == vertical + '_ORDER'))
        .join(I, (I.payment_intent_id == R.payment_intent_id) &
              (I.business_id == model.order_id) & (I.business_type == R.business_type))
        .join(F, (F.payment_intent_id == I.payment_intent_id) &
              (F.business_id == model.order_id) & (F.business_type == R.business_type))
        .join(D, D.vertical_source_decision_id == F.source_decision_id)
        .where(I.payee_id == supplier_id, F.payee_id == supplier_id,
               I.payer_id == model.account_id, F.payer_id == model.account_id,
               I.currency == model.currency, F.currency == model.currency,
               F.amount_minor == I.amount_minor,
               D.vertical == vertical, D.business_id == model.order_id,
               D.selected_source_id == supplier_id, D.evidence_reference != '',
               F.evidence_reference != ''))


def summary(vertical, row):
    return {'order_id': row.order_id, 'vertical': vertical, 'status': row.status,
            'total_amount_minor': row.total_amount_minor, 'currency': row.currency,
            'updated_at': row.updated_at.isoformat()}


def supplier_orders(supplier_id, limit=50, offset=0, vertical=None):
    if vertical is not None and vertical not in ORDERS:raise ValueError('ORDER_VERTICAL_INVALID')
    if not supplier_id:
        return {'items': [], 'count': 0, 'limit': limit, 'offset': offset}
    # Filter tenant identity in SQL before global ordering/pagination.
    queries = [supplier_query(v, supplier_id).with_only_columns(
        literal(v).label('vertical'), model.order_id.label('order_id'),
        model.updated_at.label('updated_at')) for v, model in ORDERS.items() if vertical is None or v==vertical]
    combined = union_all(*queries).subquery()
    with SessionLocal() as s:
        keys = s.execute(select(combined).order_by(combined.c.updated_at.desc(),
            combined.c.vertical, combined.c.order_id).offset(offset).limit(limit)).all()
        items = [summary(x.vertical, s.get(ORDERS[x.vertical], x.order_id)) for x in keys]
        return {'items': items, 'count': len(items), 'limit': limit, 'offset': offset}


def refund_query(vertical, supplier_id):
    model = REFUNDS[vertical]
    ids = supplier_query(vertical, supplier_id).with_only_columns(ORDERS[vertical].order_id)
    query = select(model).where(model.order_id.in_(ids))
    if vertical in {'RIDE', 'RENTAL'}:
        query = query.where(model.vertical == vertical)
    return query


def supplier_counts(supplier_id):
    orders, refunds = {}, {}
    if not supplier_id:
        return orders, refunds
    with SessionLocal() as s:
        for v in ORDERS:
            for model, query, counts in ((ORDERS[v], supplier_query(v,supplier_id), orders),
                                         (REFUNDS[v], refund_query(v,supplier_id), refunds)):
                for status, count in s.execute(query.with_only_columns(model.status,func.count()).group_by(model.status)):
                    counts[status] = counts.get(status,0) + count
    return orders, refunds


def supplier_refunds(supplier_id, status=None, limit=50, offset=0):
    if not supplier_id:
        return {'items': [], 'count': 0, 'limit': limit, 'offset': offset}
    queries=[]
    for v,model in REFUNDS.items():
        q=refund_query(v,supplier_id)
        if status:
            q=q.where(model.status==status)
        amount=model.amount_minor if v=='HOTEL' else model.refund_amount_minor
        queries.append(q.with_only_columns(model.refund_id,model.order_id,literal(v).label('vertical'),
            amount.label('amount_minor'),model.currency,model.status,model.created_at))
    rows=union_all(*queries).subquery()
    with SessionLocal() as s:
        items=[dict(x) for x in s.execute(select(rows).order_by(rows.c.created_at.desc(),
            rows.c.vertical,rows.c.refund_id).offset(offset).limit(limit)).mappings()]
        return {'items':items,'count':len(items),'limit':limit,'offset':offset}


def snapshot(vertical, order_id, *, supplier_id=None, account_id=None, admin=False):
    if vertical not in ORDERS or not (supplier_id or account_id or admin):
        raise ValueError('ORDER_NOT_FOUND')
    with SessionLocal() as s:
        model = ORDERS[vertical]
        query = supplier_query(vertical, supplier_id) if supplier_id else select(model)
        query = query.where(model.order_id == order_id)
        if account_id:
            query = query.where(model.account_id == account_id)
        order = s.scalar(query)
        if order is None:
            raise ValueError('ORDER_NOT_FOUND')
        refund_model = REFUNDS[vertical]
        rq = select(refund_model).where(refund_model.order_id == order_id)
        if vertical in {'RIDE', 'RENTAL'}:
            rq = rq.where(refund_model.vertical == vertical)
        refunds = [{'refund_id': x.refund_id, 'order_id': order_id,
                    'amount_minor': x.amount_minor if vertical == 'HOTEL' else x.refund_amount_minor,
                    'currency': x.currency, 'status': x.status}
                   for x in s.scalars(rq.order_by(refund_model.created_at, refund_model.refund_id))]
        root = s.scalar(select(R).where(R.business_type == vertical + '_ORDER', R.business_id == order_id))
        intent = s.get(I, root.payment_intent_id) if root else None
        fact = s.scalar(select(F).where(F.payment_intent_id == root.payment_intent_id)) if root else None
        valid = bool(intent and fact and intent.business_id == order_id and
            fact.business_id == order_id and intent.business_type == vertical + '_ORDER' and
            fact.business_type == intent.business_type and intent.payer_id == order.account_id and
            fact.payer_id == intent.payer_id and fact.payee_id == intent.payee_id and
            fact.currency == intent.currency == order.currency and fact.amount_minor == intent.amount_minor)
        if vertical == 'HOTEL' and valid:
            valid = intent.payee_id == order.supplier_id
        moves, ledger = [], []
        if valid:
            moves = list(s.scalars(select(m.OmnichannelMoneyMovementRow).where(
                m.OmnichannelMoneyMovementRow.root_payment_intent_id == root.payment_intent_id)))
            ledger = list(s.scalars(select(m.OmnichannelLedgerEntryRow).where(
                m.OmnichannelLedgerEntryRow.payment_intent_id == root.payment_intent_id)))
        movements = [{'movement_id': x.money_movement_id, 'parent_movement_id': x.parent_movement_id,
                      'type': x.movement_type, 'amount_minor': x.amount_minor,
                      'currency': x.currency, 'state': x.state} for x in moves]
        confirmed = [x for x in moves if x.state == 'CONFIRMED']
        captured = sum(x.amount_minor for x in confirmed if x.movement_type == 'CAPTURE')
        refunded = sum(x.amount_minor for x in confirmed if x.movement_type == 'REFUND')
        debit = sum(x.amount_minor for x in ledger if x.direction == 'DEBIT')
        credit = sum(x.amount_minor for x in ledger if x.direction == 'CREDIT')
        # Equal totals alone can hide a missing pair, wrong currency or an
        # uncertain movement. Check each actual posted financial movement.
        balanced = bool(ledger) and debit == credit and valid and intent.state == 'SUCCEEDED'
        balanced = balanced and all(x.currency == order.currency and x.state == 'CONFIRMED' for x in moves)
        balanced = balanced and all(x.currency == order.currency for x in ledger)
        for movement in [x for x in confirmed if x.movement_type not in {'AUTHORIZATION', 'RELEASE'}]:
            entries = [x for x in ledger if x.transaction_id == movement.money_movement_id]
            balanced = balanced and len(entries) == 2 and {x.direction for x in entries} == {'DEBIT', 'CREDIT'}
            balanced = balanced and all((x.amount_minor, x.currency, x.entry_type) ==
                (movement.amount_minor, movement.currency, movement.movement_type) for x in entries)
        from go_hotel.services.catalog_cash_trip_projection import read as cash_trip
        return {'order': summary(vertical, order), 'refunds': refunds,
                'cash_after_sales': cash_trip(s, order) if vertical == 'HOTEL' else None,
                'original_payment': {'payment_intent_id': intent.payment_intent_id if valid else None,
                    'binding_state': 'BOUND' if valid else 'RECONCILIATION_REQUIRED',
                    'state': intent.state if valid else 'UNKNOWN', 'captured_minor': captured,
                    'refunded_minor': refunded, 'net_minor': captured - refunded,
                    'currency': order.currency, 'capture_count': sum(x.movement_type == 'CAPTURE' for x in confirmed),
                    'refund_count': sum(x.movement_type == 'REFUND' for x in confirmed),
                    'ledger_debit_minor': debit, 'ledger_credit_minor': credit,
                    'ledger_entries': len(ledger), 'ledger_balanced': bool(balanced),
                    'reconciliation_required': not balanced},
                'movements': movements, 'scope': 'ORIGINAL_PAYMENT_ROOT',
                'bank_settlement_verified': False}
