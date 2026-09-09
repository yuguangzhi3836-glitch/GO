"""Only runs on the disposable CI PostgreSQL service, never a deployed database."""
import os
import sys
from pathlib import Path
import pytest

url = os.environ['POSTGRES_TEST_DATABASE_URL']
if url != 'postgresql+psycopg://go@localhost:5432/go':
    raise RuntimeError('DISPOSABLE_CI_DATABASE_REQUIRED')
os.environ['DATABASE_URL'] = url
project = Path(__file__).resolve().parents[2] / 'source'
sys.path.insert(0, str(project / 'tests'))
sys.path.insert(0, str(project / 'src'))


@pytest.fixture(autouse=True)
def clean_database(request):
    if request.node.get_closest_marker('no_db'):
        yield
        return
    from go_hotel.db.models import Base
    from go_hotel.db.session import engine
    from go_hotel.security.service import identity_service
    from go_hotel.connectors.mock_hotel import connector
    from go_hotel.payments.mock import payment_provider
    from go_hotel.core.faults import faults
    from sqlalchemy import text
    assert engine.dialect.name == 'postgresql'
    names = ','.join(engine.dialect.identifier_preparer.quote(t.name) for t in Base.metadata.sorted_tables)
    with engine.begin() as s:s.execute(text('TRUNCATE TABLE ' + names + ' RESTART IDENTITY CASCADE'))
    identity_service.bootstrap()
    connector.reset();payment_provider.reset();faults.clear()
    yield
    faults.clear();engine.dispose(close=True)
