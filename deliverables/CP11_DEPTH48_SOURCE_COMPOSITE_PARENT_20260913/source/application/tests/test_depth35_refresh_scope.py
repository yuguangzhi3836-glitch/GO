"""Isolated HTTP/SQLite sessions. No browser, credentials service, or Hong Kong."""
import pytest
from sqlalchemy import select
from go_hotel.security.service import identity_service
from go_hotel.db.session import SessionLocal
from go_hotel.db.models import AuthSessionRow, RefreshTokenRow


def tokens(client,actor):
    if actor=='CONSUMER':
        body={'email':'depth35@example.test','password':'Isolated-Depth35-Only!','display_name':'Isolated consumer'}
        r=client.post('/v1/consumer/auth/register',json=body)
        assert r.status_code==200,r.text
        result=identity_service.login(body['email'],body['password'])
    else:
        username,password=('supplier_owner','change-me-supplier') if actor=='SUPPLIER_USER' else ('go_admin','change-me-admin')
        result=identity_service.login(username,password)
    client.cookies.clear()
    return result


def state(t):
    principal=identity_service.authenticate(t['access_token'])
    with SessionLocal() as session:
        row=session.get(AuthSessionRow,principal.session_id)
        refresh=session.scalars(select(RefreshTokenRow).where(RefreshTokenRow.session_id==principal.session_id)).all()
        return row.csrf_token_hash,sorted((r.token_id,r.status,r.token_hash) for r in refresh)


@pytest.mark.parametrize('actor',['SUPPLIER_USER','GO_ADMIN'])
@pytest.mark.parametrize('route',['/v1/mobile/auth/refresh','/v1/consumer/auth/refresh'])
def test_wrong_consumer_end_does_not_consume_console_refresh_or_csrf(client,actor,route):
    t=tokens(client,actor);before=state(t)
    if route.startswith('/v1/mobile'):
        r=client.post(route,json={'refresh_token':t['refresh_token']})
    else:
        for name,key in [('go_consumer_access','access_token'),('go_consumer_refresh','refresh_token'),('go_consumer_csrf','csrf_token')]:
            client.cookies.set(name,t[key])
        r=client.post(route,headers={'X-CSRF-Token':t['csrf_token']})
    assert r.status_code==401,r.text
    assert r.json()['detail']=='ACCOUNT_TYPE_MISMATCH'
    assert not r.headers.get('set-cookie')
    assert state(t)==before
    rotated=identity_service.refresh(t['refresh_token'],allowed_actor_types={actor})
    assert identity_service.authenticate(rotated['access_token']).actor_type==actor


def test_console_end_does_not_consume_consumer_refresh(client):
    t=tokens(client,'CONSUMER');before=state(t)
    for name,key in [('go_access','access_token'),('go_refresh','refresh_token'),('go_csrf','csrf_token')]:
        client.cookies.set(name,t[key])
    r=client.post('/bff/auth/refresh',headers={'X-CSRF-Token':t['csrf_token']})
    assert r.status_code==401,r.text
    assert r.json()['detail']=='ACCOUNT_TYPE_MISMATCH'
    assert not r.headers.get('set-cookie');assert state(t)==before
    client.cookies.clear()
    assert client.post('/v1/mobile/auth/refresh',json={'refresh_token':t['refresh_token']}).status_code==200


@pytest.mark.parametrize('actor',['CONSUMER','SUPPLIER_USER','GO_ADMIN'])
def test_matching_end_rotates_once_and_old_refresh_cannot_be_reused(client,actor):
    t=tokens(client,actor)
    if actor=='CONSUMER':
        r=client.post('/v1/mobile/auth/refresh',json={'refresh_token':t['refresh_token']})
        assert r.status_code==200,r.text
        current=r.json()['data'];assert 'csrf_token' not in current
    else:
        # Use a request Cookie header: a domainless test-cookie jar entry would
        # coexist with Set-Cookie for testserver.local and make get() ambiguous.
        cookie='; '.join(f'{name}={t[key]}' for name,key in
                        [('go_access','access_token'),('go_refresh','refresh_token'),('go_csrf','csrf_token')])
        r=client.post('/bff/auth/refresh',headers={'X-CSRF-Token':t['csrf_token'],'Cookie':cookie})
        assert r.status_code==200,r.text
        current={'access_token':client.cookies.get('go_access'),'refresh_token':client.cookies.get('go_refresh')}
    assert current['refresh_token']!=t['refresh_token']
    assert identity_service.authenticate(current['access_token']).actor_type==actor
    with pytest.raises(ValueError,match='INVALID_REFRESH_TOKEN'):
        identity_service.refresh(t['refresh_token'])


def test_mobile_logout_revokes_only_its_bearer_session_and_refresh(client):
    consumer=tokens(client,'CONSUMER');console=tokens(client,'SUPPLIER_USER')
    r=client.post('/v1/consumer/auth/logout',headers={'Authorization':'Bearer '+consumer['access_token']})
    assert r.status_code==200 and r.json()['data']['status']=='REVOKED',r.text
    with pytest.raises(ValueError,match='SESSION_REVOKED'):
        identity_service.authenticate(consumer['access_token'])
    with pytest.raises(ValueError,match='INVALID_REFRESH_TOKEN'):
        identity_service.refresh(consumer['refresh_token'])
    assert identity_service.authenticate(console['access_token']).actor_type=='SUPPLIER_USER'
