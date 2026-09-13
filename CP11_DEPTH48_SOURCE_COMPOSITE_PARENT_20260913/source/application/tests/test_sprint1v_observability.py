from go_hotel.observability.metrics import metrics


def test_health_trace_and_metrics(client):
    r=client.get('/health'); assert r.status_code==200; assert r.headers.get('X-Trace-ID')
    m=client.get('/metrics'); assert m.status_code==200; assert 'go_http_requests_total' in m.text


def test_security_headers_present(client):
    r=client.get('/health'); assert r.headers['X-Frame-Options']=='DENY'; assert 'Content-Security-Policy' in r.headers


def test_slo_registry_has_api_availability():
    from go_hotel.observability.slo import current_slo_status
    assert any(x['key']=='api_availability' for x in current_slo_status())
