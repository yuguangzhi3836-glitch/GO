"""Local disposable full-app fixture; no auth/CSRF/tenant dependency overrides.

Usage: PYTHONPATH=src:. python scripts/partner-mobile-acceptance/server.py
  /absolute/empty/state-dir 4288 [--approved-test-policy]
Only --approved-test-policy replaces legal approval with synthetic test text.
The shipped legal registry remains unchanged and is tested on a second process.
"""
import hashlib,json,os,sys
from pathlib import Path
state=Path(sys.argv[1]).resolve();state.mkdir(exist_ok=False,parents=True)
os.environ['DATABASE_URL']='sqlite+pysqlite:///'+str(state/'isolated.db')
os.environ['GO_MEDIA_CACHE_DIR']=str(state/'media')
os.environ['APP_ENV']='test'
os.environ['COOKIE_SECURE']='false'
from go_hotel.db.models import Base
from go_hotel.db.session import engine
Base.metadata.create_all(engine)
from go_hotel.core.config import settings
settings.hosted_reservation_expiry_worker_enabled=False
from go_hotel.security.service import identity_service
from go_hotel.services.hotel_partner_core import hotel_partner_core_service as core
identity_service.bootstrap()
identity_service.ensure_user('mobile-owner@example.test','Isolated-mobile-password','SUPPLIER_USER','mobile-supplier',['SUPPLIER_OWNER'])
identity_service.ensure_user('mobile-reader@example.test','Isolated-mobile-password','SUPPLIER_USER','mobile-supplier',['READ_ONLY'])
hotel=core.create_property('mobile-supplier','fixture',{'name_zh':'隔离验收酒店','property_type':'HOTEL'})
for name in ['卧云大床房','卧云双床房','公园套房']:
 core.create_room_type('mobile-supplier','fixture',hotel['property_id'],{'name_zh':name,'physical_room_count':5,'occupancy':{'max_occupancy':2,'max_adults':2,'max_children':0}})
from go_hotel.main import app
if '--approved-test-policy' in sys.argv:
 from go_hotel.services import registration_terms as terms
 from go_hotel.api.routes import registration_terms as routes
 settings.registration_verification_enabled=True
 def document(term_id,version):
  content='SYNTHETIC ISOLATED TEST TERMS: '+term_id
  return {'id':term_id,'version':version,'title':'隔离验收条款','sha256':hashlib.sha256(content.encode()).hexdigest(),'status':'APPROVED','content':content,'content_url':'/v1/registration-terms/'+term_id+'/'+version}
 def policy(audience):
  docs=[document(k,'isolated-ui-v1') for k in ['consumer_service_terms','privacy_policy','personal_vault_terms']]
  return {'enabled':True,'acceptance_enabled':True,'versions':{d['id']:d['version'] for d in docs},'term_hashes':{d['id']:d['sha256'] for d in docs},'documents':docs}
 terms.registration_terms_status=policy;terms.require_registration_terms_ready=policy;routes.read_registration_term=document
print(json.dumps({'mode':'ISOLATED_SQLITE_FULL_APP','synthetic_policy':'--approved-test-policy' in sys.argv,'port':int(sys.argv[2])}),flush=True)
import uvicorn
uvicorn.run(app,host='127.0.0.1',port=int(sys.argv[2]),log_level='warning')
