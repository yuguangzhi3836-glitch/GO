from __future__ import annotations
import os
os.environ['DATABASE_URL']='sqlite:////tmp/go_r81_commercial_gate.db'
from pathlib import Path
from go_hotel.db.session import engine
from go_hotel.db.models import Base
from go_hotel.services.commercial_constitution import commercial_constitution_service as svc

# Deterministic, isolated gate: no broad pytest lifecycle dependency.
Path('/tmp/go_r81_commercial_gate.db').unlink(missing_ok=True)
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)

for i in range(20):
    r=svc.record_order_evidence(
        'supplier-r81','property-r81',
        {'order_id':f'od-{i}','source_type':'OFFICIAL_DIRECT','order_state':'COMPLETED','evidence':[{'reference':f'order://od-{i}'}]},
        'system',
    )
assert r['subscription']['state']=='SUBSCRIPTION_REQUIRED'

p=svc.create_policy('T20_SUBSCRIPTION','GLOBAL',{'plan':'THREE_DIAMOND','currency':'CNY'},'maker')
svc.approve_policy(p['policy_version_id'],'checker')
try:
    svc.issue_invoice('supplier-r81','2026-09','finance')
except ValueError as e:
    assert str(e)=='SUBSCRIPTION_POLICY_AMOUNT_REQUIRED'
else:
    raise AssertionError('missing subscription amount must fail closed')

p2=svc.create_policy('T20_SUBSCRIPTION','GLOBAL',{'plan':'THREE_DIAMOND','amount_minor':69900,'currency':'CNY'},'maker2')
svc.approve_policy(p2['policy_version_id'],'checker2')
inv=svc.issue_invoice('supplier-r81','2026-09','finance')
assert inv['amount_minor']==69900 and inv['currency']=='CNY'
print('R8.1_COMMERCIAL_FAIL_CLOSED_GATE: PASS')
