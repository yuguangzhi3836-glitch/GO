from __future__ import annotations
from hashlib import sha256
from json import dumps
from .base import RecoveryAdapterMetadata, RecoveryRevalidation, RecoveryMutationResult, RecoveryObservation

def h(v): return sha256(dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]

class DeterministicRecoveryAdapter:
    """Production-shaped contract implementation for engineering verification only.

    It models supplier idempotency, async acceptance, polling and webhook facts without
    pretending to be a live NDC/Rail/Mobility/Hotel/Attraction production connector.
    """
    def __init__(self,vertical:str):
        self.metadata=RecoveryAdapterMetadata(adapter_key=f"{vertical.lower()}_recovery_v1",vertical=vertical)
    def revalidate(self,*,order_id,quote_id,rule_version,expected_delta_minor,currency,facts):
        if facts.get('force_expired'): return RecoveryRevalidation('EXPIRED',expected_delta_minor,currency,quote_id,rule_version,{'reason':'QUOTE_EXPIRED'})
        if facts.get('force_sold_out'): return RecoveryRevalidation('SOLD_OUT',expected_delta_minor,currency,quote_id,rule_version,{'reason':'SUPPLIER_INVENTORY_UNAVAILABLE'})
        if facts.get('force_rule_blocked'): return RecoveryRevalidation('RULE_BLOCKED',expected_delta_minor,currency,quote_id,rule_version,{'reason':'VERTICAL_RULE_BLOCKED'})
        delta=int(facts.get('revalidated_delta_minor',expected_delta_minor))
        return RecoveryRevalidation('READY',delta,currency,quote_id,rule_version,{'adapter_key':self.metadata.adapter_key})
    def mutate(self,*,order_id,command_type,idempotency_key,quote_id,rule_version,authorized_delta_minor,currency,facts):
        ext=f"extop_{h([self.metadata.adapter_key,idempotency_key])}"
        if facts.get('force_supplier_failed'): return RecoveryMutationResult('FAILED',ext,None,{'reason':'SUPPLIER_REJECTED'})
        if facts.get('force_unknown_external_state'): return RecoveryMutationResult('UNKNOWN',ext,None,{'reason':'TIMEOUT_AFTER_SEND'})
        if facts.get('force_async_supplier'): return RecoveryMutationResult('ACCEPTED',ext,None,{'async':True})
        return RecoveryMutationResult('CONFIRMED',ext,f"supconf_{h([ext,order_id])}",{'final_delta_minor':authorized_delta_minor})
    def poll(self,*,external_operation_id,idempotency_key,order_id,facts):
        state=facts.get('poll_result') or facts.get('reconciliation_result') or ('PENDING' if facts.get('force_async_supplier') else 'CONFIRMED')
        conf=f"supconf_{h([external_operation_id or idempotency_key,order_id])}" if state=='CONFIRMED' else None
        return RecoveryObservation(state,conf,None,{'channel':'POLL','adapter_key':self.metadata.adapter_key})
    def parse_webhook(self,payload):
        return RecoveryObservation(str(payload.get('status','UNKNOWN')),payload.get('supplier_confirmation_id'),str(payload.get('external_event_id') or '') or None,{'channel':'WEBHOOK','payload':payload})
