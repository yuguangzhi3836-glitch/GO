from __future__ import annotations
import json, time
from datetime import datetime, timezone
from go_hotel.services.p0_design_code_freeze import (
    static_review, ProviderResult, HotelAdapter, FlightAdapter, RailAdapter,
    RideAdapter, RentalAdapter, AttractionAdapter, validate_cancel_refund_transition,
)

class VirtualTransport:
    def __init__(self): self.n=0
    def execute(self, provider_key, command):
        self.n += 1
        payload=dict(command.payload)
        payload.update({'virtual':True,'operation':command.operation,'vertical':command.vertical})
        return ProviderResult(f'virt-{self.n}', 'ACCEPTED_ASYNC', payload, True, 'OFFICIAL_OR_AUTHORIZED_DIRECT', provider_key)
    def query(self, provider_key, external_operation_id):
        return ProviderResult(external_operation_id, 'CONFIRMED', {'virtual':True}, True, 'OFFICIAL_OR_AUTHORIZED_DIRECT', provider_key)

ADAPTERS = {
 'HOTEL': HotelAdapter, 'FLIGHT': FlightAdapter, 'RAIL': RailAdapter,
 'RIDE': RideAdapter, 'RENTAL': RentalAdapter, 'ATTRACTION': AttractionAdapter,
}
BOOK_OP = {'HOTEL':'book','FLIGHT':'book','RAIL':'book','RIDE':'reserve','RENTAL':'reserve','ATTRACTION':'book'}

REFUND_PATH = [
 ('CANCEL_REQUESTED','SUPPLIER_PROCESSING','SYSTEM',{'cancel_request_evidence':'ev://cancel'}),
 ('SUPPLIER_PROCESSING','CANCEL_CONFIRMED','SUPPLIER_CALLBACK',{'supplier_cancel_confirmation':'ev://supplier'}),
 ('CANCEL_CONFIRMED','REFUND_AMOUNT_CONFIRMED','RULE_ENGINE',{'refund_quote_evidence':'ev://quote'}),
 ('REFUND_AMOUNT_CONFIRMED','REFUND_INITIATED','PAYMENT_SERVICE',{'refund_authorization_evidence':'ev://refund'}),
 ('REFUND_INITIATED','PSP_PROCESSING','PAYMENT_ADAPTER',{'psp_refund_operation_evidence':'ev://psp-request'}),
 ('PSP_PROCESSING','REFUND_COMPLETED','PAYMENT_CALLBACK',{'psp_refund_confirmation':'ev://psp-ok','money_movement_evidence':'ev://money'}),
]

def one_run(run_no:int):
    review=static_review()
    assert review['design_state']=='FROZEN'
    assert review['code_state']=='CODE_COMPLETE_PENDING_RUNTIME_CERTIFICATION'
    assert all(x['pass'] for x in review['requirement_implementation_evidence'].values())
    vertical_results={}
    for vertical, cls in ADAPTERS.items():
        tr=VirtualTransport(); a=cls(tr, f'{vertical.lower()}-virtual-primary')
        fn=getattr(a, BOOK_OP[vertical])
        r=fn({'order_id':f'run{run_no}-{vertical.lower()}'}, f'idem-{run_no}-{vertical}', f'ev://run/{run_no}/{vertical}')
        assert r.state=='ACCEPTED_ASYNC'
        q=a.reconcile(r.external_operation_id)
        assert q.state=='CONFIRMED'
        vertical_results[vertical]={'mutation':'ACCEPTED_ASYNC','reconciliation':'CONFIRMED'}
    for current,target,actor,evidence in REFUND_PATH:
        validate_cancel_refund_transition(current,target,actor,evidence,'FULL',10000)
    return {'run':run_no,'verticals':vertical_results,'cancel_refund':'REFUND_COMPLETED','requirements':'7/7 PASS'}

def main():
    started=datetime.now(timezone.utc).isoformat()
    runs=[]
    for i in range(1,11):
        t=time.perf_counter(); r=one_run(i); r['elapsed_ms']=round((time.perf_counter()-t)*1000,2); runs.append(r)
    out={'kind':'P0_VIRTUAL_CLOSED_LOOP_SMOKE','started_at':started,'completed_at':datetime.now(timezone.utc).isoformat(),'run_count':len(runs),'passed':len(runs),'failed':0,'scope':'design/code contract simulation only; no real provider, bank, PSP, or PostgreSQL runtime certification','runs':runs}
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
