#!/usr/bin/env python3
from pathlib import Path
import os,sys,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
fd,path=tempfile.mkstemp(prefix='go_payready_',suffix='.db');os.close(fd);os.environ['DATABASE_URL']=f'sqlite+pysqlite:///{path}'
from go_hotel.db.models import Base, HostedDirectHotelRow, HostedDirectPaymentReadinessRow
from go_hotel.db.session import engine
from go_hotel.services.payment_sandbox_runtime import payment_sandbox_runtime_service as svc
from go_hotel.connectors.payment_sandbox import payment_sandbox_executor
checks={}
try:
 for table in (HostedDirectHotelRow.__table__, HostedDirectPaymentReadinessRow.__table__):
  table.create(engine, checkfirst=True)
 from go_hotel.db.session import SessionLocal
 from go_hotel.services.omnichannel_payment import now
 with SessionLocal() as s:
  s.add(HostedDirectHotelRow(hosted_hotel_id='h_aoluguya_gate',supplier_name='哈尔滨敖麓谷雅酒店',page_slug='aoluguya-harbin',city='哈尔滨',contact_json={},state='ACTIVE',updated_at=now()));s.commit()
 r=svc.configure_readiness({'provider':'ALIPAY','merchant_account_name':'哈尔滨敖麓谷雅酒店'},'admin')
 status=svc.readiness()
 checks['readiness_state_fail_closed']=status['state']=='READY_NOT_PSP_CONNECTED' and status['external_psp_connected'] is False
 checks['full_lifecycle_declared']=status['lifecycle']==['PAYMENT_INTENT','PAYMENT_LINK','PSP_CALLBACK','AUTHORIZATION','CAPTURE','REFUND','LEDGER','SETTLEMENT_HOLD','CHECKOUT_RELEASE']
 checks['funds_hold_rule']=status['funds_rule']=='NO_HOTEL_PAYOUT_BEFORE_FULFILLMENT_AND_CHECKOUT_GATE'
 checks['no_real_money']=status['real_money_moved'] is False
 try:
  svc.create_payment_link('missing','admin'); checks['payment_link_fail_closed']=False
 except ValueError as e: checks['payment_link_fail_closed']=str(e)=='EXTERNAL_PAYMENT_SANDBOX_EXECUTOR_NOT_CONFIGURED'
 checks['executor_default_off']=payment_sandbox_executor.configured is False
finally:
 engine.dispose()
 try: os.remove(path)
 except Exception: pass
for k,v in checks.items(): print(f'{k}={"PASS" if v else "FAIL"}')
if not all(checks.values()): raise SystemExit(1)
print('R8.2_PAYMENT_SANDBOX_READINESS_GATE: PASS')
