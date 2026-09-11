#!/usr/bin/env python3
from pathlib import Path
from datetime import timedelta
import os, sys, tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
fd,path=tempfile.mkstemp(prefix='go_paycut_',suffix='.db'); os.close(fd)
os.environ['DATABASE_URL']=f'sqlite+pysqlite:///{path}'

from go_hotel.db.models import (
    HostedDirectHotelRow, HostedDirectPaymentReadinessRow, OmnichannelMerchantBindingRow,
    AuditEventRow, ApprovalRequestRow, IncidentControlRow,
)
from go_hotel.db.session import engine, SessionLocal
from go_hotel.services.payment_sandbox_runtime import payment_sandbox_runtime_service as runtime, CERTIFICATION_SCENARIOS
from go_hotel.services.payment_sandbox_cutover import payment_sandbox_cutover_service as cutover
import go_hotel.services.payment_sandbox_cutover as cutover_module
from go_hotel.services.omnichannel_payment import omnichannel_payment_service as omni, now
from go_hotel.connectors.payment_sandbox import payment_sandbox_executor

checks={}
class GoodDelegate:
    configured=True
    def certification_probe(self, **kwargs):
        return {
            'scenario_results': {x:'PASS' for x in kwargs['required_scenarios']},
            'callback_signature_verified': True,
            'reconciliation_verified': True,
            'external_evidence_reference': 'psp-sandbox://rc162/external-proof',
        }
    def create_payment_link(self, **kwargs):
        raise AssertionError('cutover safety gate must not create a payment link')

