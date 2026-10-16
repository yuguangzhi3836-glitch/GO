import concurrent.futures
import threading
import time
import unittest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import QueuePool
from observe import HoldCPU


def burn(seconds=.015):
    until = time.thread_time() + seconds
    while time.thread_time() < until:
        pass


class HoldTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', poolclass=QueuePool, pool_size=2,
                                    max_overflow=0, connect_args={'check_same_thread': False})
        self.probe = HoldCPU(self.engine)
        self.probe.wrap_transactions()

    def tearDown(self):
        self.probe.close()
        self.engine.dispose()

    def test_cpu_sleep_and_idle_excluded(self):
        with self.probe.phase('idle'):
            burn()
        with self.engine.connect():
            with self.probe.phase('compute'):
                burn()
            with self.probe.phase('sleep'):
                time.sleep(.025)
        s = self.probe.snapshot()
        self.assertTrue(s['valid'])
        rows = s['held_thread_by_phase']
        self.assertNotIn('idle', rows)
        self.assertGreater(rows['compute']['cpu_seconds'], .012)
        self.assertGreater(rows['sleep']['wall_seconds'], .02)
        self.assertLess(rows['sleep']['cpu_seconds'], .01)

    def test_nested_leases_count_thread_cpu_once(self):
        with self.engine.connect(), self.engine.connect():
            with self.probe.phase('compute'):
                burn(.03)
        s = self.probe.snapshot()
        self.assertTrue(s['valid'])
        self.assertEqual(s['checkouts'], 2)
        self.assertLess(s['held_thread_by_phase']['compute']['cpu_seconds'], .05)

    def test_failed_sql_unwinds_and_original_exception_survives(self):
        with self.engine.connect() as c:
            with self.assertRaises(DBAPIError):
                c.execute(text('select * from table_does_not_exist'))
            with self.probe.phase('after_failure'):
                burn()
            c.rollback()
        s = self.probe.snapshot()
        self.assertTrue(s['valid'])
        self.assertGreater(s['held_thread_by_phase']['after_failure']['cpu_seconds'], .012)
        self.assertIn('dbapi.rollback', s['held_thread_by_phase'])

    def test_threads_do_not_charge_each_others_cpu(self):
        barrier = threading.Barrier(2)
        def worker(label):
            with self.engine.connect():
                barrier.wait()
                with self.probe.phase(label):
                    burn(.025)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            list(pool.map(worker, ['one', 'two']))
        s = self.probe.snapshot()
        self.assertTrue(s['valid'])
        for key in ('one', 'two'):
            self.assertAlmostEqual(s['held_thread_by_phase'][key]['cpu_seconds'], .025, delta=.012)

    def test_open_and_cross_thread_leases_rejected(self):
        c = self.engine.connect()
        self.assertFalse(self.probe.snapshot()['valid'])
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            pool.submit(c.close).result()
        s = self.probe.snapshot()
        self.assertFalse(s['valid'])
        self.assertIn('CROSS_THREAD_OR_UNOBSERVED_CHECKIN', s['errors'])

    def test_nested_method_exception_and_restore(self):
        class Service:
            def inner(self):
                burn()
                raise ValueError('original')
            def outer(self):
                return self.inner()
        obj = Service()
        self.probe.wrap(obj, 'inner', 'inner')
        self.probe.wrap(obj, 'outer', 'outer')
        with self.engine.connect():
            with self.assertRaisesRegex(ValueError, 'original'):
                obj.outer()
        s = self.probe.snapshot()
        self.assertTrue(s['valid'])
        self.assertGreater(s['held_thread_by_phase']['inner']['cpu_seconds'], .012)
        self.assertLess(s['held_thread_by_phase']['outer']['cpu_seconds'], .01)
        self.probe.close()
        self.assertNotIn('inner', vars(obj))
        self.assertNotIn('outer', vars(obj))

class MapperTests(unittest.TestCase):
    setUp = HoldTests.setUp
    tearDown = HoldTests.tearDown
    def test_mapper_attributed_only_while_holding(self):
        from sqlalchemy.orm import registry
        from sqlalchemy import Column, Integer, Table
        reg = registry()
        class Model:
            pass
        reg.map_imperatively(Model, Table('isolated_model', reg.metadata,
                                         Column('id', Integer, primary_key=True)))
        try:
            with self.engine.connect():
                reg.configure()
            s = self.probe.snapshot()
            self.assertTrue(s['valid'])
            self.assertIn('orm.configure', s['held_thread_by_phase'])
        finally:
            reg.dispose()

    def test_adapter_preserves_output_and_cleanup(self):
        from adapter import with_hold_cpu
        class ExistingMetrics:
            def __init__(self, engine):
                pass
            def track(self, service, method, label):
                pass
            def snapshot(self):
                return {'existing': 42}
        class Service:
            def run(self):
                with self_engine.connect() as c:
                    return c.scalar(text('select 42'))
        # Avoid two observers for this integration check.
        self.probe.close()
        self_engine = self.engine
        m = with_hold_cpu(ExistingMetrics)(self.engine)
        obj = Service()
        m.track(obj, 'run', 'money.create')
        self.assertEqual(obj.run(), 42)
        s = m.snapshot()
        self.assertEqual(s['existing'], 42)
        self.assertTrue(s['held_cpu']['valid'])
        self.assertIn('dbapi.execute', s['held_cpu']['held_thread_by_phase'])
        self.assertNotIn('run', vars(obj))


if __name__ == "__main__":
    unittest.main()
