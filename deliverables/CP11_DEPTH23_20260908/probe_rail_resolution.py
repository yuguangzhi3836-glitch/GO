import os,sys,json,tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Event
root=Path(sys.argv[1]);db=Path(tempfile.mkdtemp(prefix='go22_probe_'))/'case.db'
os.environ['DATABASE_URL']='sqlite+pysqlite:///'+str(db)
sys.path[:0]=[str(root/'src'),str(root/'tests')]
from go_hotel.db.models import Base
from go_hotel.db.session import engine
from go_hotel.security.service import identity_service
Base.metadata.create_all(engine);identity_service.bootstrap()
from test_depth21_refund_recovery import booked
from go_hotel.services.vertical_money_bridge import vertical_money_bridge as money
svc,owner,oid=booked('RAIL');q=svc.change_quote(owner,oid,'2026-09-17');svc.execute_change(owner,oid,q['quote_id'])
entered=Event();finish=Event();original=money.capture_adjustment;calls=[]
def capture(*a,**kw):
 entered.set();assert finish.wait(15);return original(*a,**kw)
def release(*a,**kw):
 calls.append('opposite_release_dispatched');raise RuntimeError('PROBE_RELEASE_DISPATCH')
money.capture_adjustment=capture;money.release_adjustment=release
with ThreadPoolExecutor(max_workers=2) as pool:
 task=pool.submit(svc.admin_external_state,oid,'TICKETED','isolated://positive','ops','NEW',['NEW-A','NEW-B'])
 assert entered.wait(15)
 try:
  svc.admin_external_state(oid,'FAILED','isolated://negative','ops')
  rejection=None
 except Exception as e:rejection=str(e)
 finally:finish.set()
 result=task.result()
print(json.dumps({'baseline':root.name,'opposite_money_calls':len(calls),'rejected_with':rejection,'final_status':result['status'],'date':result['journey']['travel_date'],'isolated':True}))
