"""Bounded serial SQL diagnosis; synthetic sizes, never performance acceptance."""
import json
import os
import time
from pathlib import Path
from statistics import median

import pytest
from sqlalchemy import event, text
from test_correctness import baseline, db, root, move


@pytest.mark.parametrize('source_count', [0, 1000, 100000])
def test_new_write_cost(db, source_count):
    if db.candidate:
        pytest.skip('One unchanged main service; index toggled within each schema')
    with db.engine.begin() as c:
        c.execute(text("INSERT INTO catalog_credit_source SELECT 'cap-'||n, 'credit-'||n, 'intent-'||n, 100, 0, 0 FROM generate_series(1,:n) n"), {'n': source_count})
        c.execute(text('ANALYZE catalog_credit_source'))
    output = {'source_count': source_count, 'synthetic': True, 'performance_acceptance': False, 'blocks': []}
    with db.engine.connect() as c:
        output['server_version'] = c.scalar(text('SHOW server_version'))
    active = []
    def before(conn, cursor, sql, params, context, many):
        context.probe_start = time.perf_counter()
    def after(conn, cursor, sql, params, context, many):
        active.append({'sql': sql, 'params': params, 'rows': cursor.rowcount,
                       'ms': (time.perf_counter()-context.probe_start)*1000})
    event.listen(db.engine, 'before_cursor_execute', before)
    event.listen(db.engine, 'after_cursor_execute', after)
    try:
        for block, indexed in enumerate([False, True, True, False]):
            with db.engine.begin() as c:
                c.execute(text('DROP INDEX IF EXISTS probe_source_intent'))
                if indexed:
                    c.execute(text('CREATE INDEX probe_source_intent ON catalog_credit_source(payment_intent_id)'))
                c.execute(text('ANALYZE catalog_credit_source'))
            samples = []
            for n in range(13):
                iid = f'root-{block}-{n}'
                root(db, iid)
                active.clear()
                w, cpu = time.perf_counter(), time.thread_time()
                auth = move(db, 'AUTHORIZATION', iid+':auth', iid=iid)['money_movement_id']
                cap = move(db, 'CAPTURE', iid+':cap', parent=auth, iid=iid)['money_movement_id']
                wall = (time.perf_counter()-w)*1000
                thread = (time.thread_time()-cpu)*1000
                statements = list(active)
                active.clear()
                rw = time.perf_counter()
                assert move(db, 'CAPTURE', iid+':cap', parent=auth, iid=iid)['money_movement_id'] == cap
                replay = (time.perf_counter()-rw)*1000
                assert len(active) == 2 and active[1]['rows'] == 1
                assert not any('catalog_credit_source' in x['sql'] for x in active)
                assert sum(x['sql'].startswith('SELECT') for x in statements) == 9
                if n >= 3:
                    samples.append({'wall_ms': wall, 'thread_cpu_ms': thread, 'replay_ms': replay,
                                    'statements': statements})
            source = next(x for x in statements if 'FROM catalog_credit_source' in x['sql'])
            with db.engine.connect() as c:
                cursor = c.connection.cursor()
                cursor.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+source['sql'], source['params'])
                plan = cursor.fetchone()[0]
                cursor.close()
                c.rollback()
            output['blocks'].append({'indexed': indexed, 'samples': samples, 'source_plan': plan})
        for indexed in [False, True]:
            samples = [s for b in output['blocks'] if b['indexed'] == indexed for s in b['samples']]
            print('NEW_WRITE', source_count, indexed, 'wall', round(median(s['wall_ms'] for s in samples),3),
                  'source_sql', round(median(sum(x['ms'] for x in s['statements'] if 'FROM catalog_credit_source' in x['sql']) for s in samples),3),
                  'replay', round(median(s['replay_ms'] for s in samples),3))
        path = Path(os.environ['MONEY_NEW_OUTPUT'])
        path.mkdir(parents=True, exist_ok=True)
        # Keep timings and exact SQL without duplicating long SELECT text.
        catalog = []
        for block in output['blocks']:
            for sample in block['samples']:
                for statement in sample['statements']:
                    sql = statement.pop('sql')
                    if sql not in catalog:
                        catalog.append(sql)
                    statement['sql_id'] = catalog.index(sql)
        output['sql_catalog'] = catalog
        (path/f'cost-{source_count}.json').write_text(json.dumps(output, indent=2, default=str)+'\n')
    finally:
        event.remove(db.engine, 'before_cursor_execute', before)
        event.remove(db.engine, 'after_cursor_execute', after)
