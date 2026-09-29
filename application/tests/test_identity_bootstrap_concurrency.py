"""Concurrent first startup must converge without overwriting an existing user."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from go_hotel.db.models import IdentityUserRow
from go_hotel.security import service
from go_hotel.security.crypto import verify_password

pytestmark = pytest.mark.no_db


@pytest.fixture(params=["sqlite", "postgres"])
def isolated_identity(request, tmp_path, monkeypatch):
    schema = None
    if request.param == "postgres":
        url = os.getenv("GO_POOL_TEST_DATABASE_URL")
        if not url:
            pytest.skip("isolated PostgreSQL not supplied")
        parsed = make_url(url)
        assert parsed.get_backend_name() == "postgresql"
        assert parsed.host in {"127.0.0.1", "localhost"}
        assert parsed.database == "go_capacity_isolated"
        engine = create_engine(url)
        schema = "bootstrap_" + uuid.uuid4().hex
        with engine.begin() as c:
            c.execute(text(f'CREATE SCHEMA "{schema}"'))
        bound = engine.execution_options(schema_translate_map={None: schema})
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'identity.db'}")
        bound = engine
    IdentityUserRow.__table__.create(bound)
    factory = sessionmaker(bind=bound, expire_on_commit=False)
    monkeypatch.setattr(service, "SessionLocal", factory)
    try:
        yield factory
    finally:
        if schema:
            with engine.begin() as c:
                c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def test_two_first_startups_converge_on_one_account(isolated_identity, monkeypatch):
    barrier = Barrier(2)
    original = service.hash_password
    def synchronize_after_missing_user(password):
        barrier.wait(timeout=10)
        return original(password)
    monkeypatch.setattr(service, "hash_password", synchronize_after_missing_user)
    def create():
        return service.identity_service.ensure_user("concurrent", "strong-test-password", "GO_ADMIN", None, ["GO_READ_ONLY"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(create) for _ in range(2)]
        ids = [task.result(timeout=15) for task in tasks]
    assert ids[0] == ids[1]
    with isolated_identity() as s:
        assert s.scalar(select(func.count()).select_from(IdentityUserRow)) == 1
        row = s.get(IdentityUserRow, ids[0])
        assert row.roles == ["GO_READ_ONLY"]
        assert verify_password("strong-test-password", row.password_hash)


def test_existing_identity_is_never_overwritten(isolated_identity):
    identity = service.identity_service
    old = identity.ensure_user("existing", "original-test-password", "SUPPLIER_USER", "supplier-a", ["SUPPLIER_VIEWER"])
    assert identity.ensure_user("existing", "different-password", "GO_ADMIN", None, ["GO_GOVERNANCE"]) == old
    with isolated_identity() as s:
        row = s.get(IdentityUserRow, old)
        assert row.actor_type == "SUPPLIER_USER"
        assert row.supplier_id == "supplier-a"
        assert row.roles == ["SUPPLIER_VIEWER"]
        assert verify_password("original-test-password", row.password_hash)


def test_unrelated_integrity_error_is_not_swallowed(isolated_identity, monkeypatch):
    identity = service.identity_service
    old = identity.ensure_user("first", "test-password", "GO_ADMIN", None, [])
    monkeypatch.setattr(service, "uid", lambda prefix: old)
    with pytest.raises(IntegrityError):
        identity.ensure_user("different-name", "test-password", "GO_ADMIN", None, [])
    with isolated_identity() as s:
        assert s.scalar(select(func.count()).select_from(IdentityUserRow)) == 1
