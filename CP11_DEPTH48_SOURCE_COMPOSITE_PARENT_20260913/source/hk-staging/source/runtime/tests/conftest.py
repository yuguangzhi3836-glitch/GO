import os
import shutil
import tempfile
from pathlib import Path
import pytest

# tempfile is portable across the Windows review workstation and Linux Staging.
DB = Path(os.getenv("GO_TEST_DB_PATH", str(Path(tempfile.gettempdir()) / f"go_hotel_test_{os.getpid()}.db")))
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{DB}"
os.environ["SAGA_RETRY_SECONDS"] = "0"
os.environ["OUTBOX_MAX_ATTEMPTS"] = "5"


def _restore_sqlite_snapshot(Base, engine, identity_service):
    """Fast deterministic reset for the very large RC20 SQLite test schema.

    Creating the full metadata graph before every test takes ~15s on the review
    runner and made complete vertical suites look hung. Build a pristine DB once,
    then restore the file between tests. This is test-only and never changes RDS.
    """
    engine.dispose(close=True)
    live_db = Path(str(engine.url.database))
    snapshot = live_db.with_suffix(live_db.suffix + '.pristine')
    if not snapshot.exists():
        live_db.unlink(missing_ok=True)
        Base.metadata.create_all(engine)
        identity_service.bootstrap()
        engine.dispose(close=True)
        shutil.copy2(live_db, snapshot)
    else:
        live_db.unlink(missing_ok=True)
        shutil.copy2(snapshot, live_db)


@pytest.fixture(autouse=True)
def reset_db(request):
    if request.node.get_closest_marker("no_db"):
        yield
        return

    from go_hotel.db.models import Base
    from go_hotel.db.session import engine
    from go_hotel.connectors.mock_hotel import connector
    from go_hotel.payments.mock import payment_provider
    from go_hotel.core.faults import faults
    from go_hotel.security.service import identity_service

    if engine.url.get_backend_name() == "sqlite":
        _restore_sqlite_snapshot(Base, engine, identity_service)
    else:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        identity_service.bootstrap()
    connector.reset()
    payment_provider.reset()
    faults.clear()
    try:
        yield
    finally:
        faults.clear()
        connector.reset()
        payment_provider.reset()
        engine.dispose(close=True)


@pytest.fixture
def client():
    """Create a fully managed TestClient for tests that need HTTP runtime."""
    from fastapi.testclient import TestClient
    from go_hotel.db.models import Base
    from go_hotel.db.session import engine

    Base.metadata.create_all(engine)
    from go_hotel.main import app

    with TestClient(app) as test_client:
        yield test_client
