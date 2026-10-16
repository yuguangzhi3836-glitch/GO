"""Explicit disposable-PostgreSQL override after the legacy SQLite conftest.

Load only with -p ci.unknown_pg_plugin in the dedicated CI job. Refuse every
endpoint except the fixed loopback disposable database, before any schema reset.
"""
import json
import os
from pathlib import Path
import sys
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    url = make_url(os.environ['GO_UNKNOWN_PG_TEST_URL'])
    if (url.drivername != 'postgresql+psycopg' or url.host != '127.0.0.1'
            or url.port != 5432 or url.database != 'go_unknown_isolated'
            or url.username != 'go_ci' or url.query
            or os.environ.get('GO_UNKNOWN_DISPOSABLE_DB') != 'YES'):
        raise pytest.UsageError('UNKNOWN_DISPOSABLE_DATABASE_REQUIRED')
    if 'go_hotel.db.session' in sys.modules or 'go_hotel.core.config' in sys.modules:
        raise pytest.UsageError('UNKNOWN_DATABASE_SELECTED_TOO_LATE')
    os.environ['DATABASE_URL'] = url.render_as_string(hide_password=False)
    with create_engine(url).connect() as connection:
        version = int(connection.scalar(text('SHOW server_version_num')))
        database = connection.scalar(text('SELECT current_database()'))
    if version != 180004 or database != 'go_unknown_isolated':
        raise pytest.UsageError('UNKNOWN_POSTGRES_18_4_REQUIRED')
    from go_hotel.db.session import engine
    if engine.dialect.name != 'postgresql' or engine.url != url:
        raise pytest.UsageError('UNKNOWN_APPLICATION_DATABASE_MISMATCH')
    evidence = {'dialect': engine.dialect.name, 'server_version_num': version,
                'database': database, 'candidate_sha': os.environ['GO_UNKNOWN_CANDIDATE_SHA']}
    Path(os.environ['GO_UNKNOWN_DB_EVIDENCE']).write_text(json.dumps(evidence, indent=2) + '\n')
