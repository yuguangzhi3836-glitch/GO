"""The shipped isolated demo uses APP_ENV=demo; its queue must be usable."""
from go_hotel.autonomy.operations import application_executor
from go_hotel.core.config import settings


def test_shipped_demo_environment_can_observe_without_production_authority(client, monkeypatch):
    monkeypatch.setattr(settings, 'app_env', 'demo')
    login = client.post('/v1/auth/login', json={'username':'go_admin','password':'change-me-admin'})
    assert login.status_code == 200
    client.cookies.clear()
    headers = {'Authorization':'Bearer '+login.json()['data']['access_token']}
    cells = client.get('/internal/v1/autonomy/cells', headers=headers)
    assert cells.status_code == 200 and len(cells.json()['data']) == 14
    queued = client.post('/internal/v1/autonomy/observe', headers=headers,
        json={'idempotency_key':'demo-observation','cell_ids':['C01']})
    assert queued.status_code == 200 and queued.json()['data'][0]['environment'] == 'TEST'
    result = application_executor().run_once('demo-test-worker')
    assert result['status'] == 'SUCCEEDED'
    assert result['result_json']['production_certification'] is False
    assert result['result_json']['business_actions_executed'] is False
