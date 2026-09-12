"""Dedicated CI database only. Exercises the repaired guard against real PG catalogs."""
import json
import os
import sys
sys.path.insert(0,'/opt/go/staging')
import preflight
import psycopg

if os.environ.get('GO_COMPAT_ISOLATED_TEST') != 'true':
    raise SystemExit('ISOLATED_TEST_ONLY')
with psycopg.connect(host='compat-pg',dbname='compat_guard_test',user='compat_test',password='isolated-fixture-only') as conn:
    with conn.cursor() as cur:
        cur.execute('SHOW server_version'); version=cur.fetchone()[0]
        if not version.startswith('18.4'): raise RuntimeError('PG_VERSION')
        cur.execute('CREATE TABLE rail_order_runtime (status varchar(64), booking_reference varchar(128))')
        def check(expected=None):
            cur.execute("SELECT table_name,column_name,character_maximum_length,data_type,udt_name FROM information_schema.columns WHERE table_schema='public'")
            try: preflight.critical_column_gate(cur.fetchall())
            except preflight.Hold as exc:
                if exc.code != expected: raise
                return exc.code
            if expected: raise RuntimeError('UNSAFE_SCHEMA_ACCEPTED')
            return 'PASS'
        result={'exact_widths':check()}
        cur.execute('ALTER TABLE rail_order_runtime ALTER COLUMN status TYPE integer USING 0')
        result['integer_null_width_rejected']=check('DATABASE_CRITICAL_TYPE_MISMATCH')
        cur.execute('ALTER TABLE rail_order_runtime ALTER COLUMN status TYPE text USING status::text')
        result['text_unbounded_accepted']=check()
        cur.execute('ALTER TABLE rail_order_runtime ALTER COLUMN booking_reference TYPE varchar(24)')
        result['narrow_varchar_rejected']=check('DATABASE_CRITICAL_WIDTH_MISMATCH')
        result.update({'postgres_version':version,'scope':'ISOLATED_TYPE_GUARD_ONLY','hk_execution':'NOT_RUN'})
        print(json.dumps(result))
    conn.rollback()
