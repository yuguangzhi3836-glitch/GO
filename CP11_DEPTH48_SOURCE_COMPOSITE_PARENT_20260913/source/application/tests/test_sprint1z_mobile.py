def register(client,email='mobile@example.com'):
    r=client.post('/v1/consumer/auth/register',json={'email':email,'password':'StrongPass123!','display_name':'Mobile Traveler'})
    assert r.status_code==200,r.text
    return r.json()['data']['profile']

def mobile_tokens(client,email='mobile@example.com'):
    r=client.post('/v1/mobile/auth/login',json={'email':email,'password':'StrongPass123!'})
    assert r.status_code==200,r.text
    d=r.json()['data']; assert d['access_token'] and d['refresh_token']; assert 'csrf_token' not in d
    return d

def test_native_bearer_session_device_push_and_refresh(client):
    register(client); t=mobile_tokens(client); h={'Authorization':f"Bearer {t['access_token']}"}
    d=client.post('/v1/mobile/devices',headers=h,json={'device_id':'ios-device-001','platform':'IOS','app_version':'1.0.0','device_model':'iPhone','os_version':'18','push_provider':'APNS','push_token':'apns-secret-token','notifications_enabled':True})
    assert d.status_code==200,d.text
    assert d.json()['data']['push_provider']=='APNS'
    assert 'apns-secret-token' not in d.text
    items=client.get('/v1/mobile/devices',headers=h).json()['data']['items']; assert items[0]['device_id']=='ios-device-001'
    rr=client.post('/v1/mobile/auth/refresh',json={'refresh_token':t['refresh_token']})
    assert rr.status_code==200; assert rr.json()['data']['refresh_token']!=t['refresh_token']

def test_deep_links_are_allowlisted(client):
    register(client); t=mobile_tokens(client); h={'Authorization':f"Bearer {t['access_token']}"}
    ok=client.post('/v1/mobile/deep-links/resolve',headers=h,json={'url':'go://trips/order/ord_123'})
    assert ok.status_code==200 and ok.json()['data']['route']=='ORDER_DETAIL'
    bad=client.post('/v1/mobile/deep-links/resolve',headers=h,json={'url':'https://evil.example/steal'})
    assert bad.status_code==422

def test_push_token_not_returned_and_device_is_user_scoped(client):
    register(client); t=mobile_tokens(client); h={'Authorization':f"Bearer {t['access_token']}"}
    client.post('/v1/mobile/devices',headers=h,json={'device_id':'shared-device','platform':'ANDROID','push_provider':'FCM','push_token':'fcm-one','notifications_enabled':True})
    client.post('/v1/consumer/auth/logout',headers={'X-CSRF-Token':client.cookies.get('go_consumer_csrf')})
    register(client,'mobile2@example.com'); t2=mobile_tokens(client,'mobile2@example.com'); h2={'Authorization':f"Bearer {t2['access_token']}"}
    conflict=client.post('/v1/mobile/devices',headers=h2,json={'device_id':'shared-device','platform':'ANDROID'})
    assert conflict.status_code==422
