"""Trace accepted cash-change forfeiture into immutable original-capture budgets."""
from sqlalchemy import select
from go_hotel.db.models import OrderChangeRow, CatalogCashFareOperationRow as Operation
from go_hotel.services.catalog_cash_fare import lock as lock_cash_operation
from go_hotel.services.omnichannel_payment import digest


def forfeiture_evidence(s, order, cash):
    evidence=[]
    for change in s.scalars(select(OrderChangeRow).where(OrderChangeRow.order_id==order.order_id,
        OrderChangeRow.status=='CONFIRMED').order_by(OrderChangeRow.confirmed_at,OrderChangeRow.change_id)):
        op=s.scalar(select(Operation).where(Operation.quote_id==change.quote_id))
        if not op: continue  # A legacy missing operation can never contribute proved forfeiture.
        _,op,q=lock_cash_operation(s,op.operation_id)
        amount=q.get('lower_price_difference_minor',0)
        if not amount:continue
        if op.state!='COMPLETED' or q.get('lower_price_rule')!='FORFEIT_NO_REFUND_NO_FUTURE_OFFSET':
            raise ValueError('ACCEPTED_CASH_CHANGE_FORFEITURE_REQUIRED')
        evidence.append({'operation_id':op.operation_id,'plan_hash':op.plan_hash,
            'quote_hash':op.plan_json['quote_hash'],'amount_minor':amount})
    if sum(x['amount_minor'] for x in evidence)!=cash['forfeited_change_value_minor']:
        raise ValueError('HISTORICAL_FORFEITURE_ALLOCATION_RECONCILIATION_REQUIRED')
    return evidence


def split_sources(s, order, cash):
    """Retain FIFO source value and permanently exclude the residual forfeiture.

    Zero-funded captures remain reserved: excluded money must not become an
    unclaimed source that can be refunded through another entry point.
    """
    evidence=forfeiture_evidence(s,order,cash)
    excluded=cash['forfeited_change_value_minor']
    available=sum(x['amount_minor'] for x in cash['available_refund_lines'])
    retained=available-excluded
    if retained<=0:raise ValueError('FUNDED_POSITIVE_CREDIT_REQUIRED')
    remaining=retained;lines=[]
    for source in cash['available_refund_lines']:
        funded=min(remaining,source['amount_minor']);remaining-=funded
        lines.append({**source,'amount_minor':funded,'excluded_minor':source['amount_minor']-funded})
    if remaining or sum(x['excluded_minor'] for x in lines)!=excluded:
        raise ValueError('FORFEITURE_SOURCE_ALLOCATION_MISMATCH')
    return lines,{'version':'CASH_CHANGE_FORFEITURE_V1','gross_paid_minor':cash['gross_paid_minor'],
        'prior_refund_minor':cash['prior_refund_minor'],'excluded_minor':excluded,'retained_minor':retained,
        'accepted_changes':evidence,'evidence_hash':digest(evidence),'allocation_order':'ORIGINAL_CAPTURE_FIFO'}


def check_evidence(s, contract):
    proof=contract.get('cash_change_forfeiture')
    if not proof:return
    evidence=proof['accepted_changes']
    if proof.get('version')!='CASH_CHANGE_FORFEITURE_V1' or digest(evidence)!=proof['evidence_hash']:
        raise ValueError('CREDIT_FORFEITURE_EVIDENCE_MISMATCH')
    if len({x['operation_id'] for x in evidence})!=len(evidence):
        raise ValueError('CREDIT_FORFEITURE_EVIDENCE_DUPLICATED')
    for item in evidence:
        order,op,q=lock_cash_operation(s,item['operation_id'])
        if (order.order_id,op.state,op.plan_hash,op.plan_json['quote_hash'],q.get('lower_price_difference_minor'),q.get('lower_price_rule'))!=(
            contract['order_id'],'COMPLETED',item['plan_hash'],item['quote_hash'],item['amount_minor'],'FORFEIT_NO_REFUND_NO_FUTURE_OFFSET'):
            raise ValueError('CREDIT_FORFEITURE_ORIGIN_CHANGED')
    if (sum(x['amount_minor'] for x in evidence)!=proof['excluded_minor'] or
        sum(x.get('excluded_minor',0) for x in contract['sources'])!=proof['excluded_minor'] or
        proof['gross_paid_minor']-proof['prior_refund_minor']-proof['excluded_minor']!=proof['retained_minor'] or
        proof['retained_minor']!=contract['credit_value_minor']):
        raise ValueError('CREDIT_FORFEITURE_VALUE_MISMATCH')
