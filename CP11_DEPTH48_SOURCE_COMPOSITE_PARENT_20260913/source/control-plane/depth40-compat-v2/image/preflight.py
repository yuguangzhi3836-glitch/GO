"""Candidate and READ ONLY database/configuration gate; no schema or data repair."""
import hashlib
import json
import os
from pathlib import Path
import sys

TREE = '64f5d78a17b2fa2194b18f9bc1ba0cafbf0f2547f0171a859dd4300c75e37667'
HEAD = '0132_rail_runtime_field_widths'
SOURCE = Path('/opt/go/source')
FINGERPRINT = Path('/opt/go/SOURCE_FINGERPRINT.json')
WORKERS = {
    'recovery-worker': 'recovery_worker',
    'outbox-worker': 'outbox_worker',
    'mobile-push-receipt-worker': 'mobile_push_receipt_worker',
    'reconciliation-worker': 'reconciliation_worker',
    'mobile-push-worker': 'mobile_push_worker',
    'mobile-engagement-worker': 'mobile_engagement_worker',
    'judgment-worker': 'judgment_worker',
}


class Hold(Exception):
    def __init__(self, code, detail=None):
        self.code, self.detail = code, detail
        super().__init__(code)


def verify_source(source=SOURCE, fingerprint=FINGERPRINT):
    fp = json.loads(fingerprint.read_text())
    actual = {}
    for p in source.rglob('*'):
        if p.is_symlink():
            raise Hold('SOURCE_SYMLINK')
        if p.is_file():
            actual[p.relative_to(source).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    calculated = hashlib.sha256(''.join(f'{k}\0{v}\n' for k, v in sorted(actual.items())).encode()).hexdigest()
    if actual != fp or len(actual) != 1271 or calculated != TREE:
        raise Hold('SOURCE_TREE_MISMATCH')
    return {'source_tree_sha256': calculated, 'files': len(actual)}


def config_gate():
    from sqlalchemy.engine import make_url
    # Values come only from the operator's approved runtime mapping. Never print them.
    required = ('APP_ENV', 'DATABASE_URL', 'REDIS_URL', 'JWT_SIGNING_KEY',
                'CONNECTOR_VAULT_MASTER_KEY', 'WEBHOOK_SECRET', 'BOOTSTRAP_ADMIN_USERNAME',
                'BOOTSTRAP_ADMIN_PASSWORD', 'BOOTSTRAP_SUPPLIER_USERNAME',
                'BOOTSTRAP_SUPPLIER_PASSWORD', 'BOOTSTRAP_SUPPLIER_ID', 'COOKIE_SECURE',
                'MFA_REQUIRED_FOR_ADMIN', 'OUTBOX_TRANSPORT', 'MOBILE_PUSH_MODE',
                'HOSTED_RESERVATION_EXPIRY_WORKER_ENABLED', 'VERTICAL_RESERVATION_EXPIRY_WORKER_ENABLED',
                'GO_MEDIA_CACHE_DIR')
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise Hold('CONFIG_NAMES_MISSING', missing)
    if os.environ['APP_ENV'] != 'staging':
        raise Hold('STAGING_ENV_REQUIRED')
    url = make_url(os.environ['DATABASE_URL'])
    if url.drivername != 'postgresql+psycopg' or not url.host or not url.database:
        raise Hold('POSTGRES_PSYCOPG_REQUIRED')
    # Do not permit connection options to override the read-only guard/search path.
    if set(url.query) - {'sslmode', 'sslrootcert', 'sslcert', 'sslkey', 'connect_timeout'}:
        raise Hold('DATABASE_QUERY_OPTIONS_UNREVIEWED')
    if os.environ['OUTBOX_TRANSPORT'] not in {'redis', 'logging'} or os.environ['MOBILE_PUSH_MODE'] != 'mock':
        raise Hold('EXTERNAL_DELIVERY_MODE_UNREVIEWED')
    for k in ('COOKIE_SECURE', 'MFA_REQUIRED_FOR_ADMIN', 'HOSTED_RESERVATION_EXPIRY_WORKER_ENABLED',
              'VERTICAL_RESERVATION_EXPIRY_WORKER_ENABLED'):
        if os.environ[k].lower() not in {'true', 'false'}:
            raise Hold('BOOLEAN_CONFIG_INVALID', [k])
    defaults = {'dev-only-change-me', 'dev-only-change-me-jwt', 'dev-webhook-secret',
                'change-me-admin', 'change-me-supplier'}
    for k in ('JWT_SIGNING_KEY', 'CONNECTOR_VAULT_MASTER_KEY', 'WEBHOOK_SECRET',
              'BOOTSTRAP_ADMIN_PASSWORD', 'BOOTSTRAP_SUPPLIER_PASSWORD'):
        if os.environ[k] in defaults:
            raise Hold('DEFAULT_CREDENTIAL_REJECTED', [k])
    return {'configuration_names': sorted(required)}


def critical_column_gate(rows):
    """Accept explicit PostgreSQL varchar/text types, never an unknown NULL width."""
    columns = {(r[0], r[1]): (r[2], r[3], r[4]) for r in rows}
    for key, minimum in {('rail_order_runtime', 'status'): 64,
                         ('rail_order_runtime', 'booking_reference'): 128}.items():
        if key not in columns:
            raise Hold('DATABASE_REQUIRED_COLUMNS_MISSING', ['.'.join(key)])
        length, data_type, udt_name = columns[key]
        if (data_type, udt_name) not in {('character varying', 'varchar'), ('text', 'text')}:
            raise Hold('DATABASE_CRITICAL_TYPE_MISMATCH', list(key))
        if length is not None and (isinstance(length, bool) or not isinstance(length, int) or length < minimum):
            raise Hold('DATABASE_CRITICAL_WIDTH_MISMATCH', list(key))
    return columns


def database_gate():
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool
    from go_hotel.db.models import Base
    engine = create_engine(os.environ['DATABASE_URL'], poolclass=NullPool,
                          connect_args={'connect_timeout': 5, 'options':
                              '-c default_transaction_read_only=on -c statement_timeout=15000 -c search_path=public'})
    try:
        with engine.connect() as conn:
            with conn.begin():
                if conn.execute(text('SHOW transaction_read_only')).scalar_one() != 'on':
                    raise Hold('READ_ONLY_TRANSACTION_REQUIRED')
                heads = list(conn.execute(text('SELECT version_num FROM public.alembic_version')).scalars())
                if heads != [HEAD]:
                    raise Hold('DATABASE_HEAD_MISMATCH', {'observed_heads': heads, 'required_head': HEAD})
                rows = conn.execute(text("SELECT table_name,column_name,character_maximum_length,data_type,udt_name "
                    "FROM information_schema.columns WHERE table_schema='public'")).all()
                columns = {(r[0], r[1]): r[2] for r in rows}
                missing = sorted(f'{t.name}.{c.name}' for t in Base.metadata.tables.values()
                                 for c in t.columns if (t.name, c.name) not in columns)
                if missing:
                    raise Hold('DATABASE_REQUIRED_COLUMNS_MISSING', missing)
                critical_column_gate(rows)
                # Startup calls ensure_user(). Require existing principals to prevent implicit provisioning.
                identities = []
                for prefix, actor in [('ADMIN', 'GO_ADMIN'), ('SUPPLIER', 'SUPPLIER_USER')]:
                    row = conn.execute(text('SELECT actor_type,status,supplier_id FROM public.identity_user '
                        'WHERE username=:username'), {'username': os.environ['BOOTSTRAP_'+prefix+'_USERNAME']}).one_or_none()
                    if row is None or row[0] != actor or row[1] != 'ACTIVE':
                        raise Hold('EXISTING_BOOTSTRAP_IDENTITY_REQUIRED', [prefix])
                    if prefix == 'SUPPLIER' and row[2] != os.environ['BOOTSTRAP_SUPPLIER_ID']:
                        raise Hold('SUPPLIER_IDENTITY_BINDING_MISMATCH')
                    identities.append(prefix)
                version = conn.execute(text('SHOW server_version')).scalar_one()
                return {'head': heads[0], 'server_version': version, 'transaction_read_only': True,
                        'required_columns': sum(len(t.columns) for t in Base.metadata.tables.values()),
                        'existing_bootstrap_identities': identities, 'migration_executed': False}
    finally:
        engine.dispose()


def redis_gate():
    import redis
    from urllib.parse import urlsplit
    if urlsplit(os.environ['REDIS_URL']).scheme not in {'redis', 'rediss'}:
        raise Hold('REDIS_URL_INVALID')
    client = redis.Redis.from_url(os.environ['REDIS_URL'], socket_connect_timeout=5, socket_timeout=5)
    try:
        if not client.ping():
            raise Hold('REDIS_PING_FAILED')
        return {'ping': True, 'data_write': False}
    finally:
        client.close()


def media_gate():
    import sqlite3
    path=Path(os.environ['GO_MEDIA_CACHE_DIR'])
    if str(path) != '/state/media' or any(p.is_symlink() for p in (path, path.parent)):
        raise Hold('FIXED_MEDIA_VOLUME_MAPPING_REQUIRED')
    db=path/'index.sqlite3'
    if not path.is_dir() or not (path/'files').is_dir() or not db.is_file() or db.is_symlink():
        raise Hold('PREEXISTING_DURABLE_MEDIA_INDEX_REQUIRED')
    if not os.access(path, os.W_OK) or not os.access(path/'files',os.W_OK) or not os.access(db,os.W_OK):
        raise Hold('MEDIA_VOLUME_PERMISSION_MISMATCH')
    conn=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=5)
    try:
        conn.execute('PRAGMA query_only=ON')
        meta=conn.execute('SELECT id,schema_version FROM media_meta').fetchall()
        if meta != [(1,1)]:
            raise Hold('MEDIA_INDEX_SCHEMA_MISMATCH')
        conn.execute('SELECT asset_id,hotel_id,cache_file,revision,record FROM media_assets LIMIT 0')
    finally:
        conn.close()
    return {'path':'/state/media','schema_version':1,'check_read_only':True,'legacy_import_executed':False}


def run():
    return {'source': verify_source(), 'config': config_gate(), 'database': database_gate(),
            'redis': redis_gate(), 'media': media_gate()}


def emit_failure(exc):
    record = {'status': 'HOLD', 'code': exc.code if isinstance(exc, Hold) else 'PREFLIGHT_ERROR',
              'exception_type': type(exc).__name__, 'migration_executed': False}
    if isinstance(exc, Hold) and exc.detail is not None:
        record['detail'] = exc.detail
    # Never print generic exception strings: drivers can include a credential-bearing URL.
    print(json.dumps(record), flush=True)


if __name__ == '__main__':
    try:
        print(json.dumps({'status': 'PASS_READ_ONLY', **run()}))
    except Exception as exc:
        emit_failure(exc)
        sys.exit(2)
