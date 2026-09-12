import os
os.environ['DATABASE_URL']='sqlite:////tmp/go_supplier_vertical_test.db'
from go_hotel.db.models import Base
from go_hotel.db.session import engine
from go_hotel.services.supplier_multivertical import supplier_multivertical_service as svc,REQUIRED
def setup_function():Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
def test_certification_blocks_missing_capabilities_checks_and_evidence():
 r=svc.certify('s1','FLIGHT',{},'admin');assert r['state']=='BLOCKED' and r['blockers_json'] and not r['external_live']
def test_complete_contract_certification_never_claims_live():
 for c in REQUIRED:svc.configure('s1','RAIL',c,{'authority_reference':f'contract://{c}'})
 r=svc.certify('s1','RAIL',{'checks':{c.lower():True for c in REQUIRED},'evidence':[{'reference':'cert://rail'}]},'admin');assert r['state']=='PASS_CONTRACT_ONLY' and not r['external_live']
