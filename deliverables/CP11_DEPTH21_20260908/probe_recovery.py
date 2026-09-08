"""Reproduce the DEPTH20 refund/redemption race and a split-refund interruption safely."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[3]
data=Path(tempfile.mkdtemp(prefix='go21-recovery-probe-'))
os.environ.update(APP_ENV='test',DATABASE_URL='sqlite+pysqlite:///'+str(data/'probe.sqlite3'))
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from go_hotel.db.models import Base, OmnichannelMoneyMovementRow as Movement
from go_hotel.db.session import engine,SessionLocal
from sqlalchemy import select
Base.metadata.create_all(engine)
from tests.test_depth21_refund_recovery import booked,row_state
from go_hotel.services import vertical_refund_recovery as recovery
from go_hotel.services.unified_money_movement import unified_money_movement_service as money

result={'data_mode':'ISOLATED_CONTRACT_SIMULATOR','external_live':False}
svc,owner,oid=booked('ATTRACTION')
original=recovery.vertical_money_bridge.refund_with_adjustments
race={}
def interleave(*args,**kw):
    movement=original(*args,**kw)
    try:race['redemption_result']=svc.redeem(owner,oid,'isolated://redemption-during-refund')
    except ValueError as exc:race['redemption_rejected']=str(exc)
    return movement
recovery.vertical_money_bridge.refund_with_adjustments=interleave
try:refund=svc.refund(owner,oid)
finally:recovery.vertical_money_bridge.refund_with_adjustments=original
race.update(final_order_status=row_state('ATTRACTION',oid),refund_status=refund['status'])
assert race.get('redemption_rejected')=='ATTRACTION_ILLEGAL_STATE_TRANSITION'
assert race['final_order_status']=='REFUNDED'
result['refund_redemption_race']=race

svc,owner,oid=booked('RAIL','split-refund-owner')
quote=svc.change_quote(owner,oid,'2026-09-16')
svc.execute_change(owner,oid,quote['quote_id'])
svc.admin_external_state(oid,'TICKETED','isolated://changed','isolated-ops','BOOKING-NEW',['NEW-A','NEW-B'])
with SessionLocal() as s:before=set(s.scalars(select(Movement.money_movement_id).where(Movement.movement_type=='REFUND')))
create=money.create
count=0
def interrupt(*args,**kw):
    global count
    if args[1].get('movement_type')=='REFUND':
        count+=1
        if count==2:raise RuntimeError('INTERRUPTED_BEFORE_SECOND_ORIGINAL_CAPTURE_REFUND')
    return create(*args,**kw)
money.create=interrupt
split={}
try:
    svc.refund(owner,oid)
    raise AssertionError('interruption was not triggered')
except RuntimeError as exc:split['interruption']=str(exc)
finally:money.create=create
split['status_after_interruption']=row_state('RAIL',oid)
assert split['status_after_interruption']=='REFUND_PENDING'
receipt=svc.refund(owner,oid)
assert svc.refund(owner,oid)==receipt
with SessionLocal() as s:
    rows=list(s.scalars(select(Movement).where(Movement.movement_type=='REFUND')))
    rows=[r for r in rows if r.money_movement_id not in before]
    split['confirmed_refunds']=[{'amount_minor':r.amount_minor,'state':r.state} for r in rows]
    assert len(rows)==2 and sum(r.amount_minor for r in rows)==19100 and all(r.state=='CONFIRMED' for r in rows)
split['status_after_resume']=row_state('RAIL',oid)
split['replay_same_receipt']=True
result['split_original_refund_resume']=split
result['passed']=True
print(json.dumps(result,ensure_ascii=False,indent=2))
