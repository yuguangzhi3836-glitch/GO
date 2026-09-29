from registration_terms_test_support import register_synthetic_consumer
from pathlib import Path
import os
import subprocess
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import MobilePushReceiptRow
from go_hotel.mobile.orchestration import mobile_engagement
from go_hotel.mobile.push import push_worker, push_receipt_worker
from go_hotel.core.config import settings

ROOT=Path(__file__).resolve().parents[1]

def auth(client,email='2b@example.com'):
    register_synthetic_consumer(client, json={'email':email,'password':'StrongPass123!','display_name':'2B'})
    t=client.post('/v1/mobile/auth/login',json={'email':email,'password':'StrongPass123!'}).json()['data']
    return {'Authorization':f"Bearer {t['access_token']}"}

def test_push_receipt_lifecycle_with_mock_provider(client):
    h=auth(client)
    client.post('/v1/mobile/devices',headers=h,json={'device_id':'dev2b','platform':'IOS','push_provider':'APNS','push_token':'token-2b','notifications_enabled':True})
    # Create inbox notification directly through the service surface used by engagement jobs.
    from go_hotel.mobile.service import mobile_service
    n=mobile_service.create_notification('usr_missing','TEST','x','y') if False else None
    # Use authenticated user's id from /me so the notification and device match.
    uid=client.get('/v1/consumer/me',headers=h).json()['data']['user_id']
    n=mobile_service.create_notification(uid,'TEST','测试 Push','receipt lifecycle','go://home',{})
    assert push_worker.run_once()==1
    with SessionLocal() as s:
        row=s.scalar(select(MobilePushReceiptRow).where(MobilePushReceiptRow.notification_id==n['notification_id']))
        assert row is not None and row.status=='SUBMITTED' and row.provider_message_id
    old=settings.mobile_push_receipt_min_age_seconds
    settings.mobile_push_receipt_min_age_seconds=0
    try:
        assert push_receipt_worker.run_once()==1
    finally:
        settings.mobile_push_receipt_min_age_seconds=old
    receipts=push_receipt_worker.status(n['notification_id'])
    assert receipts[0]['status']=='DELIVERED' and receipts[0]['delivered_at']

def test_mobile_release_artifacts_and_offline_contract_exist():
    assert (ROOT/'mobile/go-app/eas.json').exists()
    assert (ROOT/'.github/workflows/mobile-release.yml').exists()
    assert (ROOT/'mobile/go-app/qa/REAL_DEVICE_MATRIX.md').exists()
    client_source=(ROOT/'mobile/go-app/src/api/client.ts').read_text()
    assert "import {createTransport} from './transport'" in client_source
    assert 'export const api=transport.request' in client_source
    # Execute the shared implementation: an obsolete error string in the thin
    # Expo adapter cannot prove offline blocking or idempotency behavior.
    script=r'''
import assert from 'node:assert/strict';
import {createTransport} from './mobile/go-app/src/api/transport.ts';
let connected=false;
const calls=[];
const transport=createTransport({
  baseUrl:'https://isolated.invalid', online:async()=>connected,
  accessToken:async()=>null, refreshToken:async()=>null,
  saveTokens:async()=>{}, clearTokens:async()=>{}, newKey:()=> 'generated-key',
  fetch:async(url,init)=>{calls.push({url,init});return new Response('{"data":{"ok":true}}',{status:200});}
});
const mutation={method:'POST',body:'{"amount_minor":100}',headers:{'Idempotency-Key':'caller-key'}};
await assert.rejects(transport.request('/v1/orders',mutation),e=>e.message==='NETWORK_OFFLINE'&&!e.uncertain);
assert.equal(calls.length,0,'offline financial mutation must never reach fetch');
connected=true;
await transport.request('/v1/orders',mutation);
assert.equal(calls.length,1,'reconnection must not replay an offline mutation');
assert.equal(calls[0].init.headers.get('Idempotency-Key'),'caller-key');
assert.equal(calls[0].init.body,mutation.body);
await transport.request('/v1/orders',{method:'POST',body:'{}'});
assert.equal(calls.length,2);
assert.equal(calls[1].init.headers.get('Idempotency-Key'),'generated-key');
'''
    result=subprocess.run([os.environ.get('GO_NATIVE_NODE','node'),
        '--experimental-strip-types','--input-type=module','-e',script],
        cwd=ROOT,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    matrix=(ROOT/'mobile/go-app/qa/REAL_DEVICE_MATRIX.md').read_text()
    assert 'no offline financial mutation' in matrix.lower()

def test_push_receipt_internal_api_is_not_public(client):
    headers=auth(client,'2bapi@example.com')
    client.cookies.clear()
    endpoints=[('POST','/internal/v1/mobile/push-receipts/process'),
               ('GET','/internal/v1/mobile/notifications/none/push-receipts')]
    for method,path in endpoints:
        anonymous=client.request(method,path)
        assert anonymous.status_code==401
        assert anonymous.json()['detail']=='AUTHENTICATION_REQUIRED'
        consumer=client.request(method,path,headers=headers)
        assert consumer.status_code==403
        assert consumer.json()['detail']=='GO_ADMIN_REQUIRED'
