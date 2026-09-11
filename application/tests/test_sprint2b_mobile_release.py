from pathlib import Path
from sqlalchemy import select
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import MobilePushReceiptRow
from go_hotel.mobile.orchestration import mobile_engagement
from go_hotel.mobile.push import push_worker, push_receipt_worker
from go_hotel.core.config import settings

ROOT=Path(__file__).resolve().parents[1]

def auth(client,email='2b@example.com'):
    client.post('/v1/consumer/auth/register',json={'email':email,'password':'StrongPass123!','display_name':'2B'})
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
    network=(ROOT/'mobile/go-app/src/api/client.ts').read_text()
    assert 'NETWORK_OFFLINE_RETRY_REQUIRED' in network
    assert "Idempotency-Key" in network
    matrix=(ROOT/'mobile/go-app/qa/REAL_DEVICE_MATRIX.md').read_text()
    assert 'no offline financial mutation' in matrix.lower()

def test_push_receipt_internal_api_is_not_public(client):
    auth(client,'2bapi@example.com')
    assert client.post('/internal/v1/mobile/push-receipts/process').status_code==403
    assert client.get('/internal/v1/mobile/notifications/none/push-receipts').status_code==403
