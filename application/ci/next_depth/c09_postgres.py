"""Run C09 acceptance in a random schema of the dedicated loopback PG database.

Does not load tests/conftest.py (which intentionally replaces DATABASE_URL with
SQLite). No business database, migration, remote endpoint or worker setting is used.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import runpy
import sys
import time
import traceback
import uuid
import xml.etree.ElementTree as ET

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence-dir', required=True)
    args = parser.parse_args()
    output = Path(args.evidence_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    application = Path(__file__).resolve().parents[2]
    meta = {'task_id': 'V70-R2-C09-02', 'started_at': datetime.now(timezone.utc).isoformat(),
            'source_commit': os.environ.get('GO_C09_SOURCE_COMMIT'), 'C14': 'PENDING', 'C13': 'PENDING',
            'scope': 'PostgreSQL service transactions, two independent concurrent DB sessions; no HTTP worker/runtime deployment'}
    def finish(status, reason, code):
        meta.update(status=status, reason=reason, finished_at=datetime.now(timezone.utc).isoformat())
        (output/'execution.json').write_text(json.dumps(meta, indent=2)+'\n')
        print(json.dumps({'status': status, 'reason': reason}))
        return code
    raw = os.getenv('GO_C09_RUNTIME_DATABASE_URL')
    if not raw:
        return finish('HOLD', 'ISOLATED_POSTGRES_URL_NOT_SUPPLIED', 2)
    try:
        url = make_url(raw)
    except Exception:
        return finish('HOLD', 'ISOLATED_DATABASE_URL_INVALID', 2)
    if (url.drivername != 'postgresql+psycopg' or url.host not in {'localhost','127.0.0.1','::1'}
        or url.database != 'go_c09_isolated' or url.query
        or not re.fullmatch(r'[0-9a-f]{40}', meta['source_commit'] or '')):
        return finish('HOLD', 'ISOLATED_LOOPBACK_DATABASE_AND_SOURCE_COMMIT_REQUIRED', 2)
    admin = create_engine(url, connect_args={'connect_timeout': 5})
    schema = 'c09_' + uuid.uuid4().hex
    created = False
    try:
        with admin.begin() as connection:
            meta['postgres_server_version'] = connection.scalar(text('SHOW server_version'))
            if meta['postgres_server_version'].split(' ')[0] != '18.4':
                return finish('HOLD', 'POSTGRES_18_4_REQUIRED', 2)
            connection.execute(text('CREATE SCHEMA ' + schema))
            created = True
        # Set the isolated schema before importing the product's engine.
        isolated = url.update_query_dict({'options': '-csearch_path=' + schema})
        os.environ['DATABASE_URL'] = isolated.render_as_string(hide_password=False)
        sys.path.insert(0, str(application/'src'))
        from go_hotel.db.session import engine, SessionLocal
        from go_hotel.db.models import Base
        from sqlalchemy import delete
        import pytest
        files = ['src/go_hotel/judgment/service.py', 'src/go_hotel/judgment/good_hotel_standard.py',
                 'tests/judgment/test_next_depth_concurrent_judgment.py', 'ci/next_depth/c09_postgres.py']
        meta['source_files'] = {name: hashlib.sha256((application/name).read_bytes()).hexdigest() for name in files}
        namespace = runpy.run_path(str(application/'tests/judgment/test_next_depth_concurrent_judgment.py'))
        # Only C09 plus its repository event/outbox tables are needed. All tables
        # are real PostgreSQL tables in the random schema, not mocked sessions.
        names = {'review_session_runtime','risk_event_runtime','risk_remediation_runtime',
                 'judgment_hook_runtime','judgment_evidence_package','judgment_runtime',
                 'recommendation_decision_runtime','good_hotel_standard_version',
                 'good_hotel_standard_assessment','good_hotel_standard_governance_event'}
        from go_hotel.db.models import EventRow, OutboxRow, ReviewSessionRow, RiskEventRuntimeRow, RiskRemediationRow
        names.update(x.__tablename__ for x in (EventRow,OutboxRow,ReviewSessionRow,RiskEventRuntimeRow,RiskRemediationRow))
        tables = [table for table in Base.metadata.sorted_tables if table.name in names]
        Base.metadata.create_all(engine, tables=tables)
        suite = ET.Element('testsuite', name='C09 PostgreSQL 18.4')
        results = []
        for name, test in namespace.items():
            if not name.startswith('test_') or not callable(test):
                continue
            with SessionLocal.begin() as session:
                for table in reversed(tables):
                    session.execute(delete(table))
            started = time.monotonic()
            case = ET.SubElement(suite, 'testcase', name=name)
            try:
                with pytest.MonkeyPatch.context() as patch:
                    test(**({'monkeypatch': patch} if 'monkeypatch' in inspect.signature(test).parameters else {}))
                results.append({'test': name, 'status': 'PASS'})
            except Exception:
                failure = traceback.format_exc()
                ET.SubElement(case, 'failure').text = failure
                results.append({'test': name, 'status': 'FAIL', 'traceback': failure})
            case.set('time', str(time.monotonic()-started))
        failures = sum(x['status'] == 'FAIL' for x in results)
        suite.set('tests', str(len(results)))
        suite.set('failures', str(failures))
        ET.ElementTree(suite).write(output/'junit.xml', encoding='utf-8', xml_declaration=True)
        (output/'results.json').write_text(json.dumps(results, indent=2)+'\n')
        (output/'raw.log').write_text('\n'.join(x['test']+' '+x['status']+'\n'+x.get('traceback','') for x in results)+'\n')
        meta.update(tests=len(results), failures=failures, schema=schema)
        engine.dispose()
        return finish('TEST_FAILED' if failures else 'EVIDENCE_READY', 'INDEPENDENT_REVIEW_PENDING', 1 if failures else 0)
    except Exception as exc:
        meta['error_type'] = type(exc).__name__
        return finish('HOLD', 'ISOLATED_POSTGRES_EXECUTION_UNAVAILABLE', 2)
    finally:
        if created:
            with admin.begin() as connection:
                connection.execute(text('DROP SCHEMA ' + schema + ' CASCADE'))
        admin.dispose()


if __name__ == '__main__':
    sys.exit(main())
