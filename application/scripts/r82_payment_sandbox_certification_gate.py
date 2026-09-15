#!/usr/bin/env python3
from pathlib import Path
import os, sys, tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
fd,path=tempfile.mkstemp(prefix='go_paycert_',suffix='.db');os.close(fd)
os.environ['DATABASE_URL']=f'sqlite+pysqlite:///{path}'
from go_hotel.db.models import Base, HostedDirectHotelRow, HostedDirectPaymentReadinessRow, OmnichannelMerchantBindingRow, AuditEventRow, ApprovalRequestRow, IncidentControlRow
from go_hotel.db.session import engine
from go_hotel.services.payment_sandbox_runtime import payment_sandbox_runtime_service as svc, CERTIFICATION_SCENARIOS
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as omni
from go_hotel.connectors.payment_sandbox import payment_sandbox_executor

checks={}
class GoodDelegate:
    configured=True
    def certification_probe(self, **kwargs):
        return {
            'scenario_results': {x:'PASS' for x in kwargs['required_scenarios']},
            'callback_signature_verified': True,
            'reconciliation_verified': True,
            'external_evidence_reference': 'psp-sandbox://gate/good',
        }
    def create_payment_link(self, **kwargs):
        raise AssertionError('certification gate must not create a payment link')
class BadDelegate(GoodDelegate):
    def certification_probe(self, **kwargs):
        r=super().certification_probe(**kwargs)
        r['scenario_results']['REFUND']='FAIL'
        return r
try:
    for table in (HostedDirectHotelRow.__table__, HostedDirectPaymentReadinessRow.__table__, OmnichannelMerchantBindingRow.__table__, AuditEventRow.__table__, ApprovalRequestRow.__table__, IncidentControlRow.__table__):
        table.create(engine, checkfirst=True)
    from go_hotel.db.session import SessionLocal
    from go_hotel.services.omnichannel_payment import now
    with SessionLocal() as s:
        row=HostedDirectHotelRow(hosted_hotel_id='h_aoluguya_gate',supplier_name='哈尔滨敖麓谷雅酒店',page_slug='aoluguya-harbin',city='哈尔滨',contact_json={},state='ACTIVE',updated_at=now())
        s.add(row);s.commit()
    hotel={'hosted_hotel_id':'h_aoluguya_gate'}
    svc.configure_readiness({
        'provider':'ALIPAY','merchant_account_name':'哈尔滨敖麓谷雅酒店',
        'sandbox_app_id_reference':'sandbox-app://alipay/gate',
        'kms_reference':'kms://alipay/gate/private',
    },'admin')
    merchant=omni.bind({
        'owner_type':'HOSTED_HOTEL','owner_id':hotel['hosted_hotel_id'],'channel':'ALIPAY','market':'CN',
        'merchant_reference':'psp-sandbox://alipay/merchant/gate',
        'credential_reference':'kms://alipay/gate/merchant',
        'webhook_key_reference':'vault://alipay/gate/webhook',
        'capabilities':list(CERTIFICATION_SCENARIOS),
    })
    pre=svc.certification_preflight('ALIPAY')
    checks['default_fail_closed']=pre['state']=='NOT_READY_FOR_PAYMENT_SANDBOX_CERTIFICATION' and 'EXTERNAL_SANDBOX_EXECUTOR' in pre['blockers']
    try:
        svc.certify({'channel':'ALIPAY','source_attested':True,'evidence_reference':'evidence://gate/source'},'admin')
        checks['no_executor_cannot_certify']=False
    except ValueError as e:
        checks['no_executor_cannot_certify']='EXTERNAL_SANDBOX_EXECUTOR' in str(e)
    payment_sandbox_executor.install(BadDelegate())
    try:
        svc.certify({'channel':'ALIPAY','source_attested':True,'evidence_reference':'evidence://gate/source','merchant_account_name':'哈尔滨敖麓谷雅酒店','idempotency_key':'gate-bad'},'admin')
        checks['failed_scenario_blocks_certification']=False
    except ValueError as e:
        checks['failed_scenario_blocks_certification']='REFUND' in str(e)
    payment_sandbox_executor.clear(); payment_sandbox_executor.install(GoodDelegate())
    try:
        svc.certify({'channel':'ALIPAY','source_attested':False,'evidence_reference':'evidence://gate/source'},'admin')
        checks['unattested_evidence_blocked']=False
    except ValueError as e:
        checks['unattested_evidence_blocked']=str(e)=='ATTESTED_EXTERNAL_PSP_SANDBOX_EVIDENCE_REQUIRED'
    result=svc.certify({
        'channel':'ALIPAY','source_attested':True,'evidence_reference':'evidence://gate/source',
        'merchant_account_name':'哈尔滨敖麓谷雅酒店','idempotency_key':'gate-good',
    },'admin')
    checks['all_seven_scenarios_required']=set(result['scenario_results'])==set(CERTIFICATION_SCENARIOS) and all(result['scenario_results'][x]=='PASS' for x in CERTIFICATION_SCENARIOS)
    checks['signed_callback_and_reconciliation_required']=result['callback_signature_verified'] is True and result['reconciliation_verified'] is True
    checks['merchant_promoted_only_after_certification']=merchant['state']=='REFERENCE_BOUND_NOT_CERTIFIED' and result['merchant_state']=='ACTIVE_CERTIFIED'
    checks['certified_not_live']=result['state']=='PAYMENT_SANDBOX_CERTIFIED_NOT_LIVE' and result['payment_live'] is False
    checks['no_real_money_claim']=result['real_money_moved'] is False
finally:
    payment_sandbox_executor.clear()
    engine.dispose()
    try: os.remove(path)
    except Exception: pass
for k,v in checks.items(): print(f'{k}={"PASS" if v else "FAIL"}')
if not checks or not all(checks.values()): raise SystemExit(1)
print('R8.2_PAYMENT_SANDBOX_CERTIFICATION_GATE: PASS')
