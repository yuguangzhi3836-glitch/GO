"""Security boundaries for operation-local image fact reuse."""
import asyncio
import os
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
import pytest
from go_hotel.services.hotel_original_verification_scope import original_verification_scope, original_facts
from go_hotel.services.hotel_autopage_factory import hotel_autopage_factory_service as pages
from test_hotel_direct_submission_publication import publishing
from test_hotel_direct_submission_review import ready
from test_hotel_direct_submission_verification import setup


def trace_reads(monkeypatch, media):
    reads = []
    original = media._read_bytes
    def traced(record):
        reads.append(record['asset_id'])
        return original(record)
    monkeypatch.setattr(media, '_read_bytes', traced)
    return reads


def test_each_operation_reads_once_and_new_operation_rechecks(publishing, monkeypatch):
    pub, review, pid, manifest, factory, verifier, row = publishing
    pub.publish(row['review_id'], 'one', pid, 'admin')
    reads = trace_reads(monkeypatch, verifier.media)
    for operation, expected in [
        (lambda: pages.public_page('test'), 2),
        (lambda: pub.public_content(row['review_id'],manifest['assets'][0]['asset_id']), 3),
        (lambda: review.inspection(row['review_id']), 2),
    ]:
        reads.clear(); operation(); operation()
        assert len(reads) == expected * 2


@pytest.mark.parametrize('mutation',['bytes','same_size_restored_mtime','missing','symlink','sha'])
def test_file_change_inside_scope_is_never_reused(setup, mutation):
    verifier, client, app, pid, manifest, factory = setup
    media = verifier.media
    rec = media._owned_asset('one',pid,manifest['assets'][0]['asset_id'])
    path = media.cache.files_dir / rec['cache_file']
    @original_verification_scope
    def operation():
        original_facts(media,rec)
        if mutation == 'bytes': path.write_bytes(b'corrupt')
        elif mutation == 'same_size_restored_mtime':
            st=path.stat(); path.write_bytes(b'x'*st.st_size)
            os.utime(path,ns=(st.st_atime_ns,st.st_mtime_ns))
        elif mutation == 'missing': path.unlink()
        elif mutation == 'symlink':
            other=path.with_name('replacement.jpg'); other.write_bytes(path.read_bytes())
            path.unlink(); path.symlink_to(other)
        else: rec['sha256']='0'*64
        with pytest.raises((ValueError,OSError)):
            original_facts(media,rec)
    operation()


@pytest.mark.parametrize('mutation',['rights','review','expiry'])
def test_authority_rechecked_within_scope(publishing,mutation):
    pub, review, pid, manifest, factory, verifier, row = publishing
    pub.publish(row['review_id'],'one',pid,'admin')
    @original_verification_scope
    def operation():
        pages.public_page('test')
        if mutation == 'review': review.revoke(row['review_id'],'admin')
        else:
            verifier.media.cache.decide_rights(manifest['assets'][0]['asset_id'],
                rights_state='REJECTED' if mutation=='rights' else 'HOTEL_SUBMITTED',actor='admin',
                rights_owner='Hotel',evidence_reference='review',rights_scope='DISTRIBUTE_ON_GO',
                expires_at='2000-01-01T00:00:00Z' if mutation=='expiry' else None)
        with pytest.raises(ValueError): pages.public_page('test')
        with pytest.raises(ValueError): pub.public_content(row['review_id'],manifest['assets'][0]['asset_id'])
    operation()


def test_exception_clears_cache_and_copied_context_isolated(setup,monkeypatch):
    verifier, client, app, pid, manifest, factory=setup
    media=verifier.media; rec=media._owned_asset('one',pid,manifest['assets'][0]['asset_id'])
    reads=trace_reads(monkeypatch,media); contexts=[]
    @original_verification_scope
    def read(): return original_facts(media,rec)
    @original_verification_scope
    def fail():
        read(); read(); contexts.append(copy_context())
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(copy_context().run,read).result()
        raise ValueError('test')
    with pytest.raises(ValueError): fail()
    contexts[0].run(read); read()
    assert len(reads)==4


def test_inherited_async_context_does_not_reuse_parent_facts(setup,monkeypatch):
    verifier, client, app, pid, manifest, factory=setup
    media=verifier.media; rec=media._owned_asset('one',pid,manifest['assets'][0]['asset_id'])
    reads=trace_reads(monkeypatch,media)
    @original_verification_scope
    def read(): return original_facts(media,rec)
    async def child(): read()
    @original_verification_scope
    def spawn():
        read(); read()
        return asyncio.create_task(child())
    async def parent(): await spawn()
    asyncio.run(parent())
    assert len(reads)==2


def test_active_inherited_context_cannot_share_cache_between_tasks(setup,monkeypatch):
    from go_hotel.services import hotel_original_verification_scope as scope_module
    verifier, client, app, pid, manifest, factory=setup
    media=verifier.media; rec=media._owned_asset('one',pid,manifest['assets'][0]['asset_id'])
    reads=trace_reads(monkeypatch,media)
    @original_verification_scope
    def read(): return original_facts(media,rec)
    async def child(): read(); read()
    async def parent():
        # Simulate a context copied while the synchronous parent scope is still
        # active: no production API needs to span an await to prove isolation.
        state={'owner':scope_module._owner(),'cache':{},'active':True}
        token=scope_module._facts.set(state)
        try:
            read(); read()
            await asyncio.create_task(child())
            read()
        finally:
            state['active']=False; state['cache'].clear()
            scope_module._facts.reset(token)
    asyncio.run(parent())
    assert len(reads)==3  # Parent once; each independent child read once.
