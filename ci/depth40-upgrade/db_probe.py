"""Executed inside the exact image, solely against named disposable CI databases."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool
from identity import BEFORE, AFTER

ap = argparse.ArgumentParser()
ap.add_argument('operation', choices=['snapshot', 'seed', 'long-values', 'lineage'])
ap.add_argument('--baseline')
a = ap.parse_args()
assert os.environ.get('GO_DISPOSABLE_UPGRADE_CI') == 'true'
url = make_url(os.environ['DATABASE_URL'])
assert url.host == 'postgres' and url.database in {'depth40_upgrade_ci', 'depth40_restore_ci'}

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, default=str).encode()).hexdigest()

if a.operation == 'lineage':
    entries = []
    for path in sorted(Path('/opt/go/source/alembic/versions').glob('*.py')):
        if not ('0115' <= path.name[:4] <= '0132'): continue
        tree = ast.parse(path.read_text()); values = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {'revision', 'down_revision'}:
                        values[target.id] = ast.literal_eval(node.value)
        entries.append(dict(path=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(), **values))
    assert len(entries) == 18 and entries[0]['down_revision'] == BEFORE and entries[-1]['revision'] == AFTER
    assert all(b['down_revision'] == x['revision'] for x,b in zip(entries, entries[1:]))
    print(json.dumps({'scope': 'CANDIDATE_MIGRATION_FILES', 'entries': entries}, indent=2))
    sys.exit(0)

engine = create_engine(url, poolclass=NullPool)
with engine.begin() as c:
    if a.operation == 'seed':
        assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == BEFORE
        c.execute(text("INSERT INTO rail_order_runtime VALUES "
            "('ci-rail-1','ci-account','ci-prebook-1','CONFIRMED',123456,'CNY','[]',NULL,"
            "'LEGACY-REF-001','[]','{}','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z'),"
            "('ci-rail-2','ci-account','ci-prebook-2','CANCELLED',99,'CNY','[]',NULL,"
            "NULL,'[]','{}','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"))
        c.execute(text("INSERT INTO mobility_refund_runtime VALUES "
            "('ci-refund-1','ci-rental-1','rental',10,990,'CNY','PENDING','2026-01-01T00:00:00')"))
        c.execute(text("INSERT INTO transactional_outbox(event_id,topic,event_type,aggregate_id,payload,"
            "status,attempt_count,available_at,created_at) VALUES "
            "('ci-event-1','ci','CI_ONLY','ci-aggregate','{}','PENDING',0,"
            "'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"))
        print(json.dumps({'synthetic_rail_rows': 2, 'synthetic_refund_rows': 1, 'synthetic_outbox_rows': 1}))
    elif a.operation == 'long-values':
        assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == AFTER
        c.execute(text("UPDATE rail_order_runtime SET status=:status,booking_reference=:ref WHERE order_id='ci-rail-1'"),
                  {'status': 'S'*64, 'ref': 'R'*128})
        print(json.dumps({'synthetic_maximum_widths_written': [64,128]}))
    else:
        c.execute(text('SET TRANSACTION READ ONLY'))
        assert c.execute(text('SHOW transaction_read_only')).scalar_one() == 'on'
        baseline = json.loads(Path(a.baseline).read_text()) if a.baseline else None
        rows = c.execute(text("SELECT table_name,column_name,data_type,udt_name,character_maximum_length,"
            "is_nullable,column_default FROM information_schema.columns WHERE table_schema='public' "
            "ORDER BY table_name,ordinal_position")).mappings().all()
        schema = [dict(row) for row in rows]
        tables = {}; projection = {}
        for name in c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars():
            quoted = engine.dialect.identifier_preparer.quote(name)
            names = [r['column_name'] for r in schema if r['table_name'] == name]
            values = list(c.execute(text(f'SELECT to_jsonb(t)::text FROM public.{quoted} t ORDER BY to_jsonb(t)::text')).scalars())
            tables[name] = {'columns': names, 'rows': len(values), 'rows_sha256': digest(values)}
            if baseline and name in baseline['tables']:
                cols = ','.join(engine.dialect.identifier_preparer.quote(x) for x in baseline['tables'][name]['columns'])
                old = list(c.execute(text(f'SELECT to_jsonb(t)::text FROM (SELECT {cols} FROM public.{quoted}) t ORDER BY to_jsonb(t)::text')).scalars())
                projection[name] = {'rows': len(old), 'rows_sha256': digest(old)}
        definitions = {}
        for key, query in {
            'indexes': "SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY tablename,indexname",
            'constraints': "SELECT c.relname,x.conname,pg_get_constraintdef(x.oid) FROM pg_constraint x JOIN pg_class c ON c.oid=x.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY c.relname,x.conname",
            'triggers': "SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY c.relname,t.tgname",
            'functions': "SELECT p.proname,pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prokind='f' ORDER BY p.proname,pg_get_function_identity_arguments(p.oid)",
            'sequences': "SELECT sequencename,start_value,min_value,max_value,increment_by,cycle,cache_size,last_value FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename",
        }.items():
            definitions[key] = [list(r) for r in c.execute(text(query))]
        print(json.dumps({'head': c.execute(text('SELECT version_num FROM alembic_version')).scalar_one(),
            'server_version': c.execute(text('SHOW server_version')).scalar_one(), 'schema': schema,
            'tables': tables, 'definitions': definitions, 'original_columns': projection,
            'read_only': True}, indent=2, default=str))
engine.dispose()
