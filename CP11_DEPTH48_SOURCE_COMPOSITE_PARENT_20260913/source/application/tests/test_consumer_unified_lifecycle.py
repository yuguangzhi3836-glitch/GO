import os
os.environ['DATABASE_URL']='sqlite:////tmp/go_consumer_lifecycle_test.db'
import pytest
from go_hotel.db.models import Base
from go_hotel.db.session import engine
from go_hotel.services.consumer_unified_lifecycle import consumer_unified_lifecycle_service as svc
def setup_function():
    # RC20 acceptance uses the deterministic pristine DB reset in conftest.
    pass
def body(v='FLIGHT',o='o1',state='CONFIRMED',at='2026-08-18T10:00:00+00:00'):return {'account_id':'a1','vertical':v,'order_id':o,'title':'Verified journey item','lifecycle_state':state,'payment_state':'CAPTURED','refund_state':'NONE','evidence_reference':f'{v.lower()}://fact/{o}','source_updated_at':at,'facts':{}}
def test_each_vertical_requires_complete_evidenced_fact():
 for i,v in enumerate(('FLIGHT','RAIL','HOTEL','RIDE','RENTAL','ATTRACTION')):svc.project(body(v,f'o{i}'))
 assert len(svc.list('a1'))==6
def test_missing_evidence_and_invalid_state_fail_closed():
 b=body();b['evidence_reference']=''
 with pytest.raises(ValueError,match='COMPLETE'):svc.project(b)
 b=body();b['lifecycle_state']='SUCCESSISH'
 with pytest.raises(ValueError,match='INVALID'):svc.project(b)
def test_stale_vertical_fact_cannot_overwrite_newer_truth_and_account_isolated():
 x=svc.project(body());y=svc.project(body(state='FAILED',at='2026-08-18T09:00:00+00:00'));assert y['stale_ignored'] and y['lifecycle_state']=='CONFIRMED'
 with pytest.raises(ValueError,match='NOT_FOUND'):svc.detail('other',x['consumer_unified_lifecycle_id'])
