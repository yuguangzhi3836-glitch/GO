def test_connector_list_and_certify(client):
    r=client.get('/internal/v1/connectors'); assert r.status_code==200
    assert r.json()['data'][0]['connector_id']=='conn_mock_hotel'
    r=client.post('/internal/v1/connectors/conn_mock_hotel/certify'); assert r.status_code==200
    assert r.json()['data']['passed'] is True

def test_connector_health(client):
    r=client.get('/internal/v1/connectors/health/all'); assert r.status_code==200
    assert r.json()['data'][0]['healthy'] is True
