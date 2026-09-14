"""Normal subprocess actor for isolated C11 database acceptance; no pytest fixtures."""
import argparse
import json
from pathlib import Path
import time
import traceback
from types import SimpleNamespace
from fastapi import HTTPException
from go_hotel.api.routes import flight
from go_hotel.services.vertical_transaction_bridge import vertical_transaction_bridge
from go_hotel.services.vertical_money_bridge import vertical_money_bridge


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--operation',required=True,choices=['checkout','change'])
    p.add_argument('--order',required=True);p.add_argument('--quote',default='')
    p.add_argument('--key',required=True);p.add_argument('--pause',choices=['before_bridge','after_money'])
    p.add_argument('--barrier');p.add_argument('--fault',action='store_true')
    a=p.parse_args()
    if a.pause:
        target,name=(vertical_transaction_bridge,'checkout_contract') if a.operation=='checkout' else (vertical_money_bridge,'prepare_adjustment')
        original=getattr(target,name)
        def boundary(*args,**kwargs):
            result=original(*args,**kwargs) if a.pause=='after_money' else None
            Path(a.barrier+'.ready').write_text('committed boundary reached\n')
            if a.fault:raise ValueError('C11_REAL_COMMIT_THEN_FAILURE')
            until=time.monotonic()+45
            while not Path(a.barrier+'.release').exists():
                if time.monotonic()>until:raise TimeoutError('C11_BARRIER_TIMEOUT')
                time.sleep(0.02)
            return result if a.pause=='after_money' else original(*args,**kwargs)
        setattr(target,name,boundary)
    try:
        actor=SimpleNamespace(user_id='c11-process-owner')
        result=flight.checkout(a.order,flight.CheckoutBody(payment_method_id='c11-process-method'),actor,a.key) if a.operation=='checkout' else flight.execute_change(a.order,a.quote,actor,a.key,None)
        print(json.dumps({'http':200,'result':result},sort_keys=True))
    except HTTPException as exc:
        print(json.dumps({'http':exc.status_code,'detail':exc.detail},sort_keys=True))
    except Exception:
        traceback.print_exc();return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
