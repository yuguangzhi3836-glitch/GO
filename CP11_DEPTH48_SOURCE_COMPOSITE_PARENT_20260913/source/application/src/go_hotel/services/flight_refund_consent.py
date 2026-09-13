"""Persist accepted flight refund terms in the existing append-only evidence chain.

Caller holds the order lock. Validate the chain and exact refund identity before
every retry; never fabricate consent for a historical refund.
"""
from sqlalchemy import select
from go_hotel.db.models import JourneyRecoveryEvidenceChainRow as Evidence
from go_hotel.services.rc20_vertical_evidence import append_vertical_evidence, _stable_hash
from go_hotel.services import refund_consent

KIND='REFUND_CONSENT_FROZEN'


def records(s, order):
    rows=list(s.scalars(select(Evidence).where(
        Evidence.execution_id=='rc20:FLIGHT:'+order.order_id).order_by(Evidence.sequence_no)))
    previous='GENESIS'
    found=[]
    for sequence,entry in enumerate(rows,1):
        body=entry.evidence_json
        if (not isinstance(body,dict) or entry.sequence_no!=sequence
                or entry.previous_hash!=previous
                or body.get('previous_hash')!=previous or body.get('sequence_no')!=sequence
                or body.get('vertical')!='FLIGHT' or body.get('order_id')!=order.order_id
                or body.get('kind')!=entry.evidence_kind or body.get('status')!=entry.observed_status
                or entry.execution_item_id!=order.order_id
                or entry.evidence_hash!=_stable_hash(body)
                or entry.entry_hash!=_stable_hash({'evidence_hash':entry.evidence_hash,
                    'previous_hash':previous,'sequence_no':sequence})):
            raise ValueError('REFUND_OPERATION_INTEGRITY_INVALID')
        previous=entry.entry_hash
        if entry.evidence_kind==KIND:found.append(body['payload'])
    return found


def existing(s, order, row, accepted_hash):
    found=records(s,order)
    if not found:
        if accepted_hash is not None:
            raise ValueError('REFUND_HISTORICAL_CONSENT_UNAVAILABLE')
        return
    if len(found)!=1:
        raise ValueError('REFUND_OPERATION_INTEGRITY_INVALID')
    value=found[0];quote=value.get('quote',{})
    if (value.get('account_id')!=order.account_id or value.get('refund_id')!=row.refund_id
            or (quote.get('refund_amount_minor'),quote.get('refund_fee_minor'),quote.get('currency'))
                !=(row.refund_amount_minor,row.refund_fee_minor,row.currency)):
        raise ValueError('REFUND_OPERATION_INTEGRITY_INVALID')
    refund_consent.verify(quote,accepted_hash)


def freeze(s, order, row, quote, accepted_hash):
    refund_consent.verify(quote,accepted_hash)
    if records(s,order):
        raise ValueError('REFUND_OPERATION_INTEGRITY_INVALID')
    append_vertical_evidence(s,'FLIGHT',order.order_id,KIND,order.status,
        {'account_id':order.account_id,'refund_id':row.refund_id,'quote':dict(quote)},
        source='COMMAND_CENTER')


def complete(s,order,row):
    # The consent is immutable; the ordinary REFUND_COMPLETED event records outcome.
    existing(s,order,row,None)
