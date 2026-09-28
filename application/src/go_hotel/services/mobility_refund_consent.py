"""Persist accepted mobility refund terms in the existing append-only evidence chain.

Caller holds the order lock. Validate the chain and exact refund identity before
every retry; never fabricate consent for a historical refund.
"""
from sqlalchemy import select, bindparam
from go_hotel.db.models import JourneyRecoveryEvidenceChainRow as Evidence
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence, _stable_hash
from go_hotel.services import refund_consent

KIND='REFUND_CONSENT_FROZEN'
_CHAIN = (select(Evidence).where(Evidence.execution_id==bindparam('execution_id'))
          .order_by(Evidence.sequence_no))


def verified_records(s, order, vertical):
    """Return this transaction's fully validated chain, without cross-call caching."""
    rows=list(s.scalars(_CHAIN,{'execution_id':'rc20:'+vertical+':'+order.order_id}))
    previous='GENESIS'
    for sequence,entry in enumerate(rows,1):
        body=entry.evidence_json
        if (not isinstance(body,dict) or entry.sequence_no!=sequence
                or entry.previous_hash!=previous
                or body.get('previous_hash')!=previous or body.get('sequence_no')!=sequence
                or body.get('vertical')!=vertical or body.get('order_id')!=order.order_id
                or body.get('kind')!=entry.evidence_kind or body.get('status')!=entry.observed_status
                or entry.execution_item_id!=order.order_id
                or entry.evidence_hash!=_stable_hash(body)
                or entry.entry_hash!=_stable_hash({'evidence_hash':entry.evidence_hash,
                    'previous_hash':previous,'sequence_no':sequence})):
            raise ValueError('REFUND_OPERATION_INTEGRITY_INVALID')
        previous=entry.entry_hash
    return rows


def records(s, order, vertical):
    return [row.evidence_json['payload'] for row in verified_records(s,order,vertical)
            if row.evidence_kind==KIND]


def existing(s, order, row, accepted_hash, vertical):
    found=records(s,order,vertical)
    if not found:
        if accepted_hash is not None:
            raise ValueError('REFUND_HISTORICAL_CONSENT_UNAVAILABLE')
        return
    if len(found)!=1:
        raise ValueError('REFUND_OPERATION_INTEGRITY_INVALID')
    value=found[0];quote=value.get('quote',{})
    if (value.get('account_id')!=order.account_id or value.get('refund_id')!=row.refund_id
            or value.get('settlement_plan_hash')!=_stable_hash(row.settlement_plan_json or [])
            or (quote.get('refund_amount_minor'),quote.get('fee_minor'),quote.get('currency'))
                !=(row.refund_amount_minor,row.fee_minor,row.currency)):
        raise ValueError('REFUND_OPERATION_INTEGRITY_INVALID')
    refund_consent.verify(quote,accepted_hash)


def freeze(s, order, row, quote, accepted_hash, vertical):
    refund_consent.verify(quote,accepted_hash)
    if records(s,order,vertical):
        raise ValueError('REFUND_OPERATION_INTEGRITY_INVALID')
    append_vertical_evidence(s,vertical,order.order_id,KIND,order.status,
        {'account_id':order.account_id,'refund_id':row.refund_id,'quote':dict(quote),'settlement_plan_hash':_stable_hash(row.settlement_plan_json or [])},
        source='COMMAND_CENTER')


def complete(s,order,row,vertical):
    # The consent is immutable; the ordinary REFUND_COMPLETED event records outcome.
    existing(s,order,row,None,vertical)
