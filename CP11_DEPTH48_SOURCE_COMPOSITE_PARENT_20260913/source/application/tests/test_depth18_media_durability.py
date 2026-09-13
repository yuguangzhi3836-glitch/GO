"""Real local SQLite, filesystem, multi-process and SIGKILL evidence; synthetic media only."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3

import httpx
from PIL import Image
import pytest

from go_hotel.services.media_harvester import MediaHarvesterService

pytestmark = pytest.mark.no_db


def service(directory):
    image = BytesIO()
    Image.new('RGB', (96, 80), (20, 60, 90)).save(image, 'PNG')
    return MediaHarvesterService(directory, httpx.MockTransport(
        lambda request: httpx.Response(200, content=image.getvalue(), headers={'content-type':'image/png'})))


def harvest(svc, hotel='hotel-1'):
    return svc.harvest(source_url='https://synthetic.test/photo.png', hotel_id=hotel, role='HERO', allow_private=True)


def approve(svc, asset, **kw):
    return svc.decide_rights(asset, rights_state='AUTHORIZED', actor='synthetic-reviewer',
                            rights_owner='Synthetic hotel', evidence_reference='fixture:license', **kw)


def _parallel_harvest(directory, start, connection, number):
    try:
        svc = service(directory)
        start.wait(10)
        records = [harvest(svc, f'hotel-{number}') for _ in range(8)]
        connection.send([r['asset_id'] for r in records])
    except BaseException as exc:
        connection.send(repr(exc))
    finally:
        connection.close()


def _parallel_rights(directory, asset, start, connection, number):
    try:
        svc = service(directory)
        start.wait(10)
        for index in range(6):
            svc.decide_rights(asset, rights_state='REJECTED', actor=f'worker-{number}-{index}')
        connection.send(True)
    except BaseException as exc:
        connection.send(repr(exc))
    finally:
        connection.close()


def run_processes(target, directory, *args):
    ctx = multiprocessing.get_context('fork')
    start = ctx.Event()
    children = []
    for number in range(4):
        read, write = ctx.Pipe(duplex=False)
        process = ctx.Process(target=target, args=(str(directory), *args, start, write, number))
        process.start()
        write.close()
        children.append((process, read))
    start.set()
    try:
        results = []
        for process, read in children:
            assert read.poll(25), 'child did not finish'
            results.append(read.recv())
            process.join(5)
            assert process.exitcode == 0
        return results
    finally:
        for process, read in children:
            if process.is_alive():
                process.kill()
            process.join(5)
            read.close()


@pytest.mark.skipif(os.name != 'posix', reason='requires process kill / fork')
def test_independent_processes_keep_all_harvests_and_shared_content(tmp_path):
    results = run_processes(_parallel_harvest, tmp_path)
    assert all(isinstance(r, list) and len(r) == 8 for r in results), results
    svc = service(tmp_path)
    records = svc.list_assets()
    assert {r['asset_id'] for r in records} == {a for r in results for a in r}
    assert len(records) == 32
    assert len(list(svc.files_dir.iterdir())) == 1
    for r in records:
        assert svc.content_path(r['asset_id'], require_publishable=False).is_file()


@pytest.mark.skipif(os.name != 'posix', reason='requires process kill / fork')
def test_independent_processes_preserve_every_rights_event(tmp_path):
    svc = service(tmp_path)
    asset = harvest(svc)['asset_id']
    results = run_processes(_parallel_rights, tmp_path, asset)
    assert results == [True] * 4
    rec = service(tmp_path).get(asset)
    assert rec['revision'] == 25
    assert len(rec['rights_history']) == 24
    assert {e['actor'] for e in rec['rights_history']} == {f'worker-{w}-{i}' for w in range(4) for i in range(6)}
    assert not rec['publishable']


def _crash_during_write(directory, asset, connection):
    svc = service(directory)
    original = svc._index.save
    def save_then_wait(db, record, *, revision):
        original(db, record, revision=revision)
        connection.send('written-uncommitted')
        connection.recv()
    svc._index.save = save_then_wait
    if asset:
        approve(svc, asset)
    else:
        harvest(svc, 'uncommitted-hotel')


@pytest.mark.skipif(os.name != 'posix', reason='requires SIGKILL')
@pytest.mark.parametrize('operation', ['harvest', 'rights'])
def test_sigkill_rolls_back_uncommitted_metadata_without_losing_committed_state(tmp_path, operation):
    svc = service(tmp_path)
    prior = harvest(svc)
    svc.decide_rights(prior['asset_id'], rights_state='REJECTED', actor='committed-revoker')
    ctx = multiprocessing.get_context('fork')
    parent, child = ctx.Pipe()
    process = ctx.Process(target=_crash_during_write, args=(str(tmp_path), prior['asset_id'] if operation == 'rights' else None, child))
    process.start()
    child.close()
    try:
        assert parent.poll(15)
        assert parent.recv() == 'written-uncommitted'
        process.kill()
        process.join(5)
        assert process.exitcode == -9
        reopened = service(tmp_path)
        assert len(reopened.list_assets()) == 1
        rec = reopened.get(prior['asset_id'])
        assert rec['rights_state'] == 'REJECTED' and rec['revision'] == 2
        assert len(rec['rights_history']) == 1
        assert reopened.content_path(rec['asset_id'], require_publishable=False).is_file()
        assert len(reopened.list_assets(publishable_only=True)) == 0
        # A new committed write still succeeds after hot-journal recovery.
        assert approve(reopened, rec['asset_id'], expected_revision=2)['revision'] == 3
    finally:
        if process.is_alive():
            process.kill()
        process.join(5)
        parent.close()


def test_stale_snapshot_cannot_erase_harvest_or_restore_revoked_rights(tmp_path):
    first, second = service(tmp_path), service(tmp_path)
    asset = harvest(first)['asset_id']
    approve(first, asset)
    old = first._read_index()
    second.decide_rights(asset, rights_state='REJECTED', actor='reviewer-2')
    new = harvest(second)
    with pytest.raises(ValueError, match='REVISION_CONFLICT'):
        first._write_index(old)
    assert not first.get(asset)['publishable']
    assert first.get(new['asset_id'])


def test_stale_rights_approval_cannot_override_revocation(tmp_path):
    svc = service(tmp_path)
    asset = harvest(svc)
    approved = approve(svc, asset['asset_id'], expected_revision=1)
    svc.decide_rights(asset['asset_id'], rights_state='REJECTED', actor='revoker', expected_revision=approved['revision'])
    with pytest.raises(ValueError, match='REVISION_CONFLICT'):
        approve(service(tmp_path), asset['asset_id'], expected_revision=approved['revision'])
    assert not svc.get(asset['asset_id'])['publishable']


def test_legacy_import_is_once_preserves_original_and_does_not_resurrect_grant(tmp_path):
    original = service(tmp_path / 'original')
    asset = harvest(original)
    approve(original, asset['asset_id'])
    legacy = original._read_index()
    destination = tmp_path / 'migrated'
    destination.mkdir()
    raw = json.dumps(legacy).encode()
    (destination / 'index.json').write_bytes(raw)
    imported = service(destination)
    assert imported.get(asset['asset_id'])['publishable']
    imported.decide_rights(asset['asset_id'], rights_state='REJECTED', actor='after-import')
    assert (destination / 'index.json').read_bytes() == raw
    # Reintroducing the old JSON cannot turn the current rejection into a grant.
    assert not service(destination).get(asset['asset_id'])['publishable']
    assert len(service(destination).get(asset['asset_id'])['rights_history']) == 2
    with sqlite3.connect(destination / 'index.sqlite3') as db:
        assert db.execute('SELECT legacy_sha256 FROM media_meta').fetchone()[0]


@pytest.mark.parametrize('raw', [b'{', b'[]', b'{"version":1,"assets":[]}',
    b'{"version":1,"assets":{"a":{"asset_id":"a","cache_file":"../../outside"}}}'])
def test_corrupt_legacy_is_never_replaced_by_empty_index(tmp_path, raw):
    legacy = tmp_path / 'index.json'
    legacy.write_bytes(raw)
    for _ in range(2):
        with pytest.raises(ValueError, match='MEDIA_LEGACY_INDEX_INVALID'):
            service(tmp_path)
        assert legacy.read_bytes() == raw


@pytest.mark.parametrize('fault', ['owner', 'evidence', 'expiry', 'contract'])
def test_invalid_legacy_rights_are_not_public_even_if_flag_says_true(tmp_path, fault):
    svc = service(tmp_path)
    asset = harvest(svc)['asset_id']
    approve(svc, asset)
    snapshot = svc._read_index()
    rec = snapshot['assets'][asset]
    if fault == 'owner': rec['rights_owner'] = ' '
    elif fault == 'evidence': rec['rights_evidence_reference'] = None
    elif fault == 'expiry': rec['rights_expires_at'] = 'invalid'
    else: rec['rights_state'] = 'DISTRIBUTION_LICENSE'
    svc._write_index(snapshot)
    assert not svc.get(asset)['publishable']
    assert not svc.list_assets(publishable_only=True)
    with pytest.raises(ValueError, match='NOT_PUBLISHABLE'):
        svc.content_path(asset)


def test_purge_keeps_other_hotel_shared_files_and_can_admit_same_hash_again(tmp_path):
    first, second = service(tmp_path), service(tmp_path)
    a, b = harvest(first, 'a'), harvest(second, 'b')
    assert first.purge_hotel('a')['removed_count'] == 1
    assert second.content_path(b['asset_id'], require_publishable=False).is_file()
    assert not first.list_assets(hotel_id='a')
    assert first.purge_hotel('b')['removed_count'] == 1
    assert not list(first.files_dir.iterdir())
    assert second.content_path(harvest(second, 'c')['asset_id'], require_publishable=False).is_file()


def test_concurrent_purge_and_admission_never_remove_referenced_bytes(tmp_path):
    harvest(service(tmp_path), 'purged')
    def admit(_): return harvest(service(tmp_path), 'retained')['asset_id']
    def purge(_): return service(tmp_path).purge_hotel('purged')
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(admit if n % 2 else purge, n) for n in range(24)]
        results = [future.result() for future in futures]
    svc = service(tmp_path)
    assert len(svc.list_assets(hotel_id='retained')) == 12
    for asset in (r for r in results if isinstance(r, str)):
        assert svc.content_path(asset, require_publishable=False).is_file()


def test_admission_rejects_tampered_dedup_file_and_keeps_prior_record(tmp_path):
    svc = service(tmp_path)
    rec = harvest(svc)
    path = svc.content_path(rec['asset_id'], require_publishable=False)
    path.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='INTEGRITY_FAILED'):
        harvest(svc)
    assert len(svc.list_assets()) == 1
    assert path.read_bytes() == b'tampered'
    assert not list(tmp_path.glob('download-*.part'))


def test_index_commit_failure_does_not_publish_or_erase_existing_record(tmp_path, monkeypatch):
    svc = service(tmp_path)
    prior = harvest(svc)
    def fail(*a, **kw): raise RuntimeError('injected write failure')
    monkeypatch.setattr(svc._index, 'save', fail)
    with pytest.raises(RuntimeError, match='injected'):
        harvest(svc)
    reopened = service(tmp_path)
    assert [r['asset_id'] for r in reopened.list_assets()] == [prior['asset_id']]
    assert reopened.content_path(prior['asset_id'], require_publishable=False).is_file()
    assert not list(tmp_path.glob('download-*.part'))


def test_public_route_rechecks_rights_and_never_sends_immutable_cache(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from go_hotel.api.routes import hotel_autopage_factory as routes
    svc = service(tmp_path)
    asset = harvest(svc)['asset_id']
    approve(svc, asset)
    monkeypatch.setattr(routes, 'media_svc', svc)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.get(f'/v1/hotel-media/{asset}')
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        svc.decide_rights(asset, rights_state='REJECTED', actor='revoker')
        denied = client.get(f'/v1/hotel-media/{asset}', headers={'If-None-Match': response.headers['etag']})
        assert denied.status_code == 404
        assert denied.json()['detail'] == 'MEDIA_ASSET_NOT_PUBLISHABLE'


def test_admin_rights_route_requires_current_asset_revision(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from go_hotel.api.routes import hotel_autopage_factory as routes
    svc = service(tmp_path)
    asset = harvest(svc)['asset_id']
    monkeypatch.setattr(routes, 'media_svc', svc)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.catalog_writer] = lambda: SimpleNamespace(user_id='authorized-test-admin')
    body = {'rights_state':'AUTHORIZED', 'rights_owner':'Synthetic hotel', 'evidence_reference':'fixture:license'}
    with TestClient(app) as client:
        url = f'/internal/v1/hotel-autopage/media/{asset}/rights'
        assert client.post(url, json=body).json()['detail'] == 'MEDIA_ASSET_REVISION_REQUIRED'
        assert client.post(url, json={**body, 'expected_revision':True}).status_code == 409
        assert client.post(url, json={**body, 'expected_revision':1}).status_code == 200
        assert client.post(url, json={'rights_state':'REJECTED', 'expected_revision':2}).status_code == 200
        assert client.post(url, json={**body, 'expected_revision':2}).json()['detail'] == 'MEDIA_ASSET_REVISION_CONFLICT'
        assert not svc.get(asset)['publishable']


def test_private_intermediate_redirect_is_blocked_before_network_request(tmp_path, monkeypatch):
    from go_hotel.services import media_harvester as media
    contacted=[]
    def response(request):
        contacted.append(str(request.url))
        return httpx.Response(302, headers={'location':'http://127.0.0.1/private'})
    monkeypatch.setattr(media,'_is_public_ip',lambda host:host=='public.test')
    svc=MediaHarvesterService(tmp_path,httpx.MockTransport(response))
    with pytest.raises(ValueError,match='PRIVATE_OR_UNRESOLVABLE'):
        svc.harvest(source_url='https://public.test/image',hotel_id='h1',role='HERO')
    assert contacted==['https://public.test/image']
    assert not svc.list_assets()


def test_redirect_loop_is_bounded_and_cross_origin_credentials_are_removed(tmp_path):
    headers=[]
    def response(request):
        headers.append(dict(request.headers))
        return httpx.Response(302, headers={'location':'https://other.test/loop'})
    svc=MediaHarvesterService(tmp_path,httpx.MockTransport(response))
    with pytest.raises(ValueError,match='REDIRECT_LIMIT'):
        svc.harvest(source_url='https://original.test/image',hotel_id='h1',role='HERO',allow_private=True,
                    request_headers={'Authorization':'fixture-secret','X-Api-Key':'fixture-key'})
    assert len(headers)==6
    assert headers[0]['authorization']=='fixture-secret'
    assert all('authorization' not in h and 'x-api-key' not in h for h in headers[1:])
    assert not svc.list_assets()


@pytest.mark.parametrize('environment',['production','prod','staging'])
def test_private_test_override_is_disabled_in_deployed_environments(tmp_path,monkeypatch,environment):
    monkeypatch.setenv('APP_ENV',environment)
    with pytest.raises(ValueError,match='MEDIA_PRIVATE_TEST_DISABLED'):
        harvest(service(tmp_path))
