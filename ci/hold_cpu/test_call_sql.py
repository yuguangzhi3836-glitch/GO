import concurrent.futures
import json
import threading
import unittest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import QueuePool
from call_sql import CallSQL


class CallTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', poolclass=QueuePool, pool_size=2,
            max_overflow=0, connect_args={'check_same_thread': False})
        # Initial connection setup is deliberately outside measured scenarios.
        with self.engine.connect():
            pass
        self.probe = CallSQL(self.engine)

    def tearDown(self):
        self.probe.close()
        self.engine.dispose()

    def run_call(self, label, value):
        with self.probe.call(label):
            with self.engine.connect() as c:
                self.assertEqual(c.scalar(text('select :value'), {'value': value}), value)
                c.commit()

    def test_paths_sql_commits_and_no_secret_values(self):
        for label in ('fresh_AUTH', 'fresh_CAPTURE', 'replay_AUTH', 'replay_CAPTURE'):
            self.run_call(label, 'never-export-this')
        report = self.probe.snapshot()
        self.assertTrue(report['valid'])
        self.assertEqual(len(report['calls']), 4)
        for row in report['calls']:
            self.assertEqual(len(row['sql']), 1)
            self.assertEqual(len(row['leases']), 1)
            self.assertTrue(any(t['operation'] == 'commit' for t in row['transactions']))
        self.assertNotIn('never-export-this', json.dumps(report))
        self.assertNotIn('select :value', json.dumps(report))

    def test_error_rollback_and_reuse(self):
        with self.assertRaises(DBAPIError):
            with self.probe.call('conflict'):
                with self.engine.connect() as c:
                    c.execute(text('select * from missing_private_table'))
        self.run_call('fresh_AUTH', 5)
        report = self.probe.snapshot()
        self.assertTrue(report['valid'])
        row = report['calls'][0]
        self.assertEqual(row['outcome'], 'error')
        self.assertTrue(row['sql'][0]['failed'])
        self.assertTrue(any(t['operation'] == 'rollback' for t in row['transactions']))
        self.assertNotIn('missing_private_table', json.dumps(report))

    def test_concurrent_calls_do_not_mix(self):
        barrier = threading.Barrier(2)
        def worker(label):
            with self.probe.call(label):
                with self.engine.connect() as c:
                    barrier.wait(timeout=5)
                    c.execute(text('select 1'))
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            list(pool.map(worker, ['fresh_AUTH', 'fresh_CAPTURE']))
        report = self.probe.snapshot()
        self.assertTrue(report['valid'])
        self.assertEqual({r['call_id'] for r in report['calls']}, {1, 2})
        self.assertTrue(all(len(r['sql']) == len(r['leases']) == 1 for r in report['calls']))

    def test_open_lease_and_scope_escape_rejected(self):
        with self.probe.call('fresh_AUTH'):
            c = self.engine.connect()
            self.assertFalse(self.probe.snapshot()['valid'])
        c.close()
        self.assertIn('CALL_ENDED_WITH_LEASE', self.probe.snapshot()['errors'])

    def test_acquisition_is_separate_from_queue(self):
        with self.probe.call('fresh_AUTH'):
            with self.probe.acquisition():
                c = self.engine.connect()
            c.close()
        report = self.probe.snapshot()
        self.assertIsNone(report['pool_queue_seconds'])
        self.assertEqual(len(report['calls'][0]['acquisition_seconds']), 1)

    def test_nested_scope_and_invalid_label_rejected(self):
        with self.assertRaises(ValueError):
            with self.probe.call('guessed'):
                pass
        with self.probe.call('fresh_AUTH'):
            with self.assertRaises(RuntimeError):
                with self.probe.call('fresh_CAPTURE'):
                    pass
        self.assertTrue(self.probe.snapshot()['valid'])

    def test_close_restores_dialect_and_listeners(self):
        self.probe.close()
        self.assertNotIn('do_commit', vars(self.engine.dialect))
        self.assertNotIn('do_rollback', vars(self.engine.dialect))
        with self.engine.connect() as c:
            c.execute(text('select 1'))
            c.commit()
        self.assertEqual(self.probe.snapshot()['calls'], [])

    def test_inherited_connection_cannot_look_fully_measured(self):
        with self.engine.connect() as c:
            with self.probe.call('fresh_AUTH'):
                c.execute(text('select 1'))
        self.assertIn('SQL_WITHOUT_SCOPED_LEASE', self.probe.snapshot()['errors'])


if __name__ == '__main__':
    unittest.main()
