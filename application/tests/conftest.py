import os
import sys
import shutil
import tempfile
import uuid
import hashlib
from pathlib import Path
import pytest

# Apply to every application test before terminal/JUnit evidence is emitted.
_application_root = str(Path(__file__).resolve().parents[1])
if _application_root not in sys.path:
    sys.path.insert(0, _application_root)
from tests.evidence_hygiene_plugin import pytest_runtest_makereport, pytest_make_collect_report

# tempfile is portable across the Windows review workstation and Linux Staging.
# Isolated PostgreSQL evidence jobs set GO_TEST_DATABASE_URL explicitly. All
# other tests retain the deterministic SQLite snapshot; no runtime environment is touched.
_test_database_url=os.getenv("GO_TEST_DATABASE_URL")
if _test_database_url:
    os.environ["DATABASE_URL"]=_test_database_url
else:
    DB = Path(os.getenv("GO_TEST_DB_PATH", str(Path(tempfile.gettempdir()) / f"go_hotel_test_{os.getpid()}_{uuid.uuid4().hex}.db")))
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
    from sqlalchemy.schema import CreateTable
    schema = '\n'.join(str(CreateTable(t).compile(engine)) for t in Base.metadata.sorted_tables)
    schema_hash = hashlib.sha256(schema.encode()).hexdigest()[:16]
    snapshot = live_db.with_suffix(live_db.suffix + '.' + schema_hash + '.pristine')
    if not snapshot.exists():
        live_db.unlink(missing_ok=True)
        Base.metadata.create_all(engine)
        identity_service.bootstrap()
        engine.dispose(close=True)
        shutil.copy2(live_db, snapshot)
    else:
        live_db.unlink(missing_ok=True)
        shutil.copy2(snapshot, live_db)


#: One unusable-by-design placeholder ships in `core.config`; every test that needs
#: a working runtime must replace it, and they must all replace it with the *same*
#: bytes. Kept in one place because a key that differs between two fixtures is
#: indistinguishable from a session bug: the token was minted under one key and is
#: verified under another.
SYNTHETIC_SIGNING_KEY = "synthetic-identity-flow-test-key-32b"


@pytest.fixture(autouse=True, scope="session")
def signing_key_that_can_actually_digest():
    """A usable signing key for the whole session, at *session* scope on purpose.

    Two shipped doors refuse to work under the placeholder key (under 32 bytes, or
    starting with ``dev-``): ``registration_verification.digest()``, so every code
    and recovery endpoint answers 503, and JWT verification, so every session
    cookie answers 401. Scoping the key to a single *test* is not enough: a fixture
    that sets it inside a ``MonkeyPatch.context()`` reverts on exit, and a token
    minted inside that context then fails to verify outside it with
    ``INVALID_SIGNATURE`` — a failure that reads like a session or cookie defect and
    is really a key that moved underneath a live cookie. Set it once here; the
    fixtures that patch it patch the same value, so their reversion is a no-op.
    """
    from go_hotel.core.config import settings

    settings.jwt_signing_key = SYNTHETIC_SIGNING_KEY


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