try:
    for table in (
        HostedDirectHotelRow.__table__, HostedDirectPaymentReadinessRow.__table__,
        OmnichannelMerchantBindingRow.__table__, AuditEventRow.__table__,
        ApprovalRequestRow.__table__, IncidentControlRow.__table__,
    ):
        table.create(engine, checkfirst=True)
    with SessionLocal() as s:
        s.add(HostedDirectHotelRow(
            hosted_hotel_id='h_aoluguya_rc162', supplier_name='哈尔滨敖麓谷雅酒店',
            page_slug='aoluguya-harbin', city='哈尔滨', contact_json={}, state='ACTIVE', updated_at=now()))
        s.commit()
    runtime.configure_readiness({
        'provider':'ALIPAY','merchant_account_name':'哈尔滨敖麓谷雅酒店',
        'sandbox_app_id_reference':'sandbox-app://alipay/rc162',
        'kms_reference':'kms://alipay/rc162/private',
    },'admin_maker')
    omni.bind({
        'owner_type':'HOSTED_HOTEL','owner_id':'h_aoluguya_rc162','channel':'ALIPAY','market':'CN',
        'merchant_reference':'psp-sandbox://alipay/merchant/rc162',
        'credential_reference':'kms://alipay/rc162/merchant-v1',
        'webhook_key_reference':'vault://alipay/rc162/webhook-v1',
        'capabilities':list(CERTIFICATION_SCENARIOS),
    })
    payment_sandbox_executor.install(GoodDelegate())
    cert=runtime.certify({
        'channel':'ALIPAY','source_attested':True,'evidence_reference':'evidence://rc162/cert-v1',
        'merchant_account_name':'哈尔滨敖麓谷雅酒店','idempotency_key':'rc162-cert-v1',
    },'admin_maker')
    st=cutover.status('ALIPAY')
    checks['certified_still_not_live']=st['certification_valid'] and st['payment_live'] is False and st['production_cutover_available'] is False
    checks['certification_has_expiry']=bool(st['certification_expires_at'])
    led=cutover.evidence_ledger('ALIPAY')
    checks['append_only_hash_chain']=led['append_only'] and led['chain_valid'] and led['entry_count']==1 and bool(led['latest_entry_hash'] if 'latest_entry_hash' in led else led['entries'][-1]['entry_hash'])

    req=cutover.request_cutover('ALIPAY',{
        'justification':'future production cutover review only',
        'evidence_reference':'evidence://rc162/cutover-request-v1',
    },'admin_maker')
    checks['cutover_request_not_live']=req['state']=='CUTOVER_APPROVAL_PENDING_NOT_LIVE' and req['payment_live'] is False
    try:
        cutover.approve_cutover(req['approval']['approval_id'],{'approval_note':'self approve'},'admin_maker')
        checks['maker_checker_enforced']=False
    except ValueError as e:
        checks['maker_checker_enforced']='MAKER_CHECKER' in str(e)
    approved=cutover.approve_cutover(req['approval']['approval_id'],{'approval_note':'independent checker approval; execution remains unavailable'},'admin_checker')
    checks['approval_does_not_enable_live']=approved['state']=='PAYMENT_CUTOVER_APPROVED_NOT_EXECUTED' and approved['production_cutover_available'] is False and approved['payment_live'] is False

    ks=cutover.set_executor_kill_switch('ALIPAY',{'active':True,'reason':'gate emergency stop'},'admin_ops')
    try:
        cutover.assert_sandbox_execution_allowed('ALIPAY')
        checks['kill_switch_blocks_execution']=False
    except ValueError as e:
        checks['kill_switch_blocks_execution']='KILL_SWITCH' in str(e)
    cutover.set_executor_kill_switch('ALIPAY',{'active':False},'admin_ops')

    rot=cutover.rotate_credentials('ALIPAY',{
        'credential_reference':'kms://alipay/rc162/merchant-v2',
        'webhook_key_reference':'vault://alipay/rc162/webhook-v2',
        'evidence_reference':'evidence://rc162/credential-rotation-v2',
    },'admin_security')
    checks['rotation_forces_downgrade']=rot['merchant_state']=='REFERENCE_BOUND_NOT_CERTIFIED' and rot['state']=='CREDENTIAL_ROTATED_REQUIRES_RECERTIFICATION'
    try:
        cutover.assert_sandbox_execution_allowed('ALIPAY')
        checks['rotation_blocks_until_recertified']=False
    except ValueError as e:
        checks['rotation_blocks_until_recertified']='VALID_PAYMENT_SANDBOX_CERTIFICATION_REQUIRED' in str(e)

    runtime.certify({
        'channel':'ALIPAY','source_attested':True,'evidence_reference':'evidence://rc162/cert-v2',
        'merchant_account_name':'哈尔滨敖麓谷雅酒店','idempotency_key':'rc162-cert-v2',
    },'admin_security')
    rev=cutover.revoke_certification('ALIPAY',{
        'reason':'manual security revocation gate',
        'evidence_reference':'evidence://rc162/revoke-v2',
    },'admin_security')
    checks['revocation_forces_downgrade']=rev['merchant_state']=='REFERENCE_BOUND_NOT_CERTIFIED' and rev['payment_live'] is False
    try:
        cutover.assert_sandbox_execution_allowed('ALIPAY')
        checks['revocation_blocks_execution']=False
    except ValueError:
        checks['revocation_blocks_execution']=True

    runtime.certify({
        'channel':'ALIPAY','source_attested':True,'evidence_reference':'evidence://rc162/cert-v3',
        'merchant_account_name':'哈尔滨敖麓谷雅酒店','idempotency_key':'rc162-cert-v3',
    },'admin_security')
    real_now=cutover_module.now
    expiry=cutover.status('ALIPAY')['certification_expires_at']
    from datetime import datetime
    future=datetime.fromisoformat(expiry)+timedelta(seconds=1)
    cutover_module.now=lambda: future
    exp=cutover.expire_if_due('ALIPAY')
    checks['expiry_forces_downgrade']=exp['expired'] and exp['merchant_state']=='REFERENCE_BOUND_NOT_CERTIFIED'
    cutover_module.now=real_now

    ledger=cutover.evidence_ledger('ALIPAY')
    checks['ledger_remains_chain_valid_after_controls']=ledger['chain_valid'] and ledger['entry_count']>=9 and all(x['append_only'] for x in ledger['entries'])
    actions={x['action'] for x in ledger['entries']}
    checks['ledger_covers_required_controls']={
        'PAYMENT_SANDBOX_CERTIFICATION_GRANTED','PAYMENT_PRODUCTION_CUTOVER_REQUESTED',
        'PAYMENT_PRODUCTION_CUTOVER_APPROVED_NOT_EXECUTED','PAYMENT_SANDBOX_EXECUTOR_KILL_SWITCH_ACTIVATED',
        'PAYMENT_SANDBOX_CREDENTIAL_ROTATED','PAYMENT_SANDBOX_CERTIFICATION_REVOKED',
        'PAYMENT_SANDBOX_CERTIFICATION_EXPIRED',
    }.issubset(actions)
finally:
    payment_sandbox_executor.clear()
    cutover_module.now=getattr(cutover_module,'now',now)
    engine.dispose()
    try: os.remove(path)
    except Exception: pass

for k,v in checks.items(): print(f'{k}={"PASS" if v else "FAIL"}')
if not checks or not all(checks.values()): raise SystemExit(1)
print('R8.2_PAYMENT_SANDBOX_CUTOVER_SAFETY_GATE: PASS')
